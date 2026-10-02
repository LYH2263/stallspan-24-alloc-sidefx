import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import AllocationAuditEvent, AllocationRun, Pillar, Segment, Vendor
from app.services.first_fit_engine import allocate_first_fit, result_to_dict
router = APIRouter(prefix="/allocate", tags=["allocate"])

def _compute_allocation(db: Session, segment_id: int):
    """试摆计算：只算不写。街段非法抛 404，三处（运行/审计/图面）都不增行。"""
    seg = db.get(Segment, segment_id)
    if not seg: raise HTTPException(404, "街段不存在")
    pillars = [{"position_m": p.position_m, "thickness_m": p.thickness_m}
               for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()]
    vendors = [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
               for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()]
    result = result_to_dict(allocate_first_fit(seg.width_m, vendors, pillars))
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    return seg, result

@router.post("/preview")
def preview(segment_id: int = 1, db: Session = Depends(get_db)):
    """试摆预览：不落运行表、不落审计表，也不会被记成审计成功。"""
    _seg, result = _compute_allocation(db, segment_id)
    return {"status": "preview", **result}

@router.post("/confirm")
def confirm(segment_id: int = 1, db: Session = Depends(get_db)):
    """确认落位：运行行与审计事件（集日、街段、运行主键、时间）同一事务写入；
    审计写入失败整体回滚，运行表不留半成功行。编排内不写任何删除。"""
    seg, result = _compute_allocation(db, segment_id)
    try:
        run = AllocationRun(segment_id=seg.id, created_at=datetime.utcnow(),
                            result_json=json.dumps(result, ensure_ascii=False))
        db.add(run); db.flush()
        evt = AllocationAuditEvent(run_id=run.id, market_day_id=seg.market_day_id,
                                   segment_id=seg.id, created_at=datetime.utcnow())
        db.add(evt)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "确认落库失败，已整体回滚")
    return {"id": run.id, "status": "confirmed", "audit_id": evt.id, **result}

@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    """主图数据源：只读最近一次已确认运行，与运行表同一口径恢复，绝不写库。"""
    run = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                     .order_by(AllocationRun.id.desc())).first()
    if not run:
        raise HTTPException(404, "尚无已确认的落位")
    data = json.loads(run.result_json)
    return {"id": run.id, "status": "confirmed", **data}

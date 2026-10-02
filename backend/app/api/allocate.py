"""编排层：只做入参/响应与服务调用，禁止在此内写或删除数据库行。

- POST /allocate/preview  试摆：纯计算，运行表与审计表都不变；
- POST /allocate/confirm  确认：服务层保证运行行与审计事件同事务落库；
- GET  /allocate/latest   只读最近一次确认结果，绝不隐式生成运行行。
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AllocationRun
from app.services.allocation_service import (
    SegmentNotFound,
    build_result,
    confirm_allocation,
)

router = APIRouter(prefix="/allocate", tags=["allocate"])


def get_audit_hook():
    """审计写入钩子。默认 None 用服务层实现；测试可覆盖此依赖注入失败。"""
    return None


@router.post("/preview")
def preview(segment_id: int = 1, db: Session = Depends(get_db)):
    try:
        result = build_result(db, segment_id)
    except SegmentNotFound:
        raise HTTPException(status_code=404, detail="街段不存在")
    # 试摆不返回运行主键：它从未落库。
    return {"status": "preview", **result}


@router.post("/confirm")
def confirm(
    segment_id: int = 1,
    db: Session = Depends(get_db),
    audit_hook=Depends(get_audit_hook),
):
    try:
        return confirm_allocation(db, segment_id, record_audit=audit_hook)
    except SegmentNotFound:
        raise HTTPException(status_code=404, detail="街段不存在")


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    run = db.scalars(
        select(AllocationRun)
        .where(AllocationRun.segment_id == segment_id)
        .order_by(AllocationRun.id.desc())
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="尚无确认记录")
    return {"id": run.id, "status": "confirmed", **json.loads(run.result_json)}

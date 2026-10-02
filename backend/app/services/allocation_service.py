"""确认落库副作用合同的服务层。

合同要点：
- 预览/试摆（build_result）只做纯计算，不产生任何运行行或审计行；
- 确认（confirm_allocation）必须在同一数据库事务内写运行行与审计事件，
  审计写入失败（record_audit_event 可被测试注入）时整体回滚，运行不得残留半成功行；
- 裁库（reset_to_seed）在同一事务内清空运行/审计并恢复绿仓种子。
编排层（app/api）只允许调用本模块，禁止内写删除。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.models import (
    AllocationAuditEvent,
    AllocationRun,
    MarketDay,
    Pillar,
    Segment,
    Vendor,
)
from app.services.first_fit_engine import allocate_first_fit, result_to_dict
from app.services.seed import seed_data


class SegmentNotFound(Exception):
    """非法街段：任何写操作发生之前抛出，三处一律不增行。"""


def load_segment(db: Session, segment_id: int) -> Segment:
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise SegmentNotFound(segment_id)
    return seg


def build_result(db: Session, segment_id: int) -> dict:
    """纯计算一次开间分配，不落库。预览、试摆、确认共用这一个口径。"""
    seg = load_segment(db, segment_id)
    pillars = [
        {"position_m": p.position_m, "thickness_m": p.thickness_m, "label": p.label}
        for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()
    ]
    vendors = [
        {"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
        for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()
    ]
    result = result_to_dict(allocate_first_fit(seg.width_m, vendors, pillars))
    result["market_day_id"] = seg.market_day_id
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    return result


AuditHook = Callable[..., AllocationAuditEvent]


def record_audit_event(
    db: Session,
    *,
    run: AllocationRun,
    segment: Segment,
    result: dict,
    created_at: datetime,
) -> AllocationAuditEvent:
    """默认审计写入；测试可向 confirm_allocation 注入替换实现以模拟失败。"""
    detail = {
        "placements": len(result.get("placements", [])),
        "rejected": len(result.get("rejected", [])),
        # 有摊主放不下不改变确认性质：本事件永远记录确认成功，不伪装成拒绝。
        "status": "confirmed",
    }
    event = AllocationAuditEvent(
        market_day_id=segment.market_day_id,
        segment_id=segment.id,
        run_id=run.id,
        created_at=created_at,
        kind="confirmed",
        detail_json=json.dumps(detail, ensure_ascii=False),
    )
    db.add(event)
    return event


def confirm_allocation(
    db: Session,
    segment_id: int,
    *,
    record_audit: Optional[AuditHook] = None,
    now: Callable[[], datetime] = datetime.utcnow,
) -> dict:
    """原子确认：同一事务内写运行行与审计事件，任一失败整体回滚。"""
    record = record_audit or record_audit_event
    # 非法街段在任何写操作之前失败。
    seg = load_segment(db, segment_id)
    result = build_result(db, segment_id)
    created_at = now()
    run = AllocationRun(
        market_day_id=seg.market_day_id,
        segment_id=seg.id,
        created_at=created_at,
        result_json=json.dumps(result, ensure_ascii=False),
    )
    try:
        db.add(run)
        db.flush()  # 先取运行主键，审计事件才能互指
        record(db, run=run, segment=seg, result=result, created_at=created_at)
        db.commit()  # 运行行与审计事件在同一提交点同时可见
    except Exception:
        db.rollback()  # 审计写失败 → 运行不得残留半成功行
        raise
    db.refresh(run)
    return {"id": run.id, "status": "confirmed", **result}


def reset_to_seed(db: Session) -> None:
    """裁回绿仓种子：同一事务内清空全部业务表并重灌种子，行数以种子为准。"""
    try:
        # 依外键依赖倒序：审计指运行，挡柱指街段，街段/摊主句指集日。
        db.execute(delete(AllocationAuditEvent))
        db.execute(delete(AllocationRun))
        db.execute(delete(Pillar))
        db.execute(delete(Vendor))
        db.execute(delete(Segment))
        db.execute(delete(MarketDay))
        seed_data(db)
        db.commit()
    except Exception:
        db.rollback()
        raise

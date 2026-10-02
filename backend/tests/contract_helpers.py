"""独立合同帮手：不依赖服务层实现，自行数行、互指、巡检图面色块。

口径与 frontend/src/views/Map.vue 的色块构造保持一致：
- 挡柱色块：[position_m - thickness_m/2, position_m + thickness_m/2]
- 摊位色块：[start_m, start_m + width_m]，每摊一块，按起点排序
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import (
    AllocationAuditEvent,
    AllocationRun,
    MarketDay,
    Pillar,
    Segment,
    Vendor,
)

# 裁回种子后必须与之一致的绿仓行数。
GREEN_BASELINE = {
    "market_days": 1,
    "segments": 1,
    "pillars": 2,
    "vendors": 7,
    "allocation_runs": 0,
    "allocation_audit_events": 0,
}

_TABLES = {
    "market_days": MarketDay,
    "segments": Segment,
    "pillars": Pillar,
    "vendors": Vendor,
    "allocation_runs": AllocationRun,
    "allocation_audit_events": AllocationAuditEvent,
}


def count_rows(db: Session) -> dict[str, int]:
    """六张表逐行数行，返回表名 -> 行数。"""
    return {name: db.scalar(select(func.count()).select_from(model)) for name, model in _TABLES.items()}


def runs_audits_cross_reference(db: Session) -> list[dict]:
    """运行行与审计事件互指校验：一条审计恰好互指一条运行，集日/街段/时间同口径。

    返回每条对齐记录；任何对不齐都抛 AssertionError（三处对不齐即废）。
    """
    runs = {r.id: r for r in db.scalars(select(AllocationRun)).all()}
    events = db.scalars(select(AllocationAuditEvent).order_by(AllocationAuditEvent.id)).all()
    pointed_run_ids = set()
    aligned = []
    for ev in events:
        assert ev.kind == "confirmed", f"审计 {ev.id} 非确认成功事件：{ev.kind}"
        run = runs.get(ev.run_id)
        assert run is not None, f"审计 {ev.id} 互指的运行 {ev.run_id} 不存在（脏审计）"
        assert ev.segment_id == run.segment_id, f"审计 {ev.id} 与运行街段对不齐"
        assert ev.market_day_id == run.market_day_id, f"审计 {ev.id} 与运行集日对不齐"
        assert ev.created_at == run.created_at, f"审计 {ev.id} 与运行提交时间对不齐"
        pointed_run_ids.add(ev.run_id)
        aligned.append({"run_id": run.id, "audit_id": ev.id, "segment_id": ev.segment_id,
                        "market_day_id": ev.market_day_id, "created_at": ev.created_at})
    assert len(pointed_run_ids) == len(events), "存在两条审计互指同一运行的半成功行"
    missing_audit = set(runs) - pointed_run_ids
    assert not missing_audit, f"运行 {missing_audit} 缺审计（只清审计/只写运行的脏状态）"
    return aligned


def inspect_map_blocks(result: dict) -> list[dict]:
    """按 Map.vue 的口径从结果独立巡检色块：返回排序后的 [起,止,类型,标签] 列表。"""
    import json

    if isinstance(result, str):
        result = json.loads(result)
    blocks = []
    for p in result.get("pillars", []):
        half = p["thickness_m"] / 2
        blocks.append({"start": round(p["position_m"] - half, 3),
                       "end": round(p["position_m"] + half, 3),
                       "type": "pillar", "label": p.get("label", "挡柱")})
    for p in result.get("placements", []):
        blocks.append({"start": round(p["start_m"], 3),
                       "end": round(p["start_m"] + p["width_m"], 3),
                       "type": "stall", "label": p["vendor_name"]})
    blocks.sort(key=lambda b: (b["start"], b["end"]))
    return blocks


def assert_blocks_sane(result: dict) -> list[dict]:
    """图面巡检：色块不越界、摊位色块不压挡柱；色块数 = 挡柱数 + 落位数。"""
    blocks = inspect_map_blocks(result)
    width = result["segment"]["width_m"]
    n_pillars = len(result.get("pillars", []))
    n_stalls = len(result.get("placements", []))
    assert len(blocks) == n_pillars + n_stalls, "色块数与运行结果对不上"
    pillars = [b for b in blocks if b["type"] == "pillar"]
    for b in blocks:
        assert 0 - 1e-9 <= b["start"] < b["end"] <= width + 1e-9, f"色块越界：{b}"
    for b in blocks:
        if b["type"] == "stall":
            for pillar in pillars:
                assert b["end"] <= pillar["start"] + 1e-9 or b["start"] >= pillar["end"] - 1e-9, \
                    f"摊位色块 {b['label']} 跨越挡柱 {pillar['label']}"
    return blocks


def blocks_for_each_run(db: Session) -> dict[int, list[dict]]:
    """运行表里每行都独立巡检出一份色块，供与主图/审计对账。"""
    out = {}
    for run in db.scalars(select(AllocationRun).order_by(AllocationRun.id)).all():
        import json
        out[run.id] = assert_blocks_sane(json.loads(run.result_json))
    return out


def assert_green_baseline(db: Session) -> None:
    """裁库后对账：行数须与绿仓一致，且运行/审计都为零。"""
    counts = count_rows(db)
    assert counts == GREEN_BASELINE, f"裁回种子后行数对不齐：{counts} != {GREEN_BASELINE}"

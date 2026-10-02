from datetime import date
from sqlalchemy.orm import Session
from app.models.models import MarketDay, Pillar, Segment, Vendor

# 绿仓基线：1 个集日 / 1 条街段 / 2 根挡柱 / 7 个摊主；无运行行、无审计行。
SEED_DAY = {"name": "周末夜市", "day": date(2026, 9, 20)}
SEED_SEGMENT = {"name": "东街段", "width_m": 30.0}
SEED_PILLARS = [
    {"position_m": 10.0, "thickness_m": 0.5, "label": "灯柱A"},
    {"position_m": 20.0, "thickness_m": 0.5, "label": "灯柱B"},
]
SEED_VENDORS = [
    ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 5.0, 2),
    ("小美饰品", 2.5, 2), ("大碗面", 6.0, 1), ("手作皮具", 3.5, 3),
    ("巨型舞台车", 12.0, 9),
]


def seed_data(db: Session) -> None:
    """灌入绿仓种子数据，不自行提交（由调用方与其他写操作同事务提交）。"""
    day = MarketDay(**SEED_DAY)
    db.add(day); db.flush()
    seg = Segment(market_day_id=day.id, **SEED_SEGMENT)
    db.add(seg); db.flush()
    for kw in SEED_PILLARS:
        db.add(Pillar(segment_id=seg.id, **kw))
    for name, wdt, pri in SEED_VENDORS:
        db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
    db.flush()


def seed_if_empty(db: Session) -> None:
    from sqlalchemy import func, select
    if (db.scalar(select(func.count()).select_from(MarketDay)) or 0) > 0:
        return
    seed_data(db)
    db.commit()

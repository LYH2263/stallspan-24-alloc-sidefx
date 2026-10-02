"""测试基座：独立 sqlite 绿仓 + 独立帮手（数行、互指、裁回种子、图面巡检）。

帮手自带引擎与会话，与应用完全独立；删除只允许活在帮手里（编排禁止内写删除）。
"""
import json
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="stallspan_green_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/green.db"
os.environ["SEED_ON_EMPTY"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.models import (AllocationAuditEvent, AllocationRun, MarketDay,
                               Pillar, Segment, Vendor)

GREEN_TABLES = {
    "market_days": MarketDay,
    "segments": Segment,
    "vendors": Vendor,
    "pillars": Pillar,
    "allocation_runs": AllocationRun,
    "allocation_audit_events": AllocationAuditEvent,
}


class GreenHelper:
    """独立帮手：自己的引擎/会话，与应用会话互不相干。"""

    def __init__(self, client, db_url):
        self.client = client
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        self.Session = sessionmaker(bind=self.engine)

    # ---- 数行 ----
    def counts(self):
        with self.Session() as s:
            return {name: s.scalar(select(func.count()).select_from(model))
                    for name, model in GREEN_TABLES.items()}

    def runs(self):
        with self.Session() as s:
            return [{"id": r.id, "segment_id": r.segment_id, "created_at": r.created_at,
                     "result_json": r.result_json}
                    for r in s.scalars(select(AllocationRun).order_by(AllocationRun.id)).all()]

    def audits(self):
        with self.Session() as s:
            return [{"id": a.id, "run_id": a.run_id, "market_day_id": a.market_day_id,
                     "segment_id": a.segment_id, "created_at": a.created_at}
                    for a in s.scalars(select(AllocationAuditEvent).order_by(AllocationAuditEvent.id)).all()]

    # ---- 互指 ----
    def cross_refs(self):
        """每条审计必须指向真实运行行，且街段、集日口径一致，时间非空。"""
        problems = []
        runs_by_id = {r["id"]: r for r in self.runs()}
        with self.Session() as s:
            segs = {g.id: g for g in s.scalars(select(Segment)).all()}
        for a in self.audits():
            run = runs_by_id.get(a["run_id"])
            if run is None:
                problems.append(f"audit {a['id']} 指向不存在的运行 {a['run_id']}")
                continue
            if a["segment_id"] != run["segment_id"]:
                problems.append(f"audit {a['id']} 街段与运行 {run['id']} 不一致")
            seg = segs.get(a["segment_id"])
            if seg is None or seg.market_day_id != a["market_day_id"]:
                problems.append(f"audit {a['id']} 集日口径与街段不符")
            if a["created_at"] is None:
                problems.append(f"audit {a['id']} 缺时间")
        return problems

    # ---- 图面巡检 ----
    def map_placements(self, segment_id=1):
        """主图数据源即 /allocate/latest；返回 (status_code, 可见落位)。"""
        res = self.client.get(f"/api/allocate/latest?segment_id={segment_id}")
        if res.status_code == 404:
            return 404, []
        res.raise_for_status()
        return res.status_code, res.json()["placements"]

    def run_placements(self, run_row):
        return json.loads(run_row["result_json"])["placements"]

    # ---- 裁回种子 ----
    def trim_to_seed(self):
        """只裁运行与审计；删除只允许活在测试帮手，编排内禁止出现。"""
        with self.Session() as s:
            s.execute(text("DELETE FROM allocation_audit_events"))
            s.execute(text("DELETE FROM allocation_runs"))
            s.commit()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def green_counts(client):
    """绿仓行数：种子态基线，裁回种子后必须与此一致。"""
    h = GreenHelper(client, os.environ["DATABASE_URL"])
    h.trim_to_seed()
    return h.counts()


@pytest.fixture()
def helper(client):
    h = GreenHelper(client, os.environ["DATABASE_URL"])
    h.trim_to_seed()  # 每个用例从种子态出发
    yield h
    h.trim_to_seed()  # 裁回种子，不留脏行

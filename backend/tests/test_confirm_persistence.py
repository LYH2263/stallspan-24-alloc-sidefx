"""确认落库副作用合同测例。

合同要点：
- 成功确认 = 同一事务写运行行 + 审计事件（集日、街段、运行主键、时间）
- 运行表、审计表、主图可见落位同一口径恢复，三处对不齐即废
- 审计写入失败（注入）时运行不得残留半成功行
- 预览/试摆后运行与审计相对预览前都不变，预览不得记成审计成功
- 街段非法时三处都不增行；合法确认后再打非法请求，先前运行/审计/色块必须还在
- 连续两次确认按提交瞬间各写各的，禁止第二条吃第一条未提交完的缓存半行
- 裁回种子后与绿仓行数一致，色块同步恢复
"""
import json
import pathlib

import app.api.allocate as allocate_api


def test_confirm_writes_run_and_audit_in_one_transaction(client, helper):
    before = helper.counts()
    res = client.post("/api/allocate/confirm?segment_id=1")
    assert res.status_code == 200
    body = res.json()
    # 确认成功禁止伪装成拒绝：明确成功形态
    assert body["status"] == "confirmed"
    assert body["id"] and body["audit_id"]
    assert body["placements"]

    after = helper.counts()
    assert after["allocation_runs"] == before["allocation_runs"] + 1
    assert after["allocation_audit_events"] == before["allocation_audit_events"] + 1

    # 审计携带集日、街段、运行主键、时间，且互指无误
    assert helper.cross_refs() == []
    run = helper.runs()[-1]
    evt = helper.audits()[-1]
    assert evt["run_id"] == run["id"] == body["id"]
    assert evt["segment_id"] == 1
    assert evt["market_day_id"] == 1
    assert evt["created_at"] is not None


def test_audit_failure_leaves_no_half_run(client, helper, monkeypatch):
    class BoomAudit:
        def __init__(self, **kwargs):
            raise RuntimeError("注入的审计写入失败")

    monkeypatch.setattr(allocate_api, "AllocationAuditEvent", BoomAudit)
    before = helper.counts()
    res = client.post("/api/allocate/confirm?segment_id=1")
    assert res.status_code == 500
    # 运行表不得残留半成功行，审计表也没有，三处都不增行
    assert helper.counts() == before
    code, cells = helper.map_placements()
    assert code == 404 and cells == []


def test_preview_has_zero_side_effects(client, helper):
    before = helper.counts()
    res = client.post("/api/allocate/preview?segment_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "preview"
    assert "id" not in body and "audit_id" not in body  # 预览不给运行主键
    assert body["placements"]
    # 运行与审计相对预览前都不变，预览不得记成审计成功
    assert helper.counts() == before
    assert helper.audits() == []
    code, cells = helper.map_placements()
    assert code == 404 and cells == []  # 主图仍无落位


def test_latest_get_never_writes(client, helper):
    before = helper.counts()
    assert client.get("/api/allocate/latest?segment_id=1").status_code == 404
    assert helper.counts() == before


def test_invalid_segment_adds_nothing_anywhere(client, helper):
    before = helper.counts()
    assert client.post("/api/allocate/confirm?segment_id=999").status_code == 404
    assert client.post("/api/allocate/preview?segment_id=999").status_code == 404
    assert helper.counts() == before  # 三处都不增行


def test_illegal_request_preserves_prior_confirm(client, helper):
    ok = client.post("/api/allocate/confirm?segment_id=1")
    assert ok.status_code == 200
    committed = helper.counts()
    code, cells_before = helper.map_placements()
    assert code == 200 and cells_before

    assert client.post("/api/allocate/confirm?segment_id=999").status_code == 404
    assert helper.counts() == committed  # 先前写入的运行、审计还在
    code, cells_after = helper.map_placements()
    assert code == 200 and cells_after == cells_before  # 色块还在


def test_two_confirms_commit_independently(client, helper):
    r1 = client.post("/api/allocate/confirm?segment_id=1").json()
    r2 = client.post("/api/allocate/confirm?segment_id=1").json()
    assert r1["status"] == r2["status"] == "confirmed"
    assert r1["id"] != r2["id"]
    assert r1["audit_id"] != r2["audit_id"]

    runs = helper.runs()
    audits = helper.audits()
    assert len(runs) == 2 and len(audits) == 2
    # 各写各的：第二条审计指第二条运行，禁止吃第一条未提交完的缓存半行
    assert audits[0]["run_id"] == runs[0]["id"] == r1["id"]
    assert audits[1]["run_id"] == runs[1]["id"] == r2["id"]
    assert runs[0]["created_at"] is not None and runs[1]["created_at"] is not None
    assert helper.cross_refs() == []
    # 主图与最新一条已确认运行同口径
    code, cells = helper.map_placements()
    assert code == 200
    assert cells == helper.run_placements(runs[-1])


def test_map_db_same_source_and_trim_restores_green(client, helper, green_counts):
    client.post("/api/allocate/confirm?segment_id=1")
    run = helper.runs()[-1]
    code, cells = helper.map_placements()
    assert code == 200
    # 《三处同一口径》: 图面 == 运行表落位，审计指向该运行
    assert cells == helper.run_placements(run)
    assert helper.audits()[-1]["run_id"] == run["id"]

    # 裁回种子：运行与审计同步清零，色块同步恢复；禁止只清运行留脏色块或只清审计
    helper.trim_to_seed()
    assert helper.counts() == green_counts  # 与绿仓行数一致
    code, cells = helper.map_placements()
    assert code == 404 and cells == []


def test_green_baseline_is_seed(green_counts):
    assert green_counts == {
        "market_days": 1,
        "segments": 1,
        "vendors": 7,
        "pillars": 2,
        "allocation_runs": 0,
        "allocation_audit_events": 0,
    }


def test_orchestration_contains_no_delete():
    """编排禁止内写删除：分配编排源码里不得出现删除语句。"""
    src = pathlib.Path(allocate_api.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("db.delete", ".delete(", "delete from"):
        assert forbidden not in src

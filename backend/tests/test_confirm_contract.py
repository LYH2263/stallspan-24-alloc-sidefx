"""确认落库副作用合同测试。

三处口径：运行表 allocation_runs、审计表 allocation_audit_events、主图色块
（按 frontend/src/views/Map.vue 的独立巡检口径）。任何一处对不齐即废。
"""
from __future__ import annotations

import pytest

from app.api.allocate import get_audit_hook
from app.main import app
from app.services.allocation_service import confirm_allocation

from contract_helpers import (
    GREEN_BASELINE,
    assert_blocks_sane,
    assert_green_baseline,
    blocks_for_each_run,
    count_rows,
    inspect_map_blocks,
    runs_audits_cross_reference,
)


def _confirm(client, segment_id: int = 1):
    return client.post(f"/api/allocate/confirm?segment_id={segment_id}")


def _preview(client, segment_id: int = 1):
    return client.post(f"/api/allocate/preview?segment_id={segment_id}")


def _reset(client):
    return client.post("/api/admin/reset")


def test_preview_has_no_persistence_side_effect(client, db):
    """预览/试摆：运行表与审计表相对预览前不变，预览不被记成审计成功。"""
    before = count_rows(db)
    resp = _preview(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "preview"
    assert "id" not in body, "试摆结果不得带运行主键"
    assert_blocks_sane(body)
    after = count_rows(db)
    assert after == before, f"试摆产生了落库副作用：{before} -> {after}"
    assert after["allocation_runs"] == 0
    assert after["allocation_audit_events"] == 0
    # 尚无确认时 latest 不得隐式补写一条运行。
    assert client.get("/api/allocate/latest?segment_id=1").status_code == 404
    assert count_rows(db)["allocation_runs"] == 0


def test_confirm_writes_run_and_audit_in_one_transaction(client, db):
    """成功确认：运行行与审计事件同事务写入，集日/街段/运行主键/时间互指，主图同一口径。"""
    resp = _confirm(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed", "确认成功禁止伪装成拒绝"
    run_id = body["id"]

    counts = count_rows(db)
    assert counts["allocation_runs"] == 1
    assert counts["allocation_audit_events"] == 1

    aligned = runs_audits_cross_reference(db)
    assert len(aligned) == 1
    assert aligned[0]["run_id"] == run_id
    assert aligned[0]["segment_id"] == 1

    # 主图可见落位与运行表同一口径：三处对齐才成立。
    run_blocks = blocks_for_each_run(db)[run_id]
    map_blocks = inspect_map_blocks(body)
    assert run_blocks == map_blocks, "运行表色块与主图色块对不齐"
    assert len(map_blocks) == len(body["pillars"]) + len(body["placements"])

    # latest 读回的是同一条已确认运行，不另写。
    latest = client.get("/api/allocate/latest?segment_id=1")
    assert latest.status_code == 200
    assert latest.json()["id"] == run_id
    assert inspect_map_blocks(latest.json()) == map_blocks
    assert count_rows(db)["allocation_runs"] == 1


def test_seed_has_a_rejected_vendor_but_confirm_is_still_success(client, db):
    """种子里 12m 巨型舞台车放不下；有拒摊清单不改变确认性质。"""
    body = _confirm(client).json()
    assert body["status"] == "confirmed"
    rejected_names = [r["vendor_name"] for r in body["rejected"]]
    assert "巨型舞台车" in rejected_names
    runs_audits_cross_reference(db)  # 审计仍为确认成功，互指完整


def test_audit_write_failure_rolls_back_without_leftover_run(client, db):
    """审计写入失败（测例注入）：整体回滚，运行不得残留半成功行。"""
    def failing_hook(session, *, run, segment, result, created_at):
        raise RuntimeError("注入：审计写入失败")

    app.dependency_overrides[get_audit_hook] = lambda: failing_hook
    try:
        with pytest.raises(RuntimeError, match="注入"):
            _confirm(client)
    finally:
        app.dependency_overrides.clear()
    assert count_rows(db)["allocation_runs"] == 0
    assert count_rows(db)["allocation_audit_events"] == 0
    runs_audits_cross_reference(db)


def test_audit_failure_injection_also_works_at_service_layer(db):
    """服务层直接注入失败钩子：同一保证。"""
    def boom(session, *, run, segment, result, created_at):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        confirm_allocation(db, 1, record_audit=boom)
    db.rollback()
    assert count_rows(db)["allocation_runs"] == 0
    assert count_rows(db)["allocation_audit_events"] == 0


def test_illegal_segment_confirms_nothing(client, db):
    """街段非法：运行、审计、色块三处都不增行（404 前不得有任何写）。"""
    before = count_rows(db)
    resp = _confirm(client, segment_id=9999)
    assert resp.status_code == 404
    assert count_rows(db) == before
    assert _preview(client, segment_id=9999).status_code == 404
    assert count_rows(db) == before


def test_illegal_request_after_valid_confirm_keeps_prior_writes(client, db):
    """合法确认后再打非法请求：先前的运行、审计与色块必须还在。"""
    ok = _confirm(client).json()
    prior_blocks = inspect_map_blocks(ok)
    assert _confirm(client, segment_id=9999).status_code == 404
    counts = count_rows(db)
    assert counts["allocation_runs"] == 1
    assert counts["allocation_audit_events"] == 1
    aligned = runs_audits_cross_reference(db)
    assert len(aligned) == 1
    assert blocks_for_each_run(db)[ok["id"]] == prior_blocks
    assert inspect_map_blocks(client.get("/api/allocate/latest?segment_id=1").json()) == prior_blocks


def test_two_consecutive_confirms_each_commit_their_own_rows(client, db):
    """连续两次确认：按提交瞬间各写各的，第二条不得吃第一条未提交完的缓存半行。"""
    first = _confirm(client).json()
    second = _confirm(client).json()
    assert first["id"] != second["id"]
    counts = count_rows(db)
    assert counts["allocation_runs"] == 2
    assert counts["allocation_audit_events"] == 2

    aligned = runs_audits_cross_reference(db)
    run_ids = {a["run_id"] for a in aligned}
    assert run_ids == {first["id"], second["id"]}
    # 每条审计互指各自的运行，时间各自独立。
    assert aligned[0]["created_at"] <= aligned[1]["created_at"]
    run_blocks = blocks_for_each_run(db)
    assert inspect_map_blocks(first) == run_blocks[first["id"]]
    assert inspect_map_blocks(second) == run_blocks[second["id"]]


def test_reset_to_seed_restores_rows_and_map_blocks(client, db):
    """裁回种子：运行/审计/主图同步恢复，行数与绿仓一致，禁止只清一边留脏色块。"""
    seed_preview = _preview(client).json()
    seed_blocks = inspect_map_blocks(seed_preview)

    _confirm(client)
    _confirm(client)
    assert count_rows(db)["allocation_runs"] == 2
    assert count_rows(db)["allocation_audit_events"] == 2

    assert _reset(client).status_code == 204

    assert_green_baseline(db)
    runs_audits_cross_reference(db)  # 零行零事件也算对齐：无脏审计、无缺审计的运行
    assert client.get("/api/allocate/latest?segment_id=1").status_code == 404

    # 图面同步恢复：裁库后试摆色块与绿仓预览完全一致。
    restored = _preview(client).json()
    assert inspect_map_blocks(restored) == seed_blocks, "裁库后图面色块未恢复到绿仓口径"
    # 裁库本身的预览依旧不落库。
    assert count_rows(db) == GREEN_BASELINE


def test_confirm_after_reset_writes_one_clean_pair(client, db):
    """裁回种子后再次确认：仍是一条运行配一条审计，三处重新对齐。"""
    _confirm(client)
    _reset(client)
    assert_green_baseline(db)
    body = _confirm(client).json()
    assert body["status"] == "confirmed"
    assert count_rows(db)["allocation_runs"] == 1
    aligned = runs_audits_cross_reference(db)
    assert len(aligned) == 1
    assert aligned[0]["run_id"] == body["id"]
    assert blocks_for_each_run(db)[body["id"]] == inspect_map_blocks(body)


FORBIDDEN_ORCHESTRATION_PATTERNS = ("db.add(", ".delete(", "db.commit(", "db.execute(", "session.add(")


def test_orchestration_layer_never_writes_or_deletes():
    """编排层（app/api）禁止内写删除：只允许调用服务层。静态巡检所有 .py。"""
    import pathlib
    api_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    offenders = []
    for path in sorted(api_dir.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pat in FORBIDDEN_ORCHESTRATION_PATTERNS:
                if pat in line:
                    offenders.append(f"{path.name}:{lineno}: 发现禁用写法 {pat!r} -> {stripped}")
    assert not offenders, "编排层内写/删除，违反合同：\n" + "\n".join(offenders)

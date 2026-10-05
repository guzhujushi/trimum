"""tests for the one-shot approval request channel (A2).

全部用 `tmp_path` + `monkeypatch` 隔离，绝不许碰真 `~/.trimum`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core.approvals import (  # noqa: E402
    ApprovalStore,
    DEFAULT_TTL_SECONDS,
    STATUS_APPROVED,
    STATUS_CONSUMED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    DIR_ENV,
    TTL_ENV,
)


def _make_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    return home


def test_request_writes_file_and_defaults(tmp_path, monkeypatch):
    home = _make_home(tmp_path, monkeypatch)
    store = ApprovalStore()
    assert store.directory == home / "approvals"

    rec = store.request(agent_id="a1", command="rm -rf x")
    path = store.directory / f"{rec.id}.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_PENDING
    assert on_disk["agent_id"] == "a1"
    assert rec.expires_at - rec.created_at == DEFAULT_TTL_SECONDS == 300.0


def test_env_dir_override(tmp_path, monkeypatch):
    home = _make_home(tmp_path, monkeypatch)  # 设成别处，验证 env 目录优先
    override = tmp_path / "elsewhere" / "approvals"
    monkeypatch.setenv(DIR_ENV, str(override))
    store = ApprovalStore()
    assert store.directory == override
    rec = store.request(command="ls")
    assert (override / f"{rec.id}.json").is_file()
    assert not (home / "approvals").exists()


def test_ttl_priority(tmp_path, monkeypatch):
    _make_home(tmp_path, monkeypatch)
    store = ApprovalStore()

    # 1) 显式参数最高
    assert store._parse_ttl(7.5) == 7.5
    # 2) env 次之（显式 None 时）
    monkeypatch.setenv(TTL_ENV, "120")
    assert store._parse_ttl(None) == 120.0
    assert store._parse_ttl(5) == 5.0  # 显式仍压 env
    # 3) 配置 `approvals.ttl_seconds`（config 文件不存在 ⇒ 落到默认）
    monkeypatch.delenv(TTL_ENV, raising=False)
    assert store._parse_ttl(None) == 300.0
    # 4) 非法值一律回 300
    for bad in ("abc", 0, -5):
        assert store._parse_ttl(bad) == DEFAULT_TTL_SECONDS
    monkeypatch.setenv(TTL_ENV, "xyz")
    assert store._parse_ttl(None) == DEFAULT_TTL_SECONDS


def test_decide_approve_then_consume_once(tmp_path, monkeypatch):
    store = ApprovalStore(tmp_path / "s")
    rec = store.request(command="chmod 777")
    assert store.decide(rec.id, approved=True).status == STATUS_APPROVED

    first = store.consume(rec.id)
    assert first.status == STATUS_CONSUMED
    assert first.used_at > 0

    second = store.consume(rec.id)
    assert second.status == STATUS_CONSUMED  # 不得再放行成 approved


def test_decide_deny(tmp_path, monkeypatch):
    store = ApprovalStore(tmp_path / "s")
    rec = store.request(command="kill -9 1")
    assert store.decide(rec.id, approved=False).status == STATUS_DENIED
    # fail-closed：终态不可翻回 approved
    assert store.decide(rec.id, approved=True).status == STATUS_DENIED


def test_expired_is_fail_closed(tmp_path, monkeypatch):
    now = [1000.0]
    store = ApprovalStore(tmp_path / "s", clock=lambda: now[0])
    rec = store.request(command="reboot", ttl=10.0)
    now[0] = 2000.0  # 让记录过期

    assert store.get(rec.id).status == STATUS_EXPIRED
    assert store.decide(rec.id, approved=True).status == STATUS_EXPIRED
    consumed = store.consume(rec.id)
    assert consumed.status == STATUS_EXPIRED
    assert consumed.status != STATUS_APPROVED


def test_list_pending_skips_broken_files(tmp_path, monkeypatch):
    store = ApprovalStore(tmp_path / "s")
    good = store.request(command="ls")
    (store.directory / "broken.json").write_text("{not json", encoding="utf-8")

    pending = store.list_pending()
    assert [r.id for r in pending] == [good.id]


def test_missing_request_returns_none(tmp_path, monkeypatch):
    store = ApprovalStore(tmp_path / "s")
    assert store.get("nope") is None
    assert store.decide("nope", approved=True) is None
    assert store.consume("nope") is None

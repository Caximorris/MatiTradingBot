"""Contract tests for the stdlib-only Codex research-integrity hook."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


HOOKS = Path(__file__).resolve().parents[1] / ".codex" / "hooks"
sys.path.insert(0, str(HOOKS))

import evidence_contract  # noqa: E402
import guard_core  # noqa: E402
import lock_safety  # noqa: E402
import research_guard  # noqa: E402


def _sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _manifest(root: Path, *, python: str = "3.12.5") -> Path:
    identity = {
        "repository": {"worktree_sha256": "a" * 64},
        "environment": {"python": python, "dependencies": {"pandas": "2.0"}},
        "dataset": {"sha256": "b" * 64},
        "strategy": {"resolved_name": "test_strategy", "resolved_config": {}},
        "external_inputs": [],
    }
    payload = {
        "metrics": {"cagr": "0.10"},
        "trades_sha256": "c" * 64,
        "equity_curve_sha256": "d" * 64,
    }
    document = {
        "schema_version": 1,
        "run_id": _sha256(identity),
        "identity": identity,
        "result": {"sha256": _sha256(payload), **payload},
        "artifacts": [],
    }
    destination = root / "backtests" / "manifests" / f"{document['run_id']}.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(document), encoding="utf-8")
    return destination


def test_policy_has_complete_tiered_control_contract() -> None:
    policy = guard_core.load_policy()
    required = {
        "trigger", "purpose", "order", "conditions", "tier", "max_runtime_seconds",
        "frequency", "changed_file_scope", "behavior", "validation", "outputs",
        "cache_strategy", "reuse_conditions", "success_reusable",
    }

    assert {row["id"] for row in policy["controls"]} == {
        "integrity-classify", "integrity-static-diff", "integrity-targeted",
        "evidence-contract", "completion-engineering", "research-verdict",
    }
    assert all(required <= set(row) for row in policy["controls"])
    assert max(row["tier"] for row in policy["controls"]) == 3
    assert guard_core.focal_tests({"docs"}, policy) == []


def test_hook_configuration_covers_shell_command_mutations() -> None:
    config = json.loads((Path(__file__).resolve().parents[1] / ".codex" / "hooks.json").read_text())

    assert re.fullmatch(config["hooks"]["PreToolUse"][0]["matcher"], "shell_command")
    assert re.fullmatch(config["hooks"]["PostToolUse"][0]["matcher"], "shell_command")


def _pre_shell(command: str, capsys: pytest.CaptureFixture[str]) -> dict:
    assert research_guard.handle_pre({"tool_name": "shell_command", "tool_input": {"command": command}}) == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    ("command", "expected_reason"),
    [
        ("Set-Content data/cache/BTC-USDT_1H.json '{}'", "Protected repository path"),
        ("echo '{}' > data/cache/BTC-USDT_1H.json", "Protected repository path"),
        ("Remove-Item '.\\data\\cache\\BTC-USDT_1H.json'", "Protected repository path"),
        ("cmd.exe /c del data\\cache\\BTC-USDT_1H.json", "unclassified nested shell"),
        ("python -c \"from pathlib import Path; Path('data/cache/BTC-USDT_1H.json').write_text('x')\"", "Python shell execution"),
        ("Set-Content strategies/indicators.py x; unknown-mutator data/cache/BTC-USDT_1H.json", "Unrecognized shell command"),
    ],
)
def test_shell_mutation_bypasses_are_blocked(
    command: str, expected_reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    response = _pre_shell(command, capsys)

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert expected_reason in response["hookSpecificOutput"]["permissionDecisionReason"]


def test_shell_read_only_commands_and_known_source_edits_are_classified(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert guard_core.shell_mutation_paths("git status --short") == ([], None)
    assert guard_core.shell_mutation_paths("Get-Content .codex\\hooks\\guard_core.py") == ([], None)
    paths, error = guard_core.shell_mutation_paths("Set-Content .codex\\hooks\\guard_core.py '# x'")
    assert (paths, error) == ([".codex/hooks/guard_core.py"], None)
    assert guard_core.classify(paths, guard_core.load_policy()) == {"hooks"}
    assert guard_core.focal_tests({"hooks"}, guard_core.load_policy()) == ["tests/test_research_hooks.py"]
    monkeypatch.setattr(research_guard, "update_touched", lambda *_args, **_kwargs: None)
    response = _pre_shell("Set-Content .codex\\hooks\\guard_core.py '# x'", capsys)
    assert "Changed scopes: hooks" in response["hookSpecificOutput"]["additionalContext"]


def test_shell_path_normalization_is_case_insensitive_and_expands_static_environment(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOOK_CACHE", "data/cache/BTC-USDT_1H.json")
    paths, error = guard_core.shell_mutation_paths("Set-Content $env:HOOK_CACHE x")

    assert error is None
    assert paths == ["data/cache/BTC-USDT_1H.json"]
    assert guard_core.protected("DATA\\CACHE\\BTC-USDT_1H.JSON", guard_core.load_policy())


def test_unknown_shell_commands_never_bypass_classification() -> None:
    paths, error = guard_core.shell_mutation_paths("opaque-tool --write maybe")

    assert paths == []
    assert error and "Unrecognized shell command" in error


def test_tool_paths_handles_edit_fields_and_rejects_traversal(tmp_path: Path) -> None:
    payload = {
        "tool_input": {
            "file_path": "strategies/indicators.py",
            "patch": "*** Update File: tests/test_x.py\n+--- a/tests/test_x.py\n",
            "nested": {"path": "../outside.py"},
        }
    }

    assert guard_core.tool_paths(payload, tmp_path) == [
        "strategies/indicators.py", "tests/test_x.py"
    ]

    root = Path(__file__).resolve().parents[1]
    assert guard_core.tool_paths(payload, root) == [
        "strategies/indicators.py", "tests/test_x.py"
    ]


def test_parse_status_preserves_rename_endpoints() -> None:
    status = guard_core.parse_status("R  strategies/new.py\0strategies/old.py\0?? docs/new.md\0")

    assert status["strategies/new.py"] == {"staged", "renamed"}
    assert status["strategies/old.py"] == {"renamed", "deleted"}
    assert status["docs/new.md"] == {"untracked"}


def test_static_checks_reject_requests_and_new_line_limit_regression(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("import requests\n" + "x = 1\n" * 801, encoding="utf-8")

    findings = guard_core.static_file_findings("bad.py", 800, root=tmp_path)

    assert any("forbidden requests import" in finding for finding in findings)
    assert any("800-line ratchet" in finding for finding in findings)


def test_manifest_and_report_require_immutable_identity_linkage(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    valid, run_id = evidence_contract.validate_manifest(tmp_path, manifest)
    report = tmp_path / "reports" / "summary.md"
    report.parent.mkdir()
    result_hash = json.loads(manifest.read_text(encoding="utf-8"))["result"]["sha256"]
    report.write_text(f"source {run_id}\nresult {result_hash}\n", encoding="utf-8")

    assert valid
    assert evidence_contract.validate_report_provenance(tmp_path, report, [manifest]) == (
        True, "report provenance linked"
    )
    report.write_text(f"source {run_id}\n", encoding="utf-8")
    assert not evidence_contract.validate_report_provenance(tmp_path, report, [manifest])[0]


def test_manifest_rejects_unsupported_python_and_incomplete_swing_evidence(tmp_path: Path) -> None:
    unsupported = _manifest(tmp_path, python="3.14.0")
    assert "supported research interpreter" in evidence_contract.validate_manifest(tmp_path, unsupported)[1]

    swing = _manifest(tmp_path / "swing")
    document = json.loads(swing.read_text(encoding="utf-8"))
    document["identity"]["strategy"] = {"resolved_name": "swing_allocator", "resolved_config": {}}
    document["run_id"] = _sha256(document["identity"])
    swing = swing.with_name(f"{document['run_id']}.json")
    swing.write_text(json.dumps(document), encoding="utf-8")
    assert "BTC-holder comparison metrics" in evidence_contract.validate_manifest(tmp_path / "swing", swing)[1]


def test_tier3_cli_returns_structured_fail_closed_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        research_guard,
        "validate_tier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Python 3.12 required")),
    )

    assert research_guard.cli(["validate", "--tier", "3", "--reason", "test"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "fingerprint": "", "message": "Python 3.12 required", "reused": False, "success": False
    }


def _lock_owner(token: str = "dead", **changes) -> dict:
    owner = lock_safety.owner_record(token)
    owner.update(changes)
    return owner


def _write_lock(lock: Path, owner: object) -> None:
    lock.mkdir()
    (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")


def test_state_lock_preserves_live_owner_beyond_heartbeat_ttl(tmp_path: Path) -> None:
    lock = guard_core.state_root(tmp_path) / ".lock"
    _write_lock(lock, _lock_owner(heartbeat_at=time.time() - 120, created_at=time.time() - 120))

    with pytest.raises(TimeoutError, match="unsafe"):
        with guard_core.state_lock(tmp_path, timeout=0.05):
            pass
    assert lock.exists()


def test_state_lock_recovers_abandoned_and_pid_reused_owner(tmp_path: Path, monkeypatch) -> None:
    lock = guard_core.state_root(tmp_path) / ".lock"
    _write_lock(lock, _lock_owner(pid=999_999_999, process_start=None))
    monkeypatch.setattr(lock_safety, "_pid_alive", lambda _pid: False)

    with guard_core.state_lock(tmp_path, timeout=0.1):
        assert lock.exists()
    assert not lock.exists()

    _write_lock(lock, _lock_owner(pid=123, process_start="procfs:old"))
    monkeypatch.setattr(lock_safety, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(lock_safety, "process_start_identity", lambda _pid: "procfs:new")
    with guard_core.state_lock(tmp_path, timeout=0.1):
        assert lock.exists()
    assert not lock.exists()


def test_state_lock_fails_safely_for_malformed_owner_and_refreshes_heartbeat(tmp_path: Path) -> None:
    lock = guard_core.state_root(tmp_path) / ".lock"
    _write_lock(lock, {"pid": 1})
    with pytest.raises(TimeoutError, match="unsafe"):
        with guard_core.state_lock(tmp_path, timeout=0.05):
            pass
    assert lock.exists()
    (lock / "owner.json").unlink()
    lock.rmdir()

    lock.mkdir()
    owner = _lock_owner("heartbeat")
    (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    assert lock_safety.refresh_heartbeat(lock, "heartbeat")
    assert json.loads((lock / "owner.json").read_text(encoding="utf-8"))["heartbeat_at"] >= owner["heartbeat_at"]
    assert lock_safety.release(lock, "heartbeat")
    assert not lock.exists()


def test_state_lock_serializes_concurrent_acquisition_and_preserves_session_updates(
    tmp_path: Path, monkeypatch
) -> None:
    acquired: list[int] = []
    barrier = threading.Barrier(2)

    def acquire(index: int) -> None:
        barrier.wait(timeout=1)
        with guard_core.state_lock(tmp_path, timeout=0.5):
            acquired.append(index)
            time.sleep(0.04)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(acquire, [1, 2]))
    assert sorted(acquired) == [1, 2]

    monkeypatch.setattr(guard_core, "head", lambda _root: "a" * 40)
    monkeypatch.setattr(guard_core, "worktree_status", lambda _root: {})
    guard_core.session_baseline("shared", tmp_path)
    barrier = threading.Barrier(2)

    def record(path: str) -> None:
        barrier.wait(timeout=1)
        guard_core.update_touched("shared", [path], ["hooks"], root=tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(record, [".codex/hooks/a.py", ".codex/hooks/b.py"]))

    resumed = guard_core.session_baseline("shared", tmp_path)
    assert set(resumed["touched"]) == {".codex/hooks/a.py", ".codex/hooks/b.py"}


def _specialist_receipt(agent: str, skill: str, digest: str, verdict: str, gate_passed: bool) -> dict:
    return {
        "completed": True,
        "gate_passed": gate_passed,
        "agent": agent,
        "skill": skill,
        "fingerprint": digest,
        "verdict": verdict,
        "commands": [],
        "artifacts": [],
        "manifests": [],
        "hashes": {},
        "dataset_identity": {},
        "revision_tree_state": {},
        "limitations": [],
        "negative_evidence": [],
        "permissible_downstream_claims": [],
    }


def test_receipt_and_specialist_gate_validation_reject_malformed_or_contradictory_state(
    tmp_path: Path
) -> None:
    policy = guard_core.load_policy()
    agent = "data-integrity-auditor"
    contract = policy["specialist_registry"][agent]
    digest = "d" * 64
    receipt = _specialist_receipt(agent, contract["skill"], digest, "FIT", True)

    assert research_guard.specialist_receipt_error(receipt, agent, contract, digest, policy) == ""
    contradictory = {**receipt, "gate_passed": False}
    assert "contradicts" in research_guard.specialist_receipt_error(
        contradictory, agent, contract, digest, policy
    )
    malformed = {**receipt, "commands": "pytest"}
    assert "list evidence" in research_guard.specialist_receipt_error(
        malformed, agent, contract, digest, policy
    )

    guard_core.store_success(2, digest, {"reason": "test"}, tmp_path)
    assert guard_core.receipt_valid(2, digest, tmp_path)
    receipt_path = guard_core.receipt_path(2, digest, tmp_path)
    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
    saved["tier"] = 3
    receipt_path.write_text(json.dumps(saved), encoding="utf-8")
    assert not guard_core.receipt_valid(2, digest, tmp_path)

    guard_core.store_specialist(receipt, digest, tmp_path)
    assert guard_core.specialist_valid(agent, digest, tmp_path)
    assert guard_core.specialist_completed(agent, digest, tmp_path)


def test_completed_non_passing_specialist_receipt_warns_without_becoming_a_gate_pass(
    monkeypatch, capsys
) -> None:
    policy = guard_core.load_policy()
    agent = "data-integrity-auditor"
    contract = policy["specialist_registry"][agent]
    digest = "e" * 64
    receipt = _specialist_receipt(agent, contract["skill"], digest, "NOT_FIT", False)
    stored: list[dict] = []
    monkeypatch.setattr(research_guard, "active_fingerprint", lambda *_args: (digest, {"data"}))
    monkeypatch.setattr(research_guard, "store_specialist", lambda value, *_args: stored.append(value))
    monkeypatch.setattr(research_guard, "append_audit", lambda *_args, **_kwargs: None)

    assert research_guard.handle_subagent_stop({
        "agent_type": agent,
        "last_assistant_message": "RESEARCH_HOOK_RECEIPT: " + json.dumps(receipt),
    }) == 0
    response = json.loads(capsys.readouterr().out)

    assert response["continue"] is True
    assert "downstream claims are blocked" in response["systemMessage"]
    assert stored == [receipt]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("SessionStart", {"continue": True}),
        ("PreToolUse", {"permissionDecision": "deny"}),
        ("PostToolUse", {"decision": "block"}),
        ("Stop", {"continue": False}),
    ],
)
def test_dispatcher_uses_warning_or_blocking_response_by_event(
    event: str, expected: dict, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(research_guard, "append_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(research_guard, "safe_payload", lambda _event: (None, "malformed"))

    assert research_guard.dispatch(event) == 0
    response = json.loads(capsys.readouterr().out)
    if event == "PreToolUse":
        assert response["hookSpecificOutput"].items() >= expected.items()
    else:
        assert response.items() >= expected.items()

#!/usr/bin/env python3
"""Codex lifecycle dispatcher for MatiTradingBot research-integrity gates.

This entrypoint is deliberately stdlib-only. It never launches Codex, agents, live
commands, generic backtests, raw journal readers, optimization tools, or network work.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evidence_contract import validate_manifest, validate_report_provenance  # noqa: E402
from offline_guard import child_environment, is_isolated_build  # noqa: E402

from guard_core import (  # noqa: E402
    ROOT,
    append_audit,
    classify,
    command_text,
    current_initial_lines,
    focal_tests,
    forbidden_command,
    fingerprint,
    frozen_swing_change,
    get_session,
    is_commit,
    is_pr_create,
    line_count,
    load_policy,
    normalize_path,
    parameter_diff,
    protected,
    public_policy_summary,
    receipt_valid,
    required_specialists,
    resolve_interpreter,
    run,
    secret_kinds,
    session_baseline,
    shell_mutation_paths,
    specialist_completed,
    state_root,
    static_file_findings,
    store_specialist,
    store_success,
    touched_scope,
    tool_paths,
    update_session,
    update_touched,
    worktree_status,
)


MATERIAL = {
    "hooks", "swing", "strategy", "indicator", "data", "optimization", "risk",
    "execution", "backtest", "reporting", "dependency", "parameter",
}
BACKTEST_RELATED = {"strategy", "indicator", "optimization", "execution", "backtest", "swing"}
EXPERIMENT_COMMAND = re.compile(
    r"(?i)(?:main\.py\s+(?:backtest|walk-forward|baselines|sensitivity|compare|random-backtest)|"
    r"tools[/\\].*(?:matrix|frontier|bootstrap|rolling|stress|ablation|replay)\.py)"
)
REPORT_COMMAND = re.compile(r"(?i)tools[/\\].*(?:report|chart|audit)\.py")
MANIFEST_PATH = re.compile(r"backtests[/\\]manifests[/\\]([0-9a-f]{64})\.json")
REPORT_PATH = re.compile(r"(?:reports|backtests)[/\\][A-Za-z0-9_.-]+\.(?:json|md|html)")


def emit(value: dict[str, Any]) -> int:
    print(json.dumps(value, sort_keys=True))
    return 0


def pre_deny(reason: str) -> int:
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def post_block(reason: str, context: str | None = None) -> int:
    output: dict[str, Any] = {"decision": "block", "reason": reason}
    if context:
        output["hookSpecificOutput"] = {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    return emit(output)


def continuation(reason: str) -> int:
    return emit({"decision": "block", "reason": reason})


def safe_payload(event: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.load(sys.stdin)
        if not isinstance(value, dict):
            raise TypeError("hook input must be a JSON object")
        declared = value.get("hook_event_name")
        if declared and declared != event:
            raise ValueError(f"event mismatch: configured={event}, payload={declared}")
        return value, None
    except Exception as exc:
        return None, f"Malformed {event} hook input ({type(exc).__name__}); no input content retained"


def malformed_result(event: str, reason: str) -> int:
    append_audit({"event": event, "control": "integrity-classify", "success": False, "reason": reason})
    if event == "PreToolUse":
        return pre_deny(reason)
    if event == "PostToolUse":
        return post_block(reason)
    if event in {"SubagentStop", "Stop"}:
        return emit({"continue": False, "stopReason": reason, "systemMessage": reason})
    return emit({"continue": True, "systemMessage": reason})


def raw_patch_headers(command: str) -> list[str]:
    values: list[str] = []
    for line in command.splitlines():
        match = re.match(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", line)
        if match:
            values.append(match.group(1))
    return values


def path_scope(mode: str, policy: dict[str, Any]) -> tuple[list[str], set[str]]:
    status = worktree_status(ROOT)
    if mode == "staged":
        paths = sorted(path for path, states in status.items() if "staged" in states)
    else:
        paths = sorted(status)
    normalized = [path for raw in paths if (path := normalize_path(raw, ROOT))]
    return normalized, classify(normalized, policy)


def protected_changes(paths: list[str], policy: dict[str, Any]) -> list[str]:
    return sorted(path for path in paths if protected(path, policy))


def redact_output(text: str, limit: int = 4000) -> str:
    bounded = text[-limit:]
    for pattern in (
        r"\b(?:sk-|ghp_|xox[baprs]-)[A-Za-z0-9_-]{8,}",
        r"(?i)(api[_-]?key|secret|token|password)(\s*[:=]\s*)\S+",
    ):
        bounded = re.sub(pattern, lambda match: f"{match.group(1)}<redacted>" if match.lastindex else "<redacted>", bounded)
    return bounded


def execute_plan(
    commands: list[list[str]],
    *,
    timeout: float,
    control: str,
    digest: str,
    categories: set[str],
) -> tuple[bool, list[dict[str, Any]], str]:
    started = time.monotonic()
    ledger: list[dict[str, Any]] = []
    for command in commands:
        remaining = max(1.0, timeout - (time.monotonic() - started))
        try:
            child_env = child_environment(state_root(ROOT), offline=not is_isolated_build(command))
            result = run(command, root=ROOT, timeout=remaining, env=child_env)
        except Exception as exc:
            reason = f"{control} command failed to execute: {type(exc).__name__}"
            append_audit(
                {
                    "event": "validation", "control": control, "success": False,
                    "fingerprint": digest, "categories": sorted(categories), "reason": reason,
                    "commands": [command],
                }
            )
            return False, ledger, reason
        row = {
            "command": command,
            "returncode": result.returncode,
            "stdout_tail": redact_output(result.stdout),
            "stderr_tail": redact_output(result.stderr),
        }
        ledger.append(row)
        if result.returncode:
            detail = redact_output(result.stderr or result.stdout, limit=500).strip()
            suffix = f": {detail}" if detail else ""
            reason = f"{control} failed: {' '.join(command)} (exit {result.returncode}){suffix}"
            append_audit(
                {
                    "event": "validation", "control": control, "success": False,
                    "fingerprint": digest, "categories": sorted(categories), "reason": reason,
                    "commands": [item["command"] for item in ledger],
                }
            )
            return False, ledger, reason
    return True, ledger, ""


def synthetic_smoke() -> dict[str, Any]:
    """Run BacktestEngine twice on in-memory bars with network and artifact writes denied."""
    before = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("backtests/manifests/*", "backtests/journal_*.json", "reports/*")
        for path in ROOT.glob(pattern)
        if path.is_file()
    }
    original_socket = socket.socket
    original_urlopen = urllib.request.urlopen

    class DeniedSocket(original_socket):
        def connect(self, *_args, **_kwargs):
            raise AssertionError("network access forbidden in Tier2 smoke")

    def denied_urlopen(*_args, **_kwargs):
        raise AssertionError("network access forbidden in Tier2 smoke")

    socket.socket = DeniedSocket
    urllib.request.urlopen = denied_urlopen
    try:
        from core.backtest import BacktestClient, BacktestEngine
        from data.market_data import OHLCVBar

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bars = [
            OHLCVBar(
                timestamp=int((start + timedelta(hours=index)).timestamp() * 1000),
                open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
                close=Decimal("100"), volume=Decimal("10"),
            )
            for index in range(24)
        ]

        class NoOpStrategy:
            name = "research_hook_synthetic"

            def __init__(self, client):
                self.client = client

            def run(self):
                current = self.client.current_bar_ts()
                if current.tzinfo is None or current.utcoffset() != timedelta(0):
                    raise AssertionError("BacktestEngine timestamp is not UTC-aware")

        signatures: list[tuple[str, str, int, int]] = []
        for _ in range(2):
            client = BacktestClient(
                "BTC-USDT", bars, initial_balance=Decimal("1000"), cost_mode="realistic"
            )
            engine = BacktestEngine(
                client, lambda c, _session: NoOpStrategy(c), warmup_bars=20, timeframe="1H"
            )
            result = engine.run()
            if result.final_balance < 0 or not result.final_balance.is_finite():
                raise AssertionError("synthetic smoke produced invalid balance")
            signatures.append(
                (str(result.final_balance), str(result.max_drawdown_pct), result.bars_tested, len(result.trades))
            )
        if signatures[0] != signatures[1]:
            raise AssertionError("synthetic BacktestEngine smoke is not deterministic")
    finally:
        socket.socket = original_socket
        urllib.request.urlopen = original_urlopen
    after = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("backtests/manifests/*", "backtests/journal_*.json", "reports/*")
        for path in ROOT.glob(pattern)
        if path.is_file()
    }
    if after != before:
        raise AssertionError("Tier2 smoke generated research artifacts")
    return {"deterministic": True, "network": False, "artifacts": False, "signature": signatures[0]}


def validate_tier(
    tier: int,
    reason: str,
    *,
    session_id: str | None = None,
    mode: str = "interaction",
) -> tuple[bool, str, str, bool]:
    policy = load_policy()
    if mode == "interaction" and session_id:
        paths, categories, _ = touched_scope(session_id, ROOT)
        session = get_session(session_id, ROOT)
        paths = sorted(
            set(paths)
            | {path for path in session.get("evidence_paths", []) if isinstance(path, str)}
            | {path for path in session.get("report_paths", []) if isinstance(path, str)}
        )
    elif mode == "staged":
        paths, categories = path_scope("staged", policy)
    else:
        paths, categories = path_scope("publish", policy)
    blocked = protected_changes(paths, policy)
    if blocked:
        reason_text = f"protected paths changed: {', '.join(blocked)}"
        append_audit(
            {"event": "validation", "control": "integrity-static-diff", "success": False,
             "categories": sorted(categories), "paths": blocked, "reason": reason_text}
        )
        return False, reason_text, "", False

    categories = set(categories)
    tests = focal_tests(categories, policy, ROOT) if tier == 2 else []
    required_modules = {"build", "pytest", "ruff"} if tier == 3 else ({"pytest"} if tests else set())
    prefix, version, support = resolve_interpreter(
        ROOT, tier=tier, required_modules=required_modules
    )
    digest = fingerprint(paths, categories, policy, root=ROOT, interpreter=[*prefix, f"{version[0]}.{version[1]}"])
    if receipt_valid(tier, digest, ROOT):
        return True, f"reused Tier {tier} success receipt {digest[:12]}", digest, True
    if tier == 1:
        findings: list[str] = []
        for path in paths:
            findings.extend(static_file_findings(path, line_count(path, ROOT), root=ROOT))
        if findings:
            reason_text = "; ".join(findings)
            append_audit(
                {"event": "validation", "control": "integrity-static-diff", "success": False,
                 "fingerprint": digest, "categories": sorted(categories), "reason": reason_text}
            )
            return False, reason_text, digest, False
        store_success(1, digest, {"reason": reason, "categories": sorted(categories)}, ROOT)
        return True, f"Tier 1 passed ({support})", digest, False

    commands: list[list[str]] = []
    control = "integrity-targeted" if tier == 2 else "completion-engineering"
    if tier == 2:
        if tests:
            commands.append([*prefix, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests])
        if categories & BACKTEST_RELATED:
            commands.append([*prefix, str(Path(__file__).resolve()), "--internal-smoke"])
        if not commands:
            store_success(2, digest, {"reason": reason, "categories": sorted(categories), "commands": []}, ROOT)
            return True, f"Tier 2 fast path passed ({support})", digest, False
        timeout = 30
    else:
        for suffix in policy["tier3_commands"]:
            commands.append([*prefix, *suffix])
        timeout = 900
    success, ledger, failure = execute_plan(
        commands, timeout=timeout, control=control, digest=digest, categories=categories
    )
    if not success:
        return False, failure, digest, False
    store_success(
        tier,
        digest,
        {
            "reason": reason,
            "categories": sorted(categories),
            "commands": [row["command"] for row in ledger],
            "interpreter": {"prefix": prefix, "version": list(version), "support": support},
        },
        ROOT,
    )
    append_audit(
        {"event": "validation", "control": control, "success": True, "fingerprint": digest,
         "categories": sorted(categories), "commands": [row["command"] for row in ledger]}
    )
    warning = " with unsupported interpreter warning" if support != "supported" else ""
    return True, f"Tier {tier} passed{warning}", digest, False


def handle_session(payload: dict[str, Any]) -> int:
    baseline = session_baseline(payload.get("session_id"), ROOT)
    try:
        prefix, version, support = resolve_interpreter(ROOT, tier=1)
        environment = f"{prefix} -> {version[0]}.{version[1]} ({support})"
    except RuntimeError as exc:
        environment = str(exc)
    context = (
        f"Research integrity baseline captured at {baseline['head'][:12]}. "
        f"Interpreter: {environment}. Tier3 requires Python 3.12/3.13. "
        "Raw journals, generic data-audit exit status, optimization runners and live commands are not hook-safe."
    )
    return emit(
        {
            "continue": True,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
        }
    )


def handle_pre(payload: dict[str, Any]) -> int:
    policy = load_policy()
    command = command_text(payload)
    shell_paths: list[str] | None = None
    if str(payload.get("tool_name", "")) in {"Bash", "shell_command"}:
        shell_paths, shell_error = shell_mutation_paths(command, ROOT)
        if shell_error:
            return pre_deny(shell_error)
    forbidden = forbidden_command(command, policy)
    if forbidden:
        reason = f"Blocked command by repository policy: {forbidden}"
        append_audit({"event": "PreToolUse", "control": "integrity-static-diff", "success": False, "reason": reason})
        return pre_deny(reason)
    headers = raw_patch_headers(command)
    paths = shell_paths if shell_paths is not None else tool_paths(payload, ROOT)
    if headers and len(paths) < len(set(headers)):
        return pre_deny("Patch contains an outside-repository or path-traversal target")
    secret_types = secret_kinds(command)
    if secret_types:
        reason = f"Secret-like content blocked and redacted; finding types: {', '.join(secret_types)}"
        append_audit({"event": "PreToolUse", "control": "integrity-static-diff", "success": False, "reason": reason})
        return pre_deny(reason)
    blocked = [path for path in paths if protected(path, policy)]
    if blocked:
        reason = f"Protected repository path(s) cannot be edited by this hook flow: {', '.join(blocked)}"
        append_audit({"event": "PreToolUse", "control": "integrity-static-diff", "success": False, "paths": blocked, "reason": reason})
        return pre_deny(reason)
    if any(frozen_swing_change(path, command, policy) for path in paths):
        return pre_deny("Frozen Swing v6-2 default marker change blocked; explicit approved workflow is required")
    categories = classify(paths, policy)
    parameter = parameter_diff(command, policy) if paths else False
    if paths:
        update_touched(payload.get("session_id"), paths, categories, parameter_change=parameter, root=ROOT)

    if is_commit(command):
        staged, _ = path_scope("staged", policy)
        if protected_changes(staged, policy):
            return pre_deny("Commit contains protected paths")
        success, message, _, _ = validate_tier(2, "pre-commit", mode="staged")
        if not success:
            return pre_deny(f"Tier2 pre-commit gate failed: {message}")
    if is_pr_create(payload, command):
        publish_paths, publish_categories = path_scope("publish", policy)
        session = get_session(payload.get("session_id"), ROOT)
        publish_paths = sorted(
            set(publish_paths)
            | {path for path in session.get("evidence_paths", []) if isinstance(path, str)}
            | {path for path in session.get("report_paths", []) if isinstance(path, str)}
        )
        publish_categories.update(session.get("intent_categories", []))
        prefix, version, _ = resolve_interpreter(ROOT, tier=3)
        digest = fingerprint(
            publish_paths, publish_categories, policy, root=ROOT,
            interpreter=[*prefix, f"{version[0]}.{version[1]}"],
        )
        missing = [
            row["agent"] for row in required_specialists(publish_categories, policy)
            if not specialist_completed(row["agent"], digest, ROOT)
        ]
        if not receipt_valid(3, digest, ROOT) or missing:
            update_session(
                payload.get("session_id"),
                {"pending": {"fingerprint": digest, "categories": sorted(publish_categories), "mode": "publish"}},
                ROOT,
            )
            return pre_deny(
                "PR blocked: exact publish-fingerprint Tier3 engineering and specialist receipts are missing. "
                "Run `.codex/hooks/research_guard.py validate --tier 3 --reason pr`, then the mapped specialists. "
                f"Missing specialists: {', '.join(missing) if missing else 'none'}"
            )
    context = ""
    if categories:
        context = f"Changed scopes: {', '.join(sorted(categories))}"
        if parameter:
            context += "; parameter/default diff detected"
    if context:
        return emit(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context}}
        )
    return emit({})


def handle_post(payload: dict[str, Any]) -> int:
    policy = load_policy()
    command = command_text(payload)
    shell_paths, shell_error = shell_mutation_paths(command, ROOT) if str(payload.get("tool_name", "")) in {"Bash", "shell_command"} else (None, None)
    if shell_error:
        return post_block(shell_error)
    paths = shell_paths if shell_paths is not None else tool_paths(payload, ROOT)
    session = get_session(payload.get("session_id"), ROOT)
    findings: list[str] = []
    for path in paths:
        if protected(path, policy):
            findings.append(f"protected file changed despite pre-hook: {path}")
            continue
        findings.extend(
            static_file_findings(path, current_initial_lines(session, path), root=ROOT)
        )
    if findings:
        reason = "; ".join(findings)
        append_audit({"event": "PostToolUse", "control": "integrity-static-diff", "success": False, "paths": paths, "reason": reason})
        return post_block(reason)

    response_text = json.dumps(payload.get("tool_response"), sort_keys=True, default=str)
    if EXPERIMENT_COMMAND.search(command):
        manifests = sorted(set(MANIFEST_PATH.findall(response_text)))
        if not manifests:
            reason = "Experiment completed without a referenced current-schema manifest; research evidence is incomplete"
            append_audit({"event": "PostToolUse", "control": "evidence-contract", "success": False, "reason": reason})
            return post_block(reason)
        evidence_paths: list[str] = []
        for run_id in manifests:
            relative = f"backtests/manifests/{run_id}.json"
            ok, detail = validate_manifest(ROOT, ROOT / relative)
            if not ok:
                append_audit({"event": "PostToolUse", "control": "evidence-contract", "success": False, "manifests": [relative], "reason": detail})
                return post_block(f"Evidence contract failed: {detail}")
            evidence_paths.append(relative)
        intent = ["backtest"]
        if re.search(r"(?i)(?:matrix|frontier|bootstrap|rolling|stress|ablation|replay|sensitivity)", command):
            intent.append("optimization")
        update_session(
            payload.get("session_id"),
            {"evidence_paths": evidence_paths, "intent_categories": intent},
            ROOT,
        )
        append_audit({"event": "PostToolUse", "control": "evidence-contract", "success": True, "manifests": evidence_paths})
    elif REPORT_COMMAND.search(command):
        report_paths = [normalize_path(value, ROOT) for value in REPORT_PATH.findall(response_text)]
        safe_reports = [path for path in report_paths if path and (ROOT / path).is_file()]
        if not safe_reports:
            return post_block("Report command produced no verifiable in-repository report artifact")
        session = get_session(payload.get("session_id"), ROOT)
        manifests = [ROOT / path for path in session.get("evidence_paths", []) if isinstance(path, str)]
        linked = False
        for relative in safe_reports:
            ok, _ = validate_report_provenance(ROOT, ROOT / relative, manifests)
            if ok:
                linked = True
                break
        if not linked:
            reason = "Report provenance is incomplete: cite a validated source run_id and result hash"
            append_audit({"event": "PostToolUse", "control": "evidence-contract", "success": False, "artifacts": safe_reports, "reason": reason})
            return post_block(reason)
        update_session(
            payload.get("session_id"),
            {"intent_categories": ["reporting"], "report_paths": safe_reports},
            ROOT,
        )
        append_audit({"event": "PostToolUse", "control": "evidence-contract", "success": True, "artifacts": safe_reports})
    return emit({})


def specialist_contract(agent: str, policy: dict[str, Any]) -> dict[str, Any] | None:
    return policy["specialist_registry"].get(agent)


def active_fingerprint(payload: dict[str, Any], policy: dict[str, Any]) -> tuple[str, set[str]]:
    session = get_session(payload.get("session_id"), ROOT)
    pending = session.get("pending") or {}
    if pending.get("fingerprint"):
        return str(pending["fingerprint"]), set(pending.get("categories", []))
    paths, categories, _ = touched_scope(payload.get("session_id"), ROOT)
    evidence = [path for path in session.get("evidence_paths", []) if isinstance(path, str)]
    paths = sorted(set(paths + evidence))
    needs_pytest = bool(focal_tests(categories, policy, ROOT))
    prefix, version, _ = resolve_interpreter(
        ROOT, tier=2, required_modules={"pytest"} if needs_pytest else set()
    )
    return fingerprint(
        paths, categories, policy, root=ROOT, interpreter=[*prefix, f"{version[0]}.{version[1]}"],
    ), categories


def handle_subagent_start(payload: dict[str, Any]) -> int:
    policy = load_policy()
    agent = str(payload.get("agent_type", ""))
    contract = specialist_contract(agent, policy)
    if not contract:
        return emit({"continue": True})
    digest, _ = active_fingerprint(payload, policy)
    verdict_text = ", ".join(contract["verdicts"]) if contract["verdicts"] else "no invented verdict token"
    context = (
        f"Use ${contract['skill']}. Evidence fingerprint: {digest}. End with `RESEARCH_HOOK_RECEIPT:` "
        "followed by one JSON object containing completed, gate_passed, agent, skill, fingerprint, "
        "verdict, commands, artifacts, manifests, hashes, dataset_identity, revision_tree_state, "
        "limitations, negative_evidence, permissible_downstream_claims. "
        f"Allowed verdicts: {verdict_text}. Negative/invalid evidence must be preserved and gate_passed=false."
    )
    return emit(
        {
            "continue": True,
            "hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context},
        }
    )


def parse_specialist_receipt(message: str) -> dict[str, Any] | None:
    marker = "RESEARCH_HOOK_RECEIPT:"
    if marker not in message:
        return None
    tail = message.rsplit(marker, 1)[1].strip()
    fenced = re.match(r"```(?:json)?\s*(\{.*\})\s*```\s*$", tail, re.DOTALL)
    raw = fenced.group(1) if fenced else tail
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def specialist_receipt_error(
    receipt: dict[str, Any] | None,
    agent: str,
    contract: dict[str, Any],
    digest: str,
    policy: dict[str, Any],
) -> str:
    """Validate an untrusted specialist receipt before it becomes reusable state."""
    required = set(policy["specialist_receipt_schema"]["required"])
    if receipt is None:
        return "missing RESEARCH_HOOK_RECEIPT JSON"
    if required - set(receipt):
        return f"receipt missing fields: {', '.join(sorted(required - set(receipt)))}"
    list_fields = {
        "commands", "artifacts", "manifests", "limitations", "negative_evidence",
        "permissible_downstream_claims",
    }
    if any(not isinstance(receipt.get(field), list) for field in list_fields):
        return "receipt list evidence fields are malformed"
    if any(
        not isinstance(receipt.get(field), dict)
        for field in ("hashes", "dataset_identity", "revision_tree_state")
    ):
        return "receipt identity evidence fields are malformed"
    if receipt.get("completed") is not True or not isinstance(receipt.get("gate_passed"), bool):
        return "completed must be true and gate_passed must be boolean"
    if not isinstance(receipt.get("verdict"), str) or not receipt["verdict"].strip():
        return "receipt verdict must be a non-empty string"
    if receipt.get("agent") != agent or receipt.get("skill") != contract["skill"]:
        return "receipt agent/skill identity mismatch"
    if receipt.get("fingerprint") != digest:
        return "receipt fingerprint mismatch"
    if contract["verdicts"] and receipt["verdict"] not in contract["verdicts"]:
        return "receipt verdict is outside the agent contract"
    if contract["verdicts"]:
        expected_pass = receipt["verdict"] in contract["passing"]
        if receipt["gate_passed"] != expected_pass:
            return "gate_passed contradicts the verdict vocabulary"
    return ""


def handle_subagent_stop(payload: dict[str, Any]) -> int:
    policy = load_policy()
    agent = str(payload.get("agent_type", ""))
    contract = specialist_contract(agent, policy)
    if not contract:
        return emit({"continue": True})
    digest, _ = active_fingerprint(payload, policy)
    receipt = parse_specialist_receipt(str(payload.get("last_assistant_message") or ""))
    error = specialist_receipt_error(receipt, agent, contract, digest, policy)
    if error:
        append_audit({"event": "SubagentStop", "control": "research-verdict", "success": False, "agent": agent, "reason": error})
        if payload.get("stop_hook_active"):
            return emit({"continue": False, "stopReason": error, "systemMessage": error})
        return continuation(
            f"Specialist receipt incomplete: {error}. Preserve negative evidence and emit the exact JSON contract."
        )
    assert receipt is not None
    store_specialist(receipt, digest, ROOT)
    if receipt["gate_passed"]:
        return emit({"continue": True})
    reason = (
        f"{agent} completed with non-passing evidence ({receipt.get('verdict')}); downstream claims are blocked. "
        f"Limitations: {receipt.get('limitations', [])}"
    )
    return emit({"continue": True, "systemMessage": reason})


def set_pending(session_id: str | None, digest: str, categories: set[str], mode: str) -> None:
    update_session(
        session_id,
        {"pending": {"fingerprint": digest, "categories": sorted(categories), "mode": mode}},
        ROOT,
    )


def handle_stop(payload: dict[str, Any]) -> int:
    policy = load_policy()
    session_id = payload.get("session_id")
    paths, categories, _ = touched_scope(session_id, ROOT)
    categories = set(categories)
    if not (categories & MATERIAL):
        return emit({"continue": True})
    success, message, _, _ = validate_tier(2, "task-stop", session_id=session_id, mode="interaction")
    if not success:
        append_audit({"event": "Stop", "control": "integrity-targeted", "success": False, "categories": sorted(categories), "reason": message})
        if payload.get("stop_hook_active"):
            return emit({"continue": False, "stopReason": message, "systemMessage": message})
        return continuation(f"Tier2 targeted validation failed. Fix it before completion: {message}")
    try:
        prefix, version, _ = resolve_interpreter(ROOT, tier=3)
    except RuntimeError as exc:
        reason = f"Tier3 environment is not ready: {exc}"
        append_audit({"event": "Stop", "control": "completion-engineering", "success": False, "reason": reason})
        if payload.get("stop_hook_active"):
            return emit({"continue": False, "stopReason": reason, "systemMessage": reason})
        return continuation(reason)
    session = get_session(session_id, ROOT)
    evidence = [path for path in session.get("evidence_paths", []) if isinstance(path, str)]
    digest = fingerprint(
        sorted(set(paths + evidence)), categories, policy, root=ROOT,
        interpreter=[*prefix, f"{version[0]}.{version[1]}"],
    )
    specialists = required_specialists(categories, policy)
    missing = [row for row in specialists if not specialist_completed(row["agent"], digest, ROOT)]
    tier3_missing = not receipt_valid(3, digest, ROOT)
    if not missing and not tier3_missing:
        return emit({"continue": True})
    if payload.get("stop_hook_active"):
        reason = "Research completion remains blocked after one continuation; required receipts did not materialize"
        append_audit({"event": "Stop", "control": "research-verdict", "success": False, "fingerprint": digest, "reason": reason})
        return emit({"continue": False, "stopReason": reason, "systemMessage": reason})
    set_pending(session_id, digest, categories, "interaction")
    instructions: list[str] = []
    if tier3_missing:
        instructions.append(
            f"run `{Path(__file__).as_posix()} validate --tier 3 --reason completion --session-id {session_id}`"
        )
    for row in missing:
        instructions.append(f"spawn `{row['agent']}` using `${row['skill']}` for fingerprint {digest}")
    reason = (
        "Tier2 passed, but material completion requires exact-fingerprint Tier3 evidence. "
        + "; then ".join(instructions)
        + ". Do not run walk-forward, Monte Carlo, sweeps, rolling starts or large backtests unless a frozen Tier3 research contract specifically requires them."
    )
    append_audit({"event": "Stop", "control": "research-verdict", "success": False, "fingerprint": digest, "categories": sorted(categories), "reason": reason})
    return continuation(reason)


def dispatch(event: str) -> int:
    payload, error = safe_payload(event)
    if error or payload is None:
        return malformed_result(event, error or "missing payload")
    handlers = {
        "SessionStart": handle_session,
        "PreToolUse": handle_pre,
        "PostToolUse": handle_post,
        "SubagentStart": handle_subagent_start,
        "SubagentStop": handle_subagent_stop,
        "Stop": handle_stop,
    }
    try:
        return handlers[event](payload)
    except Exception as exc:
        reason = f"{event} hook failed closed ({type(exc).__name__}): {str(exc)[:300]}"
        return malformed_result(event, reason)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", choices=("SessionStart", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop"))
    parser.add_argument("--internal-smoke", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("describe", help="Print the machine-readable hook catalog summary")
    validate_parser = subparsers.add_parser("validate", help="Run an explicit validation tier")
    validate_parser.add_argument("--tier", type=int, choices=(1, 2, 3), required=True)
    validate_parser.add_argument("--reason", required=True)
    validate_parser.add_argument("--session-id")
    args = parser.parse_args(argv)
    if args.internal_smoke:
        print(json.dumps(synthetic_smoke(), sort_keys=True))
        return 0
    if args.event:
        return dispatch(args.event)
    if args.command == "describe":
        print(json.dumps(public_policy_summary(load_policy()), indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        mode = "publish" if "pr" in args.reason.lower() or "release" in args.reason.lower() else "interaction"
        try:
            success, message, digest, reused = validate_tier(
                args.tier, args.reason, session_id=args.session_id, mode=mode
            )
        except RuntimeError as exc:
            print(json.dumps({"success": False, "message": str(exc), "fingerprint": "", "reused": False}, sort_keys=True))
            return 1
        print(json.dumps({"success": success, "message": message, "fingerprint": digest, "reused": reused}, sort_keys=True))
        return 0 if success else 1
    parser.error("choose --event, describe, or validate")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())

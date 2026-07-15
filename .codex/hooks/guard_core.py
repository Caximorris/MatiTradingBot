"""Pure helpers for the Codex research-integrity command hook."""
from __future__ import annotations

import ast
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(__file__).with_name("policy.json")
SCRIPT_PATH = Path(__file__).with_name("research_guard.py")


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def repo_key(root: Path = ROOT) -> str:
    return hashlib.sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest()[:16]


def state_root(root: Path = ROOT) -> Path:
    base = Path(tempfile.gettempdir()) / "matitradingbot-codex-hooks-v1" / repo_key(root)
    base.mkdir(parents=True, exist_ok=True)
    return base


@contextlib.contextmanager
def state_lock(root: Path = ROOT, timeout: float = 1.0):
    lock = state_root(root) / ".lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError("research hook state lock timed out")
            time.sleep(0.02)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.rmdir()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def run(
    args: list[str],
    *,
    root: Path = ROOT,
    timeout: float = 5,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
        shell=False,
    )


def git(args: list[str], *, root: Path = ROOT, timeout: float = 3) -> str:
    completed = run(["git", *args], root=root, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def normalize_path(value: str, root: Path = ROOT) -> str | None:
    raw = value.strip().strip("\"'").replace("\\", "/")
    if not raw or raw in {"/dev/null", "NUL"}:
        return None
    candidate = Path(raw)
    absolute = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = absolute.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    if relative == "." or ".." in PurePosixPath(relative).parts:
        return None
    return relative


def patch_paths(command: str, root: Path = ROOT) -> list[str]:
    found: list[str] = []
    patterns = (
        r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$",
        r"^\+\+\+\s+(?:[ab]/)?(.+?)\s*$",
        r"^---\s+(?:[ab]/)?(.+?)\s*$",
        r"^rename (?:from|to)\s+(.+?)\s*$",
    )
    for line in command.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                normalized = normalize_path(match.group(1), root)
                if normalized and normalized not in found:
                    found.append(normalized)
                break
    return found


def parse_status(raw: str) -> dict[str, set[str]]:
    """Parse porcelain-v1 -z, preserving both rename endpoints."""
    tokens = raw.split("\0")
    result: dict[str, set[str]] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token or len(token) < 4:
            continue
        xy, path = token[:2], token[3:]
        states: set[str] = set()
        if xy == "??":
            states.add("untracked")
        else:
            if xy[0] != " ":
                states.add("staged")
            if xy[1] != " ":
                states.add("unstaged")
            if "D" in xy:
                states.add("deleted")
            if "R" in xy or "C" in xy:
                states.add("renamed")
        result.setdefault(path.replace("\\", "/"), set()).update(states)
        if "R" in xy or "C" in xy:
            if index < len(tokens) and tokens[index]:
                old = tokens[index].replace("\\", "/")
                index += 1
                result.setdefault(old, set()).update({"renamed", "deleted"})
    return result


def worktree_status(root: Path = ROOT) -> dict[str, set[str]]:
    raw = git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], root=root)
    return parse_status(raw)


def head(root: Path = ROOT) -> str:
    return git(["rev-parse", "HEAD"], root=root).strip()


def session_path(session_id: str | None, root: Path = ROOT) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return state_root(root) / "sessions" / f"{safe}.json"


def session_baseline(session_id: str | None, root: Path = ROOT) -> dict[str, Any]:
    status = worktree_status(root)
    baseline = {
        "head": head(root),
        "initial_status": {path: sorted(states) for path, states in status.items()},
        "touched": {},
        "continued": [],
        "created_at": time.time(),
    }
    with state_lock(root):
        atomic_json(session_path(session_id, root), baseline)
    return baseline


def get_session(session_id: str | None, root: Path = ROOT) -> dict[str, Any]:
    path = session_path(session_id, root)
    current = read_json(path, {})
    if not current or current.get("head") != head(root):
        return session_baseline(session_id, root)
    return current


def update_touched(
    session_id: str | None,
    paths: Iterable[str],
    categories: Iterable[str],
    *,
    parameter_change: bool = False,
    root: Path = ROOT,
) -> dict[str, Any]:
    existing = get_session(session_id, root)
    with state_lock(root):
        session = read_json(session_path(session_id, root), {}) or existing
        touched = session.setdefault("touched", {})
        for path in paths:
            row = touched.setdefault(path, {"categories": [], "initial_lines": line_count(path, root)})
            row["categories"] = sorted(set(row.get("categories", [])) | set(categories))
            if parameter_change:
                row["parameter_change"] = True
        atomic_json(session_path(session_id, root), session)
    return session


def update_session(session_id: str | None, updates: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    existing = get_session(session_id, root)
    with state_lock(root):
        session = read_json(session_path(session_id, root), {}) or existing
        session.update(updates)
        atomic_json(session_path(session_id, root), session)
    return session


def append_audit(event: dict[str, Any], root: Path = ROOT) -> None:
    """Preserve bounded positive and negative evidence; never use this as a success cache."""
    allowed = {
        "event", "control", "success", "fingerprint", "categories", "paths", "reason",
        "agent", "skill", "verdict", "completed", "gate_passed", "runtime_seconds",
        "commands", "artifacts", "manifests", "limitations", "negative_evidence",
        "hashes", "dataset_identity", "revision_tree_state", "permissible_downstream_claims",
    }
    bounded = {key: event[key] for key in allowed if key in event}
    bounded["created_at"] = time.time()
    path = state_root(root) / "audit.jsonl"
    with state_lock(root):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bounded, sort_keys=True) + "\n")


def touched_scope(session_id: str | None, root: Path = ROOT) -> tuple[list[str], set[str], bool]:
    session = get_session(session_id, root)
    paths = sorted(session.get("touched", {}))
    categories: set[str] = set()
    parameter = False
    for row in session.get("touched", {}).values():
        categories.update(row.get("categories", []))
        parameter = parameter or bool(row.get("parameter_change"))
    if parameter:
        categories.add("parameter")
    categories.update(session.get("intent_categories", []))
    return paths, categories, parameter


def matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def protected(path: str, policy: dict[str, Any]) -> bool:
    return matches(path, policy["protected_patterns"])


def classify(paths: Iterable[str], policy: dict[str, Any]) -> set[str]:
    categories: set[str] = set()
    for path in paths:
        for name, patterns in policy["categories"].items():
            if matches(path, patterns):
                categories.add(name)
    return categories


def changed_lines(command: str) -> list[str]:
    return [
        line[1:]
        for line in command.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def parameter_diff(command: str, policy: dict[str, Any]) -> bool:
    lines = changed_lines(command)
    assignment = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*(?::[^=]+)?=\s*(?:[-+]?\d|True|False|None|['\"])")
    return any(assignment.search(line) for line in lines) or any(
        marker in line for marker in policy["frozen_swing_markers"] for line in lines
    )


def frozen_swing_change(path: str, command: str, policy: dict[str, Any]) -> bool:
    return path == "strategies/swing_allocator.py" and any(
        marker in line
        for marker in policy["frozen_swing_markers"]
        for line in changed_lines(command)
    )


SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "api-token": re.compile(r"\b(?:sk-|ghp_|xox[baprs]-)[A-Za-z0-9_-]{12,}"),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+_.-]{12,}"
    ),
}


def secret_kinds(text: str) -> list[str]:
    return sorted(name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text))


def requests_import(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:import\s+requests\b|from\s+requests\b)", text))


def line_count(path: str, root: Path = ROOT) -> int | None:
    absolute = root / path
    try:
        with absolute.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except (OSError, UnicodeError):
        return None


def static_file_findings(
    path: str,
    initial_lines: int | None,
    *,
    root: Path = ROOT,
) -> list[str]:
    absolute = root / path
    if not path.endswith(".py") or not absolute.is_file():
        return []
    try:
        text = absolute.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [f"cannot safely read changed Python source: {path}"]
    findings: list[str] = []
    try:
        ast.parse(text, filename=path)
    except SyntaxError as exc:
        findings.append(f"Python syntax error in {path}:{exc.lineno}: {exc.msg}")
    if requests_import(text):
        findings.append(f"forbidden requests import in {path}; use aiohttp or urllib.request")
    current_lines = len(text.splitlines())
    if current_lines > 800 and (initial_lines is None or current_lines > initial_lines):
        findings.append(
            f"800-line ratchet exceeded in {path}: initial={initial_lines}, current={current_lines}"
        )
    return findings


def safe_file_hash(path: str, policy: dict[str, Any], root: Path = ROOT) -> str:
    if protected(path, policy):
        return "PROTECTED"
    absolute = root / path
    if not absolute.exists():
        return "DELETED"
    if not absolute.is_file():
        return "NONFILE"
    digest = hashlib.sha256()
    with absolute.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(
    paths: Iterable[str],
    categories: Iterable[str],
    policy: dict[str, Any],
    *,
    root: Path = ROOT,
    interpreter: Iterable[str] = (),
) -> str:
    instruction_hashes: dict[str, str] = {}
    for candidate in sorted((root / ".codex" / "agents").glob("*.toml")):
        instruction_hashes[candidate.relative_to(root).as_posix()] = hashlib.sha256(
            candidate.read_bytes()
        ).hexdigest()
    for candidate in sorted((root / ".codex" / "skills").glob("*/SKILL.md")):
        instruction_hashes[candidate.relative_to(root).as_posix()] = hashlib.sha256(
            candidate.read_bytes()
        ).hexdigest()
    payload = {
        "head": head(root),
        "paths": {path: safe_file_hash(path, policy, root) for path in sorted(set(paths))},
        "categories": sorted(set(categories)),
        "policy": hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
        "guard": hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest(),
        "guard_core": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "specialist_instructions": instruction_hashes,
        "interpreter": list(interpreter),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def receipt_path(tier: int, digest: str, root: Path = ROOT) -> Path:
    return state_root(root) / "receipts" / f"tier{tier}" / f"{digest}.json"


def receipt_valid(tier: int, digest: str, root: Path = ROOT) -> bool:
    row = read_json(receipt_path(tier, digest, root), {})
    return row.get("success") is True and row.get("fingerprint") == digest


def store_success(tier: int, digest: str, details: dict[str, Any], root: Path = ROOT) -> None:
    value = {"success": True, "fingerprint": digest, "tier": tier, "created_at": time.time(), **details}
    with state_lock(root):
        atomic_json(receipt_path(tier, digest, root), value)


def specialist_path(agent: str, digest: str, root: Path = ROOT) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", agent)
    return state_root(root) / "specialists" / digest / f"{safe}.json"


def specialist_valid(agent: str, digest: str, root: Path = ROOT) -> bool:
    row = read_json(specialist_path(agent, digest, root), {})
    return row.get("success") is True and row.get("fingerprint") == digest


def specialist_completed(agent: str, digest: str, root: Path = ROOT) -> bool:
    row = read_json(specialist_path(agent, digest, root), {})
    return row.get("completed") is True and row.get("fingerprint") == digest


def store_specialist(receipt: dict[str, Any], digest: str, root: Path = ROOT) -> None:
    agent = str(receipt["agent"])
    value = {
        "success": bool(receipt.get("gate_passed")),
        "completed": bool(receipt.get("completed")),
        "gate_passed": bool(receipt.get("gate_passed")),
        "agent": agent,
        "skill": receipt.get("skill"),
        "verdict": receipt.get("verdict"),
        "fingerprint": digest,
        "commands": receipt.get("commands", []),
        "artifacts": receipt.get("artifacts", []),
        "manifests": receipt.get("manifests", []),
        "hashes": receipt.get("hashes", {}),
        "dataset_identity": receipt.get("dataset_identity", {}),
        "revision_tree_state": receipt.get("revision_tree_state", {}),
        "limitations": receipt.get("limitations", []),
        "negative_evidence": receipt.get("negative_evidence", []),
        "permissible_downstream_claims": receipt.get("permissible_downstream_claims", []),
        "created_at": time.time(),
    }
    with state_lock(root):
        atomic_json(specialist_path(agent, digest, root), value)
    append_audit({"event": "specialist", "fingerprint": digest, **value}, root)


def interpreter_version(prefix: list[str], root: Path = ROOT) -> tuple[int, int] | None:
    try:
        completed = run(
            [*prefix, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            root=root,
            timeout=3,
        )
        if completed.returncode:
            return None
        major, minor = completed.stdout.strip().split(".", 1)
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def resolve_interpreter(root: Path = ROOT, *, tier: int) -> tuple[list[str], tuple[int, int], str]:
    candidates: list[list[str]] = []
    override = os.environ.get("MATIBOT_HOOK_PYTHON")
    if override:
        candidates.append([override])
    if os.name == "nt":
        candidates.extend(
            [
                [str(root / ".venv" / "Scripts" / "python.exe")],
                ["py", "-3.13"],
                ["py", "-3.12"],
                ["python"],
            ]
        )
    else:
        candidates.extend(
            [
                [str(root / ".venv" / "bin" / "python")],
                ["python3.13"],
                ["python3.12"],
                ["python3"],
            ]
        )
    seen: set[tuple[str, ...]] = set()
    fallback: tuple[list[str], tuple[int, int]] | None = None
    for prefix in candidates:
        key = tuple(prefix)
        if key in seen:
            continue
        seen.add(key)
        version = interpreter_version(prefix, root)
        if version in {(3, 12), (3, 13)}:
            return prefix, version, "supported"
        if version and fallback is None:
            fallback = (prefix, version)
    if tier <= 2 and fallback:
        return fallback[0], fallback[1], "unsupported-warning"
    version_text = f"; found {fallback[1][0]}.{fallback[1][1]}" if fallback else ""
    raise RuntimeError(f"Python 3.12 or 3.13 is required for Tier {tier}{version_text}")


def command_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    value = tool_input.get("command")
    if isinstance(value, str):
        return value
    return json.dumps(tool_input, sort_keys=True)


def is_commit(command: str) -> bool:
    return bool(re.search(r"(?i)(?:^|[\s;&])git\s+commit(?:\s|$)", command))


def is_pr_create(payload: dict[str, Any], command: str) -> bool:
    tool = str(payload.get("tool_name", ""))
    return "create_pull_request" in tool or bool(
        re.search(r"(?i)(?:^|[\s;&])gh\s+pr\s+create(?:\s|$)", command)
    )


def forbidden_command(command: str, policy: dict[str, Any]) -> str | None:
    lowered = command.lower().replace("\\", "/")
    for forbidden in policy["forbidden_commands"]:
        if forbidden.lower().replace("\\", "/") in lowered:
            return forbidden
    destructive = (
        "git reset --hard",
        "git clean -fd",
        "git push --force",
        "git checkout --",
    )
    return next((item for item in destructive if item in lowered), None)


def required_specialists(categories: Iterable[str], policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in sorted(set(categories)):
        for row in policy["specialists"].get(category, []):
            if row["agent"] not in seen:
                rows.append(row)
                seen.add(row["agent"])
    return rows


def focal_tests(categories: Iterable[str], policy: dict[str, Any], root: Path = ROOT) -> list[str]:
    tests: set[str] = set()
    for category in categories:
        tests.update(policy["tier2_tests"].get(category, []))
    return sorted(test for test in tests if (root / test).is_file())


def current_initial_lines(session: dict[str, Any], path: str) -> int | None:
    row = session.get("touched", {}).get(path, {})
    value = row.get("initial_lines")
    return value if isinstance(value, int) else None


def public_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": policy["schema_version"],
        "controls": [
            {
                key: row[key]
                for key in (
                    "id", "tier", "trigger", "max_runtime_seconds", "frequency",
                    "changed_file_scope", "behavior", "success_reusable", "reuse_conditions",
                )
            }
            for row in sorted(policy["controls"], key=lambda item: item["order"])
        ],
        "known_blockers": policy["known_blockers"],
    }

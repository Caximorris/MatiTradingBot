"""Fail-closed classification for shell commands accepted by the research hook."""
from __future__ import annotations

import os
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHELL_MUTATORS = {
    "set-content", "add-content", "out-file", "remove-item", "move-item",
    "copy-item", "rename-item", "new-item", "del", "erase", "move", "copy", "ren",
}
SHELL_PYTHONS = {"python", "py", "python3", "python3.12", "python3.13"}
SHELL_READ_ONLY = {
    "cat", "dir", "echo", "get-childitem", "get-content", "get-location", "ls", "pwd", "rg",
    "select-string", "test-path", "type", "where", "write-output",
}


def normalize_path(value: str, root: Path) -> str | None:
    raw = value.strip().strip("\"'").replace("\\", "/")
    if not raw or raw in {"/dev/null", "NUL"}:
        return None
    candidate = Path(raw)
    absolute = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = absolute.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return None if relative == "." or ".." in Path(relative).parts else relative


def _shell_segments(command: str) -> list[str] | None:
    """Split only top-level shell chains; substitutions remain intentionally unsupported."""
    if re.search(r"`|\$\(|\$\{[^}]*\}\s*\(|\b(?:powershell|pwsh|cmd(?:\.exe)?)\b", command, re.I):
        return None
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for char in command:
        if char in "\"'":
            quote = "" if quote == char else (char if not quote else quote)
        if not quote and char in ";|&\n":
            if current:
                parts.append("".join(current).strip())
                current = []
            continue
        current.append(char)
    if quote:
        return None
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _expand_shell_variables(command: str, root: Path) -> str | None:
    values = {"PWD": str(root), "CD": str(root)} | {
        key.upper(): value for key, value in os.environ.items()
    }

    def replace(match: re.Match[str]) -> str:
        name = next(item for item in match.groups() if item is not None).upper()
        return values.get(name, match.group(0))

    expanded = re.sub(
        r"\$env:([A-Za-z_]\w*)|%([^%]+)%|\$\{?([A-Za-z_]\w*)\}?",
        replace,
        command,
        flags=re.I,
    )
    return None if re.search(r"\$env:|%[^%]+%|\$\{?[A-Za-z_]", expanded, re.I) else expanded


def _shell_tokens(segment: str) -> list[str]:
    return [token.strip("\"'") for token in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', segment)]


def _shell_path(value: str, root: Path) -> str | None:
    return None if any(marker in value for marker in ("*", "?", "[", "]")) else normalize_path(value, root)


def _resolved_shell_path(value: str, root: Path) -> Path | None:
    relative = _shell_path(value, root)
    try:
        candidate = root / relative if relative else None
        return None if candidate is None or candidate.is_symlink() else candidate.resolve(strict=True)
    except OSError:
        return None


def _option_values(args: list[str], names: set[str]) -> list[str]:
    return [args[index + 1] for index, value in enumerate(args[:-1]) if value.lower() in names]


def is_guard_cli(script: str, args: list[str], root: Path) -> bool:
    relative = Path(script.replace("\\", "/"))
    expected = root / ".codex" / "hooks" / "research_guard.py"
    if (
        relative.parts != (".codex", "hooks", "research_guard.py")
        or (root / relative).is_symlink()
        or _resolved_shell_path(script, root) != expected.resolve()
    ):
        return False
    if args == ["describe"]:
        return True
    if len(args) not in {5, 7} or args[:2] != ["validate", "--tier"]:
        return False
    if args[2] not in {"1", "2", "3"} or args[3] != "--reason" or not args[4]:
        return False
    return len(args) == 5 or (args[5] == "--session-id" and bool(args[6]))


def is_safe_pytest(args: list[str], root: Path) -> bool:
    if args[:3] != ["-m", "pytest", "-q"]:
        return False
    targets = args[3:]
    if targets[:2] == ["-p", "no:cacheprovider"]:
        targets = targets[2:]
    if not targets:
        return True
    tests_root = (root / "tests").resolve()
    return all(
        (path := _resolved_shell_path(target.split("::", 1)[0], root))
        and path.is_relative_to(tests_root)
        for target in targets
    )


def _is_safe_main_cli(script: str, args: list[str], root: Path) -> bool:
    expected = root / "main.py"
    if script.replace("\\", "/") != "main.py" or _resolved_shell_path(script, root) != expected.resolve():
        return False
    if args == ["--help"]:
        return True
    if len(args) == 2 and args[1] == "--help" and args[0] and not args[0].startswith("-"):
        return True
    if _is_safe_offline_backtest(args):
        return True
    return args in (["mode"], ["status"], ["paper-status"], ["anomaly-check"])


def _is_safe_offline_backtest(args: list[str]) -> bool:
    """Allow bounded local backtests; live and stateful commands remain forbidden elsewhere."""
    if not args or args[0] != "backtest":
        return False
    values: dict[str, str] = {}
    index = 1
    while index < len(args):
        key = args[index]
        if key not in {"--strategy", "--symbol", "--from", "--to", "--timeframe", "--balance", "--costs", "--config", "--verbose"}:
            return False
        if key == "--verbose":
            if key in values:
                return False
            values[key] = "true"
            index += 1
            continue
        if index + 1 >= len(args) or key in values:
            return False
        values[key] = args[index + 1]
        index += 2
    required = {"--strategy", "--from", "--to", "--costs"}
    if not required <= set(values):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]+", values["--strategy"]):
        return False
    if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[key]) for key in ("--from", "--to")):
        return False
    if values["--costs"] not in {"ideal", "realistic", "conservative"}:
        return False
    if "--symbol" in values and not re.fullmatch(r"[A-Z0-9]+-[A-Z0-9]+", values["--symbol"]):
        return False
    if "--timeframe" in values and not re.fullmatch(r"(?:\d+[mMhHdDwW])", values["--timeframe"]):
        return False
    if "--balance" in values:
        try:
            if float(values["--balance"]) <= 0:
                return False
        except ValueError:
            return False
    if "--config" in values:
        try:
            if not isinstance(json.loads(values["--config"]), dict):
                return False
        except json.JSONDecodeError:
            return False
    return True


def _is_trusted_python(token: str, root: Path) -> bool:
    normalized = token.replace("\\", "/")
    if "/" not in normalized:
        return normalized.lower().removesuffix(".exe") in SHELL_PYTHONS
    candidate = Path(normalized)
    if candidate.parts in {(".venv", "bin", "python"), (".venv", "Scripts", "python.exe")}:
        return True
    try:
        resolved = candidate.resolve(strict=True) if candidate.is_absolute() else (root / candidate).resolve(strict=True)
    except OSError:
        return False
    return resolved in {
        (root / ".venv" / "bin" / "python").resolve(),
        (root / ".venv" / "Scripts" / "python.exe").resolve(),
    }


def _is_safe_python_command(args: list[str], root: Path) -> bool:
    if is_safe_pytest(args, root):
        return True
    if args in (
        ["-m", "compileall", "-q", "."],
        ["-m", "build"],
        ["-m", "pip", "check"],
        ["-m", "ruff", "check", "."],
        ["tools/ruff_ratchet.py"],
    ):
        return True
    if args and is_guard_cli(args[0], args[1:], root):
        return True
    if args == ["tools/cross_asset_swing_matrix.py"]:
        return (root / args[0]).is_file()
    return bool(args) and _is_safe_main_cli(args[0], args[1:], root)


def _classify_git(args: list[str], root: Path) -> tuple[list[str], str | None]:
    if not args:
        return [], "Git command is not an approved read-only or publication operation"
    command, rest = args[0], args[1:]
    if command == "status" and all(
        value in {"--short", "--branch", "--porcelain", "--porcelain=v1"} for value in rest
    ):
        return [], None
    if command == "diff":
        options = {"--stat", "--check", "--name-status", "--cached", "--staged", "--quiet", "--exit-code"}
        if "--" in rest:
            separator = rest.index("--")
            flags, targets = rest[:separator], rest[separator + 1:]
        else:
            flags, targets = rest, []
        if all(value in options or value.startswith("--unified=") for value in flags) and all(
            normalize_path(value, root) for value in targets
        ):
            return [], None
    if command == "rev-parse" and rest in (
        ["HEAD"], ["--show-toplevel"], ["--abbrev-ref", "HEAD"],
    ):
        return [], None
    if command == "branch" and rest == ["--show-current"]:
        return [], None
    if command == "switch" and len(rest) == 2 and rest[0] == "-c" and _is_codex_branch(rest[1]):
        return [], None
    if command == "remote" and rest == ["-v"]:
        return [], None
    if command == "add" and rest[:1] == ["--"] and rest[1:]:
        targets = [normalize_path(value, root) for value in rest[1:]]
        return ([value for value in targets if value] if all(targets) else []), (
            None if all(targets) else "Git add target is outside the repository"
        )
    if command == "commit" and len(rest) == 2 and rest[0] == "-m" and rest[1].strip():
        return [], None
    if command == "push":
        publish = rest[1:] if rest[:1] == ["-u"] else rest
        if len(publish) == 2 and publish[0] == "origin" and _is_codex_branch(publish[1]):
            return [], None
    return [], "Git command is not an approved read-only or publication operation"


def _is_codex_branch(value: str) -> bool:
    forbidden = ("..", "@{", "//", "\\", ":", "~", "^", "?", "*", "[")
    return (
        value.startswith("codex/")
        and not any(marker in value for marker in forbidden)
        and not value.endswith(("/", ".", ".lock"))
        and "/." not in value
        and re.fullmatch(r"codex/[A-Za-z0-9][A-Za-z0-9._/-]*", value) is not None
    )


def _is_safe_ruff(args: list[str]) -> bool:
    return args in (["--version"], ["check", "."])


def shell_mutation_paths(command: str, root: Path = ROOT) -> tuple[list[str], str | None]:
    """Return classified mutation targets or a fail-closed reason."""
    expanded = _expand_shell_variables(command, root)
    segments = _shell_segments(expanded) if expanded is not None else None
    if not segments:
        return [], "Shell command contains an unclassified nested shell, substitution, variable, or quote"
    paths: list[str] = []

    def add(value: str) -> bool:
        path = _shell_path(value, root)
        if not path:
            return False
        if path not in paths:
            paths.append(path)
        return True

    for segment in segments:
        tokens = _shell_tokens(segment)
        if not tokens:
            continue
        name = Path(tokens[0].replace("\\", "/")).name.lower().removesuffix(".exe")
        args = tokens[1:]
        if is_guard_cli(tokens[0], args, root):
            continue
        redirects = re.findall(r"(?<![<>=])(?:\d?>{1,2})\s*(\"[^\"]*\"|'[^']*'|\S+)", segment)
        for target in redirects:
            if not target.lstrip().startswith("&") and not add(target):
                return [], "Shell redirection target is not a deterministic in-repository path"
        if name == "git":
            git_paths, git_error = _classify_git(args, root)
            if git_error:
                return [], git_error
            if not all(add(path) for path in git_paths):
                return [], "Git mutation lacks complete deterministic in-repository paths"
            continue
        if name == "ruff":
            if not _is_safe_ruff(args):
                return [], "Ruff command is not an approved read-only check"
            continue
        if name in SHELL_PYTHONS:
            if "-c" in args or "-" in args:
                return [], "Python shell execution is not an approved validation or read-only CLI command"
            if not _is_trusted_python(tokens[0], root):
                return [], "Python interpreter path is not trusted for validation"
            if not _is_safe_python_command(args, root):
                return [], "Python shell execution is not an approved validation or read-only CLI command"
        if name in SHELL_MUTATORS:
            if name in {"rename-item", "ren"}:
                return [], "Rename shell commands are not safely classifiable"
            named = _option_values(
                args, {"-path", "-literalpath", "-filepath", "-destination", "-outfilepath"}
            )
            positional = [
                value for index, value in enumerate(args)
                if not value.startswith("-") and (not index or not args[index - 1].startswith("-"))
            ]
            if name == "new-item" and not named:
                return [], "New-Item requires an explicit deterministic -Path or -LiteralPath"
            targets = (named or positional)[:2 if name in {"move-item", "copy-item", "move", "copy"} else 1]
            required = 2 if name in {"move-item", "copy-item", "move", "copy"} else 1
            if len(targets) != required or not all(add(target) for target in targets):
                return [], "Shell mutation lacks complete deterministic in-repository paths"
        elif name not in SHELL_READ_ONLY and not (
            name in SHELL_PYTHONS and _is_safe_python_command(args, root)
        ):
            return [], f"Unrecognized shell command '{tokens[0]}' is not classified read-only"
    return paths, None

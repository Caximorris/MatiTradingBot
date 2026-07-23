"""Owner-aware local lock for Codex hook state.

The lock directory is local to the host temp directory.  A heartbeat is recorded
for diagnostics, but expiry never steals a lock from a process that is still
alive: only a dead or identity-mismatched owner is reclaimable.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


STALE_SECONDS = 60.0


def owner_record(token: str) -> dict[str, Any]:
    return {
        "token": token, "pid": os.getpid(), "process_start": process_start_identity(os.getpid()),
        "host": socket.gethostname(), "session": session_identity(),
        "created_at": time.time(), "heartbeat_at": time.time(),
    }


def session_identity() -> str:
    for key in ("CODEX_SESSION_ID", "CODEX_THREAD_ID", "TERM_SESSION_ID", "SESSIONNAME"):
        if value := os.environ.get(key):
            return value
    return f"pid:{os.getpid()}"


def process_start_identity(pid: int) -> str | None:
    """Return a stable process incarnation where the local OS exposes one."""
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        tail = proc_stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return f"procfs:{tail[19]}"  # field 22, after state (field 3)
    except (OSError, IndexError, UnicodeError):
        return None


def _read_owner(lock: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    required = {"token", "pid", "host", "session", "created_at", "heartbeat_at", "process_start"}
    if not isinstance(value, dict) or set(value) != required:
        return None
    if not isinstance(value["token"], str) or not value["token"] or not isinstance(value["pid"], int):
        return None
    if value["pid"] <= 0 or not all(isinstance(value[key], str) and value[key] for key in ("host", "session")):
        return None
    if not all(isinstance(value[key], (int, float)) for key in ("created_at", "heartbeat_at")):
        return None
    if value["process_start"] is not None and not isinstance(value["process_start"], str):
        return None
    return value


def _pid_alive(pid: int) -> bool | None:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return _windows_tasklist_liveness(pid)
            code = wintypes.DWORD()
            try:
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == 259
                return _windows_tasklist_liveness(pid)
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return _windows_tasklist_liveness(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _windows_tasklist_liveness(pid: int) -> bool | None:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False, capture_output=True, text=True, timeout=1,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    return f'"{pid}"' in result.stdout


def owner_liveness(owner: dict[str, Any]) -> str:
    """Return live, dead, unknown, or malformed without trusting elapsed time."""
    required = _read_owner_from_value(owner)
    if required is None:
        return "malformed"
    if required["host"] != socket.gethostname():
        return "unknown"
    alive = _pid_alive(required["pid"])
    if alive is not True:
        return "dead" if alive is False else "unknown"
    expected, current = required["process_start"], process_start_identity(required["pid"])
    if expected is not None and current is not None and expected != current:
        return "dead"
    return "live"


def _read_owner_from_value(value: Any) -> dict[str, Any] | None:
    # Reuse strict parsing without trusting a disk path supplied by callers.
    required = {"token", "pid", "host", "session", "created_at", "heartbeat_at", "process_start"}
    if not isinstance(value, dict) or set(value) != required:
        return None
    if not isinstance(value["token"], str) or not value["token"] or not isinstance(value["pid"], int):
        return None
    if value["pid"] <= 0 or not all(isinstance(value[key], str) and value[key] for key in ("host", "session")):
        return None
    if not all(isinstance(value[key], (int, float)) for key in ("created_at", "heartbeat_at")):
        return None
    return value if value["process_start"] is None or isinstance(value["process_start"], str) else None


def _atomic_owner(path: Path, value: dict[str, Any]) -> None:
    temporary = path.parent.parent / f".{path.parent.name}.{uuid.uuid4().hex}.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def refresh_heartbeat(lock: Path, token: str) -> bool:
    owner = _read_owner(lock)
    if owner is None or owner["token"] != token:
        return False
    owner["heartbeat_at"] = time.time()
    _atomic_owner(lock / "owner.json", owner)
    return True


def release(lock: Path, token: str) -> bool:
    owner = _read_owner(lock)
    if owner is None or owner["token"] != token:
        return False
    try:
        (lock / "owner.json").unlink()
        lock.rmdir()
        return True
    except OSError:
        return False


def reclaim_abandoned(lock: Path) -> bool:
    owner = _read_owner(lock)
    if owner is None or owner_liveness(owner) != "dead":
        return False
    try:
        (lock / "owner.json").unlink()
        lock.rmdir()
        return True
    except OSError:
        return False


@contextlib.contextmanager
def state_lock(directory: Path, timeout: float = 1.0):
    lock, token, deadline = directory / ".lock", uuid.uuid4().hex, time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            _atomic_owner(lock / "owner.json", owner_record(token))
            break
        except FileExistsError:
            if reclaim_abandoned(lock):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("research hook state lock timed out or owner state is unsafe")
            time.sleep(0.02)
    try:
        yield token
    finally:
        release(lock, token)

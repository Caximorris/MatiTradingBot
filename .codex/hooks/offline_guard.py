"""Offline environment for Python validations launched by the research hook."""
from __future__ import annotations

import os
from pathlib import Path


SITECUSTOMIZE = '''import os
if os.environ.get("MATIBOT_HOOK_OFFLINE") == "1":
    import socket

    def _matibot_network_denied(*_args, **_kwargs):
        raise OSError("network access disabled by MatiTradingBot research hook")

    class _MatiBotOfflineSocket(socket.socket):
        def connect(self, *_args, **_kwargs):
            return _matibot_network_denied()

        def connect_ex(self, *_args, **_kwargs):
            return _matibot_network_denied()

    socket.socket = _MatiBotOfflineSocket
    socket.create_connection = _matibot_network_denied
    socket.getaddrinfo = _matibot_network_denied
'''


def is_isolated_build(command: list[str]) -> bool:
    return command[-2:] == ["-m", "build"]


def child_environment(state_directory: Path, *, offline: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(state_directory / "pycache")
    if not offline:
        for name in (
            "MATIBOT_HOOK_OFFLINE", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_INDEX", "UV_OFFLINE",
        ):
            env.pop(name, None)
        offline_path = str(state_directory / "offline-python")
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in env.get("PYTHONPATH", "").split(os.pathsep)
            if entry and entry != offline_path
        )
        return env

    site_directory = state_directory / "offline-python"
    destination = site_directory / "sitecustomize.py"
    site_directory.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or destination.read_text(encoding="utf-8") != SITECUSTOMIZE:
        temporary = site_directory / f"sitecustomize.{os.getpid()}.tmp"
        temporary.write_text(SITECUSTOMIZE, encoding="utf-8")
        os.replace(temporary, destination)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(site_directory), env.get("PYTHONPATH", "")))
    )
    env["MATIBOT_HOOK_OFFLINE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["UV_OFFLINE"] = "1"
    env["NO_PROXY"] = ""
    return env

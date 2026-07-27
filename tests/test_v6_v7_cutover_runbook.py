from __future__ import annotations

import re
from pathlib import Path

from tools.v6_v7_demo_cutover import build_parser


RUNBOOK = Path(__file__).parents[1] / "docs" / "V7_OKX_DEMO_CUTOVER_RUNBOOK.md"


def test_runbook_cli_commands_are_current_and_safe():
    text = RUNBOOK.read_text(encoding="utf-8")
    commands = set(re.findall(r"v6_v7_demo_cutover\.py ([a-z0-9-]+)", text))
    choices = set(build_parser()._actions[1].choices)  # positional command action
    assert commands <= choices
    assert {
        "audit-v6",
        "show-audit",
        "export-v6-evidence",
        "stop-v6",
        "create-v7-inactive",
        "preflight-v7",
        "activate-v7",
        "status",
        "pause-v7",
        "resume-v7",
        "deactivate-v7",
    } <= commands
    assert "matibot-v7-certified-okx-demo.service" in text
    assert "STATE-CHANGING" in text and "FRAGILE" in text and "NOT_READY" in text
    assert not re.search(r"[A-Za-z]:\\", text)
    assert not re.search(r"(?i)(api[_-]?key|password|passphrase|secret)\s*=", text)
    command_text = "\n".join(re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL))
    assert not re.search(r"git (reset|clean)|force push|--force", command_text)
    assert "liquidat" in text.lower() and "never liquidates automatically" in text

from pathlib import Path


def test_runbook_documents_implemented_cli_and_no_unit_placeholders():
    root = Path(__file__).parents[1]
    text = (root / "docs" / "V7_OKX_DEMO_CUTOVER_RUNBOOK.md").read_text()
    for command in ("collect-v6-runtime", "observe-okx-demo-account", "build-v6-audit-inputs", "audit-v6", "render", "install-inactive", "preflight-v7", "activate-v7", "pause-v7", "resume-v7", "deactivate-v7"):
        assert command in text
    assert "__RUN_USER__" not in text and "__APP_DIR__" not in text

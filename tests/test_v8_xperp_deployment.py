from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v8_units_start_only_v8_entrypoints_and_keep_secrets_external() -> None:
    executor = (ROOT / "deploy" / "matibot-v8-xperp-demo.service").read_text()
    telegram = (ROOT / "deploy" / "matibot-v8-xperp-telegram.service").read_text()
    assert "tools/v8_xperp_demo.py run --enable-continuous-demo" in executor
    assert "tools/v8_xperp_telegram.py" in telegram
    assert "EnvironmentFile=__ENV_FILE__" in executor
    assert "EnvironmentFile=__ENV_FILE__" in telegram
    combined = executor + telegram
    assert "telegram_remote.py" not in combined
    assert "v7_telegram.py" not in combined
    assert "V8_TELEGRAM_BOT_TOKEN=" not in combined


def test_example_environment_contains_fail_closed_v8_controls() -> None:
    value = (ROOT / ".env.example").read_text()
    required = {
        "V8_LIVE_EXECUTION_ENABLED=false",
        "V8_SCHEDULE_MODE=real_cycle",
        "V8_SYNTHETIC_DEMO_CYCLE_ENABLED=false",
        "V8_SYNTHETIC_CYCLE_ANCHOR_UTC=",
        "V8_TELEGRAM_ENABLED=false",
        "V8_TELEGRAM_BOT_TOKEN=",
        "V8_TELEGRAM_ALLOWED_CHAT_IDS=",
        "V8_TELEGRAM_CONFIRMATION_SECONDS=120",
    }
    assert required <= set(value.splitlines())

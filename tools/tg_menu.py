"""Persistent one-tap keyboard for the Telegram remote control."""
from __future__ import annotations

import json


MENU_ACTIONS = {
    "📊 Resumen": "/status",
    "🟢 V6 sim": "/status_v6",
    "🟠 OKX demo": "/status_demo",
    "🏁 Prop firm": "/prop",
    "🚨 Auditoría": "/audit",
    "🩺 Salud VM": "/health",
    "📋 Report v6": "/report_v6",
    "📋 Report demo": "/report_demo",
    "📋 Report prop": "/prop_report",
    "📈 Equity v6": "/equity_v6",
    "📈 Equity demo": "/equity_demo",
    "🕯 BTC 30d": "/chart 30",
    "🧭 Señales": "/signals",
    "⚖️ Paridad": "/parity",
    "❓ Ayuda": "/help",
}

_KEYBOARD = [
    ["📊 Resumen", "🟢 V6 sim", "🟠 OKX demo"],
    ["🏁 Prop firm", "🚨 Auditoría", "🩺 Salud VM"],
    ["📋 Report v6", "📋 Report demo", "📋 Report prop"],
    ["📈 Equity v6", "📈 Equity demo", "🕯 BTC 30d"],
    ["🧭 Señales", "⚖️ Paridad", "❓ Ayuda"],
]


def resolve_menu_text(text: str) -> str:
    """Translate a friendly keyboard label into the existing command syntax."""
    return MENU_ACTIONS.get(text.strip(), text)


def main_menu_markup() -> str:
    """Telegram ReplyKeyboardMarkup encoded for the Bot API."""
    return json.dumps({
        "keyboard": _KEYBOARD,
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Elige una acción",
    }, ensure_ascii=False)

"""Persistent one-tap keyboard for the Telegram remote control."""
from __future__ import annotations

import json


MENU_ACTIONS = {
    "🧪 V7 certificado": "/v7_status",
    "📜 Logs V7": "/v7_logs",
    "📊 Resumen": "/status",
    "🚨 Auditoría": "/audit",
    "🩺 Salud VM": "/health",
    "📋 Report v6": "/report v6",
    "📋 Report demo": "/report demo",
    "📈 Equity v6": "/equity v6 30",
    "📈 Equity demo": "/equity demo 30",
    "🕯 BTC 30d": "/chart 30",
    "🧭 Señales": "/signals",
    "⚖️ Paridad": "/parity",
    "❓ Ayuda": "/help",
}

_KEYBOARD = [
    ["🧪 V7 certificado", "📜 Logs V7", "📊 Resumen"],
    ["🚨 Auditoría", "🩺 Salud VM", "📋 Report v6"],
    ["📋 Report demo", "📈 Equity v6", "📈 Equity demo"],
    ["🕯 BTC 30d", "🧭 Señales", "⚖️ Paridad"],
    ["❓ Ayuda"],
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

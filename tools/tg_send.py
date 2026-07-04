"""Helper de envio a Telegram — compartido por telegram_remote.py y los scripts de cron.

Uso CLI (para deploy/daily_checks.sh):
    python tools/tg_send.py "mensaje"

Requiere en .env (o entorno): TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
Sin credenciales configuradas, el envio es no-op con warning (no rompe el cron).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

_API = "https://api.telegram.org"
_TIMEOUT = 15


def tg_credentials() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def tg_api(method: str, params: dict, timeout: int = _TIMEOUT) -> dict:
    """Llamada generica a la Bot API. Lanza excepcion en fallo de red/API."""
    token, _ = tg_credentials()
    url = f"{_API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error en {method}: {payload}")
    return payload


def tg_send(text: str, parse_mode: str | None = None) -> bool:
    """Envia un mensaje al chat configurado. Devuelve False si no hay credenciales o falla.

    parse_mode="HTML" activa formato (negritas, <pre>); si Telegram rechaza el HTML
    (entidades mal balanceadas), reintenta en texto plano para no perder el mensaje.
    """
    token, chat_id = tg_credentials()
    if not token or not chat_id:
        print("tg_send: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no configurados — no-op", file=sys.stderr)
        return False
    # Telegram limita a 4096 chars por mensaje
    params = {"chat_id": chat_id, "text": text[:4000]}
    if parse_mode:
        params["parse_mode"] = parse_mode
    try:
        tg_api("sendMessage", params)
        return True
    except Exception as exc:
        if parse_mode:
            try:
                tg_api("sendMessage", {"chat_id": chat_id, "text": text[:4000]})
                return True
            except Exception:
                pass
        print(f"tg_send fallo: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python tools/tg_send.py \"mensaje\"")
    ok = tg_send(" ".join(sys.argv[1:]))
    raise SystemExit(0 if ok else 1)

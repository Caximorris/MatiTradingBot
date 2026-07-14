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
_UPLOAD_TIMEOUT = 60


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


def tg_send(text: str, parse_mode: str | None = None,
            reply_markup: str | None = None) -> bool:
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
    if reply_markup:
        params["reply_markup"] = reply_markup
    try:
        tg_api("sendMessage", params)
        return True
    except Exception as exc:
        if parse_mode:
            try:
                fallback = {"chat_id": chat_id, "text": text[:4000]}
                if reply_markup:
                    fallback["reply_markup"] = reply_markup
                tg_api("sendMessage", fallback)
                return True
            except Exception:
                pass
        print(f"tg_send fallo: {exc}", file=sys.stderr)
        return False


def _multipart(fields: dict[str, str], file_field: str, filename: str,
               content: bytes) -> tuple[bytes, str]:
    """Codifica un formulario multipart/form-data (urllib no lo trae de serie)."""
    boundary = "----MatiTradingBot" + os.urandom(8).hex()
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
            .encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        .encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _tg_upload(method: str, file_field: str, filename: str, content: bytes,
               caption: str = "", parse_mode: str | None = None) -> bool:
    """sendPhoto/sendDocument. Devuelve False si no hay credenciales o falla."""
    token, chat_id = tg_credentials()
    if not token or not chat_id:
        print("tg_upload: credenciales no configuradas — no-op", file=sys.stderr)
        return False
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption[:1000]
    if parse_mode:
        fields["parse_mode"] = parse_mode
    body, boundary = _multipart(fields, file_field, filename, content)
    req = urllib.request.Request(
        f"{_API}/bot{token}/{method}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_UPLOAD_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error en {method}: {payload}")
        return True
    except Exception as exc:
        print(f"tg_upload fallo: {exc}", file=sys.stderr)
        return False


def tg_send_photo(content: bytes, caption: str = "", parse_mode: str | None = None) -> bool:
    return _tg_upload("sendPhoto", "photo", "chart.png", content, caption, parse_mode)


def tg_send_document(filename: str, content: bytes, caption: str = "") -> bool:
    return _tg_upload("sendDocument", "document", filename, content, caption)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python tools/tg_send.py \"mensaje\"")
    ok = tg_send(" ".join(sys.argv[1:]))
    raise SystemExit(0 if ok else 1)

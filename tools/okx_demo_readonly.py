"""Capability-minimal authenticated OKX Demo reader; no mutation methods exist."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from urllib.request import Request, urlopen

from core.v7_certified_paper import PaperSafetyError

_HOSTS = {"https://www.okx.com", "https://my.okx.com"}


class OKXDemoReadOnlyClient:
    """Only GET endpoints required by the V6 observation boundary."""

    is_paper = True
    endpoint = "okx_demo"

    def __init__(
        self, config: dict[str, Any], transport: Callable[..., bytes] | None = None
    ) -> None:
        if (
            config.get("trading_mode") != "paper"
            or config.get("simulated_trading") is not True
            or config.get("demo_confirmed") is not True
            or config.get("okx_demo_domain") not in _HOSTS
        ):
            raise PaperSafetyError("runtime is not explicitly confirmed as OKX Demo")
        self._key, self._secret, self._passphrase = (
            config.get(key)
            for key in ("demo_api_key", "demo_secret", "demo_passphrase")
        )
        if not all((self._key, self._secret, self._passphrase)):
            raise PaperSafetyError("required demo credentials are unavailable")
        self._host, self._transport = (
            config["okx_demo_domain"],
            transport or self._request,
        )
        self.account_id, self.precision, self.minimum_size = "okx-demo", {}, {}

    def _request(self, path: str) -> bytes:
        stamp = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        sign = base64.b64encode(
            hmac.new(
                str(self._secret).encode(), f"{stamp}GET{path}".encode(), hashlib.sha256
            ).digest()
        ).decode()
        request = Request(
            self._host + path,
            headers={
                "OK-ACCESS-KEY": str(self._key),
                "OK-ACCESS-SIGN": sign,
                "OK-ACCESS-TIMESTAMP": stamp,
                "OK-ACCESS-PASSPHRASE": str(self._passphrase),
                "x-simulated-trading": "1",
            },
        )
        with urlopen(request, timeout=10) as response:
            return response.read()

    def _get(self, path: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._transport(path).decode())
        except Exception as exc:
            raise PaperSafetyError("OKX Demo read request failed") from exc
        if data.get("code") != "0" or not isinstance(data.get("data"), list):
            raise PaperSafetyError("OKX Demo response is unavailable or malformed")
        return data["data"]

    def get_balance(self) -> dict[str, Decimal]:
        rows = self._get("/api/v5/account/balance")
        if len(rows) != 1 or not isinstance(rows[0].get("details"), list):
            raise PaperSafetyError("ambiguous OKX Demo balance response")
        values = {
            row.get("ccy"): Decimal(str(row.get("availEq") or row.get("availBal")))
            for row in rows[0]["details"]
        }
        if None in values or len(values) != len(rows[0]["details"]):
            raise PaperSafetyError("ambiguous OKX Demo asset response")
        return values

    def get_positions(self):
        return self._get("/api/v5/account/positions")

    def get_open_orders(self, symbol):
        return self._get(f"/api/v5/trade/orders-pending?instId={symbol}")

    def get_order_history(self, symbol, limit=20):
        return self._get(
            f"/api/v5/trade/orders-history?instId={symbol}&limit={min(limit, 100)}"
        )

"""Authenticated private-stream supervision for the isolated V8 Demo adapter.

REST remains authoritative after a disconnect, sequence gap, malformed event, or
stale heartbeat.  This module never places an order.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import websockets

from .adapter import SafetyError, _utc_now

DEMO_PRIVATE_WS = "wss://wseeapap.okx.com:8443/ws/v5/private"
LIVE_PRIVATE_WS = "wss://wseea.okx.com:8443/ws/v5/private"
STALE_SECONDS = 20.0


@dataclass(frozen=True)
class StreamState:
    connected: bool
    subscribed: bool
    stale: bool
    reconnects: int
    last_event_at: datetime | None


class PrivateStreamSupervisor:
    """Small ordered-event gate; an uncertain stream blocks all execution."""

    def __init__(self, *, api_key: str, secret: str, passphrase: str, instrument_id: str,
                 reconcile: Callable[[], None], on_event: Callable[[dict[str, Any]], None] | None = None,
                 environment: str = "okx_demo", url: str | None = None) -> None:
        allowed = {"okx_demo": DEMO_PRIVATE_WS, "okx_live": LIVE_PRIVATE_WS}
        if environment not in allowed:
            raise SafetyError("unrecognized X-Perp environment")
        if url is not None and url != allowed[environment]:
            raise SafetyError("private WebSocket endpoint is outside the environment allowlist")
        if environment != "okx_demo":
            raise SafetyError("live private stream is disabled pending separate authorization")
        self.api_key, self.secret, self.passphrase = api_key, secret, passphrase
        self.instrument_id, self.reconcile, self.on_event, self.url = instrument_id, reconcile, on_event, allowed[environment]
        self._last_event_monotonic = 0.0
        self._seen: set[tuple[str, str, str]] = set()
        self._subscribed: set[tuple[tuple[str, str], ...]] = set()
        self._socket: Any | None = None
        self._reconciled = False
        self._state = StreamState(False, False, True, 0, None)

    @property
    def state(self) -> StreamState:
        stale = not self._state.subscribed or time.monotonic() - self._last_event_monotonic > STALE_SECONDS
        return StreamState(self._state.connected, self._state.subscribed, stale, self._state.reconnects, self._state.last_event_at)

    def assert_healthy(self) -> None:
        if self.state.stale:
            raise SafetyError("private WebSocket is stale or reconnecting; execution blocked")

    def accept_heartbeat(self) -> None:
        """Record a server pong without treating it as an account event."""
        if not self._state.connected or not self._state.subscribed or not self._reconciled:
            raise SafetyError("private WebSocket heartbeat arrived before reconciliation")
        self._last_event_monotonic = time.monotonic()
        self._state = StreamState(
            True, True, False, self._state.reconnects, _utc_now()
        )

    def login_payload(self) -> dict[str, Any]:
        timestamp = str(int(time.time()))
        sign = base64.b64encode(hmac.new(self.secret.encode(), f"{timestamp}GET/users/self/verify".encode(), hashlib.sha256).digest()).decode()
        return {"op": "login", "args": [{"apiKey": self.api_key, "passphrase": self.passphrase,
                                                "timestamp": timestamp, "sign": sign}]}

    def subscriptions(self) -> list[dict[str, str]]:
        return [{"channel": "orders", "instType": "FUTURES", "instId": self.instrument_id},
                {"channel": "positions", "instType": "FUTURES", "instId": self.instrument_id},
                {"channel": "balance_and_position"}, {"channel": "account", "ccy": "USDC"}]

    def accept(self, message: dict[str, Any]) -> bool:
        """Deduplicate updates and reject malformed/out-of-order updates by staling the stream."""
        if message.get("event") == "error":
            self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
            return False
        if message.get("event") == "channel-conn-count":
            return self._state.subscribed and self._reconciled
        if message.get("event") == "subscribe":
            arg = message.get("arg")
            if not isinstance(arg, dict):
                self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
                return False
            self._subscribed.add(tuple(sorted((str(key), str(value)) for key, value in arg.items())))
            expected = {
                tuple(sorted((str(key), str(value)) for key, value in item.items()))
                for item in self.subscriptions()
            }
            complete = self._subscribed == expected
            if complete:
                try:
                    self.reconcile()
                    self._reconciled = True
                except Exception:
                    self._reconciled = False
                    self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
                    return False
            self._state = StreamState(True, complete and self._reconciled, not complete, self._state.reconnects, _utc_now())
            self._last_event_monotonic = time.monotonic()
            return complete
        arg, rows = message.get("arg"), message.get("data")
        if not isinstance(arg, dict) or not isinstance(rows, list):
            self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
            return False
        for row in rows:
            if not isinstance(row, dict):
                self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
                return False
            key = (str(arg.get("channel")), str(row.get("ordId") or row.get("posId") or row.get("ccy")), str(row.get("uTime") or row.get("fillTime") or row.get("pTime")))
            if key in self._seen:
                continue
            self._seen.add(key)
            if self.on_event:
                self.on_event({"arg": arg, "data": [row]})
        self._last_event_monotonic = time.monotonic()
        healthy = self._state.subscribed and self._reconciled
        self._state = StreamState(True, healthy, not healthy, self._state.reconnects, _utc_now())
        return True

    async def run(self, stop: asyncio.Event) -> None:
        delay = 1.0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=10, ping_timeout=10) as socket:
                    self._socket = socket
                    self._subscribed.clear()
                    self._reconciled = False
                    self._state = StreamState(True, False, True, self._state.reconnects, self._state.last_event_at)
                    await socket.send(json.dumps(self.login_payload()))
                    login = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
                    if login.get("event") != "login" or login.get("code") not in ("0", 0):
                        raise SafetyError("private WebSocket login was rejected")
                    await socket.send(json.dumps({"op": "subscribe", "args": self.subscriptions()}))
                    delay = 1.0
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=10)
                        except asyncio.TimeoutError:
                            await socket.send("ping")
                            raw = await asyncio.wait_for(socket.recv(), timeout=5)
                        if raw == "pong":
                            self.accept_heartbeat()
                        else:
                            self.accept(json.loads(raw))
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException, SafetyError, json.JSONDecodeError):
                self._socket = None
                self._reconciled = False
                self._subscribed.clear()
                self._state = StreamState(False, False, True, self._state.reconnects + 1, self._state.last_event_at)
                try:
                    self.reconcile()
                except Exception:
                    pass
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def force_disconnect(self) -> None:
        """Test/operations hook: close only this local socket; never mutate exchange state."""
        if self._socket is None:
            raise SafetyError("private WebSocket is not connected")
        await self._socket.close()
        self._state = StreamState(False, False, True, self._state.reconnects, self._state.last_event_at)

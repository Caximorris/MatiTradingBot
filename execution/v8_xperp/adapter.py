"""V8-only, fail-closed OKX EEA X-Perp Demo execution adapter.

This module deliberately does not import the legacy exchange or V7 execution
modules.  Demo credentials are read only from ``OKX_XPERP_DEMO_*`` and every
private SDK call uses the simulated-trading flag.  It is intentionally a
one-shot adapter: continuous operation needs a separate explicit enable gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Iterator

from loguru import logger
from okx.Account import AccountAPI
from okx.Funding import FundingAPI
from okx.MarketData import MarketAPI
from okx.PublicData import PublicAPI
from okx.Trade import TradeAPI
from okx.consts import GET


DOMAIN = "https://eea.okx.com"
ENVIRONMENT = "okx_demo"
CLIENT_PREFIX = "v8xp"
MAX_SPREAD_BPS = Decimal("30")
MAX_SLIPPAGE_BPS = Decimal("20")
MAX_TICKER_AGE = timedelta(seconds=15)
EXPIRY_WARNING = timedelta(days=7)
FEE_RESERVE_BPS = Decimal("10")
FUNDING_RESERVE_BPS = Decimal("20")
SLIPPAGE_RESERVE_BPS = Decimal("20")


class SafetyError(RuntimeError):
    """A pre-trade invariant failed; no new risk may be opened."""


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except Exception as exc:  # exchange values are untrusted input
        raise SafetyError("OKX returned a non-decimal numeric field") from exc


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Instrument:
    inst_id: str
    inst_family: str
    uly: str
    settle_ccy: str
    ct_type: str
    ct_val: Decimal
    ct_val_ccy: str
    lot_sz: Decimal
    min_sz: Decimal
    tick_sz: Decimal
    lever: Decimal
    exp_time: datetime
    metadata_hash: str


@dataclass(frozen=True)
class Market:
    bid: Decimal
    ask: Decimal
    last: Decimal
    timestamp: datetime
    spread_bps: Decimal
    estimated_slippage_bps: Decimal


@dataclass(frozen=True)
class PreflightReport:
    environment: str
    domain: str
    instrument: Instrument
    available_usdc: Decimal
    collateral_enabled: bool
    account_level: str
    position_mode: str
    market: Market
    checked_at: datetime


@dataclass(frozen=True)
class TargetCalculation:
    target: str
    available_usdc: Decimal
    eligible_usdc: Decimal
    raw_contract_qty: Decimal
    quantized_contract_qty: Decimal
    actual_notional: Decimal
    actual_leverage: Decimal
    initial_margin: Decimal
    estimated_maintenance_margin: Decimal
    trading_fee_reserve: Decimal
    funding_reserve: Decimal
    slippage_reserve: Decimal
    remaining_available_margin: Decimal
    estimated_liquidation_price: Decimal | None


class _ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "_ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            raise SafetyError("another V8 X-Perp executor owns the process lock") from exc
        return self

    def __exit__(self, *_: object) -> None:
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


class V8XPerpDemoAdapter:
    """Smallest safe authenticated execution surface for the dedicated subaccount."""

    def __init__(self, *, runtime_root: Path = Path("data/runtime/v8_xperp_demo"),
                 account: Any | None = None, trade: Any | None = None,
                 funding: Any | None = None, market: Any | None = None,
                 public: Any | None = None, raw_get: Callable[[str], dict[str, Any]] | None = None,
                 allow_test_clients: bool = False) -> None:
        injected = (account, trade, funding, market, public, raw_get)
        if any(client is not None for client in injected) and not allow_test_clients:
            raise SafetyError("injected REST clients require the explicit test-only gate")
        key, secret, passphrase = self._credentials()
        self.runtime_root = runtime_root
        self.journal_path = runtime_root / "journal.jsonl"
        self.intent_path = runtime_root / "intents.json"
        self.snapshot_dir = runtime_root / "reconciliation"
        self._startup_recovered = False
        self._lock_depth = 0
        self.account_hash = _safe_hash(key)
        self._account_lock_path = (
            Path("data/runtime/v8_xperp_locks")
            / f"{_safe_hash(key)}.lock"
        )
        kwargs = {"use_server_time": False, "flag": "1", "domain": DOMAIN, "debug": False}
        self.account = account or AccountAPI(key, secret, passphrase, **kwargs)
        self.trade = trade or TradeAPI(key, secret, passphrase, **kwargs)
        self.funding = funding or FundingAPI(key, secret, passphrase, **kwargs)
        self.market_api = market or MarketAPI(flag="1", domain=DOMAIN, debug=False)
        self.public = public or PublicAPI(flag="1", domain=DOMAIN, debug=False)
        # The installed OKX SDK does not expose collateral-assets yet.  Its
        # authenticated request method retains its signed request and simulated
        # header contract; no independent HTTP client or second credential path.
        self._raw_get = raw_get or (lambda path: self.account._request_with_params(GET, path.split("?", 1)[0],
                                                                                     dict(urllib.parse.parse_qsl(path.partition("?")[2]))))

    @staticmethod
    def _credentials() -> tuple[str, str, str]:
        names = ("OKX_XPERP_DEMO_API_KEY", "OKX_XPERP_DEMO_SECRET_KEY", "OKX_XPERP_DEMO_PASSPHRASE")
        values = tuple(os.getenv(name, "").strip() for name in names)
        if not all(values):
            # Do not load the application's shared Settings object: it reads legacy
            # and live credential names.  This narrow parser selects only the three
            # dedicated V8 keys when a local .env is used for an operator command.
            selected: dict[str, str] = {}
            env_path = Path(".env")
            if env_path.exists():
                for raw in env_path.read_text(encoding="utf-8").splitlines():
                    key, separator, value = raw.partition("=")
                    if separator and key.strip() in names:
                        selected[key.strip()] = value.strip().strip('"').strip("'")
            values = tuple(selected.get(name, "") for name in names)
        if not all(values):
            raise SafetyError("dedicated OKX_XPERP_DEMO credential triplet is required")
        return values  # type: ignore[return-value]

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self._lock_depth:
            raise SafetyError("nested V8 X-Perp process lock acquisition is forbidden")
        with _ProcessLock(self._account_lock_path):
            self._lock_depth = 1
            try:
                yield
            finally:
                self._lock_depth = 0

    def _assert_lock_held(self) -> None:
        if self._lock_depth != 1:
            raise SafetyError("exclusive V8 account process lock is not held")

    def _ok(self, payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
        if payload.get("code") != "0":
            raise SafetyError(f"{label} rejected by OKX: code={payload.get('code')}, msg={payload.get('msg', '')[:160]}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise SafetyError(f"{label} returned malformed data")
        return data

    def _append(self, event: str, payload: dict[str, Any]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        safe = {"at": _utc_now().isoformat(), "event": event, "payload": payload}
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, sort_keys=True, default=str) + "\n")
        logger.bind(execution="v8_xperp_demo").info("recorded {}", event)

    @staticmethod
    def client_id_hash(client_id: str) -> str:
        return _safe_hash(client_id)

    def _intent_execution(self) -> Any:
        # Lazy imports avoid coupling the frozen ledger to adapter construction.
        from .intents import IntentLedger
        from .recovery import IntentExecution

        return IntentExecution(adapter=self, ledger=IntentLedger(self.intent_path))

    def _create_intent(
        self,
        *,
        instrument: Instrument,
        action: str,
        target: str,
        side: str,
        contracts: Decimal,
        reduce_only: bool,
        order_type: str,
        price: Decimal | None = None,
    ) -> Any:
        from .intents import Intent, IntentLedger

        transition_at = _utc_now().isoformat()
        client_id = self._client_id(
            instrument=instrument,
            action=action,
            transition_at=transition_at,
        )
        transition_id = hashlib.sha256(
            f"{client_id}|{action}|{target}".encode("utf-8")
        ).hexdigest()
        intent = Intent(
            transition_id=transition_id,
            client_order_id=client_id,
            instrument_id=instrument.inst_id,
            target=target,
            action=action,
            side=side,
            contracts=str(contracts),
            reduce_only=reduce_only,
            order_type=order_type,
            price=str(price) if price is not None else None,
            metadata_hash=instrument.metadata_hash,
        )
        created = IntentLedger(self.intent_path).create(intent)
        self._append(
            "intent_created",
            {
                "client_id_hash": _safe_hash(client_id),
                "transition_id": transition_id,
                "instrument": instrument.inst_id,
                "action": action,
                "side": side,
                "contracts": str(contracts),
                "reduce_only": reduce_only,
                "order_type": order_type,
            },
        )
        return created

    def _assert_recovered(self) -> None:
        if not self._startup_recovered:
            raise SafetyError("startup recovery has not completed; execution blocked")

    def _snapshot(self, report: PreflightReport) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / f"{report.checked_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(asdict(report), default=str, sort_keys=True, indent=2), encoding="utf-8")

    def _discover(self) -> Instrument:
        # PublicData currently omits EEA X-Perps.  The authenticated account
        # catalogue is the authoritative, account-entitled FUTURES universe.
        rows = self._ok(self.account.get_instruments("FUTURES"), "instrument discovery")
        candidates = [row for row in rows if row.get("state") == "live" and row.get("ruleType") == "xperp"
                      and row.get("uly") == "BTC-USD" and row.get("settleCcy") == "USDC"
                      and row.get("ctType") == "linear"]
        if len(candidates) != 1:
            raise SafetyError(f"expected exactly one eligible BTC X-Perp; found {len(candidates)}")
        row = candidates[0]
        required = ("instId", "instFamily", "uly", "ctVal", "ctValCcy", "lotSz", "minSz", "tickSz", "lever", "expTime")
        if any(not row.get(field) for field in required):
            raise SafetyError("X-Perp instrument metadata is incomplete")
        expiry = datetime.fromtimestamp(int(row["expTime"]) / 1000, UTC)
        if expiry - _utc_now() <= EXPIRY_WARNING:
            raise SafetyError("X-Perp expiry is inside the seven-day warning window")
        canonical = json.dumps(
            {field: row.get(field) for field in (
                "instId",
                "instFamily",
                "uly",
                "settleCcy",
                "ctType",
                "ctVal",
                "ctValCcy",
                "lotSz",
                "minSz",
                "tickSz",
                "lever",
                "expTime",
            )},
            sort_keys=True,
            separators=(",", ":"),
        )
        return Instrument(str(row["instId"]), str(row["instFamily"]), str(row["uly"]), str(row["settleCcy"]),
                          str(row["ctType"]), _decimal(row["ctVal"]), str(row["ctValCcy"]), _decimal(row["lotSz"]),
                          _decimal(row["minSz"]), _decimal(row["tickSz"]), _decimal(row["lever"]), expiry,
                          hashlib.sha256(canonical.encode()).hexdigest())

    def _market(self, instrument: Instrument) -> Market:
        ticker = self._ok(self.market_api.get_ticker(instrument.inst_id), "ticker")
        book = self._ok(self.market_api.get_orderbook(instrument.inst_id, sz="5"), "order book")
        if len(ticker) != 1 or len(book) != 1 or not book[0].get("bids") or not book[0].get("asks"):
            raise SafetyError("missing X-Perp ticker or order book")
        tick = ticker[0]
        try:
            ticker_timestamp = datetime.fromtimestamp(int(tick["ts"]) / 1000, UTC)
            book_timestamp = datetime.fromtimestamp(int(book[0]["ts"]) / 1000, UTC)
        except (KeyError, TypeError, ValueError) as exc:
            raise SafetyError("X-Perp market timestamp is invalid") from exc
        # A ticker's timestamp records the last trade and can remain unchanged
        # while the validated order book is actively refreshing.  Market
        # freshness therefore uses the newest exchange-supplied price component.
        timestamp = max(ticker_timestamp, book_timestamp)
        if _utc_now() - timestamp > MAX_TICKER_AGE:
            raise SafetyError("X-Perp market data is stale")
        bid, ask, last = _decimal(book[0]["bids"][0][0]), _decimal(book[0]["asks"][0][0]), _decimal(tick["last"])
        if bid <= 0 or ask <= bid or last <= 0:
            raise SafetyError("invalid X-Perp market prices")
        spread = (ask - bid) / ((ask + bid) / Decimal("2")) * Decimal("10000")
        slippage = spread / Decimal("2")
        if spread > MAX_SPREAD_BPS or slippage > MAX_SLIPPAGE_BPS:
            raise SafetyError("X-Perp spread or estimated slippage exceeds configured limit")
        return Market(bid, ask, last, timestamp, spread, slippage)

    def preflight(self) -> PreflightReport:
        config = self._ok(self.account.get_account_config(), "account config")
        if len(config) != 1 or config[0].get("posMode") != "net_mode" or str(config[0].get("acctLv")) != "2":
            raise SafetyError("account level or net position mode is incompatible")
        balances = self._ok(self.account.get_account_balance(ccy="USDC"), "USDC trading balance")
        details = (balances[0].get("details") if balances else None) or []
        usdc = next((row for row in details if row.get("ccy") == "USDC"), None)
        available = _decimal(usdc.get("availEq") or usdc.get("availBal")) if usdc else Decimal("0")
        if available <= 0:
            raise SafetyError("USDC available equity is zero")
        collateral = self._ok(self._raw_get("/api/v5/account/collateral-assets?ccy=USDC"), "USDC collateral")
        if len(collateral) != 1 or collateral[0].get("collateralEnabled") is not True:
            raise SafetyError("USDC collateral is not enabled")
        positions = self._ok(self.account.get_positions(instType="FUTURES"), "FUTURES positions")
        if any(_decimal(row.get("pos")) != 0 for row in positions):
            raise SafetyError("unknown FUTURES position exists; manual reconciliation required")
        orders = self._ok(self.trade.get_order_list(instType="FUTURES", state="live"), "FUTURES open orders")
        if orders:
            raise SafetyError("unknown FUTURES open order exists; manual reconciliation required")
        instrument = self._discover()
        report = PreflightReport(ENVIRONMENT, DOMAIN, instrument, available, True, str(config[0]["acctLv"]),
                                 str(config[0]["posMode"]), self._market(instrument), _utc_now())
        self._snapshot(report)
        self._append("preflight_pass", {"instrument": instrument.inst_id, "metadata_hash": instrument.metadata_hash,
                                         "available_usdc": str(available), "spread_bps": str(report.market.spread_bps)})
        self._startup_recovered = True
        return report

    def operational_report(self, instrument: Instrument) -> PreflightReport:
        """Fresh account/market report after startup recovery proved ownership."""
        self._assert_lock_held()
        self._assert_recovered()
        current = self._discover()
        if (
            current.inst_id != instrument.inst_id
            or current.metadata_hash != instrument.metadata_hash
        ):
            raise SafetyError("operational X-Perp metadata changed")
        config = self._ok(self.account.get_account_config(), "operational account config")
        if len(config) != 1 or config[0].get("posMode") != "net_mode" or str(config[0].get("acctLv")) != "2":
            raise SafetyError("operational account level or position mode is incompatible")
        balances = self._ok(
            self.account.get_account_balance(ccy="USDC"),
            "operational USDC balance",
        )
        details = (balances[0].get("details") if balances else None) or []
        usdc = next((row for row in details if row.get("ccy") == "USDC"), None)
        available = _decimal(usdc.get("availEq") or usdc.get("availBal")) if usdc else Decimal("0")
        if available <= 0:
            raise SafetyError("operational USDC available equity is zero")
        collateral = self._ok(
            self._raw_get("/api/v5/account/collateral-assets?ccy=USDC"),
            "operational USDC collateral",
        )
        if len(collateral) != 1 or collateral[0].get("collateralEnabled") is not True:
            raise SafetyError("operational USDC collateral is not enabled")
        return PreflightReport(
            ENVIRONMENT, DOMAIN, current, available, True,
            str(config[0]["acctLv"]), str(config[0]["posMode"]),
            self._market(current), _utc_now(),
        )

    def startup_recovery(self, instrument: Instrument) -> dict[str, Any]:
        from .intents import IntentLedger
        from .recovery import StartupRecovery

        result = StartupRecovery(
            adapter=self,
            ledger=IntentLedger(self.intent_path),
        ).run(instrument)
        self._startup_recovered = True
        return result

    def calculate_target(self, report: PreflightReport, target: str) -> TargetCalculation:
        leverage = {"flat": Decimal("0"), "long 1x": Decimal("1"), "long 2x": Decimal("2"), "short 2x": Decimal("2")}.get(target)
        if leverage is None:
            raise ValueError("target must be flat, long 1x, long 2x, or short 2x")
        eligible = report.available_usdc * Decimal("0.95")
        raw = (eligible * leverage) / (report.market.last * report.instrument.ct_val) if leverage else Decimal("0")
        quantity = (raw / report.instrument.lot_sz).to_integral_value(rounding=ROUND_DOWN) * report.instrument.lot_sz
        notional = quantity * report.market.last * report.instrument.ct_val
        actual_lev = notional / eligible if eligible else Decimal("0")
        if actual_lev > leverage:
            raise SafetyError("lot quantization would exceed requested leverage")
        initial = notional / report.instrument.lever if report.instrument.lever else notional
        maintenance = notional * Decimal("0.005")
        fee = notional * FEE_RESERVE_BPS / Decimal("10000")
        funding = notional * FUNDING_RESERVE_BPS / Decimal("10000")
        slip = notional * SLIPPAGE_RESERVE_BPS / Decimal("10000")
        remaining = report.available_usdc - initial - fee - funding - slip
        if remaining < 0:
            raise SafetyError("insufficient available USDC after execution reserves")
        # Exchange liquidation tiers are account-specific; a conservative estimate requires a live tier endpoint.
        liquidation = None
        return TargetCalculation(target, report.available_usdc, eligible, raw, quantity, notional, actual_lev,
                                 initial, maintenance, fee, funding, slip, remaining, liquidation)

    def funding_reconciliation(self, report: PreflightReport) -> dict[str, Any]:
        """Read X-Perp-specific funding and funding-related account bills exactly once."""
        current = self._ok(self.public.get_funding_rate(report.instrument.inst_id), "X-Perp funding rate")
        history = self._ok(self.public.funding_rate_history(report.instrument.inst_id, limit="100"), "X-Perp funding history")
        bills = self._ok(self.account.get_account_bills(instType="FUTURES", mgnMode="isolated", limit="100"), "X-Perp bills")
        if len(current) != 1:
            raise SafetyError("missing current X-Perp funding rate")
        row = current[0]
        result = {"inst_id": report.instrument.inst_id, "rate": str(row.get("fundingRate")),
                  "funding_time": str(row.get("fundingTime")), "next_funding_time": str(row.get("nextFundingTime")),
                  "history_count": len(history), "funding_bills": [bill for bill in bills if bill.get("instId") == report.instrument.inst_id and bill.get("type") in {"8", 8}]}
        self._append("funding_snapshot", {"inst_id": result["inst_id"], "rate": result["rate"], "history_count": len(history), "funding_bill_count": len(result["funding_bills"])})
        return result

    def margin_tiers(self, report: PreflightReport) -> tuple[Any, ...]:
        """Fetch and validate the complete current isolated-margin tier table."""
        from .margins import parse_margin_tiers

        rows = self._ok(
            self.public.get_position_tiers(
                "FUTURES", "isolated", instFamily=report.instrument.inst_family
            ),
            "X-Perp position tiers",
        )
        return parse_margin_tiers(rows, instrument=report.instrument)

    def selected_leverage(self, report: PreflightReport) -> Decimal:
        rows = self._ok(
            self.account.get_leverage("isolated", instId=report.instrument.inst_id),
            "X-Perp selected leverage",
        )
        if len(rows) != 1 or rows[0].get("mgnMode") != "isolated":
            raise SafetyError("isolated leverage response is ambiguous")
        leverage = _decimal(rows[0].get("lever"))
        if leverage <= 0:
            raise SafetyError("isolated leverage is missing or nonpositive")
        return leverage

    def verified_server_time(self) -> tuple[datetime, Decimal]:
        rows = self._ok(self.public.get_system_time(), "OKX server time")
        if len(rows) != 1 or rows[0].get("ts") in (None, ""):
            raise SafetyError("OKX server time response is ambiguous")
        server = datetime.fromtimestamp(int(rows[0]["ts"]) / 1000, UTC)
        drift = abs(Decimal(str((_utc_now() - server).total_seconds())))
        return server, drift

    def margin_evidence(self, report: PreflightReport) -> dict[str, Any]:
        """Prefer venue risk response; missing EEA X-Perp tier data blocks continuous mode."""
        tiers = self.margin_tiers(report)
        risk = self._ok(self.account.get_position_risk(instType="FUTURES"), "X-Perp position risk")
        result = {
            "tier_count": len(tiers),
            "selected_leverage": str(self.selected_leverage(report)),
            "risk_rows": len(risk),
            "continuous_eligible": bool(tiers),
        }
        self._append("margin_snapshot", result)
        return result

    def minimum_margin_comparison(self) -> dict[str, Any]:
        """Open one minimum Demo lot, compare exchange/local risk, and flatten."""
        from .margins import assess_margin

        self._assert_lock_held()
        report = self.preflight()
        leverage_before = self.selected_leverage(report)
        leverage = min(leverage_before, Decimal("2"))
        if leverage_before != leverage:
            changed = self._ok(
                self.account.set_leverage(
                    str(leverage), "isolated", instId=report.instrument.inst_id
                ),
                "set isolated canary leverage",
            )
            if not changed:
                raise SafetyError("isolated leverage update returned no confirmation")
            leverage = self.selected_leverage(report)
        tiers = self.margin_tiers(report)
        opening_id: str | None = None
        try:
            opening_id, _ = self.place_market(
                report,
                side="buy",
                contracts=report.instrument.min_sz,
                reduce_only=False,
                target="long 1x",
            )
            positions = self._ok(
                self.account.get_positions(
                    instType="FUTURES", instId=report.instrument.inst_id
                ),
                "minimum margin position",
            )
            active = [row for row in positions if _decimal(row.get("pos")) != 0]
            if len(active) != 1:
                raise SafetyError("minimum margin comparison position is ambiguous")
            row = active[0]
            assessment = assess_margin(
                instrument=report.instrument,
                tiers=tiers,
                contracts=abs(_decimal(row["pos"])),
                side="long" if _decimal(row["pos"]) > 0 else "short",
                mark_price=_decimal(row["markPx"]),
                entry_price=_decimal(row["avgPx"]),
                leverage=leverage,
                available_usdc=report.available_usdc,
                reserve_usdc=Decimal("5"),
                exchange_position=row,
            )
            evidence = {
                "environment": ENVIRONMENT,
                "instrument": report.instrument.inst_id,
                "opening_client_id_hash": _safe_hash(opening_id),
                "leverage_before": str(leverage_before),
                "leverage_compared": str(leverage),
                "tier_count": len(tiers),
                "assessment": asdict(assessment),
            }
            self._append(
                "minimum_margin_comparison",
                {
                    "instrument": report.instrument.inst_id,
                    "tier": assessment.tier.tier,
                    "notional": str(assessment.actual_notional),
                    "liquidation_distance_pct": str(assessment.liquidation_distance_pct),
                    "source_hash": assessment.source_hash,
                },
            )
            return evidence
        finally:
            if self._position(report.instrument) != 0:
                self.emergency_flatten(report)

    def _client_id(self, *, instrument: Instrument, action: str, transition_at: str) -> str:
        """Stable for a persisted transition, short enough for OKX's client-id limit."""
        seed = f"{ENVIRONMENT}|{instrument.inst_id}|{action}|{transition_at}|v1"
        return CLIENT_PREFIX + hashlib.sha256(seed.encode()).hexdigest()[:27]

    def _await_terminal(self, instrument: Instrument, client_id: str, timeout: float = 12.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self._ok(self.trade.get_order(instrument.inst_id, clOrdId=client_id), "order query")
            if len(rows) == 1 and rows[0].get("state") in {"filled", "canceled", "mmp_canceled"}:
                return rows[0]
            time.sleep(0.5)
        raise SafetyError("ambiguous order timeout: query-before-retry required; no retry was sent")

    def _position(self, instrument: Instrument) -> Decimal:
        rows = self._ok(self.account.get_positions(instType="FUTURES", instId=instrument.inst_id), "position reconciliation")
        if not rows:
            return Decimal("0")
        if len(rows) != 1:
            raise SafetyError("ambiguous X-Perp position response")
        return _decimal(rows[0].get("pos"))

    def place_market(
        self,
        report: PreflightReport,
        *,
        side: str,
        contracts: Decimal,
        reduce_only: bool,
        target: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if (
            contracts < report.instrument.min_sz
            or contracts % report.instrument.lot_sz != 0
        ):
            raise SafetyError("market contracts violate instrument minimum or lot size")
        before = self._position(report.instrument)
        if reduce_only:
            if before == 0:
                raise SafetyError("refusing reduce-only order while flat")
            expected = "sell" if before > 0 else "buy"
            if side != expected:
                raise SafetyError("reduce-only side would not close the known position")
        elif before != 0:
            raise SafetyError("refusing new risk before flat reconciliation")
        self._assert_recovered()
        action = f"{side}-{'close' if reduce_only else 'open'}"
        intent = self._create_intent(
            instrument=report.instrument,
            action=action,
            target=target or ("flat" if reduce_only else ("long" if side == "buy" else "short")),
            side=side,
            contracts=contracts,
            reduce_only=reduce_only,
            order_type="market",
        )
        result = self._intent_execution().submit_order(
            intent,
            before_position=before,
        )
        terminal = result.order or {}
        self._append("terminal", {"client_id_hash": _safe_hash(intent.client_order_id), "state": terminal.get("state"),
                                  "fill_count": result.fill_count, "acc_fill_sz": str(result.filled_contracts)})
        if terminal.get("state") != "filled" or result.filled_contracts < contracts:
            raise SafetyError("market order did not fill completely")
        return intent.client_order_id, terminal

    def place_minimum(self, report: PreflightReport, *, side: str, reduce_only: bool) -> tuple[str, dict[str, Any]]:
        return self.place_market(
            report,
            side=side,
            contracts=report.instrument.min_sz,
            reduce_only=reduce_only,
        )

    def place_far_limit(self, report: PreflightReport) -> tuple[str, dict[str, Any]]:
        """Create one deliberately non-marketable V8-owned order for cancel testing."""
        if self._position(report.instrument) != 0:
            raise SafetyError("limit cancellation test requires a flat reconciled position")
        self._assert_recovered()
        price = (report.market.ask * Decimal("2")).quantize(report.instrument.tick_sz)
        intent = self._create_intent(
            instrument=report.instrument,
            action="limit-cancel-test",
            target="flat",
            side="sell",
            contracts=report.instrument.min_sz,
            reduce_only=False,
            order_type="limit",
            price=price,
        )
        result = self._intent_execution().submit_order(
            intent,
            before_position=Decimal("0"),
        )
        order = result.order or {}
        if order.get("state") != "live":
            raise SafetyError("far V8 limit order did not remain open")
        return intent.client_order_id, order

    def cancel_v8_order(self, report: PreflightReport, client_id: str) -> dict[str, Any]:
        if not client_id.startswith(CLIENT_PREFIX):
            raise SafetyError("refusing cancellation outside the V8 client-id namespace")
        self._assert_recovered()
        intent = self._create_intent(
            instrument=report.instrument,
            action=f"cancel-{client_id[-8:]}",
            target=client_id,
            side="cancel",
            contracts=Decimal("0"),
            reduce_only=True,
            order_type="cancel",
        )
        result = self._intent_execution().cancel_order(
            intent,
            original_client_id=client_id,
        )
        terminal = result.order or {}
        if terminal.get("state") not in {"canceled", "filled"}:
            raise SafetyError("V8 limit order did not reach cancelled state")
        if terminal.get("state") == "canceled" and result.position != 0:
            raise SafetyError("cancelled V8 limit unexpectedly changed position")
        self._append("cancelled", {"client_id": client_id, "state": terminal.get("state")})
        return terminal

    def reverse_minimum(self, report: PreflightReport) -> dict[str, Any]:
        """Bounded two-leg reversal; each leg owns a separate durable intent."""
        current = self._position(report.instrument)
        if abs(current) != report.instrument.min_sz:
            raise SafetyError("minimum reversal requires exactly one known minimum-size position")
        close_side = "sell" if current > 0 else "buy"
        open_side = close_side
        close_id, close = self.place_minimum(
            report,
            side=close_side,
            reduce_only=True,
        )
        if self._position(report.instrument) != 0:
            raise SafetyError("reversal close leg did not reconcile flat; open leg blocked")
        open_id, opening = self.place_minimum(
            report,
            side=open_side,
            reduce_only=False,
        )
        return {
            "close_client_id": close_id,
            "close_state": close.get("state"),
            "open_client_id": open_id,
            "open_state": opening.get("state"),
            "position": str(self._position(report.instrument)),
        }

    def cancel_known_pending(self, report: PreflightReport) -> int:
        """Cancel only exchange orders proven to belong to this durable ledger."""
        from .intents import IntentLedger

        self._assert_lock_held()
        self._assert_recovered()
        intent_ids = {
            item.client_order_id for item in IntentLedger(self.intent_path).load()
        }
        orders = self._ok(
            self.trade.get_order_list(instType="FUTURES", state="live"),
            "known-order cancellation inventory",
        )
        unknown = [
            row for row in orders
            if row.get("clOrdId") not in intent_ids
            or not str(row.get("clOrdId", "")).startswith(CLIENT_PREFIX)
        ]
        if unknown:
            raise SafetyError("unknown FUTURES order blocks known-order cancellation")
        for order in orders:
            self.cancel_v8_order(report, str(order["clOrdId"]))
        remaining = self._ok(
            self.trade.get_order_list(instType="FUTURES", state="live"),
            "post-cancel order inventory",
        )
        if remaining:
            raise SafetyError("known V8 order remains after cancellation")
        return len(orders)

    def _emergency_flatten_locked(self, report: PreflightReport) -> dict[str, Any]:
        """Cancel known pending risk, then flatten one proven V8 position."""
        self._assert_lock_held()
        self._assert_recovered()
        incident = {
            "kind": "emergency_flatten",
            "instrument": report.instrument.inst_id,
            "metadata_hash": report.instrument.metadata_hash,
        }
        self._append("incident_started", incident)
        try:
            current_metadata = self._discover()
            if (
                current_metadata.inst_id != report.instrument.inst_id
                or current_metadata.metadata_hash != report.instrument.metadata_hash
            ):
                raise SafetyError("X-Perp metadata changed after recovery; emergency mutation blocked")
            positions = self._ok(
                self.account.get_positions(instType="FUTURES"),
                "emergency FUTURES positions",
            )
            nonzero = [row for row in positions if _decimal(row.get("pos")) != 0]
            if len(nonzero) > 1 or (
                nonzero and nonzero[0].get("instId") != report.instrument.inst_id
            ):
                raise SafetyError("unknown or multiple FUTURES positions block emergency flatten")
            canceled_orders = self.cancel_known_pending(report)

            current = self._position(report.instrument)
            if current == 0:
                self._append(
                    "incident_resolved",
                    {**incident, "position": "0", "open_orders": 0, "result": "already_flat"},
                )
                return {"status": "already_flat", "canceled_orders": canceled_orders}
            self._assert_recovered()
            side = "sell" if current > 0 else "buy"
            intent = self._create_intent(
                instrument=report.instrument,
                action="emergency-flatten",
                target="flat",
                side=side,
                contracts=abs(current),
                reduce_only=True,
                order_type="market",
            )
            self._append("incident_order", {
                **incident,
                "client_id_hash": _safe_hash(intent.client_order_id),
                "position_before": str(current),
            })
            result = self._intent_execution().submit_order(
                intent,
                before_position=current,
            )
            terminal = result.order or {}
            if terminal.get("state") != "filled" or result.position != 0:
                raise SafetyError("emergency flatten did not restore flat position")
            final_positions = self._ok(
                self.account.get_positions(instType="FUTURES"),
                "post-flatten FUTURES positions",
            )
            if any(_decimal(row.get("pos")) != 0 for row in final_positions):
                raise SafetyError("FUTURES position remains after emergency flatten")
            remaining = self._ok(self.trade.get_order_list(instType="FUTURES", state="live"), "post-flatten orders")
            if remaining:
                raise SafetyError("open FUTURES orders remain after emergency flatten")
            self._append("incident_resolved", {
                **incident,
                "client_id_hash": _safe_hash(intent.client_order_id),
                "state": terminal.get("state"),
                "position": "0",
                "open_orders": 0,
            })
            return {"status": "flat", "client_id": intent.client_order_id, "terminal": terminal.get("state")}
        except Exception as exc:
            self._append(
                "incident_failed",
                {**incident, "error": type(exc).__name__, "message": str(exc)[:160]},
            )
            raise

    def emergency_flatten(self, report: PreflightReport) -> dict[str, Any]:
        if self._lock_depth:
            return self._emergency_flatten_locked(report)
        with self.locked():
            return self._emergency_flatten_locked(report)

    def smoke(self) -> dict[str, Any]:
        with self.locked():
            report = self.preflight()
            records: list[dict[str, Any]] = []
            for open_side, close_side, label in (("buy", "sell", "long"), ("sell", "buy", "short")):
                opening_id, opening = self.place_minimum(report, side=open_side, reduce_only=False)
                if self._position(report.instrument) == 0:
                    raise SafetyError("filled opening order did not create a position")
                closing_id, closing = self.place_minimum(report, side=close_side, reduce_only=True)
                if self._position(report.instrument) != 0:
                    raise SafetyError("reduce-only close did not restore flat position")
                records.append({"leg": label, "open_client_id_hash": _safe_hash(opening_id), "open_state": opening.get("state"),
                                "close_client_id_hash": _safe_hash(closing_id), "close_state": closing.get("state")})
            remaining = self._ok(self.trade.get_order_list(instType="FUTURES", state="live"), "final open orders")
            if remaining:
                raise SafetyError("V8 smoke left FUTURES open orders")
            self._append("smoke_pass", {"records": records, "instrument": report.instrument.inst_id})
            return {"preflight": report, "records": records, "final_position": "0", "open_orders": 0}

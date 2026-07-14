"""BTC Swing Allocator: dynamic BTC/USDT allocation.

Current default: v6-2, frozen. Rollback to v5:
--config '{"use_phase_policy_router": false, "use_funding_overlay": false}'.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

@dataclass
class SwingAllocatorConfig:
    symbol: str = "BTC-USDT"

    # -- Limites de allocation --
    base_btc_pct:  float = 0.60   # punto neutral (sin senales)
    # v4 default: floor 0.20 desbloquea la defensa profunda. Rollback: 0.30.
    min_btc_pct:   float = 0.20   # hard floor
    max_btc_pct:   float = 1.00   # hard ceiling — hasta 100%

    # -- Control de rebalanceo --
    rebalance_threshold:        float = 0.10  # umbral minimo de diferencia para actuar
    min_days_between_rebalance: int   = 3     # cooldown entre rebalanceos
    max_price_jump_pct:         float = 0.25  # F14: rechazar tick si salta >25% vs vela previa
    persist_live_rebalance_log: bool  = True  # F14: JSONL en paper/live (no backtest)

    # -- Toggles de senales (para ablation testing) --
    use_regime:    bool = True    # EMA50D/200D + ADX — regimen macro
    use_mvrv:      bool = False   # MVRV ratio — descartado en sensitivity v1
    use_rsi:       bool = False   # RSI diario — descartado en sensitivity v1
    use_pi_cycle:  bool = False   # Pi Cycle Top — descartado en sensitivity v1
    use_vix:       bool = False   # VIX — descartado en sensitivity v1
    use_macd_4h:   bool = False   # MACD en 4H — descartado en sensitivity v1
    use_halving:   bool = True    # fases de halving — contexto de ciclo
    use_funding:   bool = False   # funding rate — experimental
    use_dxy:       bool = False   # DXY direction — experimental
    instance_id:   str = ""       # live/paper namespace for parallel experiments
    # v6-2 default: table-driven v5-equivalent policy + accumulation funding overlay.
    # Set both flags False for an exact v5 rollback.
    use_phase_policy_router: bool = True
    phase_policy_profile: str = "v5_equiv"
    use_funding_overlay: bool = True
    funding_overlay_phases: str = "accumulation"
    funding_overlay_delta: float = 0.05
    funding_low_pctile: float = 0.10
    funding_high_pctile: float = 0.90
    funding_overlay_lookback_settlements: int = 90
    funding_overlay_ttl_days: int = 7
    funding_overlay_dedup_days: int = 7

    # v2: en bear_onset suprime SOLO regime_bull; regime_bear se mantiene. False vuelve a v1.
    regime_off_on_bear_onset: bool = True

    # v3: en bull_peak, perder EMA50D cerrada capea solo el target maximo a 85%.
    bull_peak_ema50_cap_enabled: bool = True
    bull_peak_ema50_cap:         float = 0.85

    # Latch del cap probado y descartado: default False mantiene v3 intacto.
    bull_peak_cap_latch: bool = False

    # -- Deltas de cada senal (cuanto mueve el target) --
    delta_regime_bull:   float =  0.20   # bull macro: EMA50D>200D + precio>200D + ADX>15
    delta_regime_bear:   float = -0.20   # bear macro: EMA50D<200D
    delta_rsi_ob:        float = -0.15   # RSI > rsi_overbought
    delta_rsi_os:        float =  0.15   # RSI < rsi_oversold
    delta_mvrv_high:     float = -0.10   # MVRV > mvrv_reduce
    delta_pi_cycle:      float = -0.20   # Pi Cycle Top activo
    delta_vix_panic:     float =  0.10   # VIX > vix_panic_buy (panico = oportunidad)
    delta_vix_extreme:   float = -0.10   # VIX > vix_extreme (crisis sistemica)
    delta_macd_4h_bull:  float =  0.05   # 4H MACD por encima de signal line
    delta_macd_4h_bear:  float = -0.05   # 4H MACD por debajo de signal line
    delta_post_halving:  float =  0.20   # fase post_halving / bull_peak — v1 validado WF 4/4
    delta_bear_onset:    float = -0.30   # fase bear_onset — v4 (era -0.20 en v1-v3). Rollback: -0.20
    delta_funding_high:  float = -0.05   # funding > funding_high (mercado muy largo)
    delta_funding_neg:   float =  0.05   # funding negativo (shorts excesivos)
    delta_dxy_strong:    float = -0.05   # DXY subio > 1.5% en 10 dias
    delta_dxy_weak:      float =  0.05   # DXY bajo > 1.5% en 10 dias

    # -- Thresholds de senales --
    adx_min_trend:  float = 15.0
    rsi_overbought: float = 75.0
    rsi_oversold:   float = 35.0
    mvrv_reduce:    float = 2.5
    vix_panic_buy:  float = 35.0
    vix_extreme:    float = 55.0
    funding_high:   float = 0.0005   # mismo umbral que Pro Trend

    # -- Flags de correccion de auditoria (F8/F9). --
    # F8: indicadores diarios solo con dias cerrados. False reproduce v4 congelado.
    daily_on_closed_only: bool = True
    # clock_aligned_cadence: evalua en horas UTC multiplos de 4 en vez de _bar_count % 4
    # (F9 medido y NO adoptado: no redujo sensibilidad al offset).
    clock_aligned_cadence: bool = False

    # -- Umbrales de fase de halving (F4 auditoria) --
    # Defaults historicos; solo para sensitivity.
    phase_post_end:  int = 180
    phase_peak_end:  int = 540
    phase_onset_end: int = 900

    # -- Historial para indicadores de largo plazo --
    # OJO: EMA200D truncada a esta ventana; cambiar lookback_hours cambia senales.
    lookback_hours:   int  = 6000    # ~250 dias en 1H — suficiente para EMA200D
    pi_cycle_enabled: bool = True    # auto-False para no-BTC en main.py

    @classmethod
    def from_dict(cls, d: dict) -> "SwingAllocatorConfig":
        c = cls()
        # Existing isolated v5 paper rows predate the v6 default and therefore omit
        # these flags. Keep that named control on real v5 after a code deployment.
        if str(d.get("instance_id", "")).lower() == "v5":
            if "use_phase_policy_router" not in d:
                c.use_phase_policy_router = False
            if "use_funding_overlay" not in d:
                c.use_funding_overlay = False
        for k, v in d.items():
            if not hasattr(c, k):
                continue
            attr = getattr(c, k)
            if isinstance(attr, bool):
                if isinstance(v, str):
                    setattr(c, k, v.lower() not in ("false", "0", ""))
                else:
                    setattr(c, k, bool(v))
            elif isinstance(attr, int):
                setattr(c, k, int(v))
            elif isinstance(attr, float):
                setattr(c, k, float(v))
            else:
                setattr(c, k, v)
        return c

    def to_dict(self) -> dict:
        return asdict(self)

class SwingAllocatorBot:
    """Gestiona la allocation BTC/USDT dinamicamente segun senales de mercado."""

    def __init__(self, client, config: SwingAllocatorConfig, session=None, risk_manager=None) -> None:
        self._client  = client
        self._cfg     = config
        self._session = session
        self._risk_manager = risk_manager

        # F4 auditoria: aplicar umbrales de fase de halving (default = sin cambio)
        from strategies.macro_context import set_phase_bounds
        set_phase_bounds(config.phase_post_end, config.phase_peak_end, config.phase_onset_end)

        # Estado interno
        self._initialized     = False
        self._last_rebalance: datetime | None = None
        self._bar_count       = 0
        self._cap_latched     = False   # trinquete del cap dentro de una fase bull_peak
        self._instance_id     = self._sanitize_instance_id(config.instance_id)

        # Estado persistente live/paper: `start` re-instancia la estrategia en cada tick.
        self._live_mode = not self._is_backtest_client()
        self._live_state: dict = {
            "initialized": False, "last_rebalance": None, "last_eval_block": None,
        }
        if self._live_mode and self._session is not None:
            self._load_live_state()

        # Caches de indicadores (mismo patron que Pro Trend)
        self._daily_cache: dict = {}   # {"date": "YYYY-MM-DD", "ind": {...}}
        self._4h_cache:    dict = {}   # {"key": "YYYY-MM-DD-N", "ind": {...}}

        # Log de rebalanceos (distinto de _journal para no confundir al engine)
        self._rebalance_log: list[dict] = []

    @property
    def name(self) -> str:
        sym = self._cfg.symbol.lower().replace("-", "_")
        mid = f"_{self._instance_id}" if self._instance_id else ""
        return f"swing_allocator{mid}_{sym}"

    @property
    def _state_name(self) -> str:
        return f"swing_allocator_{self._instance_id}" if self._instance_id else "swing_allocator"

    @staticmethod
    def _sanitize_instance_id(value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value).lower())
        return safe.strip("_")

    def run(self) -> None:
        self._bar_count += 1

        # Primera barra: inicializar allocation comprando BTC
        if not self._initialized:
            if not self._market_data_ok():
                return
            self._initialize()
            return

        # Cadencia de evaluacion.
        # Backtest: cada 4 barras 1H (o clock_aligned_cadence, F9 — no adoptado como default).
        # Live/paper: UNA evaluacion por bloque 4H UTC, persistida en BotState — el scheduler
        # re-instancia la estrategia en cada tick y _bar_count no sirve de cadencia alli.
        eval_block: str | None = None
        if self._live_mode:
            eval_block = self._current_eval_block()
            if eval_block == self._live_state.get("last_eval_block"):
                return
        elif self._cfg.clock_aligned_cadence:
            if self._client.current_time().hour % 4 != 0:
                return
        elif self._bar_count % 4 != 0:
            return

        # Cooldown entre rebalanceos
        if not self._cooldown_ok():
            if eval_block is not None:
                self._consume_eval_block(eval_block)
            return

        # Live: si los datos de mercado fallan NO se consume el bloque — se reintenta en el
        # siguiente tick del scheduler. En backtest este check es no-op (ver _market_data_ok).
        if not self._market_data_ok():
            return

        if eval_block is not None:
            self._consume_eval_block(eval_block)

        current          = self._current_btc_pct()
        target, signals  = self._compute_target(current)
        diff             = target - current

        if abs(diff) < self._cfg.rebalance_threshold:
            return

        self._rebalance(target, current, signals)

    def _initialize(self) -> None:
        """Primera barra: comprar base_btc_pct del capital en BTC."""
        balance = self._client.get_balance()
        usdt    = balance.get("USDT", Decimal("0"))
        base    = self._cfg.symbol.split("-")[0]

        if balance.get(base, Decimal("0")) > Decimal("0"):
            # Ya tiene BTC (raro en backtest, pero defensivo)
            self._mark_initialized()
            return

        invest = usdt * Decimal(str(self._cfg.base_btc_pct))
        if not self._risk_allows_buy(invest):
            self._mark_initialized()
            return

        price  = self._client.get_ticker(self._cfg.symbol)
        qty    = (invest / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

        if qty <= Decimal("0"):
            self._mark_initialized()
            return

        result = self._client.place_order(
            self._cfg.symbol, "buy", "market", qty, strategy=self.name
        )

        if result.status == "filled":
            logger.info(
                "[{}] Init: {:.6f} BTC a {:.2f} ({:.0f}% del capital)",
                self.name, float(qty), float(price), self._cfg.base_btc_pct * 100,
            )
            self._log_rebalance(
                pct_before=0.0,
                pct_target=self._cfg.base_btc_pct,
                pct_after=self._current_btc_pct_raw(usdt, qty, price),
                direction="INIT",
                price=float(price),
                qty=float(qty),
                portfolio_usdt=float(usdt),
                signals=["init"],
            )
        else:
            logger.warning("[{}] Init rechazada: {}", self.name, result.error)

        self._mark_initialized()

    def _compute_target(self, current_pct: float) -> float:
        """
        Agrega deltas de senales sobre la base. Aplica hard limits.
        Devuelve el porcentaje objetivo de BTC [min_btc_pct, max_btc_pct].
        """
        cfg    = self._cfg
        target = cfg.base_btc_pct
        active: list[str] = []

        try:
            ind    = self._get_daily_indicators()
            h4     = self._get_4h_context()
            macro  = self._get_macro_context()
            market = self._get_market_context()
        except Exception as exc:
            logger.debug("[{}] Error al obtener indicadores: {}", self.name, exc)
            ind = h4 = macro = market = None

        # Mitigacion Q4 2025: suprime solo regime_bull en bear_onset.
        phase = macro.get("halving_phase", "") if macro else ""
        bear_onset_active = bool(cfg.use_halving and phase == "bear_onset")
        suppress_bull = cfg.regime_off_on_bear_onset and bear_onset_active

        price = float(self._client.get_ticker(self._cfg.symbol))

        used_phase_policy = False
        if cfg.use_phase_policy_router and cfg.use_halving and macro:
            try:
                from strategies.swing_phase_policy import phase_policy_target, regime_state
                regime = regime_state(ind, price, cfg.adx_min_trend, cfg.use_regime)
                routed = phase_policy_target(cfg.phase_policy_profile, phase, regime)
                if routed is not None:
                    target, active = routed
                    used_phase_policy = True
            except Exception as exc:
                logger.debug("[{}] Phase policy router fallback: {}", self.name, exc)

        # --- Regimen macro: EMA50D/200D + ADX ---
        if not used_phase_policy and cfg.use_regime and ind:
            ema50  = ind.get("ema50d",  0.0)
            ema200 = ind.get("ema200d", 0.0)
            adx_v  = ind.get("adx",     0.0)
            if ema50 > ema200 and price > ema200 and adx_v > cfg.adx_min_trend:
                if suppress_bull:
                    active.append("regime_bull_suppressed_bear_onset")
                else:
                    target += cfg.delta_regime_bull
                    active.append("regime_bull")
            elif ema50 < ema200:
                target += cfg.delta_regime_bear
                active.append("regime_bear")

        # --- Halving phase ---
        if not used_phase_policy and cfg.use_halving and macro:
            if phase in ("post_halving", "bull_peak"):
                target += cfg.delta_post_halving
                active.append(f"halving_{phase}")
            elif phase == "bear_onset":
                target += cfg.delta_bear_onset
                active.append("halving_bear_onset")

        # --- MVRV valoracion ---
        if cfg.use_mvrv and macro:
            mvrv = macro.get("mvrv", 0.0) or 0.0
            if mvrv > cfg.mvrv_reduce:
                target += cfg.delta_mvrv_high
                active.append(f"mvrv_{mvrv:.2f}")

        # --- RSI diario ---
        if cfg.use_rsi and ind:
            rsi_v = ind.get("rsi", 50.0)
            if rsi_v > cfg.rsi_overbought:
                target += cfg.delta_rsi_ob
                active.append(f"rsi_ob_{rsi_v:.0f}")
            elif rsi_v < cfg.rsi_oversold:
                target += cfg.delta_rsi_os
                active.append(f"rsi_os_{rsi_v:.0f}")

        # --- Pi Cycle Top ---
        if cfg.use_pi_cycle and cfg.pi_cycle_enabled and ind:
            if ind.get("pi_cycle_top", False):
                target += cfg.delta_pi_cycle
                active.append("pi_cycle_top")

        # --- VIX panico/crisis ---
        if cfg.use_vix and market:
            vix = market.get("vix_level") or 0.0
            if vix > cfg.vix_extreme:
                target += cfg.delta_vix_extreme
                active.append(f"vix_extreme_{vix:.0f}")
            elif vix > cfg.vix_panic_buy:
                target += cfg.delta_vix_panic
                active.append(f"vix_panic_{vix:.0f}")

        # --- MACD 4H momentum ---
        if cfg.use_macd_4h and h4 is not None:
            if h4.get("macd_above", False):
                target += cfg.delta_macd_4h_bull
                active.append("macd4h_bull")
            else:
                target += cfg.delta_macd_4h_bear
                active.append("macd4h_bear")

        # --- Funding rate (experimental) ---
        if cfg.use_funding and macro:
            funding = macro.get("funding_rate", 0.0) or 0.0
            if funding > cfg.funding_high:
                target += cfg.delta_funding_high
                active.append(f"funding_high_{funding:.4f}")
            elif funding < 0:
                target += cfg.delta_funding_neg
                active.append(f"funding_neg_{funding:.4f}")

        if cfg.use_funding_overlay:
            try:
                from strategies.swing_funding_overlay import funding_overlay_adjustment
                adj, reason = funding_overlay_adjustment(
                    cfg.symbol, self._client.current_time(), phase, cfg
                )
                if reason:
                    target += adj
                    active.append(reason)
            except Exception as exc:
                # Warning, no debug: si el overlay esta activo y falla, v6 degrada a v5
                # en silencio. En vivo esto debe verse (ej. cache de funding ausente/corrupto).
                logger.warning("[{}] Funding overlay skipped: {}", self.name, exc)

        # --- DXY direction (experimental) ---
        if cfg.use_dxy and market:
            dxy_change = market.get("dxy_change") or 0.0
            if dxy_change > 1.5:
                target += cfg.delta_dxy_strong
                active.append(f"dxy_strong_{dxy_change:.1f}")
            elif dxy_change < -1.5:
                target += cfg.delta_dxy_weak
                active.append(f"dxy_weak_{dxy_change:.1f}")

        # --- Late-cycle de-risk: cap after losing the previous full day's EMA50D ---
        ema50_closed = ind.get("ema50d_closed") if ind else None
        if phase != "bull_peak":
            self._cap_latched = False   # reset al salir de bull_peak

        if cfg.bull_peak_ema50_cap_enabled and cfg.use_halving and phase == "bull_peak":
            lost_ema50 = ema50_closed is not None and price < float(ema50_closed)
            if lost_ema50 and cfg.bull_peak_cap_latch:
                self._cap_latched = True
            apply_cap = lost_ema50 or (cfg.bull_peak_cap_latch and self._cap_latched)
            if apply_cap and target > cfg.bull_peak_ema50_cap:
                target = cfg.bull_peak_ema50_cap
                tag = "bull_peak_ema50_cap" if lost_ema50 else "bull_peak_cap_hold"
                active.append(f"{tag}_{target:.2f}")

        # Hard limits
        target = max(cfg.min_btc_pct, min(cfg.max_btc_pct, target))

        logger.debug(
            "[{}] Target: {:.0f}% (actual {:.0f}%) | {}",
            self.name, target * 100, current_pct * 100,
            ", ".join(active) if active else "base",
        )

        return target, active

    def _rebalance(self, target: float, current: float, signals: list[str]) -> None:
        balance  = self._client.get_balance()
        usdt_bal = balance.get("USDT", Decimal("0"))
        base     = self._cfg.symbol.split("-")[0]
        btc_bal  = balance.get(base, Decimal("0"))
        price    = self._client.get_ticker(self._cfg.symbol)

        total              = usdt_bal + btc_bal * price
        target_btc_value   = total * Decimal(str(target))
        current_btc_value  = btc_bal * price
        delta_value        = target_btc_value - current_btc_value

        if delta_value > Decimal("1"):  # Comprar BTC
            # Reservar 0.35% para cubrir fee+slippage en todos los modos (conservative=0.25%)
            buy_usdt = min(delta_value, usdt_bal * Decimal("0.9965"))
            if not self._risk_allows_buy(buy_usdt):
                return
            qty = (buy_usdt / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            if qty < Decimal("0.000001"):
                return
            result    = self._client.place_order(
                self._cfg.symbol, "buy", "market", qty, strategy=self.name
            )
            direction = "BUY"

        elif delta_value < Decimal("-1"):  # Vender BTC
            sell_qty = (abs(delta_value) / price).quantize(
                Decimal("0.000001"), rounding=ROUND_DOWN
            )
            sell_qty = min(sell_qty, btc_bal)
            if sell_qty < Decimal("0.000001"):
                return
            result    = self._client.place_order(
                self._cfg.symbol, "sell", "market", sell_qty, strategy=self.name
            )
            direction = "SELL"

        else:
            return

        if result.status != "filled":
            logger.warning("[{}] Orden rechazada: {}", self.name, result.error)
            return

        pct_after = self._current_btc_pct()
        residual = abs(target - pct_after)
        # Un fill incompleto no debe ocultar durante 3 dias una cartera lejos del target.
        if residual < self._cfg.rebalance_threshold:
            self._last_rebalance = self._client.current_time()
            self._save_live_state()   # no-op en backtest
        else:
            logger.warning("[{}] Rebalanceo incompleto: target {:.1f}%, actual {:.1f}% "
                           "(residual {:.1f}%); sin cooldown, reintento en proximo bloque 4H",
                           self.name, target * 100, pct_after * 100, residual * 100)
        logger.info(
            "[{}] {} | {:.0f}% -> {:.0f}% | {:.2f} USDT | qty {:.6f}",
            self.name, direction,
            current * 100, pct_after * 100,
            float(price), float(result.filled_qty),
        )

        self._log_rebalance(
            pct_before=current,
            pct_target=target,
            pct_after=pct_after,
            direction=direction,
            price=float(price),
            qty=float(result.filled_qty),
            portfolio_usdt=float(total),
            signals=signals,
        )

    def _risk_allows_buy(self, size_usdt: Decimal) -> bool:
        """RiskManager del live/paper: bloquear solo compras si se supero perdida diaria."""
        if self._risk_manager is None:
            return True
        try:
            limit_hit, daily_pnl = self._risk_manager.check_daily_loss()
        except Exception as exc:
            logger.warning("[{}] RiskManager fallo; compra bloqueada: {}", self.name, exc)
            return False
        if limit_hit:
            logger.warning(
                "[{}] Compra bloqueada por limite de perdida diaria: {:.2f} USDT (orden {:.2f})",
                self.name, daily_pnl, float(size_usdt),
            )
            return False
        return True

    def _market_data_ok(self) -> bool:
        """
        Control minimo F14: no operar con OHLCV ausente o precio anomalo.
        SOLO live/paper (M2 auditoria v5): en backtest es no-op — los datos del cache ya estan
        validados (salto 1H maximo historico BTC 19.18%, ETH 24.07%) y un skip silencioso de la
        barra de decision romperia el protocolo de medicion aislada.
        """
        if self._is_backtest_client():
            return True
        threshold = self._cfg.max_price_jump_pct
        if threshold <= 0:
            return True
        try:
            df = self._client.get_ohlcv(self._cfg.symbol, limit=2)
            if df is None or len(df) < 2:
                logger.warning("[{}] OHLCV insuficiente; se omite decision", self.name)
                return False
            prev_close = float(df["close"].iloc[-2])
            price = float(self._client.get_ticker(self._cfg.symbol))
            if prev_close <= 0 or price <= 0:
                logger.warning("[{}] Precio invalido prev={} current={}", self.name, prev_close, price)
                return False
            jump = abs(price / prev_close - 1.0)
            if jump > threshold:
                logger.warning(
                    "[{}] Tick rechazado por salto anomalo: {:.2%} > {:.2%}",
                    self.name, jump, threshold,
                )
                return False
            return True
        except Exception as exc:
            logger.warning("[{}] Validacion de mercado fallo; se omite decision: {}", self.name, exc)
            return False

    def _is_backtest_client(self) -> bool:
        return self._client.__class__.__name__ == "BacktestClient"

    def _load_live_state(self) -> None:
        try:
            from core.database import get_or_create_bot_state
            bot_state = get_or_create_bot_state(
                self._session, strategy_name=self._state_name, symbol=self._cfg.symbol,
            )
            self._live_state = {**self._live_state, **bot_state.get_config()}
        except Exception as exc:
            logger.warning("[{}] No se pudo cargar estado live (se usa fresco): {}", self.name, exc)
            return
        self._initialized = bool(self._live_state.get("initialized", False))
        last_reb = self._live_state.get("last_rebalance")
        if last_reb:
            try:
                self._last_rebalance = datetime.fromisoformat(last_reb)
            except ValueError:
                logger.warning("[{}] last_rebalance corrupto en estado live: {}", self.name, last_reb)

    def _save_live_state(self) -> None:
        if not self._live_mode or self._session is None:
            return
        self._live_state["initialized"] = self._initialized
        self._live_state["last_rebalance"] = (
            self._last_rebalance.isoformat() if self._last_rebalance else None
        )
        try:
            from core.database import get_or_create_bot_state
            bot_state = get_or_create_bot_state(
                self._session, strategy_name=self._state_name, symbol=self._cfg.symbol,
            )
            bot_state.set_config(self._live_state)
        except Exception as exc:
            logger.warning("[{}] No se pudo guardar estado live: {}", self.name, exc)

    def _mark_initialized(self) -> None:
        self._initialized = True
        self._save_live_state()

    def _current_eval_block(self) -> str:
        """Identificador del bloque 4H UTC actual, p.ej. '2026-07-02T3' (12:00-15:59)."""
        now = self._client.current_time()
        return f"{now.date().isoformat()}T{now.hour // 4}"

    def _consume_eval_block(self, block: str) -> None:
        self._live_state["last_eval_block"] = block
        self._save_live_state()

    def _get_daily_indicators(self) -> dict | None:
        current_dt = self._client.current_time()
        date_key   = current_dt.strftime("%Y-%m-%d")

        if self._daily_cache.get("date") == date_key:
            return self._daily_cache["ind"]

        try:
            from strategies.indicators import (
                resample_to_daily, ema as ema_fn, rsi as rsi_fn,
                adx as adx_fn, sma as sma_fn,
            )

            df = self._client.get_ohlcv(self._cfg.symbol, limit=self._cfg.lookback_hours)
            if df is None or len(df) < 500:
                return None

            daily = resample_to_daily(df)
            if len(daily) < 201:
                return None

            current_day = pd.Timestamp(current_dt.date(), tz="UTC")
            closed_daily = daily[daily["dt"] < current_day]

            # F8 auditoria (C2): con daily_on_closed_only todos los indicadores diarios se
            # calculan SOLO con dias cerrados (regla invariante #1). Rollback False reproduce
            # v4 congelado, que incluia el dia en curso parcial.
            calc = closed_daily if self._cfg.daily_on_closed_only else daily
            if len(calc) < 201:
                return None

            closes = calc["close"]
            highs  = calc["high"]
            lows   = calc["low"]

            ema50d  = ema_fn(closes, 50)
            ema200d = ema_fn(closes, 200)
            rsi14   = rsi_fn(closes, 14)
            adx14   = adx_fn(highs, lows, closes, 14)

            ema50d_closed = None
            if len(closed_daily) >= 50:
                ema50d_closed = float(ema_fn(closed_daily["close"], 50).iloc[-1])

            # Pi Cycle Top: SMA111D * 2 >= SMA350D
            pi_cycle_top = False
            if self._cfg.pi_cycle_enabled and len(daily) >= 351:
                sma111 = sma_fn(closes, 111)
                sma350 = sma_fn(closes, 350)
                pi_cycle_top = (float(sma111.iloc[-1]) * 2) >= float(sma350.iloc[-1])

            ind = {
                "ema50d":       float(ema50d.iloc[-1]),
                "ema200d":      float(ema200d.iloc[-1]),
                "rsi":          float(rsi14.iloc[-1]),
                "adx":          float(adx14.iloc[-1]),
                "pi_cycle_top": pi_cycle_top,
                "ema50d_closed": ema50d_closed,
            }

            self._daily_cache = {"date": date_key, "ind": ind}
            return ind

        except Exception as exc:
            logger.debug("[{}] Error ind diarios: {}", self.name, exc)
            return None

    def _get_4h_context(self) -> dict | None:
        current_dt = self._client.current_time()
        block      = current_dt.hour // 4
        key        = f"{current_dt.strftime('%Y-%m-%d')}-{block}"

        if self._4h_cache.get("key") == key:
            return self._4h_cache["ctx"]

        try:
            from strategies.indicators import resample_to_4h, macd as macd_fn

            df = self._client.get_ohlcv(self._cfg.symbol, limit=2000)
            if df is None or len(df) < 200:
                return None

            df4h = resample_to_4h(df)
            if len(df4h) < 40:
                return None

            # Excluir bloque 4H actual incompleto (lookahead fix — igual que Pro Trend)
            closes4h = df4h["close"].iloc[:-1]

            macd_line, signal_line, _ = macd_fn(closes4h)
            macd_above = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

            ctx = {"macd_above": macd_above}
            self._4h_cache = {"key": key, "ctx": ctx}
            return ctx

        except Exception as exc:
            logger.debug("[{}] Error 4H context: {}", self.name, exc)
            return None

    def _get_macro_context(self) -> dict | None:
        try:
            from strategies.macro_context import get_macro_signal
            return get_macro_signal(self._client.current_time())
        except Exception as exc:
            logger.debug("[{}] Error macro context: {}", self.name, exc)
            return None

    def _get_market_context(self) -> dict | None:
        try:
            from strategies.market_context import get_market_context
            return get_market_context(self._client.current_time())
        except Exception as exc:
            logger.debug("[{}] Error market context: {}", self.name, exc)
            return None

    def _current_btc_pct(self) -> float:
        balance = self._client.get_balance()
        usdt    = float(balance.get("USDT", Decimal("0")))
        base    = self._cfg.symbol.split("-")[0]
        btc     = float(balance.get(base, Decimal("0")))
        price   = float(self._client.get_ticker(self._cfg.symbol))
        total   = usdt + btc * price
        return (btc * price / total) if total > 0 else 0.0

    def _current_btc_pct_raw(
        self, usdt_before: Decimal, qty: Decimal, price: Decimal
    ) -> float:
        btc_val = float(qty * price)
        total   = float(usdt_before)
        return btc_val / total if total > 0 else 0.0

    def _cooldown_ok(self) -> bool:
        if self._last_rebalance is None:
            return True
        elapsed = self._client.current_time() - self._last_rebalance
        return elapsed >= timedelta(days=self._cfg.min_days_between_rebalance)

    def _log_rebalance(
        self,
        pct_before:     float,
        pct_target:     float,
        pct_after:      float,
        direction:      str,
        price:          float,
        qty:            float,
        portfolio_usdt: float,
        signals:        list[str],
    ) -> None:
        entry = {
            "num":            len(self._rebalance_log) + 1,
            "timestamp":      self._client.current_time().isoformat(),
            "direction":      direction,
            "price":          round(price, 2),
            "qty":            round(qty, 6),
            "btc_pct_before": round(pct_before, 4),
            "btc_pct_target": round(pct_target, 4),
            "btc_pct_after":  round(pct_after,  4),
            "portfolio_usdt": round(portfolio_usdt, 2),
            "signals":        signals,
        }
        self._rebalance_log.append(entry)
        self._persist_live_rebalance(entry)

    def _persist_live_rebalance(self, entry: dict) -> None:
        if self._is_backtest_client() or not self._cfg.persist_live_rebalance_log:
            return
        try:
            out_dir = Path("data") / "runtime"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "swing_rebalances.jsonl"
            payload = {"strategy": self.name, "symbol": self._cfg.symbol, **entry}
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.warning("[{}] No se pudo persistir rebalance live: {}", self.name, exc)

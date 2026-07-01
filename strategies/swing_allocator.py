"""
BTC Swing Allocator — gestion dinamica de allocation BTC/USDT.

Mantiene siempre un porcentaje minimo en BTC y ajusta entre 30-100%
segun senales macro, de valoracion, y tecnicas.

Objetivo: batir BTC Buy & Hold acumulando mas BTC en correcciones.
Diferencia vs Pro Trend: nunca sale del todo — ajusta el porcentaje.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class SwingAllocatorConfig:
    symbol: str = "BTC-USDT"

    # -- Limites de allocation --
    base_btc_pct:  float = 0.60   # punto neutral (sin senales)
    min_btc_pct:   float = 0.30   # hard floor — nunca menos del 30%
    max_btc_pct:   float = 1.00   # hard ceiling — hasta 100%

    # -- Control de rebalanceo --
    rebalance_threshold:        float = 0.10  # umbral minimo de diferencia para actuar
    min_days_between_rebalance: int   = 3     # cooldown entre rebalanceos

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

    # -- Mitigacion Q4 2025 — v2 DEFAULT desde 2026-07-01 (reversible: False vuelve a v1) --
    # Cuando bear_onset esta activo, suprime SOLO la rama regime_bull (ruido de EMA-cross al alza
    # en lateral, causa del ping-pong 60%<->30% en Q4 2025). regime_bear se mantiene (defensa real
    # en bear market). Version anterior (suprimir todo regime) rompia 2022 — ver sesion 13.
    # Validado go/no-go completo: 2015-26 +80.6% CAGR / -55.23% DD, 2018-26 +41.5% / -53.42%,
    # WF 4/4 TEST positivo, ETH identico a v1 (sin halvings). Estructural: bear_onset = distribucion.
    regime_off_on_bear_onset: bool = True

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
    delta_bear_onset:    float = -0.20   # fase bear_onset — v1 validado WF 4/4
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

    # -- Historial para indicadores de largo plazo --
    lookback_hours:   int  = 6000    # ~250 dias en 1H — suficiente para EMA200D
    pi_cycle_enabled: bool = True    # auto-False para no-BTC en main.py

    @classmethod
    def from_dict(cls, d: dict) -> "SwingAllocatorConfig":
        c = cls()
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


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class SwingAllocatorBot:
    """
    Gestiona la allocation BTC/USDT dinamicamente segun senales de mercado.
    Siempre mantiene min_btc_pct en BTC — nunca sale del todo.
    Compatible con BacktestEngine (requiere run() y name).
    """

    def __init__(self, client, config: SwingAllocatorConfig, session=None) -> None:
        self._client  = client
        self._cfg     = config
        self._session = session

        # Estado interno
        self._initialized     = False
        self._last_rebalance: datetime | None = None
        self._bar_count       = 0

        # Caches de indicadores (mismo patron que Pro Trend)
        self._daily_cache: dict = {}   # {"date": "YYYY-MM-DD", "ind": {...}}
        self._4h_cache:    dict = {}   # {"key": "YYYY-MM-DD-N", "ind": {...}}

        # Log de rebalanceos (distinto de _journal para no confundir al engine)
        self._rebalance_log: list[dict] = []

    @property
    def name(self) -> str:
        return f"swing_allocator_{self._cfg.symbol.lower().replace('-', '_')}"

    # -----------------------------------------------------------------------
    # Loop principal — llamado en cada barra por BacktestEngine
    # -----------------------------------------------------------------------

    def run(self) -> None:
        self._bar_count += 1

        # Primera barra: inicializar allocation comprando BTC
        if not self._initialized:
            self._initialize()
            return

        # Evaluar solo cada 4 barras (cadencia 4H en datos 1H — reduce ruido)
        if self._bar_count % 4 != 0:
            return

        # Cooldown entre rebalanceos
        if not self._cooldown_ok():
            return

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
            self._initialized = True
            return

        invest = usdt * Decimal(str(self._cfg.base_btc_pct))
        price  = self._client.get_ticker(self._cfg.symbol)
        qty    = (invest / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

        if qty <= Decimal("0"):
            self._initialized = True
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

        self._initialized = True

    # -----------------------------------------------------------------------
    # Calculo del target
    # -----------------------------------------------------------------------

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

        # Mitigacion Q4 2025 (quirurgica): si bear_onset activo y flag on, se suprime SOLO
        # la rama regime_bull (ruido de EMA-cross al alza en lateral, causa del ping-pong Q4 2025)
        # pero se MANTIENE regime_bear (senal defensiva real en bear market — su supresion rompio
        # 2022 en la version anterior). Ver analisis sesion 13.
        bear_onset_active = bool(
            cfg.use_halving and macro and macro.get("halving_phase", "") == "bear_onset"
        )
        suppress_bull = cfg.regime_off_on_bear_onset and bear_onset_active

        # --- Regimen macro: EMA50D/200D + ADX ---
        if cfg.use_regime and ind:
            ema50  = ind.get("ema50d",  0.0)
            ema200 = ind.get("ema200d", 0.0)
            adx_v  = ind.get("adx",     0.0)
            price  = float(self._client.get_ticker(self._cfg.symbol))
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
        if cfg.use_halving and macro:
            phase = macro.get("halving_phase", "")
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

        # --- DXY direction (experimental) ---
        if cfg.use_dxy and market:
            dxy_change = market.get("dxy_change") or 0.0
            if dxy_change > 1.5:
                target += cfg.delta_dxy_strong
                active.append(f"dxy_strong_{dxy_change:.1f}")
            elif dxy_change < -1.5:
                target += cfg.delta_dxy_weak
                active.append(f"dxy_weak_{dxy_change:.1f}")

        # Hard limits
        target = max(cfg.min_btc_pct, min(cfg.max_btc_pct, target))

        logger.debug(
            "[{}] Target: {:.0f}% (actual {:.0f}%) | {}",
            self.name, target * 100, current_pct * 100,
            ", ".join(active) if active else "base",
        )

        return target, active

    # -----------------------------------------------------------------------
    # Ejecucion del rebalanceo
    # -----------------------------------------------------------------------

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
            qty       = sell_qty
            direction = "SELL"

        else:
            return

        if result.status != "filled":
            logger.warning("[{}] Orden rechazada: {}", self.name, result.error)
            return

        self._last_rebalance = self._client.current_time()
        pct_after = self._current_btc_pct()

        logger.info(
            "[{}] {} | {:.0f}% -> {:.0f}% | {:.2f} USDT | qty {:.6f}",
            self.name, direction,
            current * 100, pct_after * 100,
            float(price), float(qty),
        )

        self._log_rebalance(
            pct_before=current,
            pct_target=target,
            pct_after=pct_after,
            direction=direction,
            price=float(price),
            qty=float(qty),
            portfolio_usdt=float(total),
            signals=signals,
        )

    # -----------------------------------------------------------------------
    # Indicadores — con cache para evitar O(n^2)
    # -----------------------------------------------------------------------

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

            closes = daily["close"]
            highs  = daily["high"]
            lows   = daily["low"]

            ema50d  = ema_fn(closes, 50)
            ema200d = ema_fn(closes, 200)
            rsi14   = rsi_fn(closes, 14)
            adx14   = adx_fn(highs, lows, closes, 14)

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

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

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
        self._rebalance_log.append({
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
        })

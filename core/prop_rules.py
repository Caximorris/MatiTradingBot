"""
Simulador de reglas de prop firm (HyroTrader) sobre curvas de equity.

P1 de HYROTRADER_PLAN.md. Estrategia-agnostico: consume la equity_curve de cualquier
BacktestResult (timestamps UTC + Decimal) y evalua las reglas verificadas 2026-07-03:

- Daily drawdown: importe fijo = pct x balance inicial del challenge.
  * standard (trailing): suelo = pico de equity del dia UTC - importe. Un retroceso desde el
    pico intradia breachea AUNQUE el dia sea positivo.
  * swing upgrade (estatico): suelo = equity de inicio del dia UTC - importe.
- Max loss total: estatico sobre el balance inicial.
- Max perdida REALIZADA por trade: pct del balance inicial.
- Profit target + minimo de dias de trading.
- Profit Distribution: ningun dia UTC > pct del resultado neto total (solo evaluacion).
  No es fallo terminal: el challenge sigue hasta que la distribucion normaliza o hay timeout.
- Reset diario: medianoche UTC. Equity incluye uPnL y fees (la curva del backtest ya lo hace).

LIMITACION DOCUMENTADA: la equity es horaria (cierres de vela 1H); el trailing real es
tick-a-tick, asi que los picos/valles intradia se SUBESTIMAN. `intrabar_buffer` endurece los
limites (0.2 = 20%) para compensar — usar >=0.2 en decisiones, 0.0 solo para cota optimista.

Interno en float: esto es analitica de probabilidades, no contabilidad de ordenes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Sequence

# ---------------------------------------------------------------------------
# Config y presets (numeros verificados en HYROTRADER_PLAN.md seccion 9)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PropRulesConfig:
    label:                   str
    daily_dd_pct:            float          # fraccion del balance inicial (0.05 = 5%)
    max_loss_pct:            float          # fraccion del balance inicial
    profit_target_pct:       float          # fraccion del balance inicial
    min_trading_days:        int
    swing_upgrade:           bool  = False  # True = daily DD estatico desde inicio del dia
    max_trade_loss_pct:      float = 0.03   # perdida realizada maxima por trade
    profit_distribution_pct: float = 0.40   # ningun dia > 40% del resultado neto total
    intrabar_buffer:         float = 0.0    # endurece daily/total (equity 1H subestima picos)
    max_days:                int   = 365    # timeout de simulacion (el real es ilimitado)
    near_breach_dist:        float = 0.01   # "cerca del breach" = distancia < 1% del balance

    def with_(self, **kw) -> "PropRulesConfig":
        from dataclasses import replace
        return replace(self, **kw)


ONE_STEP    = PropRulesConfig("one_step",    daily_dd_pct=0.04, max_loss_pct=0.06,
                              profit_target_pct=0.10, min_trading_days=5)
TWO_STEP_P1 = PropRulesConfig("two_step_p1", daily_dd_pct=0.05, max_loss_pct=0.10,
                              profit_target_pct=0.10, min_trading_days=10)
TWO_STEP_P2 = PropRulesConfig("two_step_p2", daily_dd_pct=0.05, max_loss_pct=0.10,
                              profit_target_pct=0.05, min_trading_days=5)

# Estados terminales de un challenge simulado
PASSED       = "passed"
BREACH_DAILY = "breach_daily"
BREACH_TOTAL = "breach_total"
TRADE_LOSS   = "trade_loss_violation"
TIMEOUT      = "timeout"        # max_days sin target ni breach
DATA_END     = "data_end"       # se acabo el historico antes de resolver (no cuenta en tasas)


# ---------------------------------------------------------------------------
# Resultado de un challenge individual
# ---------------------------------------------------------------------------

@dataclass
class ChallengeResult:
    status:            str
    start_ts:          datetime
    end_ts:            datetime | None = None
    days_elapsed:      int   = 0
    trading_days:      int   = 0
    final_return_pct:  float = 0.0      # resultado neto al terminar (fraccion del inicial)
    worst_daily_dd:    float = 0.0      # peor drawdown diario observado (fraccion, positivo)
    near_breach_days:  int   = 0        # dias con distancia al suelo diario < near_breach_dist
    dist_blocked_days: int   = 0        # dias con target cumplido pero distribucion violada
    worst_day:         float = 0.0      # peor resultado diario (fraccion, negativo o 0)
    best_day:          float = 0.0      # mejor resultado diario (fraccion)
    max_day_share:     float = 0.0      # mejor dia / resultado total al cierre (si total > 0)
    worst_trade:       float = 0.0      # peor perdida realizada por trade (fraccion, negativo o 0)


# ---------------------------------------------------------------------------
# Evaluacion de un challenge desde un punto de la curva
# ---------------------------------------------------------------------------

def _as_float_curve(equity: Sequence[tuple[datetime, Decimal]]) -> list[tuple[datetime, float]]:
    return [(ts, float(v)) for ts, v in equity]


def evaluate_challenge(
    equity: Sequence[tuple[datetime, float]],
    start_idx: int,
    cfg: PropRulesConfig,
    trade_pnls: Sequence[tuple[datetime, float]] | None = None,
) -> ChallengeResult:
    """
    Simula UN challenge que arranca en equity[start_idx].

    equity: curva (ts UTC, valor) YA en float — usar _as_float_curve/simulate_challenges
    para curvas Decimal. La cuenta prop se normaliza a 1.0 en el arranque: todos los
    limites son fracciones del balance inicial del challenge.

    trade_pnls: PnL realizado por trade (ts, pnl en unidades de la curva). Se normaliza por
    el equity del arranque. Si es None, la regla por-trade no se evalua y los dias de trading
    se aproximan a "todo dia con datos" (valido para estrategias siempre-en-mercado).
    """
    if start_idx >= len(equity) - 1:
        return ChallengeResult(status=DATA_END, start_ts=equity[-1][0] if equity else datetime.min)

    base = equity[start_idx][1]
    if base <= 0:
        return ChallengeResult(status=DATA_END, start_ts=equity[start_idx][0])

    start_ts = equity[start_idx][0]
    daily_limit = cfg.daily_dd_pct * (1.0 - cfg.intrabar_buffer)
    total_floor = 1.0 - cfg.max_loss_pct * (1.0 - cfg.intrabar_buffer)
    target      = 1.0 + cfg.profit_target_pct

    # Trades normalizados dentro de la ventana, indexados por dia UTC.
    # trade_days queda intacto para contar dias de trading (trades_by_day se consume).
    trades_by_day: dict[date, list[float]] = {}
    if trade_pnls is not None:
        for ts, pnl in trade_pnls:
            if ts >= start_ts:
                trades_by_day.setdefault(ts.date(), []).append(pnl / base)
    trade_days: frozenset[date] = frozenset(trades_by_day)

    res = ChallengeResult(status=TIMEOUT, start_ts=start_ts)
    day_results: list[float] = []       # resultado de cada dia UTC cerrado (fraccion)
    cur_day: date | None = None
    day_start_rel = day_peak_rel = 1.0
    day_min_dist = float("inf")
    trading_days = 0
    worst_trade = 0.0

    def _close_day(rel_at_close: float) -> None:
        nonlocal trading_days
        day_results.append(rel_at_close - day_start_rel)
        if day_min_dist < cfg.near_breach_dist:
            res.near_breach_days += 1
        if trade_pnls is None or cur_day in trade_days:
            trading_days += 1

    def _finish(status: str, ts: datetime, rel: float) -> ChallengeResult:
        res.status = status
        res.end_ts = ts
        res.days_elapsed = (ts.date() - start_ts.date()).days + 1
        res.trading_days = trading_days
        res.final_return_pct = rel - 1.0
        if day_results:
            res.worst_day = min(day_results)
            res.best_day = max(day_results)
            total = rel - 1.0
            if total > 0:
                res.max_day_share = max(day_results) / total
        res.worst_trade = worst_trade
        return res

    prev_rel = 1.0
    for i in range(start_idx, len(equity)):
        ts, val = equity[i]
        rel = val / base
        d = ts.date()

        if d != cur_day:
            if cur_day is not None:
                _close_day(prev_rel)
                # -- Chequeos de fin de dia: target + dias minimos + distribucion --
                total = prev_rel - 1.0
                if prev_rel >= target and trading_days >= cfg.min_trading_days:
                    max_day = max(day_results) if day_results else 0.0
                    if total > 0 and max_day / total <= cfg.profit_distribution_pct:
                        return _finish(PASSED, ts, prev_rel)
                    res.dist_blocked_days += 1
                if (d - start_ts.date()).days > cfg.max_days:
                    return _finish(TIMEOUT, ts, prev_rel)
            cur_day = d
            day_start_rel = prev_rel if cur_day != start_ts.date() else 1.0
            day_peak_rel = day_start_rel
            day_min_dist = float("inf")

        day_peak_rel = max(day_peak_rel, rel)
        floor = (day_start_rel - daily_limit) if cfg.swing_upgrade \
            else (day_peak_rel - daily_limit)
        day_min_dist = min(day_min_dist, rel - floor)
        dd_today = (day_peak_rel - rel) if not cfg.swing_upgrade else (day_start_rel - rel)
        res.worst_daily_dd = max(res.worst_daily_dd, dd_today)

        # -- Regla por trade (perdida realizada) --
        if cur_day in trades_by_day:
            for pnl in trades_by_day.pop(cur_day):
                worst_trade = min(worst_trade, pnl)
                if pnl <= -cfg.max_trade_loss_pct:
                    return _finish(TRADE_LOSS, ts, rel)

        if rel <= floor:
            return _finish(BREACH_DAILY, ts, rel)
        if rel <= total_floor:
            return _finish(BREACH_TOTAL, ts, rel)

        prev_rel = rel

    return _finish(DATA_END, equity[-1][0], prev_rel)


# ---------------------------------------------------------------------------
# Two-Step: encadena fase 1 -> fase 2 (cuenta nueva, equity rebasada)
# ---------------------------------------------------------------------------

def evaluate_two_step(
    equity: Sequence[tuple[datetime, float]],
    start_idx: int,
    p1: PropRulesConfig = TWO_STEP_P1,
    p2: PropRulesConfig = TWO_STEP_P2,
    trade_pnls: Sequence[tuple[datetime, float]] | None = None,
) -> ChallengeResult:
    """Simula fase 1 y, si pasa, fase 2 desde la barra siguiente. PASSED = ambas."""
    r1 = evaluate_challenge(equity, start_idx, p1, trade_pnls)
    if r1.status != PASSED:
        return r1
    # Fase 2 arranca en el primer indice posterior al fin de fase 1
    next_idx = next((i for i, (ts, _) in enumerate(equity) if ts >= r1.end_ts), None)
    if next_idx is None or next_idx >= len(equity) - 1:
        r1.status = DATA_END
        return r1
    r2 = evaluate_challenge(equity, next_idx, p2, trade_pnls)
    # El resultado agregado hereda el estado de la fase 2 y suma duraciones
    r2.start_ts = r1.start_ts
    r2.days_elapsed += r1.days_elapsed
    r2.trading_days += r1.trading_days
    r2.near_breach_days += r1.near_breach_days
    r2.dist_blocked_days += r1.dist_blocked_days
    r2.worst_daily_dd = max(r2.worst_daily_dd, r1.worst_daily_dd)
    r2.worst_day = min(r2.worst_day, r1.worst_day)
    r2.worst_trade = min(r2.worst_trade, r1.worst_trade)
    return r2


# ---------------------------------------------------------------------------
# Simulacion agregada: ventanas rodantes sobre toda la curva
# ---------------------------------------------------------------------------

@dataclass
class ChallengeStats:
    label:            str
    windows:          int = 0                  # ventanas RESUELTAS (excluye data_end)
    by_status:        dict = field(default_factory=dict)
    pass_rate:        float = 0.0
    breach_rate:      float = 0.0              # daily + total + trade_loss
    timeout_rate:     float = 0.0
    median_days_pass: float = 0.0
    near_breach_day_pct: float = 0.0           # % de dias-ventana cerca del breach
    worst_daily_dd:   float = 0.0
    results:          list[ChallengeResult] = field(default_factory=list)

    def row(self) -> str:
        return (f"{self.label},{self.windows},{self.pass_rate:.3f},{self.breach_rate:.3f},"
                f"{self.timeout_rate:.3f},{self.median_days_pass:.0f},"
                f"{self.near_breach_day_pct:.3f},{self.worst_daily_dd:.4f}")


def simulate_challenges(
    equity_curve: Sequence[tuple[datetime, Decimal]],
    cfg: PropRulesConfig,
    start_every_days: int = 7,
    trade_pnls: Sequence[tuple[datetime, Decimal]] | None = None,
    two_step: bool = False,
) -> ChallengeStats:
    """
    Lanza un challenge cada `start_every_days` a lo largo de la curva y agrega resultados.
    two_step=True usa evaluate_two_step con cfg como fase 1 y TWO_STEP_P2 como fase 2.
    """
    equity = _as_float_curve(equity_curve)
    tp = [(ts, float(p)) for ts, p in trade_pnls] if trade_pnls is not None else None

    stats = ChallengeStats(label=cfg.label + ("+p2" if two_step else ""))
    if not equity:
        return stats
    # La fase 2 hereda upgrade y buffer de la fase 1
    p2 = TWO_STEP_P2.with_(swing_upgrade=cfg.swing_upgrade,
                           intrabar_buffer=cfg.intrabar_buffer)

    next_start: datetime | None = None
    total_days = 0
    near_days = 0
    for i, (ts, _) in enumerate(equity):
        if next_start is not None and ts < next_start:
            continue
        next_start = ts + timedelta(days=start_every_days)
        r = (evaluate_two_step(equity, i, cfg, p2, tp) if two_step
             else evaluate_challenge(equity, i, cfg, tp))
        if r.status == DATA_END:
            continue
        stats.results.append(r)
        stats.by_status[r.status] = stats.by_status.get(r.status, 0) + 1
        total_days += r.days_elapsed
        near_days += r.near_breach_days
        stats.worst_daily_dd = max(stats.worst_daily_dd, r.worst_daily_dd)

    stats.windows = len(stats.results)
    if stats.windows == 0:
        return stats
    n = stats.windows
    stats.pass_rate = stats.by_status.get(PASSED, 0) / n
    stats.breach_rate = (stats.by_status.get(BREACH_DAILY, 0)
                         + stats.by_status.get(BREACH_TOTAL, 0)
                         + stats.by_status.get(TRADE_LOSS, 0)) / n
    stats.timeout_rate = stats.by_status.get(TIMEOUT, 0) / n
    days_pass = [r.days_elapsed for r in stats.results if r.status == PASSED]
    stats.median_days_pass = float(median(days_pass)) if days_pass else 0.0
    stats.near_breach_day_pct = (near_days / total_days) if total_days else 0.0
    return stats


def trade_pnls_from_result(result) -> list[tuple[datetime, Decimal]]:
    """Extrae (ts, pnl) de un BacktestResult (trades con pnl realizado no-None)."""
    return [(t.timestamp, t.pnl) for t in result.trades if t.pnl is not None]

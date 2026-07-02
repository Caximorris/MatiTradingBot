"""
OKX Trading Bot — CLI principal.

Uso:
    python main.py start                         # Arranca todos los bots activos
    python main.py stop                          # Parada de emergencia
    python main.py status                        # Estado actual del sistema
    python main.py dashboard                     # Dashboard en vivo
    python main.py trades                        # Historial de trades
    python main.py report --year 2025            # Informe fiscal IRPF
    python main.py mode                          # Muestra el modo actual
    python main.py bot list                      # Lista de bots configurados
    python main.py bot enable NAME SYMBOL        # Activa un bot
    python main.py bot disable NAME SYMBOL       # Desactiva un bot
    python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31
    python main.py compare --strategies adaptive,pro --from 2018 --to 2024
    python main.py random-backtest --strategy pro --windows 10 --months 24
"""
from __future__ import annotations

import json
import random as _random
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import print as rprint

app = typer.Typer(
    name="okx-trader",
    help="Bot de trading automatizado para OKX.",
    add_completion=False,
    no_args_is_help=True,
)
bot_app = typer.Typer(help="Gestión de bots individuales.", no_args_is_help=True)
app.add_typer(bot_app, name="bot")

console = Console()

# ---------------------------------------------------------------------------
# Benchmarks de referencia (fuente: datos reales de mercado)
# ---------------------------------------------------------------------------

_BENCHMARKS: dict[str, dict[int, float]] = {
    "S&P 500": {2018: -4.38, 2019: 31.49, 2020: 18.40, 2021: 28.71,
                2022: -18.11, 2023: 26.29, 2024: 23.31},
    "NASDAQ":  {2018: -3.88, 2019: 35.23, 2020: 43.64, 2021: 21.39,
                2022: -32.97, 2023: 43.43, 2024: 28.64},
}

_STRAT_LABELS = {
    "adaptive": "Adaptive Trend",
    "adaptive_trend": "Adaptive Trend",
    "pro": "Pro Trend",
    "pro_trend": "Pro Trend",
    "trend": "Adaptive Trend",
    "scalp": "Scalp Momentum",
    "scalp_momentum": "Scalp Momentum",
    "range": "Range Reversion",
    "range_reversion": "Range Reversion",
    "swing": "Swing Allocator",
    "swing_allocator": "Swing Allocator",
}

# Fecha más antigua disponible en OKX para BTC-USDT
_OKX_EARLIEST = datetime(2018, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers de formato (módulo-nivel para reutilización)
# ---------------------------------------------------------------------------

def _pct(v: float) -> str:
    color = "green" if v > 0 else ("red" if v < 0 else "dim")
    return f"[{color}]{v:+.1f}%[/{color}]"


def _usd(v: float, base: float) -> str:
    color = "green" if v >= base else "red"
    return f"[{color}]${v:,.0f}[/{color}]"


# ---------------------------------------------------------------------------
# Helpers de análisis de curva de equity
# ---------------------------------------------------------------------------

def _annual_returns_from_curve(
    equity_curve: list[tuple[datetime, Decimal]],
    years: list[int],
    initial_balance: Decimal,
) -> dict[int, dict]:
    """Extrae rentabilidad anual de un backtest continuo sin reiniciar por año."""
    result: dict[int, dict] = {}
    for year in years:
        y_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        y_end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        before   = [(dt, v) for dt, v in equity_curve if dt < y_start]
        in_year  = [(dt, v) for dt, v in equity_curve if y_start <= dt <= y_end]

        if not in_year:
            result[year] = {"pnl_pct": 0.0, "end_val": float(initial_balance)}
            continue

        start_val = before[-1][1] if before else initial_balance
        end_val   = in_year[-1][1]
        pnl_pct   = float((end_val - start_val) / start_val * 100) if start_val > 0 else 0.0
        result[year] = {"pnl_pct": pnl_pct, "end_val": float(end_val), "start_val": float(start_val)}

    return result


def _btc_year_returns(bars: list, years: list[int]) -> dict[int, float]:
    """Calcula rentabilidad anual de BTC B&H a partir de las barras descargadas."""
    result: dict[int, float] = {}
    for year in years:
        y_start_ts = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        y_end_ts   = int(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

        start_bars = [b for b in bars if b.timestamp >= y_start_ts]
        end_bars   = [b for b in bars if b.timestamp <= y_end_ts]

        if start_bars and end_bars:
            sp = float(start_bars[0].close)
            ep = float(end_bars[-1].close)
            result[year] = (ep - sp) / sp * 100 if sp > 0 else 0.0

    return result


def _quarterly_breakdown(result) -> list[tuple[str, int, int, Decimal]]:
    """Agrupa trades cerrados por trimestre: (label, n_trades, n_wins, pnl)."""
    quarters: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": Decimal("0")})
    for trade in result.trades:
        q = (trade.timestamp.month - 1) // 3 + 1
        key = f"{trade.timestamp.year}-Q{q}"
        quarters[key]["trades"] += 1
        if trade.pnl and trade.pnl > 0:
            quarters[key]["wins"] += 1
        if trade.pnl:
            quarters[key]["pnl"] += trade.pnl

    rows = []
    for key in sorted(quarters.keys()):
        d = quarters[key]
        rows.append((key, d["trades"], d["wins"], d["pnl"]))
    return rows


def _print_quarterly_table(result, title: str) -> None:
    """Imprime tabla trimestral de trades cerrados de un BacktestResult."""
    quarters = _quarterly_breakdown(result)
    if not quarters:
        return

    tq = Table(title=title, header_style="bold blue", show_lines=False)
    tq.add_column("Trimestre")
    tq.add_column("Trades", justify="right")
    tq.add_column("Win %", justify="right")
    tq.add_column("P&L USDT", justify="right")
    tq.add_column("P&L Acum.", justify="right")

    acc = Decimal("0")
    for key, n_trades, n_wins, pnl in quarters:
        acc += pnl
        win_s = f"{n_wins / n_trades * 100:.0f}%" if n_trades > 0 else "—"
        cp  = "green" if pnl >= 0 else "red"
        ca  = "green" if acc  >= 0 else "red"
        year, q = key.split("-")
        tq.add_row(
            f"{q} {year}", str(n_trades), win_s,
            f"[{cp}]{float(pnl):+.2f}[/{cp}]",
            f"[{ca}]{float(acc):+.2f}[/{ca}]",
        )
    console.print(tq)


# ---------------------------------------------------------------------------
# Carga perezosa de settings
# ---------------------------------------------------------------------------

def _load_settings():
    try:
        from config.settings import settings
        return settings
    except EnvironmentError as exc:
        console.print(f"[red]Error de configuración:[/red] {exc}")
        console.print("[yellow]Copia .env.example a .env y rellena los valores.[/yellow]")
        raise typer.Exit(1)


def _make_client(settings):
    from core.exchange import OKXClient
    # persist_paper_state=True: el portfolio paper sobrevive a reinicios del proceso
    # (data/runtime/paper_state.json). Los tests crean OKXClient sin persistencia.
    return OKXClient(settings, persist_paper_state=True)


# ---------------------------------------------------------------------------
# Fábrica de estrategias desde BotState
# ---------------------------------------------------------------------------

def _instantiate_strategy(bot_state, client, risk_manager, session):
    name   = bot_state.strategy_name
    config = bot_state.get_config()
    try:
        if name.startswith("adaptive_"):
            from strategies.adaptive_trend import AdaptiveTrendBot, AdaptiveTrendConfig
            return AdaptiveTrendBot(client=client,
                                    config=AdaptiveTrendConfig.from_dict(config),
                                    session=session, risk_manager=risk_manager)
        elif name.startswith("pro_trend"):
            from strategies.pro_trend import ProTrendBot, ProTrendConfig
            return ProTrendBot(client=client,
                               config=ProTrendConfig.from_dict(config),
                               session=session, risk_manager=risk_manager)
        elif name.startswith("scalp_momentum"):
            from strategies.scalp_momentum import ScalpMomentumBot, ScalpMomentumConfig
            return ScalpMomentumBot(client=client,
                                    config=ScalpMomentumConfig.from_dict(config),
                                    session=session, risk_manager=risk_manager)
        elif name.startswith("swing_allocator") or name.startswith("swing"):
            from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig
            cfg = {"symbol": bot_state.symbol}
            cfg.update(config)
            if bot_state.symbol.split("-")[0].upper() != "BTC":
                cfg.setdefault("pi_cycle_enabled", False)
            return SwingAllocatorBot(client=client,
                                     config=SwingAllocatorConfig.from_dict(cfg),
                                     session=session, risk_manager=risk_manager)
        else:
            logger.warning("Tipo de estrategia desconocido: {}", name)
            return None
    except Exception as exc:
        logger.error("Error al instanciar {}: {}", name, exc)
        return None


# ---------------------------------------------------------------------------
# Backtest runner (reutilizado por backtest, compare y random-backtest)
# ---------------------------------------------------------------------------

def _run_backtest(
    symbol: str, timeframe: str, strat_type: str,
    balance: float, config: dict,
    from_dt: datetime, to_dt: datetime,
    prefetched_bars=None,
    show_progress: bool = True,
    cost_mode: str = "ideal",
    journal_out: list | None = None,
):
    """
    Descarga (o reutiliza) barras y ejecuta el BacktestEngine con barra de progreso.

    prefetched_bars: lista de OHLCVBar ya descargada que incluye el warmup.
                     Si se pasa, no se hace ninguna petición a OKX.
    show_progress:   muestra barras Rich de descarga y simulación.
    """
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn
    from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
    from strategies.macro_context  import load_macro_context
    from strategies.market_context import load_market_context
    from strategies.funding_context import load_funding_history

    # Carga unica de datos macro, mercado y funding antes de la simulacion
    load_macro_context(from_dt, to_dt, symbol)
    load_market_context(from_dt, to_dt)
    load_funding_history(symbol, from_dt, to_dt)

    if strat_type in ("pro", "pro_trend"):
        WARMUP_DAYS = 625   # EMA350D necesita ~350 dias + buffer
    elif strat_type in ("scalp", "scalp_momentum"):
        WARMUP_DAYS = 25   # necesita EMA20D diaria → 25 días de calentamiento
    elif strat_type in ("range", "range_reversion"):
        WARMUP_DAYS = 240  # EMA200D diaria
    elif strat_type in ("swing", "swing_allocator"):
        WARMUP_DAYS = 250  # EMA200D diaria con buffer
    else:
        WARMUP_DAYS = 240
    warmup_start = from_dt - timedelta(days=WARMUP_DAYS)
    label = _STRAT_LABELS.get(strat_type, strat_type)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[progress.percentage]{task.percentage:>5.1f}%"),
        TextColumn("[dim]{task.fields[detail]}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:

        # ── Fase 1: descarga ──────────────────────────────────────────────
        if prefetched_bars is not None:
            all_bars = prefetched_bars
        else:
            dl_task = progress.add_task(
                f"Descargando {symbol}/{timeframe}", total=None, detail=""
            )
            def on_page(n_bars: int) -> None:
                progress.update(dl_task, detail=f"{n_bars:,} velas")

            all_bars = fetch_historical_bars(
                symbol=symbol, bar=timeframe,
                from_dt=warmup_start, to_dt=to_dt,
                on_page=on_page,
            )
            progress.update(dl_task, completed=1, total=1,
                            detail=f"{len(all_bars):,} velas")

        if not all_bars:
            return None

        # ── Fase 2: simulación ────────────────────────────────────────────
        from_ts       = int(from_dt.timestamp() * 1000)
        warmup_bars   = [b for b in all_bars if b.timestamp < from_ts]
        engine_warmup = max(len(warmup_bars), 20)
        total_ticks   = len(all_bars) - engine_warmup

        sim_task = progress.add_task(
            f"Simulando {label}", total=total_ticks, detail=""
        )

        def on_tick(done: int, total: int) -> None:
            pct = done / total if total else 0
            # Estima equity actual sin acceder al motor
            progress.update(sim_task, completed=done,
                            detail=f"{done:,}/{total:,} barras")

        bt_client = BacktestClient(symbol=symbol, bars=all_bars,
                                    initial_balance=Decimal(str(balance)),
                                    cost_mode=cost_mode)

        def factory(client, session):
            sym = symbol.upper()
            if strat_type in ("adaptive", "adaptive_trend", "trend"):
                from strategies.adaptive_trend import AdaptiveTrendBot, AdaptiveTrendConfig
                cfg = {"symbol": sym}; cfg.update(config)
                return AdaptiveTrendBot(client=client,
                                        config=AdaptiveTrendConfig.from_dict(cfg),
                                        session=session)
            elif strat_type in ("pro", "pro_trend"):
                from strategies.pro_trend import ProTrendBot, ProTrendConfig
                cfg = {"symbol": sym}; cfg.update(config)
                if sym.split("-")[0].upper() != "BTC":
                    cfg.setdefault("pi_cycle_enabled", False)
                return ProTrendBot(client=client,
                                   config=ProTrendConfig.from_dict(cfg),
                                   session=session)
            elif strat_type in ("scalp", "scalp_momentum"):
                from strategies.scalp_momentum import ScalpMomentumBot, ScalpMomentumConfig
                cfg = {"symbol": sym}; cfg.update(config)
                return ScalpMomentumBot(client=client,
                                        config=ScalpMomentumConfig.from_dict(cfg),
                                        session=session)
            elif strat_type in ("range", "range_reversion"):
                from strategies.range_reversion import RangeReversionBot, RangeReversionConfig
                cfg = {"symbol": sym}; cfg.update(config)
                return RangeReversionBot(client=client,
                                         config=RangeReversionConfig.from_dict(cfg),
                                         session=session)
            elif strat_type in ("swing", "swing_allocator"):
                from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig
                cfg = {"symbol": sym}; cfg.update(config)
                if sym.split("-")[0].upper() != "BTC":
                    cfg.setdefault("pi_cycle_enabled", False)
                return SwingAllocatorBot(client=client,
                                         config=SwingAllocatorConfig.from_dict(cfg),
                                         session=session)
            else:
                raise ValueError(f"Estrategia '{strat_type}' no soportada.")

        try:
            engine = BacktestEngine(bt_client=bt_client, strategy_factory=factory,
                                    warmup_bars=engine_warmup, timeframe=timeframe)
            result = engine.run(on_tick=on_tick)

            # Escribir journal de trades con todos los indicadores y contexto
            strat = engine.last_strategy
            cfg_obj = getattr(strat, "_cfg", None) if strat is not None else None
            if cfg_obj is not None and hasattr(cfg_obj, "to_dict"):
                resolved_config = cfg_obj.to_dict()
            else:
                resolved_config = getattr(strat, "_config", {}) if strat is not None else {}
                resolved_config = resolved_config or {}

            backtest_summary = {
                "initial_balance":      result.initial_balance,
                "final_balance":        result.final_balance,
                "total_pnl":            result.total_pnl,
                "total_return_pct":     result.total_pnl_pct,
                "buy_hold_return_pct":  result.buy_hold_pnl_pct,
                "cagr_pct":             result.cagr,
                "max_drawdown_pct":     result.max_drawdown_pct,
                "sharpe":               result.sharpe_ratio,
                "sortino":              result.sortino,
                "time_in_market_pct":   result.time_in_market_pct,
                "profit_factor":        result.profit_factor,
                "win_rate_pct":         result.win_rate,
                "total_trades":         result.total_trades,
                "winning_trades":       result.winning_trades,
                "losing_trades":        result.losing_trades,
                "max_consec_losses":    result.max_consec_losses,
                "expectancy":           result.expectancy,
                "avg_win":              result.avg_win,
                "avg_loss":             result.avg_loss,
                "bars_tested":          result.bars_tested,
                "warmup_bars":          engine_warmup,
                "cost_mode":            result.cost_mode,
                "start_date":           result.start_date,
                "end_date":             result.end_date,
            }

            if strat is not None and hasattr(strat, "_journal") and strat._journal:
                from reporting.trade_journal import write_journal
                journal_path = write_journal(
                    journal=strat._journal,
                    strategy_name=strat.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    from_date=from_dt.strftime("%Y-%m-%d"),
                    to_date=to_dt.strftime("%Y-%m-%d"),
                    cost_mode=cost_mode,
                    config_overrides=config if config else {},
                    resolved_config=resolved_config,
                    backtest_summary=backtest_summary,
                )
                if journal_out is not None:
                    journal_out.append(journal_path)
                else:
                    console.print(f"[dim]Journal guardado -> {journal_path}[/dim]")

            # Journal de rebalanceos para Swing Allocator
            if strat is not None and hasattr(strat, "_rebalance_log") and strat._rebalance_log:
                from reporting.swing_journal import write_swing_journal
                _base_ccy     = symbol.split("-")[0]
                _final_balance_raw = bt_client.get_balance()
                _final_btc    = float(_final_balance_raw.get(_base_ccy, 0))
                swing_path = write_swing_journal(
                    rebalance_log=strat._rebalance_log,
                    strategy_name=strat.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    from_date=from_dt.strftime("%Y-%m-%d"),
                    to_date=to_dt.strftime("%Y-%m-%d"),
                    cost_mode=cost_mode,
                    config_overrides=config if config else {},
                    initial_balance=float(bt_client.initial_balance),
                    final_balance=float(result.final_balance),
                    final_btc_qty=_final_btc,
                    resolved_config=resolved_config,
                    backtest_summary=backtest_summary,
                )
                # BTC vs B&H — metrica fundacional del Swing (SWING_PLAN): <1.0 = tienes menos BTC que B&H
                _init_ev = next((r for r in strat._rebalance_log if r["direction"] == "INIT"), None)
                _init_px = _init_ev["price"] if _init_ev else 0.0
                _bnh_btc = (float(bt_client.initial_balance) / _init_px) if _init_px > 0 else 0.0
                _ratio   = (_final_btc / _bnh_btc) if _bnh_btc > 0 else 0.0
                if journal_out is not None:
                    journal_out.append(swing_path)
                else:
                    console.print(f"[dim]Swing journal -> {swing_path}[/dim]")
                    _rc = "green" if _ratio >= 1.0 else "red"
                    console.print(
                        f"[bold]BTC vs B&H:[/bold] [{_rc}]{_ratio:.4f}[/{_rc}]  "
                        f"(final {_final_btc:.4f} BTC vs B&H {_bnh_btc:.4f})"
                    )

            return result
        except Exception as exc:
            logger.debug("Error en backtest {}: {}", strat_type, exc)
            return None


# ---------------------------------------------------------------------------
# Comando: START
# ---------------------------------------------------------------------------

@app.command()
def start(
    tick: int = typer.Option(30, "--tick", "-t", help="Segundos entre ticks de cada bot."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Arranca todos los bots marcados como activos en la DB."""
    _setup_logging(verbose)
    settings = _load_settings()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        console.print("[red]apscheduler no instalado. Ejecuta: pip install apscheduler[/red]")
        raise typer.Exit(1)

    from core.database import BotState, get_session, init_db
    from core.risk_manager import RiskManager

    init_db()
    client       = _make_client(settings)
    risk_manager = RiskManager(client=client, app_settings=settings)

    with get_session() as s:
        active_bots = s.query(BotState).filter(BotState.is_active == True).all()
        bot_configs = [(b.strategy_name, b.symbol, b.get_config()) for b in active_bots]

    if not bot_configs:
        console.print("[yellow]No hay bots activos. Usa 'okx-trader bot enable' para activar uno.[/yellow]")
        raise typer.Exit(0)

    mode_label = "PAPER" if settings.is_paper else "[bold red]LIVE[/bold red]"
    console.print(f"[bold cyan]Iniciando {len(bot_configs)} bot(s) en modo {mode_label}[/bold cyan]")

    scheduler = BackgroundScheduler(timezone="UTC")
    _running   = True

    def _make_job(strategy_name, symbol, config):
        def job():
            try:
                with get_session() as session:
                    state = (session.query(BotState)
                             .filter_by(strategy_name=strategy_name, symbol=symbol)
                             .first())
                    if not state or not state.is_active:
                        return
                    strategy = _instantiate_strategy(state, client, risk_manager, session)
                    if strategy:
                        strategy.run()
                        state.last_run = datetime.now(timezone.utc)
            except Exception as exc:
                logger.error("[{}] Error en tick: {}", strategy_name, exc)
        return job

    for name, symbol, config in bot_configs:
        scheduler.add_job(_make_job(name, symbol, config), "interval",
                          seconds=tick, id=name, max_instances=1)
        console.print(f"  [green][OK][/green] {name} ({symbol}) — tick cada {tick}s")

    scheduler.start()
    console.print("[bold green]Bots en marcha. Pulsa Ctrl+C para detener.[/bold green]")

    def _shutdown(signum, frame):
        nonlocal _running
        _running = False
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while _running:
        time.sleep(1)


# ---------------------------------------------------------------------------
# Comando: STOP
# ---------------------------------------------------------------------------

@app.command()
def stop(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Parada de emergencia: cancela órdenes y desactiva todos los bots."""
    _setup_logging(verbose)
    settings = _load_settings()
    client   = _make_client(settings)
    from core.risk_manager import RiskManager
    from core.database import init_db
    init_db()
    RiskManager(client=client, app_settings=settings).emergency_stop()
    console.print("[bold red]EMERGENCY STOP ejecutado.[/bold red] Todos los bots desactivados.")


# ---------------------------------------------------------------------------
# Comando: STATUS
# ---------------------------------------------------------------------------

@app.command()
def status(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Muestra el estado actual: bots, balance y posiciones abiertas."""
    _setup_logging(verbose)
    settings = _load_settings()
    client   = _make_client(settings)

    from core.database import BotState, Position, Trade, get_session, init_db
    from sqlalchemy import func

    init_db()
    mode = "PAPER" if settings.is_paper else "LIVE"
    console.rule(f"[bold cyan]OKX Trading Bot — modo {mode}[/bold cyan]")

    try:
        balance = client.get_balance()
        console.print("\n[bold]Balance[/bold]")
        for token, amount in balance.items():
            if amount > Decimal("0"):
                console.print(f"  {token}: [green]{amount:,.6f}[/green]")
    except Exception as exc:
        console.print(f"  [red]Exchange no disponible: {exc}[/red]")

    console.print("\n[bold]Bots configurados[/bold]")
    with get_session() as s:
        bots = s.query(BotState).order_by(BotState.created_at).all()
        bot_rows = [(b.strategy_name, b.symbol, b.is_active, b.last_run, float(b.total_pnl))
                    for b in bots]

    if not bot_rows:
        console.print("  [dim]Sin bots configurados.[/dim]")
    else:
        t = Table(show_header=True, header_style="bold blue")
        t.add_column("Nombre"); t.add_column("Par"); t.add_column("Estado")
        t.add_column("Último tick"); t.add_column("P&L total", justify="right")
        for name, symbol, active, last_run, pnl in bot_rows:
            sl = "[green]ACTIVO[/green]" if active else "[red]PARADO[/red]"
            last = last_run.strftime("%d/%m %H:%M") if last_run else "—"
            pc = "green" if pnl >= 0 else "red"
            t.add_row(name, symbol, sl, last, f"[{pc}]{pnl:+.2f}[/{pc}]")
        console.print(t)

    console.print("\n[bold]Posiciones abiertas[/bold]")
    with get_session() as s:
        positions = s.query(Position).all()
        pos_rows  = [(p.symbol, p.strategy, p.side, float(p.entry_price),
                      float(p.current_price), float(p.unrealized_pnl)) for p in positions]

    if not pos_rows:
        console.print("  [dim]Sin posiciones abiertas.[/dim]")
    else:
        pt = Table(show_header=True, header_style="bold blue")
        pt.add_column("Par"); pt.add_column("Estrategia")
        pt.add_column("Lado"); pt.add_column("Entrada", justify="right")
        pt.add_column("Actual", justify="right"); pt.add_column("PnL no realizado", justify="right")
        for sym, strat, side, entry, current, upnl in pos_rows:
            c = "green" if upnl >= 0 else "red"
            pt.add_row(sym, strat, side, f"{entry:,.2f}", f"{current:,.2f}",
                       f"[{c}]{upnl:+.2f}[/{c}]")
        console.print(pt)

    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), datetime.min.time()
    ).replace(tzinfo=timezone.utc)
    with get_session() as s:
        res = (s.query(func.sum(Trade.pnl), func.count(Trade.id))
                 .filter(Trade.timestamp >= today_start).one())
    daily_pnl    = float(res[0] or 0)
    daily_trades = res[1] or 0
    c = "green" if daily_pnl >= 0 else "red"
    console.print(f"\n[bold]Hoy:[/bold] {daily_trades} trades | P&L: [{c}]{daily_pnl:+.2f} USDT[/{c}]")


# ---------------------------------------------------------------------------
# Comando: DASHBOARD
# ---------------------------------------------------------------------------

@app.command()
def dashboard(
    refresh: int = typer.Option(30, "--refresh", "-r"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Lanza el dashboard interactivo en tiempo real (Ctrl+C para salir)."""
    _setup_logging(verbose)
    settings = _load_settings()
    client   = _make_client(settings)
    from core.database import init_db
    from reporting.dashboard import run_dashboard
    init_db()
    run_dashboard(client=client, mode=settings.trading_mode, refresh_seconds=refresh)


# ---------------------------------------------------------------------------
# Comando: TRADES
# ---------------------------------------------------------------------------

@app.command()
def trades(
    limit: int = typer.Option(20, "--limit", "-n"),
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s"),
    paper: Optional[bool] = typer.Option(None, "--paper/--live"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Muestra el historial de trades recientes."""
    _setup_logging(verbose)
    _load_settings()
    from core.database import Trade, get_session, init_db
    init_db()

    with get_session() as s:
        q = s.query(Trade).order_by(Trade.timestamp.desc())
        if symbol:
            q = q.filter(Trade.symbol == symbol.upper())
        if paper is not None:
            q = q.filter(Trade.is_paper == paper)
        rows = [(t.timestamp, t.symbol, t.side, float(t.quantity),
                 float(t.price), t.pnl, t.strategy, t.is_paper)
                for t in q.limit(limit).all()]

    if not rows:
        console.print("[dim]Sin trades que mostrar.[/dim]")
        return

    t = Table(title=f"Últimos {limit} trades", header_style="bold blue", show_lines=False)
    t.add_column("Fecha/Hora"); t.add_column("Par", style="cyan")
    t.add_column("Lado", justify="center"); t.add_column("Cantidad", justify="right")
    t.add_column("Precio", justify="right"); t.add_column("P&L", justify="right")
    t.add_column("Estrategia", style="dim"); t.add_column("", style="dim")

    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
    for ts, sym, side, qty, price, pnl, strat, is_paper in rows:
        side_lbl = "[green]BUY[/green]" if side == "buy" else "[red]SELL[/red]"
        pnl_str  = "—"
        if pnl is not None:
            c = "green" if float(pnl) >= 0 else "red"
            pnl_str = f"[{c}]{float(pnl):+.2f}[/{c}]"
        t.add_row(ts.astimezone(MADRID).strftime("%d/%m/%Y %H:%M"),
                  sym, side_lbl, f"{qty:.6f}", f"{price:,.2f}", pnl_str,
                  strat, "[dim]P[/dim]" if is_paper else "[bold]L[/bold]")
    console.print(t)


# ---------------------------------------------------------------------------
# Comando: REPORT
# ---------------------------------------------------------------------------

@app.command()
def report(
    year: int = typer.Option(2025, "--year", "-y"),
    rate: float = typer.Option(0.92, "--rate", "-r"),
    losses: float = typer.Option(0.0, "--losses", "-l"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Genera el informe fiscal IRPF para el año indicado (Excel + JSON)."""
    _setup_logging(verbose)
    _load_settings()
    from core.database import get_session, init_db
    from reporting.fiscal_report import FiscalReportGenerator
    init_db()
    console.print(f"[bold]Generando informe fiscal {year}[/bold] (tasa {rate} USDT/€)...")
    with get_session() as s:
        gen = FiscalReportGenerator(
            session=s,
            usd_eur_rate=Decimal(str(rate)),
            carryover_losses_eur=Decimal(str(losses)),
        )
        excel_path = gen.generate_annual_report(year)
    if excel_path:
        console.print(f"[green][OK][/green] Excel: [bold]{excel_path}[/bold]")
        json_path = excel_path.replace(".xlsx", ".json")
        if Path(json_path).exists():
            console.print(f"[green][OK][/green] JSON:  [bold]{json_path}[/bold]")
    else:
        console.print("[yellow]Informe JSON generado. openpyxl no disponible para Excel.[/yellow]")


# ---------------------------------------------------------------------------
# Comando: MODE
# ---------------------------------------------------------------------------

@app.command()
def mode():
    """Muestra el modo de trading actual (paper/live)."""
    settings = _load_settings()
    if settings.is_paper:
        console.print("[bold yellow]Modo actual: PAPER[/bold yellow]")
        console.print("[dim]Para cambiar a live: TRADING_MODE=live en el .env[/dim]")
    else:
        console.print("[bold red]Modo actual: LIVE[/bold red]")
        console.print(f"[dim]Pares: {', '.join(settings.trading_pairs)}[/dim]")


# ---------------------------------------------------------------------------
# Sub-comandos: BOT
# ---------------------------------------------------------------------------

@bot_app.command("list")
def bot_list():
    """Lista todos los bots configurados en la DB."""
    from core.database import BotState, get_session, init_db
    init_db()
    with get_session() as s:
        rows = [(b.strategy_name, b.symbol, b.is_active, b.created_at)
                for b in s.query(BotState).order_by(BotState.strategy_name).all()]
    if not rows:
        console.print("[dim]Sin bots configurados.[/dim]")
        return
    t = Table(header_style="bold blue")
    t.add_column("Nombre"); t.add_column("Par"); t.add_column("Estado"); t.add_column("Creado")
    for name, symbol, active, created in rows:
        t.add_row(name, symbol,
                  "[green]ACTIVO[/green]" if active else "[dim]PARADO[/dim]",
                  created.strftime("%d/%m/%Y"))
    console.print(t)


@bot_app.command("enable")
def bot_enable(
    name:   str = typer.Argument(...),
    symbol: str = typer.Argument(...),
):
    """Activa un bot (lo crea si no existe)."""
    from core.database import get_session, set_bot_active, init_db
    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=True)
    console.print(f"[green][OK][/green] Bot [bold]{state.strategy_name}[/bold] activado.")


@bot_app.command("disable")
def bot_disable(
    name:   str = typer.Argument(...),
    symbol: str = typer.Argument(...),
):
    """Desactiva un bot."""
    from core.database import get_session, set_bot_active, init_db
    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=False)
    console.print(f"[yellow]○[/yellow] Bot [bold]{state.strategy_name}[/bold] desactivado.")


@bot_app.command("add")
def bot_add(
    strategy_type: str = typer.Argument(..., help="Tipo: adaptive | pro_trend | scalp | range | swing"),
    symbol: str = typer.Argument(...),
    config_json: str = typer.Option("{}", "--config", "-c"),
):
    """Registra un nuevo bot con su configuración."""
    from core.database import get_session, get_or_create_bot_state, init_db
    init_db()

    valid_types = ("adaptive", "pro_trend", "pro", "scalp_momentum", "scalp",
                   "range_reversion", "range", "swing_allocator", "swing")
    t = strategy_type.lower()
    if not any(t.startswith(v) for v in valid_types):
        console.print(f"[red]Tipo inválido '{strategy_type}'. Válidos: adaptive, pro_trend, scalp, range, swing[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido: {exc}[/red]")
        raise typer.Exit(1)

    sym_clean = symbol.upper().replace("-", "_").lower()
    name_map  = {
        "adaptive":        f"adaptive_trend_{sym_clean}",
        "pro_trend":       f"pro_trend_{sym_clean}",
        "pro":             f"pro_trend_{sym_clean}",
        "scalp_momentum":  f"scalp_momentum_{sym_clean}",
        "scalp":           f"scalp_momentum_{sym_clean}",
        "range_reversion": f"range_reversion_{sym_clean}",
        "range":           f"range_reversion_{sym_clean}",
        "swing_allocator": f"swing_allocator_{sym_clean}",
        "swing":           f"swing_allocator_{sym_clean}",
    }
    name = next(name_map[v] for v in valid_types if t.startswith(v))

    with get_session() as s:
        state = get_or_create_bot_state(s, name, symbol.upper(), config=config)
        state.set_config(config)

    console.print(
        f"[green][OK][/green] Bot [bold]{name}[/bold] registrado.\n"
        f"  Actívalo con: [bold]python main.py bot enable {name} {symbol.upper()}[/bold]"
    )


# ---------------------------------------------------------------------------
# Comando: BACKTEST  (backtest continuo de un solo período)
# ---------------------------------------------------------------------------

@app.command()
def backtest(
    strategy: str  = typer.Option("adaptive", "--strategy", "-s"),
    symbol: str    = typer.Option("BTC-USDT", "--symbol"),
    from_date: str = typer.Option("2024-01-01", "--from", "-f"),
    to_date: str   = typer.Option("2024-12-31", "--to", "-t"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    balance: float = typer.Option(10000.0, "--balance", "-b"),
    config_json: str = typer.Option("{}", "--config", "-c"),
    costs: str     = typer.Option("ideal", "--costs",
                                  help="Modelo de costes: ideal | realistic | conservative"),
    verbose: bool  = typer.Option(False, "--verbose", "-v"),
):
    """
    Backtest continuo de una estrategia.  Las posiciones se abren y cierran
    únicamente por señales — sin reiniciar por año ni por fecha.

    Ejemplo:
      python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31
    """
    _setup_logging(verbose)

    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        console.print("[red]Formato de fecha inválido. Usa YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido en --config: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Backtest:[/bold cyan] {strategy.upper()} / {symbol} / {timeframe}")
    console.print(f"Descargando {from_dt.date()} -> {to_dt.date()} (+ warmup)")

    result = _run_backtest(symbol, timeframe, strategy.lower(), balance, config, from_dt, to_dt,
                           cost_mode=costs)
    if result is None:
        console.print("[red]No se pudieron descargar datos o ejecutar el backtest.[/red]")
        raise typer.Exit(1)

    # Tabla resumen
    t = Table(title=f"Resultados — {result.strategy_name} / {symbol}",
              header_style="bold blue", show_lines=False)
    t.add_column("Métrica", style="dim"); t.add_column("Valor", justify="right")
    for label, value in result.summary_rows():
        t.add_row(label, value)
    console.print(t)

    is_swing_allocator = result.strategy_name.startswith("swing_allocator")
    if result.total_trades == 0:
        console.print("[yellow](!)  Sin trades generados.[/yellow]")
    elif is_swing_allocator:
        console.print(
            "[yellow](!)  En Swing, PF/WR son metricas contables de rebalanceos; "
            "usa CAGR, Max DD, Calmar y BTC vs B&H como anclas.[/yellow]"
        )
    elif result.profit_factor > Decimal("1.5"):
        console.print("[green][OK] Profit Factor > 1.5 — estrategia prometedora.[/green]")
    elif result.profit_factor < Decimal("1.0"):
        console.print("[red][X] Profit Factor < 1.0 — estrategia pierde dinero en este período.[/red]")

    # Resumen trimestral (solo visualización)
    _print_quarterly_table(result, f"Resumen trimestral — {result.strategy_name}")


# ---------------------------------------------------------------------------
# Comando: WALK-FORWARD  (validación out-of-sample)
# ---------------------------------------------------------------------------

@app.command(name="walk-forward")
def walk_forward(
    strategy: str  = typer.Option("pro", "--strategy", "-s"),
    symbol: str    = typer.Option("BTC-USDT", "--symbol"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    balance: float = typer.Option(10000.0, "--balance", "-b"),
    config_json: str = typer.Option("{}", "--config", "-c"),
    costs: str     = typer.Option("realistic", "--costs"),
    verbose: bool  = typer.Option(False, "--verbose", "-v"),
):
    """
    Validacion walk-forward: entrena en un periodo y evalua en el siguiente.

    Ventanas fijas (no optimiza parametros — congela la config actual):
      Train 2018-2021 / Test 2022-2023
      Train 2018-2023 / Test 2024-2026
      Train 2018-2020 / Test 2021-2022
      Train 2020-2022 / Test 2023-2025

    El objetivo NO es maximizar rentabilidad sino ver si la logica
    sobrevive fuera de muestra sin retocar nada.

    Ejemplo:
      python main.py walk-forward --strategy pro --costs realistic
    """
    _setup_logging(verbose)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON invalido en --config: {exc}[/red]")
        raise typer.Exit(1)

    windows = [
        ("2018-01-01", "2021-12-31", "2022-01-01", "2023-12-31", "Train 18-21 / Test 22-23"),
        ("2018-01-01", "2023-12-31", "2024-01-01", "2026-01-01", "Train 18-23 / Test 24-26"),
        ("2018-01-01", "2020-12-31", "2021-01-01", "2022-12-31", "Train 18-20 / Test 21-22"),
        ("2020-01-01", "2022-12-31", "2023-01-01", "2025-01-01", "Train 20-22 / Test 23-25"),
    ]

    console.print(f"\n[bold cyan]Walk-Forward:[/bold cyan] {strategy.upper()} / {symbol} / costes={costs}")
    console.print("[dim]IMPORTANTE: no se optimizan parametros. La config es fija en todas las ventanas.[/dim]\n")

    rows_train = []
    rows_test  = []
    journals: list[str] = []

    for tr_from, tr_to, ts_from, ts_to, label in windows:
        def _parse(s):
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        console.print(f"[cyan]{label}[/cyan]")

        # Train
        r_train = _run_backtest(symbol, timeframe, strategy.lower(), balance, config,
                                _parse(tr_from), _parse(tr_to), cost_mode=costs,
                                journal_out=journals)
        # Test
        r_test  = _run_backtest(symbol, timeframe, strategy.lower(), balance, config,
                                _parse(ts_from), _parse(ts_to), cost_mode=costs,
                                journal_out=journals)

        def _fmt(r):
            if r is None:
                return ["ERROR"] * 6
            pnl_color = "green" if r.total_pnl_pct >= 0 else "red"
            return [
                f"[{pnl_color}]{r.total_pnl_pct:+.1f}%[/{pnl_color}]",
                f"{r.cagr:+.1f}%",
                f"{r.max_drawdown_pct:.1f}%",
                f"{r.sharpe_ratio:.2f}",
                f"{r.profit_factor:.2f}",
                str(r.total_trades),
            ]

        rows_train.append([label + " (TRAIN)"] + _fmt(r_train))
        rows_test.append( [label + " (TEST)"]  + _fmt(r_test))

    t = Table(title="Walk-Forward Results", header_style="bold blue", show_lines=True)
    t.add_column("Ventana",        style="dim", min_width=28)
    t.add_column("P&L",            justify="right")
    t.add_column("CAGR",           justify="right")
    t.add_column("Max DD",         justify="right")
    t.add_column("Sharpe",         justify="right")
    t.add_column("PF",             justify="right")
    t.add_column("Trades",         justify="right")

    for r_tr, r_ts in zip(rows_train, rows_test):
        t.add_row(*r_tr, style="dim")
        t.add_row(*r_ts)

    console.print(t)
    console.print("\n[bold]Criterio de robustez:[/bold]")
    console.print("  - Si los periodos TEST tienen CAGR > 0 y PF > 1.0: logica causal, no solo memorizada.")
    console.print("  - Si TEST empeora drasticamente vs TRAIN: probable overfitting.")
    console.print("  - Con solo 11 trades historicos, 1-2 trades en TEST limitan la significancia estadistica.")
    if journals:
        console.print("\n[dim]Journals guardados:[/dim]")
        for p in journals:
            console.print(f"[dim]  -> {p}[/dim]")


# ---------------------------------------------------------------------------
# Comando: BASELINES  (comparativa contra estrategias simples)
# ---------------------------------------------------------------------------

@app.command()
def baselines(
    symbol: str    = typer.Option("BTC-USDT", "--symbol"),
    from_date: str = typer.Option("2018-01-01", "--from", "-f"),
    to_date: str   = typer.Option("2026-01-01", "--to", "-t"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    balance: float = typer.Option(10000.0, "--balance", "-b"),
    costs: str     = typer.Option("realistic", "--costs"),
    verbose: bool  = typer.Option(False, "--verbose", "-v"),
):
    """
    Compara la estrategia Pro Trend contra baselines simples.

    Baselines implementados:
      1. Buy & Hold BTC
      2. EMA crossover semanal (EMA20W > EMA50W) con trailing 20%
      3. Precio > EMA200D con trailing 20%
      4. Pro Trend sin datos externos (solo scoring tecnico)
      5. Pro Trend sin scoring, solo gates estructurales (score_min=1)

    El objetivo: saber si la complejidad aporta valor real o si una regla
    sencilla consigue resultados similares con menos riesgo de overfitting.

    Ejemplo:
      python main.py baselines --from 2018-01-01 --to 2026-01-01 --costs realistic
    """
    _setup_logging(verbose)

    from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
    from strategies.macro_context  import load_macro_context
    from strategies.market_context import load_market_context
    from strategies.funding_context import load_funding_history

    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        console.print("[red]Formato de fecha invalido. Usa YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]Baselines:[/bold cyan] {symbol} / {from_dt.date()} -> {to_dt.date()} / costes={costs}\n")

    results = []
    journals: list[str] = []

    # ── 1. Pro Trend completo (referencia)
    load_macro_context(from_dt, to_dt, symbol)
    load_market_context(from_dt, to_dt)
    load_funding_history(symbol, from_dt, to_dt)
    r_pro = _run_backtest(symbol, timeframe, "pro", balance, {}, from_dt, to_dt,
                          cost_mode=costs, journal_out=journals)
    results.append(("Pro Trend v12 (completo)", r_pro))

    # ── 2. Pro Trend sin datos externos (MVRV, VIX, DXY, NASDAQ, funding, Pi Cycle Top)
    # Mide cuánto aportan los filtros externos vs la lógica técnica pura.
    r_no_ext = _run_backtest(symbol, timeframe, "pro", balance,
                             {"disable_external_filters": True},
                             from_dt, to_dt, cost_mode=costs, journal_out=journals)
    results.append(("Pro Trend sin filtros externos", r_no_ext))

    # ── 3. Pro Trend score_min=1 (solo gates estructurales, sin umbral de score)
    r_noscore = _run_backtest(symbol, timeframe, "pro", balance,
                              {"entry_score_min": 1, "entry_score_gap": 0},
                              from_dt, to_dt, cost_mode=costs, journal_out=journals)
    results.append(("Pro Trend score_min=1 (gates only)", r_noscore))

    # ── 4. Pro Trend con sizing fijo 50% (reduccion agresividad)
    r_50pct = _run_backtest(symbol, timeframe, "pro", balance,
                            {"size_ultra": "0.50", "size_high": "0.50", "size_mid": "0.50"},
                            from_dt, to_dt, cost_mode=costs, journal_out=journals)
    results.append(("Pro Trend sizing fijo 50%", r_50pct))

    # ── 5. Adaptive Trend (estrategia mas simple, BTC-only)
    r_adaptive = _run_backtest(symbol, timeframe, "adaptive", balance, {}, from_dt, to_dt,
                               cost_mode=costs, journal_out=journals)
    results.append(("Adaptive Trend (mas simple)", r_adaptive))

    # ── 6. Buy & Hold (calculado desde las barras directamente)
    if r_pro is not None:
        bh_pct = float(r_pro.buy_hold_pnl_pct)
        bh_final = balance * (1 + bh_pct / 100)
        years = (to_dt - from_dt).days / 365.25
        bh_cagr = (bh_final / balance) ** (1 / years) - 1 if years > 0 else 0
        results.append(("Buy & Hold BTC", None, bh_pct, bh_cagr * 100))

    # ── Tabla de comparacion
    t = Table(title=f"Baselines — {symbol} {from_dt.year}-{to_dt.year}",
              header_style="bold blue", show_lines=True)
    t.add_column("Estrategia",     style="dim", min_width=35)
    t.add_column("P&L",            justify="right")
    t.add_column("CAGR",           justify="right")
    t.add_column("Max DD",         justify="right")
    t.add_column("Sharpe",         justify="right")
    t.add_column("PF",             justify="right")
    t.add_column("Trades",         justify="right")
    t.add_column("Tiempo mkt",     justify="right")

    def _row(name, r, override_pnl=None, override_cagr=None):
        if r is None and override_pnl is not None:
            pnl_s = f"{override_pnl:+.1f}%"
            cagr_s = f"{override_cagr:+.1f}%"
            return [name, pnl_s, cagr_s, "—", "—", "—", "—", "100%"]
        if r is None:
            return [name, "ERROR", "—", "—", "—", "—", "—", "—"]
        c = "green" if r.total_pnl_pct >= 0 else "red"
        return [
            name,
            f"[{c}]{r.total_pnl_pct:+.1f}%[/{c}]",
            f"{r.cagr:+.1f}%",
            f"{r.max_drawdown_pct:.1f}%",
            f"{r.sharpe_ratio:.2f}",
            f"{r.profit_factor:.2f}",
            str(r.total_trades),
            f"{r.time_in_market_pct:.0f}%",
        ]

    for entry in results:
        if len(entry) == 2:
            t.add_row(*_row(entry[0], entry[1]))
        else:
            t.add_row(*_row(entry[0], None, entry[2], entry[3]))

    console.print(t)
    console.print("\n[bold]Interpretacion:[/bold]")
    console.print("  - Si Pro Trend score_min=1 iguala al completo: el scoring no aporta valor real.")
    console.print("  - Si Pro Trend sin externos iguala al completo: los filtros macro son decorativos.")
    console.print("  - Si Adaptive Trend consigue resultados similares con menos complejidad: simplificar.")
    console.print("  - Si Buy & Hold supera en CAGR con menos DD: la estrategia no justifica su complejidad.")
    if journals:
        console.print("\n[dim]Journals guardados:[/dim]")
        for p in journals:
            console.print(f"[dim]  -> {p}[/dim]")


# ---------------------------------------------------------------------------
# Comando: SENSITIVITY  (un parametro a la vez, mide fragilidad)
# ---------------------------------------------------------------------------

@app.command()
def sensitivity(
    symbol: str    = typer.Option("BTC-USDT", "--symbol"),
    from_date: str = typer.Option("2018-01-01", "--from", "-f"),
    to_date: str   = typer.Option("2026-01-01", "--to", "-t"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    balance: float = typer.Option(10000.0, "--balance", "-b"),
    costs: str     = typer.Option("realistic", "--costs"),
    verbose: bool  = typer.Option(False, "--verbose", "-v"),
):
    """
    Sensitivity analysis de Pro Trend v12: barre un parametro a la vez
    manteniendo el resto en sus valores default.

    Parametros analizados (default entre corchetes):
      entry_score_min:         8 / [9] / 10
      adx_min_entry:          10 / [15] / 20
      trailing_stop_pct_bull: 0.24 / [0.28] / 0.32
      cooldown_atr_stop_days: 15 / [30] / 45

    El objetivo es MEDIR fragilidad, no optimizar. Si un cambio de +/-1 paso
    degrada el resultado drasticamente -> ese threshold esta sobreajustado.
    Si el resultado es estable -> el parametro es robusto.

    Ejemplo:
      python main.py sensitivity --from 2018-01-01 --to 2026-01-01 --costs realistic
    """
    _setup_logging(verbose)

    from core.backtest import fetch_historical_bars
    from strategies.macro_context  import load_macro_context
    from strategies.market_context import load_market_context
    from strategies.funding_context import load_funding_history

    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        console.print("[red]Formato de fecha invalido. Usa YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold cyan]Sensitivity Analysis:[/bold cyan] {symbol} / "
        f"{from_dt.date()} -> {to_dt.date()} / costes={costs}\n"
    )

    # Descarga unica de barras — se reutiliza en las 9 variantes
    WARMUP_DAYS = 625
    warmup_start = from_dt - timedelta(days=WARMUP_DAYS)
    console.print("[dim]Descargando barras (unica descarga para todas las variantes)...[/dim]")
    all_bars = fetch_historical_bars(
        symbol=symbol, bar=timeframe, from_dt=warmup_start, to_dt=to_dt
    )
    if not all_bars:
        console.print("[red]No se pudieron descargar datos.[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]{len(all_bars):,} velas. Cargando contexto macro/mercado/funding...[/dim]")

    load_macro_context(from_dt, to_dt, symbol)
    load_market_context(from_dt, to_dt)
    load_funding_history(symbol, from_dt, to_dt)

    # Variantes: (label_display, parametro_grupo, config_override)
    # El primero es siempre el DEFAULT (cfg vacío)
    variants: list[tuple[str, str, dict]] = [
        ("DEFAULT v12",          "default",                {}),
        # ── entry_score_min ──────────────────────────────────────────────
        ("score_min=8",          "entry_score_min",        {"entry_score_min": 8}),
        ("score_min=10",         "entry_score_min",        {"entry_score_min": 10}),
        # ── adx_min_entry ────────────────────────────────────────────────
        ("adx_min=10",           "adx_min_entry",          {"adx_min_entry": 10.0}),
        ("adx_min=20",           "adx_min_entry",          {"adx_min_entry": 20.0}),
        # ── trailing_stop_pct_bull ───────────────────────────────────────
        ("trail_bull=0.24",      "trailing_stop_pct_bull", {"trailing_stop_pct_bull": 0.24}),
        ("trail_bull=0.32",      "trailing_stop_pct_bull", {"trailing_stop_pct_bull": 0.32}),
        # ── cooldown_atr_stop_days ───────────────────────────────────────
        ("cooldown_atr=15d",     "cooldown_atr_stop_days", {"cooldown_atr_stop_days": 15}),
        ("cooldown_atr=45d",     "cooldown_atr_stop_days", {"cooldown_atr_stop_days": 45}),
    ]

    run_results: list[tuple[str, str, dict, object]] = []
    journals: list[str] = []
    for i, (label, group, cfg) in enumerate(variants, 1):
        console.print(f"  [{i}/{len(variants)}] {label}...", end="\r")
        r = _run_backtest(
            symbol, timeframe, "pro", balance, cfg,
            from_dt, to_dt,
            prefetched_bars=all_bars,
            cost_mode=costs,
            journal_out=journals,
        )
        run_results.append((label, group, cfg, r))
    console.print(" " * 60, end="\r")

    default_r = run_results[0][3]

    def _delta_cagr(r) -> str:
        if r is None or default_r is None:
            return "—"
        d = float(r.cagr) - float(default_r.cagr)
        c = "green" if d >= 0 else "red"
        return f"[{c}]{d:+.1f}pp[/{c}]"

    def _delta_pf(r) -> str:
        if r is None or default_r is None:
            return "—"
        d = float(r.profit_factor) - float(default_r.profit_factor)
        c = "green" if d >= 0 else "red"
        return f"[{c}]{d:+.2f}[/{c}]"

    t = Table(
        title=f"Sensitivity — Pro Trend v12 / {symbol} {from_dt.year}-{to_dt.year} ({costs})",
        header_style="bold blue", show_lines=True,
    )
    t.add_column("Variante",   style="dim", min_width=16, max_width=18)
    t.add_column("CAGR",       justify="right", min_width=7)
    t.add_column("dCAGR",      justify="right", min_width=7)
    t.add_column("MaxDD",      justify="right", min_width=6)
    t.add_column("Sharpe",     justify="right", min_width=6)
    t.add_column("PF",         justify="right", min_width=5)
    t.add_column("dPF",        justify="right", min_width=6)
    t.add_column("Trades",     justify="right", min_width=6)

    last_group = None
    for label, group, cfg, r in run_results:
        is_default = (group == "default")
        if not is_default and group != last_group:
            t.add_section()
        last_group = group

        if r is None:
            t.add_row(label, "—", "ERROR", "—", "—", "—", "—", "—")
            continue

        lbl = f"[bold]{label}[/bold]" if is_default else label
        t.add_row(
            lbl,
            f"{float(r.cagr):+.1f}%",
            "—" if is_default else _delta_cagr(r),
            f"{float(r.max_drawdown_pct):.1f}%",
            f"{float(r.sharpe_ratio):.2f}",
            f"{float(r.profit_factor):.2f}",
            "—" if is_default else _delta_pf(r),
            str(r.total_trades),
        )

    console.print(t)
    console.print("\n[bold]Interpretacion:[/bold]")
    console.print("  dCAGR / dPF: delta vs DEFAULT v12. Verde=mejora, Rojo=empeora.")
    console.print("  |dCAGR| < 2pp y |dPF| < 0.30  -> parametro ROBUSTO (no sobreajustado).")
    console.print("  |dCAGR| >= 2pp o |dPF| >= 0.30 -> parametro FRAGIL (posible overfitting).")
    console.print("  Regla de fragilidad: un threshold robusto debe tolerar +/-1 paso sin colapsar.")
    if journals:
        console.print("\n[dim]Journals guardados:[/dim]")
        for p in journals:
            console.print(f"[dim]  -> {p}[/dim]")


# ---------------------------------------------------------------------------
# Comando: COMPARE  (backtest continuo + desglose anual y trimestral)
# ---------------------------------------------------------------------------

@app.command()
def compare(
    strategies: str = typer.Option(
        "adaptive", "--strategies", "-s",
        help="Estrategias separadas por comas: mean, adaptive, pro",
    ),
    from_year: int  = typer.Option(2018, "--from", "-f"),
    to_year: int    = typer.Option(2024, "--to",   "-t"),
    symbol: str     = typer.Option("BTC-USDT", "--symbol"),
    timeframe: str  = typer.Option("1H", "--timeframe"),
    balance: float  = typer.Option(10_000.0, "--balance", "-b"),
    verbose: bool   = typer.Option(False, "--verbose", "-v"),
):
    """
    Compara estrategias en un backtest CONTINUO (sin fronteras de año).
    Las posiciones se abren y cierran solo por señales de mercado.
    Muestra desglose anual y trimestral como referencia — no afectan la lógica.

    Ejemplo:
      python main.py compare --strategies adaptive,pro --from 2018 --to 2024
    """
    _setup_logging(verbose)
    from core.backtest import fetch_historical_bars

    strat_list = [s.strip().lower() for s in strategies.split(",") if s.strip()]
    years      = list(range(from_year, to_year + 1))

    if not strat_list:
        console.print("[red]Indica al menos una estrategia con --strategies[/red]")
        raise typer.Exit(1)

    from_dt = datetime(from_year, 1, 1, tzinfo=timezone.utc)
    to_dt   = datetime(to_year, 12, 31, hour=23, minute=59, second=59, tzinfo=timezone.utc)

    # Descarga única de barras para todas las estrategias.
    # 625 dias: suficiente para EMA350D de Pi Cycle Top (pro_trend).
    WARMUP = 625 if any(s in strat_list for s in ("pro", "pro_trend")) else 240
    warmup_start = from_dt - timedelta(days=WARMUP)
    console.print(
        f"[bold cyan]Descargando {symbol}/{timeframe} "
        f"{from_dt.date()} -> {to_dt.date()} (+{WARMUP}d warmup)...[/bold cyan]"
    )
    all_bars = fetch_historical_bars(symbol=symbol, bar=timeframe,
                                      from_dt=warmup_start, to_dt=to_dt)
    if not all_bars:
        console.print("[red]No se pudieron descargar datos de OKX.[/red]")
        raise typer.Exit(1)

    bh_by_year = _btc_year_returns(all_bars, years)

    # Un solo backtest continuo por estrategia
    results: dict[str, object] = {}
    for idx, strat in enumerate(strat_list, 1):
        label = _STRAT_LABELS.get(strat, strat)
        console.print(f"  [{idx}/{len(strat_list)}] {label} ({from_dt.date()} -> {to_dt.date()})...")
        results[strat] = _run_backtest(
            symbol, timeframe, strat, balance, {}, from_dt, to_dt,
            prefetched_bars=all_bars,
        )

    # Extraer métricas anuales de la curva de equity continua
    annual: dict[str, dict] = {}
    for strat, r in results.items():
        if r is None:
            annual[strat] = {y: {"pnl_pct": 0.0, "end_val": balance} for y in years}
        else:
            annual[strat] = _annual_returns_from_curve(r.equity_curve, years,
                                                        r.initial_balance)

    col_labels = [_STRAT_LABELS.get(s, s) for s in strat_list]

    # ── Tabla 1: rentabilidad anual ─────────────────────────────────────────
    t1 = Table(
        title=f"Rentabilidad anual — {symbol} (backtest continuo, inicio ${balance:,.0f})",
        header_style="bold blue", show_lines=True,
    )
    t1.add_column("Año", style="bold")
    t1.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t1.add_column(lbl, justify="right")
    for bm in _BENCHMARKS:
        t1.add_column(bm, justify="right")

    avg_bh = sum(bh_by_year.values()) / len(bh_by_year) if bh_by_year else 0.0
    for year in years:
        row = [str(year), _pct(bh_by_year.get(year, 0.0))]
        for strat in strat_list:
            row.append(_pct(annual[strat].get(year, {}).get("pnl_pct", 0.0)))
        for bm, bm_data in _BENCHMARKS.items():
            row.append(_pct(bm_data.get(year, 0.0)))
        t1.add_row(*row)

    avg_row = ["Promedio", _pct(avg_bh)]
    for strat in strat_list:
        vals = [annual[strat].get(y, {}).get("pnl_pct", 0.0) for y in years]
        avg_row.append(_pct(sum(vals) / len(vals)) if vals else "—")
    for bm, bm_data in _BENCHMARKS.items():
        bm_v = [bm_data.get(y, 0.0) for y in years if y in bm_data]
        avg_row.append(_pct(sum(bm_v) / len(bm_v)) if bm_v else "—")
    t1.add_row(*avg_row)
    console.print(t1)

    # ── Tabla 2: valor acumulado (compounding continuo) ─────────────────────
    t2 = Table(
        title=f"Valor acumulado — ${balance:,.0f} invertidos en {from_year} (compounding continuo)",
        header_style="bold blue", show_lines=True,
    )
    t2.add_column("Fin de año", style="bold")
    t2.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t2.add_column(lbl, justify="right")
    for bm in _BENCHMARKS:
        t2.add_column(bm, justify="right")

    acc_bh = balance
    acc_bm = {bm: balance for bm in _BENCHMARKS}
    for year in years:
        acc_bh *= (1 + bh_by_year.get(year, 0.0) / 100)
        row = [str(year), _usd(acc_bh, balance)]
        for strat in strat_list:
            row.append(_usd(annual[strat].get(year, {}).get("end_val", balance), balance))
        for bm, bm_data in _BENCHMARKS.items():
            acc_bm[bm] *= (1 + bm_data.get(year, 0.0) / 100)
            row.append(_usd(acc_bm[bm], balance))
        t2.add_row(*row)

    mult_row = ["Multiplicador", f"[bold]{acc_bh / balance:.2f}x[/bold]"]
    for strat in strat_list:
        final = annual[strat].get(years[-1], {}).get("end_val", balance)
        mult_row.append(f"[bold]{final / balance:.2f}x[/bold]")
    for bm in _BENCHMARKS:
        mult_row.append(f"[bold]{acc_bm[bm] / balance:.2f}x[/bold]")
    t2.add_row(*mult_row)
    console.print(t2)

    # ── Tabla 3: resumen trimestral por estrategia ──────────────────────────
    for strat, r in results.items():
        if r is not None:
            _print_quarterly_table(r, f"Resumen trimestral — {_STRAT_LABELS.get(strat, strat)}")

    # ── Tabla 4: estadísticas resumen ───────────────────────────────────────
    t4 = Table(title="Estadísticas resumen", header_style="bold blue", show_lines=True)
    t4.add_column("Métrica", style="dim")
    t4.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t4.add_column(lbl, justify="right")
    for bm in _BENCHMARKS:
        t4.add_column(bm, justify="right")

    bh_vals   = list(bh_by_year.values())
    strat_vals = {s: [annual[s].get(y, {}).get("pnl_pct", 0.0) for y in years] for s in strat_list}
    bm_vals    = {bm: [bm_data.get(y, 0.0) for y in years if y in bm_data]
                  for bm, bm_data in _BENCHMARKS.items()}

    def _stat(name, fn):
        row = [name]
        bh_v = fn(bh_vals)
        row.append(_pct(bh_v) if isinstance(bh_v, float) else str(bh_v))
        for s in strat_list:
            v = fn(strat_vals[s]) if strat_vals[s] else 0.0
            row.append(_pct(v) if isinstance(v, float) else str(v))
        for bm in _BENCHMARKS:
            v = fn(bm_vals[bm]) if bm_vals[bm] else 0.0
            row.append(_pct(v) if isinstance(v, float) else str(v))
        t4.add_row(*row)

    _stat("Mejor año",   lambda v: float(max(v)))
    _stat("Peor año",    lambda v: float(min(v)))
    _stat("Años > 0%",   lambda v: f"{sum(1 for x in v if x > 0)}/{len(v)}")
    _stat("Años < 0%",   lambda v: f"{sum(1 for x in v if x < 0)}/{len(v)}")
    _stat("Prom. anual", lambda v: float(sum(v) / len(v)))

    # Sharpe y MaxDD de cada resultado continuo
    for strat, r in results.items():
        if r is None:
            continue
        lbl = _STRAT_LABELS.get(strat, strat)
        t4.add_row(
            f"Sharpe ({lbl})",
            "—", *([f"{float(r.sharpe_ratio):.2f}"] + ["—"] * (len(strat_list) - 1 + len(_BENCHMARKS))),
        )
        t4.add_row(
            f"Max DD ({lbl})",
            "—", *([f"[red]-{float(r.max_drawdown_pct):.1f}%[/red]"] + ["—"] * (len(strat_list) - 1 + len(_BENCHMARKS))),
        )

    console.print(t4)


# ---------------------------------------------------------------------------
# Comando: RANDOM-BACKTEST  (N ventanas aleatorias de M meses)
# ---------------------------------------------------------------------------

@app.command()
def random_backtest(
    strategy: str  = typer.Option("adaptive", "--strategy", "-s",
                                   help="Tipo: mean | adaptive | pro"),
    symbol: str    = typer.Option("BTC-USDT", "--symbol"),
    windows: int   = typer.Option(10, "--windows", "-w",
                                   help="Número de ventanas aleatorias"),
    months: int    = typer.Option(24, "--months", "-m",
                                   help="Duración de cada ventana en meses"),
    balance: float = typer.Option(10_000.0, "--balance", "-b"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    seed: Optional[int] = typer.Option(None, "--seed",
                                        help="Semilla para reproducibilidad"),
    verbose: bool  = typer.Option(False, "--verbose", "-v"),
):
    """
    Valida una estrategia con N ventanas de M meses en fechas ALEATORIAS.

    Ninguna ventana empieza el 1 de enero ni en fecha especial — las fechas
    se eligen al azar dentro del histórico disponible de BTC en OKX.

    Ejemplo:
      python main.py random-backtest --strategy pro --windows 10 --months 24
      python main.py random-backtest --strategy adaptive --windows 15 --seed 42
    """
    _setup_logging(verbose)
    from core.backtest import fetch_historical_bars

    strat = strategy.lower()
    label = _STRAT_LABELS.get(strat, strat)

    if seed is not None:
        _random.seed(seed)

    # Rango válido para fechas de inicio
    window_days  = months * 30
    WARMUP       = 625 if strat in ("pro", "pro_trend") else 240
    latest_start = datetime.now(timezone.utc) - timedelta(days=window_days + 30)
    valid_days   = max(0, (latest_start - _OKX_EARLIEST).days)

    if valid_days < window_days:
        console.print("[red]Histórico insuficiente para ventanas de ese tamaño.[/red]")
        raise typer.Exit(1)

    # Generar fechas de inicio aleatorias (sin repetición)
    offsets = sorted(_random.sample(range(valid_days), min(windows, valid_days)))
    windows_list = [
        (
            _OKX_EARLIEST + timedelta(days=off),
            _OKX_EARLIEST + timedelta(days=off + window_days),
        )
        for off in offsets
    ]

    console.print(
        f"[bold cyan]{label} — {windows} ventanas aleatorias de {months} meses[/bold cyan]"
        + (f" (seed={seed})" if seed is not None else "")
    )

    # Resultados individuales
    win_results = []
    for i, (w_from, w_to) in enumerate(windows_list, 1):
        console.print(
            f"  [{i}/{windows}] {w_from.strftime('%d %b %Y')} -> {w_to.strftime('%d %b %Y')}...",
            end="\r",
        )
        r = _run_backtest(symbol, timeframe, strat, balance, {}, w_from, w_to)
        win_results.append((w_from, w_to, r))

    console.print(" " * 70, end="\r")

    # Tabla de resultados por ventana
    tw = Table(
        title=f"{label} — resultados por ventana ({symbol}, inicio ${balance:,.0f})",
        header_style="bold blue", show_lines=False,
    )
    tw.add_column("Ventana")
    tw.add_column("Trades", justify="right")
    tw.add_column("P&L %", justify="right")
    tw.add_column("BTC B&H %", justify="right")
    tw.add_column("Alpha %", justify="right")
    tw.add_column("Max DD", justify="right")
    tw.add_column("Sharpe", justify="right")
    tw.add_column("Win %", justify="right")

    pnl_pcts   = []
    bh_pcts    = []
    alphas     = []
    dds        = []
    sharpes    = []
    win_rates  = []

    for w_from, w_to, r in win_results:
        lbl_w = f"{w_from.strftime('%d %b %y')} -> {w_to.strftime('%d %b %y')}"
        if r is None:
            tw.add_row(lbl_w, "—", "—", "—", "—", "—", "—", "—")
            continue

        pnl_p  = float(r.total_pnl_pct)
        bh_p   = float(r.buy_hold_pnl_pct)
        alpha  = pnl_p - bh_p
        dd     = float(r.max_drawdown_pct)
        sharpe = float(r.sharpe_ratio)
        wr     = float(r.win_rate)

        pnl_pcts.append(pnl_p); bh_pcts.append(bh_p); alphas.append(alpha)
        dds.append(dd); sharpes.append(sharpe); win_rates.append(wr)

        ca = "green" if alpha >= 0 else "red"
        tw.add_row(
            lbl_w,
            str(r.total_trades),
            _pct(pnl_p),
            _pct(bh_p),
            f"[{ca}]{alpha:+.1f}%[/{ca}]",
            f"[red]-{dd:.1f}%[/red]",
            f"{sharpe:.2f}",
            f"{wr:.1f}%",
        )

    console.print(tw)

    if not pnl_pcts:
        console.print("[red]Sin resultados válidos.[/red]")
        raise typer.Exit(1)

    # Tabla de estadísticas agregadas
    import statistics as _stats

    ta = Table(title="Estadísticas agregadas", header_style="bold blue", show_lines=True)
    ta.add_column("Métrica", style="dim")
    ta.add_column(label, justify="right")
    ta.add_column("BTC B&H ref.", justify="right")

    def _agg_row(name, fn, vals, bh_v, fmt=_pct):
        ta.add_row(name, fmt(fn(vals)), fmt(fn(bh_v)))

    avg_pnl  = _stats.mean(pnl_pcts);  avg_bh  = _stats.mean(bh_pcts)
    std_pnl  = _stats.stdev(pnl_pcts) if len(pnl_pcts) > 1 else 0.0
    wins_pos = sum(1 for p in pnl_pcts if p > 0)

    ta.add_row("Ventanas válidas",    str(len(pnl_pcts)), str(len(bh_pcts)))
    ta.add_row("Ventanas positivas",  f"{wins_pos}/{len(pnl_pcts)}",
               f"{sum(1 for p in bh_pcts if p > 0)}/{len(bh_pcts)}")
    ta.add_row("P&L medio",           _pct(avg_pnl),     _pct(avg_bh))
    ta.add_row("P&L desv. estándar",  f"{std_pnl:.1f}%", "—")
    ta.add_row("Mejor ventana",       _pct(max(pnl_pcts)), _pct(max(bh_pcts)))
    ta.add_row("Peor ventana",        _pct(min(pnl_pcts)), _pct(min(bh_pcts)))
    ta.add_row("Alpha medio",         _pct(_stats.mean(alphas)), "—")
    ta.add_row("Max DD medio",        f"[red]-{_stats.mean(dds):.1f}%[/red]", "—")
    ta.add_row("Sharpe medio",        f"{_stats.mean(sharpes):.2f}", "—")
    ta.add_row("Win rate medio",      f"{_stats.mean(win_rates):.1f}%", "—")

    console.print(ta)

    # Veredicto
    beat_bh = sum(1 for a in alphas if a > 0)
    console.print(
        f"\n[bold]Veredicto:[/bold] {label} superó a BTC B&H en "
        f"[{'green' if beat_bh > len(alphas) / 2 else 'red'}]"
        f"{beat_bh}/{len(alphas)}[/] ventanas."
    )


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    logger.remove()
    stderr_level = "DEBUG" if verbose else "WARNING"
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(sys.stderr, level=stderr_level,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(log_dir / "trading_{time:YYYY-MM-DD}.log",
               rotation="00:00", retention="30 days", level="DEBUG", encoding="utf-8")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

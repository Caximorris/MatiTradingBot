"""
Motor común del CLI: instanciación de estrategias y ejecución de backtests.
Reutilizado por backtest, walk-forward, baselines, sensitivity, compare y random-backtest.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from loguru import logger

from cli.common import console


# ---------------------------------------------------------------------------
# Fábrica de estrategias desde BotState
# ---------------------------------------------------------------------------

def _instantiate_strategy(bot_state, client, risk_manager, session):
    from strategies.registry import resolve
    name   = bot_state.strategy_name
    config = bot_state.get_config()
    try:
        meta = resolve(name)
        if meta is None:
            logger.warning("Tipo de estrategia desconocido: {}", name)
            return None
        cfg_obj = meta.make_config(bot_state.symbol, config)
        return meta.make_bot(client, cfg_obj, session, risk_manager)
    except Exception as exc:
        logger.error("Error al instanciar {}: {}", name, exc)
        return None


# ---------------------------------------------------------------------------
# Backtest runner
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

    from strategies.registry import get as _get_strategy
    meta        = _get_strategy(strat_type)
    WARMUP_DAYS = meta.warmup_days
    warmup_start = from_dt - timedelta(days=WARMUP_DAYS)
    label       = meta.display_name

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
            cfg_obj = meta.make_config(symbol.upper(), config)
            return meta.make_bot(client, cfg_obj, session)

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

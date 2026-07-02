"""
Comandos de backtest y validación: backtest, walk-forward, baselines, sensitivity.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import typer
from rich.table import Table

from cli.common import console, _print_quarterly_table, _setup_logging
from cli.runner import _run_backtest


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

    from strategies.registry import get as _get_strategy
    _strat_meta = _get_strategy(strategy.lower())
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

    if result.total_trades == 0:
        console.print("[yellow](!)  Sin trades generados.[/yellow]")
    elif _strat_meta.output == "allocator":
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
    from strategies.registry import get as _get_strategy
    WARMUP_DAYS = _get_strategy("pro").warmup_days
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


def register(app: typer.Typer) -> None:
    app.command()(backtest)
    app.command(name="walk-forward")(walk_forward)
    app.command()(baselines)
    app.command()(sensitivity)

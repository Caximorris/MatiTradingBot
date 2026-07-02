"""
Comandos de comparación multi-estrategia: compare, random-backtest.
"""
from __future__ import annotations

import random as _random
from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.table import Table

from cli.common import (
    console, _BENCHMARKS, _OKX_EARLIEST, _pct, _usd, _strat_display,
    _annual_returns_from_curve, _btc_year_returns, _print_quarterly_table,
    _setup_logging,
)
from cli.runner import _run_backtest


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

    # Descarga única de barras para todas las estrategias — warmup del más exigente.
    from strategies.registry import get as _get_strategy
    WARMUP = max(_get_strategy(s).warmup_days for s in strat_list)
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
        label = _strat_display(strat)
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

    col_labels = [_strat_display(s) for s in strat_list]

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
            _print_quarterly_table(r, f"Resumen trimestral — {_strat_display(strat)}")

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
        lbl = _strat_display(strat)
        t4.add_row(
            f"Sharpe ({lbl})",
            "—", *([f"{float(r.sharpe_ratio):.2f}"] + ["—"] * (len(strat_list) - 1 + len(_BENCHMARKS))),
        )
        t4.add_row(
            f"Max DD ({lbl})",
            "—", *([f"[red]-{float(r.max_drawdown_pct):.1f}%[/red]"] + ["—"] * (len(strat_list) - 1 + len(_BENCHMARKS))),
        )

    console.print(t4)


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

    strat = strategy.lower()
    label = _strat_display(strat)

    if seed is not None:
        _random.seed(seed)

    # Rango válido para fechas de inicio
    from strategies.registry import get as _get_strategy
    window_days  = months * 30
    WARMUP       = _get_strategy(strat).warmup_days
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


def register(app: typer.Typer) -> None:
    app.command()(compare)
    app.command(name="random-backtest")(random_backtest)

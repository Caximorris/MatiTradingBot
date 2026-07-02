"""
Helpers compartidos por todos los comandos del CLI.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

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

# Fecha más antigua disponible en OKX para BTC-USDT
_OKX_EARLIEST = datetime(2018, 1, 1, tzinfo=timezone.utc)


def _strat_display(name: str) -> str:
    from strategies.registry import display
    return display(name)


# ---------------------------------------------------------------------------
# Helpers de formato
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
# Settings / cliente / logging
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


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    stderr_level = "DEBUG" if verbose else "WARNING"
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(sys.stderr, level=stderr_level,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(log_dir / "trading_{time:YYYY-MM-DD}.log",
               rotation="00:00", retention="30 days", level="DEBUG", encoding="utf-8")

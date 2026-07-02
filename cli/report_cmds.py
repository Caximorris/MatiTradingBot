"""
Comandos de reporting: trades, report (fiscal IRPF).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from cli.common import console, _load_settings, _setup_logging


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


def register(app: typer.Typer) -> None:
    app.command()(trades)
    app.command()(report)

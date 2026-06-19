"""
Dashboard de terminal con rich.
Muestra en tiempo real: balance, posiciones, bots activos y trades recientes.
Todas las fechas se muestran en hora de Madrid (Europe/Madrid).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from loguru import logger
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.database import BotState, Position, Trade, get_session
from core.exchange import OKXClient

MADRID = ZoneInfo("Europe/Madrid")
_START_TIME = datetime.now(timezone.utc)


def _madrid(dt: datetime) -> str:
    return dt.astimezone(MADRID).strftime("%d/%m %H:%M")


def _elapsed() -> str:
    delta = datetime.now(timezone.utc) - _START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _pnl_color(value: Decimal | float | None) -> str:
    if value is None:
        return "white"
    return "green" if float(value) >= 0 else "red"


# ---------------------------------------------------------------------------
# Paneles individuales
# ---------------------------------------------------------------------------

def _header_panel(mode: str) -> Panel:
    now_madrid = datetime.now(MADRID).strftime("%d/%m/%Y  %H:%M:%S")
    mode_label = Text(f"● {mode.upper()}", style="bold yellow" if mode == "paper" else "bold red")
    line = Text()
    line.append("OKX Trading Bot  ", style="bold cyan")
    line.append(mode_label)
    line.append(f"   {now_madrid}  ", style="dim")
    line.append(f"uptime {_elapsed()}", style="dim")
    return Panel(line, style="bold blue")


def _balance_panel(client: OKXClient) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="dim")
    table.add_column("val", justify="right", style="bold")

    try:
        balance = client.get_balance()
        total_usdt = balance.get("USDT", Decimal("0"))
        table.add_row("USDT disponible", f"[green]{total_usdt:,.2f}[/green]")
        for token, amount in balance.items():
            if token != "USDT" and amount > Decimal("0"):
                table.add_row(token, f"{amount:.6f}")
    except Exception:
        table.add_row("estado", "[red]Exchange no disponible[/red]")

    return Panel(table, title="[bold]Balance[/bold]", border_style="blue")


def _bots_panel() -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Bot", style="cyan", no_wrap=True)
    table.add_column("Par", justify="center")
    table.add_column("Estado", justify="center")
    table.add_column("Último tick", justify="right", style="dim")
    table.add_column("P&L total", justify="right")

    try:
        with get_session() as s:
            bots = s.query(BotState).order_by(BotState.created_at).all()
            rows = [
                (
                    b.strategy_name,
                    b.symbol,
                    b.is_active,
                    b.last_run,
                    b.total_pnl,
                )
                for b in bots
            ]
    except Exception:
        rows = []

    if not rows:
        table.add_row("[dim]Sin bots configurados[/dim]", "", "", "", "")
    else:
        for name, symbol, active, last_run, total_pnl in rows:
            status = "[green]● ACTIVO[/green]" if active else "[red]○ PARADO[/red]"
            last = _madrid(last_run) if last_run else "—"
            pnl_str = f"[{_pnl_color(total_pnl)}]{float(total_pnl):+.2f}[/{_pnl_color(total_pnl)}]"
            table.add_row(name, symbol, status, last, pnl_str)

    return Panel(table, title="[bold]Bots activos[/bold]", border_style="blue")


def _positions_panel() -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Par", style="cyan")
    table.add_column("Estrategia", style="dim")
    table.add_column("Lado", justify="center")
    table.add_column("Entrada", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("PnL no realizado", justify="right")

    try:
        with get_session() as s:
            positions = s.query(Position).all()
            rows = [
                (p.symbol, p.strategy, p.side, p.entry_price, p.current_price, p.unrealized_pnl)
                for p in positions
            ]
    except Exception:
        rows = []

    if not rows:
        table.add_row("[dim]Sin posiciones abiertas[/dim]", "", "", "", "", "")
    else:
        for symbol, strat, side, entry, current, upnl in rows:
            side_label = "[green]LONG[/green]" if side == "long" else "[red]SHORT[/red]"
            c = _pnl_color(upnl)
            table.add_row(
                symbol, strat, side_label,
                f"{float(entry):,.2f}",
                f"{float(current):,.2f}",
                f"[{c}]{float(upnl):+.2f}[/{c}]",
            )

    return Panel(table, title="[bold]Posiciones abiertas[/bold]", border_style="blue")


def _trades_panel(limit: int = 12) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Hora", style="dim", no_wrap=True)
    table.add_column("Par", style="cyan")
    table.add_column("Lado", justify="center")
    table.add_column("Qty", justify="right")
    table.add_column("Precio", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("", style="dim")  # paper marker

    try:
        with get_session() as s:
            trades = (
                s.query(Trade)
                .order_by(Trade.timestamp.desc())
                .limit(limit)
                .all()
            )
            rows = [
                (t.timestamp, t.symbol, t.side, t.quantity, t.price, t.pnl, t.is_paper)
                for t in trades
            ]
    except Exception:
        rows = []

    if not rows:
        table.add_row("[dim]Sin trades registrados[/dim]", "", "", "", "", "", "")
    else:
        for ts, symbol, side, qty, price, pnl, is_paper in rows:
            side_label = "[green]BUY[/green]" if side == "buy" else "[red]SELL[/red]"
            pnl_str = f"[{_pnl_color(pnl)}]{float(pnl):+.2f}[/{_pnl_color(pnl)}]" if pnl is not None else "—"
            paper = "[dim]P[/dim]" if is_paper else ""
            table.add_row(
                _madrid(ts), symbol, side_label,
                f"{float(qty):.6f}", f"{float(price):,.2f}", pnl_str, paper,
            )

    return Panel(table, title="[bold]Trades recientes[/bold]", border_style="blue")


def _footer_panel() -> Panel:
    """Resumen diario: P&L del día, número de trades, límite de pérdida."""
    today_pnl = Decimal("0")
    trades_today = 0
    try:
        from datetime import date
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        with get_session() as s:
            from sqlalchemy import func
            result = (
                s.query(func.sum(Trade.pnl), func.count(Trade.id))
                .filter(Trade.timestamp >= today_start, Trade.pnl.isnot(None))
                .one()
            )
            if result[0] is not None:
                today_pnl = Decimal(str(result[0]))
            trades_today = result[1] or 0
    except Exception:
        pass

    c = _pnl_color(today_pnl)
    text = Text()
    text.append("  P&L hoy: ")
    text.append(f"{float(today_pnl):+.2f} USDT", style=c)
    text.append(f"   |   Trades hoy: {trades_today}", style="dim")
    text.append("   |   Actualización cada 30s", style="dim")
    return Panel(text, style="dim")


# ---------------------------------------------------------------------------
# Render completo del layout
# ---------------------------------------------------------------------------

def _render(client: OKXClient, mode: str) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_header_panel(mode), name="header", size=3),
        Layout(name="body"),
        Layout(_footer_panel(), name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    layout["left"].split_column(
        Layout(_balance_panel(client), name="balance", ratio=1),
        Layout(_bots_panel(), name="bots", ratio=2),
    )
    layout["right"].split_column(
        Layout(_positions_panel(), name="positions", ratio=1),
        Layout(_trades_panel(), name="trades", ratio=2),
    )
    return layout


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def run_dashboard(client: OKXClient, mode: str, refresh_seconds: int = 30) -> None:
    """
    Arranca el dashboard interactivo en el terminal.
    Refresca los datos cada `refresh_seconds` segundos.
    Pulsa Ctrl+C para salir.
    """
    console = Console()
    console.print(
        f"[bold cyan]Dashboard iniciado[/bold cyan] — modo [yellow]{mode.upper()}[/yellow] "
        f"— refresco cada {refresh_seconds}s — Ctrl+C para salir"
    )

    with Live(
        _render(client, mode),
        console=console,
        screen=True,
        refresh_per_second=1,
        auto_refresh=False,
    ) as live:
        try:
            while True:
                live.update(_render(client, mode))
                live.refresh()
                # Espera el intervalo en trozos de 1s para que Ctrl+C responda rápido
                for _ in range(refresh_seconds):
                    time.sleep(1)
                    live.update(_render(client, mode))
                    live.refresh()
        except KeyboardInterrupt:
            pass

    console.print("[bold]Dashboard cerrado.[/bold]")

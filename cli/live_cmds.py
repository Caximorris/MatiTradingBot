"""
Comandos de operación live/paper: start, stop, status, dashboard, mode.
"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import typer
from loguru import logger
from rich.table import Table

from cli.common import console, _load_settings, _make_client, _setup_logging
from cli.runner import _instantiate_strategy


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
    default_client = _make_client(settings)
    default_risk_manager = RiskManager(client=default_client, app_settings=settings)

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

    clients: dict[tuple[str, str], tuple[object, RiskManager]] = {}
    for name, symbol, config in bot_configs:
        if config.get("execution") == "okx_demo":
            # Ordenes contra la cuenta DEMO real de OKX (data de mercado sigue siendo real).
            # Si falla (credenciales demo ausentes/invalidas), se salta SOLO este bot: los
            # demas siguen arrancando.
            try:
                from core.okx_demo_client import OKXDemoClient
                mirror = str(config.get("paper_portfolio_id") or "okx_demo")
                bot_client = OKXDemoClient(
                    settings, mirror_name=mirror,
                    exec_quote=config.get("execution_quote"),
                    bridge_quote=config.get("execution_bridge"),
                )
                bot_risk = RiskManager(client=bot_client, app_settings=settings)
            except Exception as exc:
                console.print(f"  [red][SKIP][/red] {name}: OKXDemoClient no disponible — {exc}")
                continue
            clients[(name, symbol)] = (bot_client, bot_risk)
            continue
        portfolio_id = config.get("paper_portfolio_id") if settings.is_paper else None
        if portfolio_id:
            bot_client = _make_client(settings, paper_state_name=str(portfolio_id))
            bot_risk = RiskManager(client=bot_client, app_settings=settings)
        else:
            bot_client, bot_risk = default_client, default_risk_manager
        clients[(name, symbol)] = (bot_client, bot_risk)

    def _make_job(strategy_name, symbol, config):
        def job():
            try:
                with get_session() as session:
                    state = (session.query(BotState)
                             .filter_by(strategy_name=strategy_name, symbol=symbol)
                             .first())
                    if not state or not state.is_active:
                        return
                    bot_client, bot_risk = clients[(strategy_name, symbol)]
                    strategy = _instantiate_strategy(state, bot_client, bot_risk, session)
                    if strategy:
                        strategy.run()
                        state.last_run = datetime.now(timezone.utc)
            except Exception as exc:
                logger.error("[{}] Error en tick: {}", strategy_name, exc)
        return job

    for name, symbol, config in bot_configs:
        if (name, symbol) not in clients:
            continue   # bot saltado arriba (p.ej. demo sin credenciales)
        job_id = f"{name}_{symbol}".replace("-", "_")
        scheduler.add_job(_make_job(name, symbol, config), "interval",
                          seconds=tick, id=job_id, max_instances=1)
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


def status(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Muestra el estado actual: bots, balance y posiciones abiertas."""
    _setup_logging(verbose)
    settings = _load_settings()

    from core.database import BotState, Position, Trade, get_session, init_db
    from sqlalchemy import func
    from tools.status_snapshot import (
        build_bot_records,
        build_paper_portfolios,
        format_madrid,
    )

    init_db()
    mode = "PAPER" if settings.is_paper else "LIVE"
    console.rule(f"[bold cyan]OKX Trading Bot — modo {mode}[/bold cyan]")

    with get_session() as s:
        bots = s.query(BotState).order_by(BotState.created_at).all()
        bot_rows = build_bot_records(bots)

    if settings.is_paper:
        from tools.paper_snapshot import RUNTIME
        portfolios = build_paper_portfolios(bot_rows, RUNTIME)
        console.print("\n[bold]Carteras paper aisladas[/bold]")
        if not portfolios:
            console.print("  [dim]Sin bots operables configurados.[/dim]")
        else:
            bt = Table(show_header=True, header_style="bold blue")
            bt.add_column("Bot")
            bt.add_column("Ejecucion")
            bt.add_column("BTC", justify="right")
            bt.add_column("Efectivo", justify="right")
            bt.add_column("Fuente")
            for p in portfolios:
                cash = f"{p['quote_balance']:,.2f} {p['quote_currency']}"
                if not p["wallet_exists"]:
                    cash = "[red]wallet ausente[/red]"
                bt.add_row(
                    p["label"],
                    f"{p['execution_symbol']} · {p['execution_venue']}",
                    f"{p['base_balance']:,.6f}",
                    cash,
                    p["wallet_path"].name,
                )
            console.print(bt)
            if any(p["quote_is_alias"] for p in portfolios):
                console.print(
                    "[dim]Demo: el efectivo es USDC real; la estrategia lo recibe como "
                    "alias USDT para mantener paridad con el backtest.[/dim]"
                )
    else:
        client = _make_client(settings)
        try:
            balance = client.get_balance()
            console.print("\n[bold]Balance exchange[/bold]")
            for token, amount in balance.items():
                if amount > Decimal("0"):
                    console.print(f"  {token}: [green]{amount:,.6f}[/green]")
        except Exception as exc:
            console.print(f"  [red]Exchange no disponible: {exc}[/red]")

    console.print("\n[bold]Bots configurados[/bold]")

    if not bot_rows:
        console.print("  [dim]Sin bots operables configurados.[/dim]")
    else:
        t = Table(show_header=True, header_style="bold blue")
        t.add_column("Nombre"); t.add_column("Señal"); t.add_column("Ejecución")
        t.add_column("Estado"); t.add_column("Último tick Madrid")
        t.add_column("P&L total", justify="right")
        for row in bot_rows:
            sl = "[green]ACTIVO[/green]" if row["is_active"] else "[red]PARADO[/red]"
            pnl = row["total_pnl"]
            pc = "green" if pnl >= 0 else "red"
            execution = f"{row['execution_symbol']} · {row['execution_venue']}"
            t.add_row(
                row["name"], row["signal_symbol"], execution, sl,
                format_madrid(row["last_run"]), f"[{pc}]{pnl:+.2f}[/{pc}]",
            )
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
    console.print(
        f"\n[bold]Hoy:[/bold] {daily_trades} trades | "
        f"P&L registrado: [{c}]{daily_pnl:+.2f} USD-equivalente[/{c}]"
    )


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


def mode():
    """Muestra el modo de trading actual (paper/live)."""
    settings = _load_settings()
    if settings.is_paper:
        console.print("[bold yellow]Modo actual: PAPER[/bold yellow]")
        console.print("[dim]Para cambiar a live: TRADING_MODE=live en el .env[/dim]")
    else:
        console.print("[bold red]Modo actual: LIVE[/bold red]")
        console.print(f"[dim]Pares: {', '.join(settings.trading_pairs)}[/dim]")


def register(app: typer.Typer) -> None:
    app.command()(start)
    app.command()(stop)
    app.command()(status)
    app.command()(dashboard)
    app.command()(mode)

"""
OKX Trading Bot — CLI principal.

Uso:
    python main.py start                    # Arranca todos los bots activos
    python main.py stop                     # Parada de emergencia
    python main.py status                   # Estado actual del sistema
    python main.py dashboard                # Dashboard en vivo
    python main.py trades                   # Historial de trades
    python main.py report --year 2025       # Informe fiscal IRPF
    python main.py mode                     # Muestra el modo actual
    python main.py bot list                 # Lista de bots configurados
    python main.py bot enable NAME SYMBOL   # Activa un bot
    python main.py bot disable NAME SYMBOL  # Desactiva un bot
"""
from __future__ import annotations

import json
import signal
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# ---------------------------------------------------------------------------
# App raíz y sub-app "bot"
# ---------------------------------------------------------------------------

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
# Carga perezosa de settings (evita fallar al pedir --help sin .env)
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
    return OKXClient(settings)


# ---------------------------------------------------------------------------
# Fábrica de estrategias — instancia la clase correcta desde BotState
# ---------------------------------------------------------------------------

def _instantiate_strategy(bot_state, client, risk_manager, session):
    """
    Determina el tipo de estrategia por el prefijo de strategy_name
    y la instancia con la configuración guardada en config_json.
    """
    name = bot_state.strategy_name
    config = bot_state.get_config()

    try:
        if name.startswith("grid_"):
            from strategies.grid_bot import GridBot, GridConfig
            return GridBot(
                client=client,
                config=GridConfig.from_dict(config),
                session=session,
                risk_manager=risk_manager,
            )
        elif name.startswith("dca_"):
            from strategies.dca_bot import DCABot, DCAConfig
            return DCABot(
                client=client,
                config=DCAConfig.from_dict(config),
                session=session,
                risk_manager=risk_manager,
            )
        elif name.startswith("mean_"):
            from strategies.mean_reversion import MeanReversionBot, MeanReversionConfig
            return MeanReversionBot(
                client=client,
                config=MeanReversionConfig.from_dict(config),
                session=session,
                risk_manager=risk_manager,
            )
        elif name.startswith("signal"):
            from strategies.signal_follower import SignalFollower, SignalConfig
            return SignalFollower(
                client=client,
                config=SignalConfig(**config) if config else SignalConfig(),
                session=session,
                risk_manager=risk_manager,
            )
        else:
            logger.warning("Tipo de estrategia desconocido: {}", name)
            return None
    except Exception as exc:
        logger.error("Error al instanciar {}: {}", name, exc)
        return None


# ---------------------------------------------------------------------------
# Comando: START
# ---------------------------------------------------------------------------

@app.command()
def start(
    tick: int = typer.Option(30, "--tick", "-t", help="Segundos entre ticks de cada bot."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logs DEBUG."),
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
    client = _make_client(settings)
    risk_manager = RiskManager(client=client, app_settings=settings)

    # Carga bots activos
    with get_session() as s:
        active_bots = s.query(BotState).filter(BotState.is_active == True).all()
        bot_configs = [(b.strategy_name, b.symbol, b.get_config()) for b in active_bots]

    if not bot_configs:
        console.print("[yellow]No hay bots activos. Usa 'okx-trader bot enable' para activar uno.[/yellow]")
        raise typer.Exit(0)

    mode_label = "PAPER" if settings.is_paper else "[bold red]LIVE[/bold red]"
    console.print(f"[bold cyan]Iniciando {len(bot_configs)} bot(s) en modo {mode_label}[/bold cyan]")

    scheduler = BackgroundScheduler(timezone="UTC")
    _running = True

    def _make_job(strategy_name: str, symbol: str, config: dict):
        def job():
            try:
                with get_session() as session:
                    from core.database import BotState
                    state = (
                        session.query(BotState)
                        .filter_by(strategy_name=strategy_name, symbol=symbol)
                        .first()
                    )
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
        job_fn = _make_job(name, symbol, config)
        scheduler.add_job(job_fn, "interval", seconds=tick, id=name, max_instances=1)
        console.print(f"  [green]✓[/green] {name} ({symbol}) — tick cada {tick}s")

    scheduler.start()
    console.print("[bold green]Bots en marcha. Pulsa Ctrl+C para detener.[/bold green]")

    def _shutdown(signum, frame):
        nonlocal _running
        _running = False
        console.print("\n[yellow]Parando scheduler...[/yellow]")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while _running:
        time.sleep(1)


# ---------------------------------------------------------------------------
# Comando: STOP
# ---------------------------------------------------------------------------

@app.command()
def stop(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Parada de emergencia: cancela órdenes y desactiva todos los bots."""
    _setup_logging(verbose)
    settings = _load_settings()
    client = _make_client(settings)

    from core.risk_manager import RiskManager
    from core.database import init_db

    init_db()
    rm = RiskManager(client=client, app_settings=settings)
    rm.emergency_stop()
    console.print("[bold red]EMERGENCY STOP ejecutado.[/bold red] Todos los bots desactivados.")


# ---------------------------------------------------------------------------
# Comando: STATUS
# ---------------------------------------------------------------------------

@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Muestra el estado actual: bots, balance y posiciones abiertas."""
    _setup_logging(verbose)
    settings = _load_settings()
    client = _make_client(settings)

    from core.database import BotState, Position, Trade, get_session, init_db
    from sqlalchemy import func

    init_db()

    mode = "PAPER" if settings.is_paper else "LIVE"
    console.rule(f"[bold cyan]OKX Trading Bot — modo {mode}[/bold cyan]")

    # Balance
    try:
        balance = client.get_balance()
        console.print("\n[bold]Balance[/bold]")
        for token, amount in balance.items():
            if amount > Decimal("0"):
                console.print(f"  {token}: [green]{amount:,.6f}[/green]")
    except Exception as exc:
        console.print(f"  [red]Exchange no disponible: {exc}[/red]")

    # Bots
    console.print("\n[bold]Bots configurados[/bold]")
    with get_session() as s:
        bots = s.query(BotState).order_by(BotState.created_at).all()
        bot_rows = [
            (b.strategy_name, b.symbol, b.is_active, b.last_run, float(b.total_pnl))
            for b in bots
        ]

    if not bot_rows:
        console.print("  [dim]Sin bots configurados. Usa 'bot add' para crear uno.[/dim]")
    else:
        t = Table(show_header=True, header_style="bold blue")
        t.add_column("Nombre")
        t.add_column("Par")
        t.add_column("Estado")
        t.add_column("Último tick")
        t.add_column("P&L total", justify="right")
        for name, symbol, active, last_run, pnl in bot_rows:
            status_label = "[green]ACTIVO[/green]" if active else "[red]PARADO[/red]"
            last = last_run.strftime("%d/%m %H:%M") if last_run else "—"
            pnl_label = f"[{'green' if pnl >= 0 else 'red'}]{pnl:+.2f}[/{'green' if pnl >= 0 else 'red'}]"
            t.add_row(name, symbol, status_label, last, pnl_label)
        console.print(t)

    # Posiciones
    console.print("\n[bold]Posiciones abiertas[/bold]")
    with get_session() as s:
        positions = s.query(Position).all()
        pos_rows = [
            (p.symbol, p.strategy, p.side, float(p.entry_price),
             float(p.current_price), float(p.unrealized_pnl))
            for p in positions
        ]

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

    # P&L diario
    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), datetime.min.time()
    ).replace(tzinfo=timezone.utc)
    with get_session() as s:
        result = (
            s.query(func.sum(Trade.pnl), func.count(Trade.id))
            .filter(Trade.timestamp >= today_start)
            .one()
        )
    daily_pnl = float(result[0] or 0)
    daily_trades = result[1] or 0
    c = "green" if daily_pnl >= 0 else "red"
    console.print(f"\n[bold]Hoy:[/bold] {daily_trades} trades | P&L: [{c}]{daily_pnl:+.2f} USDT[/{c}]")


# ---------------------------------------------------------------------------
# Comando: DASHBOARD
# ---------------------------------------------------------------------------

@app.command()
def dashboard(
    refresh: int = typer.Option(30, "--refresh", "-r", help="Segundos entre refrescos."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Lanza el dashboard interactivo en tiempo real (Ctrl+C para salir)."""
    _setup_logging(verbose)
    settings = _load_settings()
    client = _make_client(settings)

    from core.database import init_db
    from reporting.dashboard import run_dashboard

    init_db()
    run_dashboard(client=client, mode=settings.trading_mode, refresh_seconds=refresh)


# ---------------------------------------------------------------------------
# Comando: TRADES
# ---------------------------------------------------------------------------

@app.command()
def trades(
    limit: int = typer.Option(20, "--limit", "-n", help="Número de trades a mostrar."),
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s", help="Filtrar por par."),
    paper: Optional[bool] = typer.Option(None, "--paper/--live", help="Filtrar paper o live."),
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
        trade_list = q.limit(limit).all()
        rows = [
            (t.timestamp, t.symbol, t.side, float(t.quantity),
             float(t.price), t.pnl, t.strategy, t.is_paper)
            for t in trade_list
        ]

    if not rows:
        console.print("[dim]Sin trades que mostrar.[/dim]")
        return

    t = Table(title=f"Últimos {limit} trades", header_style="bold blue", show_lines=False)
    t.add_column("Fecha/Hora")
    t.add_column("Par", style="cyan")
    t.add_column("Lado", justify="center")
    t.add_column("Cantidad", justify="right")
    t.add_column("Precio", justify="right")
    t.add_column("P&L", justify="right")
    t.add_column("Estrategia", style="dim")
    t.add_column("", style="dim")

    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
    for ts, sym, side, qty, price, pnl, strat, is_paper in rows:
        side_label = "[green]BUY[/green]" if side == "buy" else "[red]SELL[/red]"
        pnl_str = "—"
        if pnl is not None:
            c = "green" if float(pnl) >= 0 else "red"
            pnl_str = f"[{c}]{float(pnl):+.2f}[/{c}]"
        paper_label = "[dim]P[/dim]" if is_paper else "[bold]L[/bold]"
        t.add_row(
            ts.astimezone(MADRID).strftime("%d/%m/%Y %H:%M"),
            sym, side_label, f"{qty:.6f}", f"{price:,.2f}", pnl_str, strat, paper_label,
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Comando: REPORT
# ---------------------------------------------------------------------------

@app.command()
def report(
    year: int = typer.Option(2025, "--year", "-y", help="Año fiscal (ej: 2025)."),
    rate: float = typer.Option(0.92, "--rate", "-r", help="Tipo de cambio USDT/EUR."),
    losses: float = typer.Option(0.0, "--losses", "-l",
                                  help="Pérdidas arrastradas de años anteriores (EUR)."),
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
        console.print(f"[green]✓[/green] Excel: [bold]{excel_path}[/bold]")
        json_path = excel_path.replace(".xlsx", ".json")
        if Path(json_path).exists():
            console.print(f"[green]✓[/green] JSON:  [bold]{json_path}[/bold]")
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
        bots = s.query(BotState).order_by(BotState.strategy_name).all()
        rows = [(b.strategy_name, b.symbol, b.is_active, b.created_at) for b in bots]

    if not rows:
        console.print("[dim]Sin bots configurados.[/dim]")
        console.print("Crea uno con: [bold]bot add grid BTC-USDT ...[/bold]")
        return

    t = Table(header_style="bold blue")
    t.add_column("Nombre"); t.add_column("Par"); t.add_column("Estado"); t.add_column("Creado")
    for name, symbol, active, created in rows:
        status = "[green]ACTIVO[/green]" if active else "[dim]PARADO[/dim]"
        t.add_row(name, symbol, status, created.strftime("%d/%m/%Y"))
    console.print(t)


@bot_app.command("enable")
def bot_enable(
    name: str = typer.Argument(..., help="Nombre del bot (ej: grid_btc_usdt)"),
    symbol: str = typer.Argument(..., help="Par de trading (ej: BTC-USDT)"),
):
    """Activa un bot. Lo crea si no existe (con configuración vacía)."""
    from core.database import get_session, set_bot_active, init_db

    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=True)
    console.print(f"[green]✓[/green] Bot [bold]{state.strategy_name}[/bold] activado.")


@bot_app.command("disable")
def bot_disable(
    name: str = typer.Argument(..., help="Nombre del bot"),
    symbol: str = typer.Argument(..., help="Par de trading"),
):
    """Desactiva un bot (no cancela órdenes abiertas)."""
    from core.database import get_session, set_bot_active, init_db

    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=False)
    console.print(f"[yellow]○[/yellow] Bot [bold]{state.strategy_name}[/bold] desactivado.")


@bot_app.command("add")
def bot_add(
    strategy_type: str = typer.Argument(
        ..., help="Tipo: grid | dca | mean | signal"
    ),
    symbol: str = typer.Argument(..., help="Par de trading (ej: BTC-USDT)"),
    config_json: str = typer.Option(
        "{}", "--config", "-c",
        help="Configuración JSON del bot. Consulta la documentación para los campos.",
    ),
):
    """
    Registra un nuevo bot con su configuración.

    Ejemplos de --config:

    Grid:
      --config '{"upper_price":"70000","lower_price":"60000","num_grids":10,"total_investment":"1000"}'

    DCA:
      --config '{"base_order_size":"100","safety_order_size":"100","price_deviation_pct":"2","take_profit_pct":"1.5","max_safety_orders":3,"safety_order_volume_scale":"1.5","interval_hours":"24"}'
    """
    from core.database import get_session, get_or_create_bot_state, init_db

    init_db()

    valid_types = ("grid", "dca", "mean", "signal")
    t = strategy_type.lower()
    if not any(t.startswith(v) for v in valid_types):
        console.print(f"[red]Tipo inválido '{strategy_type}'. Válidos: {valid_types}[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido: {exc}[/red]")
        raise typer.Exit(1)

    # Normalizar el nombre según la convención
    sym_clean = symbol.upper().replace("-", "_").lower()
    name_map = {"grid": f"grid_{sym_clean}", "dca": f"dca_{sym_clean}",
                "mean": f"mean_{sym_clean}", "signal": "signal_follower"}
    name = next(name_map[v] for v in valid_types if t.startswith(v))

    with get_session() as s:
        state = get_or_create_bot_state(s, name, symbol.upper(), config=config)
        state.set_config(config)

    console.print(
        f"[green]✓[/green] Bot [bold]{name}[/bold] registrado.\n"
        f"  Actívalo con: [bold]okx-trader bot enable {name} {symbol.upper()}[/bold]"
    )


# ---------------------------------------------------------------------------
# Comando: BACKTEST
# ---------------------------------------------------------------------------

@app.command()
def backtest(
    strategy: str = typer.Option("grid", "--strategy", "-s",
                                  help="Tipo: grid | dca | mean | signal"),
    symbol: str = typer.Option("BTC-USDT", "--symbol",
                                help="Par de trading (ej: BTC-USDT)"),
    from_date: str = typer.Option("2024-01-01", "--from", "-f",
                                   help="Fecha inicio YYYY-MM-DD"),
    to_date: str = typer.Option("2024-12-31", "--to", "-t",
                                 help="Fecha fin YYYY-MM-DD"),
    timeframe: str = typer.Option("1H", "--timeframe",
                                   help="Temporalidad OKX: 1m, 5m, 15m, 1H, 4H, 1D"),
    balance: float = typer.Option(10000.0, "--balance", "-b",
                                   help="Balance inicial simulado en USDT"),
    config_json: str = typer.Option("{}", "--config", "-c",
                                     help="Configuración JSON de la estrategia"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    Backtesting de una estrategia con datos históricos de OKX.

    Ejemplos:

      python main.py backtest --strategy grid --symbol BTC-USDT --from 2024-01-01 --to 2024-12-31

      python main.py backtest --strategy dca --symbol ETH-USDT --balance 5000 \\
        --config '{"base_order_size":"100","take_profit_pct":"1.5","price_deviation_pct":"2"}'
    """
    _setup_logging(verbose)

    from datetime import date as dt_date
    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError:
        console.print("[red]Formato de fecha inválido. Usa YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido en --config: {exc}[/red]")
        raise typer.Exit(1)

    from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
    from rich.table import Table as RichTable
    from rich.panel import Panel

    # 1 — Descargar datos históricos
    console.print(f"[bold cyan]Backtest:[/bold cyan] {strategy.upper()} / {symbol} / {timeframe}")
    console.print(f"Descargando datos {from_dt.date()} → {to_dt.date()}…")

    bars = fetch_historical_bars(symbol=symbol, bar=timeframe, from_dt=from_dt, to_dt=to_dt)
    if not bars:
        console.print("[red]No se pudieron descargar datos. Verifica conexión y parámetros.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] {len(bars)} velas descargadas.")

    # 2 — Preparar cliente y estrategia
    bt_client = BacktestClient(
        symbol=symbol,
        bars=bars,
        initial_balance=Decimal(str(balance)),
    )

    strat_type = strategy.lower()
    sym_clean = symbol.upper().replace("-", "_").lower()

    def _strategy_factory(client, session):
        if strat_type == "grid":
            from strategies.grid_bot import GridBot, GridConfig
            first_price = bars[20].close  # precio real al inicio del backtest (post-warmup)
            defaults = {
                "symbol": symbol.upper(),
                "upper_price": str((first_price * Decimal("1.1")).quantize(Decimal("0.01"))),
                "lower_price": str((first_price * Decimal("0.9")).quantize(Decimal("0.01"))),
                "num_grids": 10,
                "total_investment": str(Decimal(str(balance)) * Decimal("0.8")),
                "auto_adjust": True,
            }
            defaults.update(config)
            return GridBot(client=client, config=GridConfig.from_dict(defaults), session=session)

        elif strat_type == "dca":
            from strategies.dca_bot import DCABot, DCAConfig
            defaults = {
                "symbol": symbol.upper(),
                "base_order_size": "200",
                "safety_order_size": "200",
                "price_deviation_pct": "2.0",
                "take_profit_pct": "1.5",
                "max_safety_orders": 3,
                "safety_order_volume_scale": "1.5",
                "interval_hours": "24",
            }
            defaults.update(config)
            return DCABot(client=client, config=DCAConfig.from_dict(defaults), session=session)

        elif strat_type in ("mean", "mean_reversion"):
            from strategies.mean_reversion import MeanReversionBot, MeanReversionConfig
            defaults = {"symbol": symbol.upper()}
            defaults.update(config)
            return MeanReversionBot(client=client,
                                    config=MeanReversionConfig.from_dict(defaults),
                                    session=session)
        else:
            console.print(f"[red]Estrategia '{strategy}' no soportada en backtest.[/red]")
            raise typer.Exit(1)

    # 3 — Ejecutar simulación
    console.print("Simulando…")
    engine = BacktestEngine(bt_client=bt_client, strategy_factory=_strategy_factory)
    try:
        result = engine.run()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # 4 — Mostrar resultados
    t = RichTable(title=f"Resultados Backtest — {result.strategy_name} / {symbol}",
                  header_style="bold blue", show_lines=False)
    t.add_column("Métrica", style="dim")
    t.add_column("Valor", justify="right")
    for label, value in result.summary_rows():
        t.add_row(label, value)
    console.print(t)

    if result.total_trades == 0:
        console.print("[yellow]⚠  Sin trades generados. Revisa la configuración y el rango de fechas.[/yellow]")
    elif result.profit_factor > Decimal("1.5"):
        console.print("[green]✓ Profit Factor > 1.5 — estrategia prometedora en este período.[/green]")
    elif result.profit_factor < Decimal("1.0"):
        console.print("[red]✗ Profit Factor < 1.0 — estrategia pierde dinero en este período.[/red]")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(sys.stderr, level=level, format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(
        log_dir / "trading_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="DEBUG",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

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
    python main.py backtest --strategy mean --from 2024-01-01 --to 2024-12-31
    python main.py compare --strategies mean,adaptive --from 2018 --to 2024
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
    name = bot_state.strategy_name
    config = bot_state.get_config()
    try:
        if name.startswith("mean_"):
            from strategies.mean_reversion import MeanReversionBot, MeanReversionConfig
            return MeanReversionBot(client=client,
                                    config=MeanReversionConfig.from_dict(config),
                                    session=session, risk_manager=risk_manager)
        elif name.startswith("adaptive_"):
            from strategies.adaptive_trend import AdaptiveTrendBot, AdaptiveTrendConfig
            return AdaptiveTrendBot(client=client,
                                    config=AdaptiveTrendConfig.from_dict(config),
                                    session=session, risk_manager=risk_manager)
        elif name.startswith("signal"):
            from strategies.signal_follower import SignalFollower, SignalConfig
            return SignalFollower(client=client,
                                  config=SignalConfig(**config) if config else SignalConfig(),
                                  session=session, risk_manager=risk_manager)
        else:
            logger.warning("Tipo de estrategia desconocido: {}", name)
            return None
    except Exception as exc:
        logger.error("Error al instanciar {}: {}", name, exc)
        return None


# ---------------------------------------------------------------------------
# Helper: ejecuta un backtest y devuelve el resultado
# ---------------------------------------------------------------------------

def _run_backtest(symbol: str, timeframe: str, strat_type: str,
                  balance: float, config: dict,
                  from_dt: "datetime", to_dt: "datetime") -> "BacktestResult | None":
    """
    Descarga barras, construye cliente+estrategia y ejecuta el BacktestEngine.
    Retorna BacktestResult o None si los datos no están disponibles.
    """
    from datetime import timedelta
    from decimal import Decimal
    from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars

    WARMUP_DAYS = 240
    warmup_start = from_dt - timedelta(days=WARMUP_DAYS)
    all_bars = fetch_historical_bars(symbol=symbol, bar=timeframe,
                                     from_dt=warmup_start, to_dt=to_dt)
    if not all_bars:
        return None

    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = [b for b in all_bars if b.timestamp < from_ts]
    engine_warmup = max(len(warmup_bars), 20)

    bt_client = BacktestClient(symbol=symbol, bars=all_bars,
                                initial_balance=Decimal(str(balance)))

    def factory(client, session):
        sym = symbol.upper()
        if strat_type in ("mean", "mean_reversion"):
            from strategies.mean_reversion import MeanReversionBot, MeanReversionConfig
            cfg = {"symbol": sym}
            cfg.update(config)
            return MeanReversionBot(client=client,
                                    config=MeanReversionConfig.from_dict(cfg),
                                    session=session)
        elif strat_type in ("adaptive", "adaptive_trend", "trend"):
            from strategies.adaptive_trend import AdaptiveTrendBot, AdaptiveTrendConfig
            cfg = {"symbol": sym}
            cfg.update(config)
            return AdaptiveTrendBot(client=client,
                                    config=AdaptiveTrendConfig.from_dict(cfg),
                                    session=session)
        else:
            raise ValueError(f"Estrategia '{strat_type}' no soportada.")

    try:
        engine = BacktestEngine(bt_client=bt_client, strategy_factory=factory,
                                warmup_bars=engine_warmup)
        return engine.run()
    except Exception:
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
    strategy_type: str = typer.Argument(..., help="Tipo: mean | adaptive | signal"),
    symbol: str = typer.Argument(..., help="Par de trading (ej: BTC-USDT)"),
    config_json: str = typer.Option("{}", "--config", "-c",
                                     help="Configuración JSON del bot."),
):
    """
    Registra un nuevo bot con su configuración.

    Ejemplo:
      python main.py bot add adaptive BTC-USDT
    """
    from core.database import get_session, get_or_create_bot_state, init_db

    init_db()

    valid_types = ("mean", "adaptive", "signal")
    t = strategy_type.lower()
    if not any(t.startswith(v) for v in valid_types):
        console.print(f"[red]Tipo inválido '{strategy_type}'. Válidos: {valid_types}[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido: {exc}[/red]")
        raise typer.Exit(1)

    sym_clean = symbol.upper().replace("-", "_").lower()
    name_map = {"mean": f"mean_{sym_clean}",
                "adaptive": f"adaptive_trend_{sym_clean}",
                "signal": "signal_follower"}
    name = next(name_map[v] for v in valid_types if t.startswith(v))

    with get_session() as s:
        state = get_or_create_bot_state(s, name, symbol.upper(), config=config)
        state.set_config(config)

    console.print(
        f"[green]✓[/green] Bot [bold]{name}[/bold] registrado.\n"
        f"  Actívalo con: [bold]python main.py bot enable {name} {symbol.upper()}[/bold]"
    )


# ---------------------------------------------------------------------------
# Comando: BACKTEST
# ---------------------------------------------------------------------------

@app.command()
def backtest(
    strategy: str = typer.Option("adaptive", "--strategy", "-s",
                                  help="Tipo: mean | adaptive"),
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

    Ejemplo:
      python main.py backtest --strategy adaptive --symbol BTC-USDT --from 2024-01-01 --to 2024-12-31
    """
    _setup_logging(verbose)

    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = datetime.strptime(to_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        console.print("[red]Formato de fecha inválido. Usa YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido en --config: {exc}[/red]")
        raise typer.Exit(1)

    from rich.table import Table as RichTable

    console.print(f"[bold cyan]Backtest:[/bold cyan] {strategy.upper()} / {symbol} / {timeframe}")
    console.print(f"Descargando {from_dt.date()} → {to_dt.date()} (+ 240d calentamiento)…")

    result = _run_backtest(symbol, timeframe, strategy.lower(), balance, config, from_dt, to_dt)
    if result is None:
        console.print("[red]No se pudieron descargar datos o ejecutar el backtest.[/red]")
        raise typer.Exit(1)

    t = RichTable(title=f"Resultados Backtest — {result.strategy_name} / {symbol}",
                  header_style="bold blue", show_lines=False)
    t.add_column("Métrica", style="dim")
    t.add_column("Valor", justify="right")
    for label, value in result.summary_rows():
        t.add_row(label, value)
    console.print(t)

    if result.total_trades == 0:
        console.print("[yellow]⚠  Sin trades generados.[/yellow]")
    elif result.profit_factor > Decimal("1.5"):
        console.print("[green]✓ Profit Factor > 1.5 — estrategia prometedora.[/green]")
    elif result.profit_factor < Decimal("1.0"):
        console.print("[red]✗ Profit Factor < 1.0 — estrategia pierde dinero en este período.[/red]")


# ---------------------------------------------------------------------------
# Comando: COMPARE — corre todos los años de una vez y muestra tabla completa
# ---------------------------------------------------------------------------

# Rentabilidades históricas de benchmarks (fuente: datos reales de mercado)
_BENCHMARKS: dict[str, dict[int, float]] = {
    "S&P 500": {2018: -4.38, 2019: 31.49, 2020: 18.40, 2021: 28.71,
                2022: -18.11, 2023: 26.29, 2024: 23.31},
    "NASDAQ":  {2018: -3.88, 2019: 35.23, 2020: 43.64, 2021: 21.39,
                2022: -32.97, 2023: 43.43, 2024: 28.64},
}

_STRAT_LABELS = {
    "mean": "Mean Rev.",
    "mean_reversion": "Mean Rev.",
    "adaptive": "Adaptive Trend",
    "adaptive_trend": "Adaptive Trend",
    "trend": "Adaptive Trend",
}


@app.command()
def compare(
    strategies: str = typer.Option(
        "mean,adaptive", "--strategies", "-s",
        help="Estrategias separadas por comas: mean, adaptive",
    ),
    from_year: int = typer.Option(2018, "--from", "-f", help="Año inicio"),
    to_year: int = typer.Option(2024, "--to", "-t", help="Año fin"),
    symbol: str = typer.Option("BTC-USDT", "--symbol", help="Par de trading"),
    timeframe: str = typer.Option("1H", "--timeframe"),
    balance: float = typer.Option(10_000.0, "--balance", "-b",
                                   help="Balance inicial USDT por año"),
    cumulative: bool = typer.Option(
        False, "--cumulative", "-C",
        help="Compounding: el balance del año anterior se lleva al siguiente",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    Compara múltiples estrategias año a año en una sola ejecución.

    Ejemplos:
      python main.py compare
      python main.py compare --strategies mean,adaptive --from 2018 --to 2024
      python main.py compare --cumulative
    """
    _setup_logging(verbose)

    from datetime import timedelta
    from rich.table import Table as RichTable

    strat_list = [s.strip().lower() for s in strategies.split(",") if s.strip()]
    years = list(range(from_year, to_year + 1))

    if not strat_list:
        console.print("[red]Indica al menos una estrategia con --strategies[/red]")
        raise typer.Exit(1)

    # Silenciar logs de estrategias durante la ejecución masiva
    logger.remove()
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(log_dir / "trading_{time:YYYY-MM-DD}.log",
               rotation="00:00", retention="30 days", level="DEBUG", encoding="utf-8")
    if verbose:
        logger.add(sys.stderr, level="INFO",
                   format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

    # ── Recopilar resultados ────────────────────────────────────────────────
    # results[strat][year] = {"pnl_pct": float, "final": float, "bh_pct": float, "trades": int}
    results: dict[str, dict[int, dict]] = {s: {} for s in strat_list}
    bh_by_year: dict[int, float] = {}   # Buy & Hold BTC % por año

    current_balance: dict[str, float] = {s: balance for s in strat_list}

    total = len(years) * len(strat_list)
    done = 0

    for year in years:
        from_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        to_dt   = datetime(year, 12, 31, hour=23, minute=59, second=59, tzinfo=timezone.utc)

        for strat in strat_list:
            start_bal = current_balance[strat] if cumulative else balance
            done += 1
            console.print(
                f"  [{done}/{total}] {_STRAT_LABELS.get(strat, strat)} {year}  "
                f"(balance={start_bal:,.0f} USDT)…",
                end="\r",
            )

            res = _run_backtest(symbol, timeframe, strat, start_bal, {}, from_dt, to_dt)

            if res is None:
                results[strat][year] = {"pnl_pct": 0.0, "final": start_bal,
                                        "bh_pct": 0.0, "trades": 0}
            else:
                final = float(res.final_balance)
                pnl_pct = (final - start_bal) / start_bal * 100
                results[strat][year] = {
                    "pnl_pct": pnl_pct,
                    "final": final,
                    "bh_pct": float(res.buy_hold_pnl_pct),
                    "trades": res.total_trades,
                }
                if year not in bh_by_year:
                    bh_by_year[year] = float(res.buy_hold_pnl_pct)

            if cumulative and results[strat][year]:
                current_balance[strat] = results[strat][year]["final"]

    console.print(" " * 80, end="\r")  # limpiar línea de progreso

    # ── Helpers de formato ──────────────────────────────────────────────────
    def _pct(v: float) -> str:
        color = "green" if v > 0 else ("red" if v < 0 else "dim")
        return f"[{color}]{v:+.1f}%[/{color}]"

    def _usd(v: float) -> str:
        color = "green" if v >= balance else "red"
        return f"[{color}]${v:,.0f}[/{color}]"

    col_labels = [_STRAT_LABELS.get(s, s) for s in strat_list]

    # ── Tabla 1: % P&L anual ────────────────────────────────────────────────
    t1 = RichTable(title=f"Rentabilidad anual — {symbol} (inicio ${balance:,.0f}/año)",
                   header_style="bold blue", show_lines=True)
    t1.add_column("Año", style="bold")
    t1.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t1.add_column(lbl, justify="right")
    for bm_name in _BENCHMARKS:
        t1.add_column(bm_name, justify="right")

    for year in years:
        bh = bh_by_year.get(year, 0.0)
        row = [str(year), _pct(bh)]
        for strat in strat_list:
            row.append(_pct(results[strat][year]["pnl_pct"]))
        for bm_name, bm_data in _BENCHMARKS.items():
            row.append(_pct(bm_data.get(year, 0.0)))
        t1.add_row(*row)

    # Fila resumen: media anual
    avg_bh = sum(bh_by_year.values()) / len(bh_by_year) if bh_by_year else 0.0
    avg_row = ["Promedio", _pct(avg_bh)]
    for strat in strat_list:
        vals = [results[strat][y]["pnl_pct"] for y in years if y in results[strat]]
        avg_row.append(_pct(sum(vals) / len(vals)) if vals else "—")
    for bm_name, bm_data in _BENCHMARKS.items():
        vals = [bm_data[y] for y in years if y in bm_data]
        avg_row.append(_pct(sum(vals) / len(vals)) if vals else "—")
    t1.add_row(*avg_row)

    console.print(t1)

    # ── Tabla 2: balance final por año (inicio $balance independiente) ──────
    if not cumulative:
        t2 = RichTable(title=f"Balance final por año — inicio ${balance:,.0f} cada año",
                       header_style="bold blue", show_lines=True)
        t2.add_column("Año", style="bold")
        t2.add_column("BTC B&H", justify="right")
        for lbl in col_labels:
            t2.add_column(lbl, justify="right")
        for bm_name in _BENCHMARKS:
            t2.add_column(bm_name, justify="right")

        for year in years:
            bh = bh_by_year.get(year, 0.0)
            bh_bal = balance * (1 + bh / 100)
            row = [str(year), _usd(bh_bal)]
            for strat in strat_list:
                row.append(_usd(results[strat][year]["final"]))
            for bm_name, bm_data in _BENCHMARKS.items():
                bm_bal = balance * (1 + bm_data.get(year, 0.0) / 100)
                row.append(_usd(bm_bal))
            t2.add_row(*row)

        console.print(t2)

    # ── Tabla 3: acumulado (compounding desde año inicial) ──────────────────
    t3 = RichTable(
        title=f"Acumulado — ${balance:,.0f} invertidos en enero {from_year} (compounding)",
        header_style="bold blue", show_lines=True,
    )
    t3.add_column("Fin de año", style="bold")
    t3.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t3.add_column(lbl, justify="right")
    for bm_name in _BENCHMARKS:
        t3.add_column(bm_name, justify="right")

    acc_bh   = balance
    acc_strat: dict[str, float] = {s: balance for s in strat_list}
    acc_bm:   dict[str, float] = {bm: balance for bm in _BENCHMARKS}

    for year in years:
        bh_pct = bh_by_year.get(year, 0.0)
        acc_bh *= (1 + bh_pct / 100)

        row = [str(year), _usd(acc_bh)]
        for strat in strat_list:
            pct = results[strat][year]["pnl_pct"]
            acc_strat[strat] *= (1 + pct / 100)
            row.append(_usd(acc_strat[strat]))
        for bm_name, bm_data in _BENCHMARKS.items():
            acc_bm[bm_name] *= (1 + bm_data.get(year, 0.0) / 100)
            row.append(_usd(acc_bm[bm_name]))
        t3.add_row(*row)

    # Fila multiplicador
    mult_bh = acc_bh / balance
    mult_row = ["Multiplicador", f"[bold]{mult_bh:.2f}×[/bold]"]
    for strat in strat_list:
        mult_row.append(f"[bold]{acc_strat[strat] / balance:.2f}×[/bold]")
    for bm_name in _BENCHMARKS:
        mult_row.append(f"[bold]{acc_bm[bm_name] / balance:.2f}×[/bold]")
    t3.add_row(*mult_row)

    console.print(t3)

    # ── Tabla 4: estadísticas resumen ───────────────────────────────────────
    t4 = RichTable(title="Estadísticas resumen", header_style="bold blue", show_lines=True)
    t4.add_column("Métrica", style="dim")
    t4.add_column("BTC B&H", justify="right")
    for lbl in col_labels:
        t4.add_column(lbl, justify="right")
    for bm_name in _BENCHMARKS:
        t4.add_column(bm_name, justify="right")

    def _stat_rows():
        bh_vals = list(bh_by_year.values())
        strat_vals = {s: [results[s][y]["pnl_pct"] for y in years if y in results[s]]
                      for s in strat_list}
        bm_vals = {bm: [bm_data[y] for y in years if y in bm_data]
                   for bm, bm_data in _BENCHMARKS.items()}

        metrics = [
            ("Mejor año",   lambda v: max(v)),
            ("Peor año",    lambda v: min(v)),
            ("Años > 0%",   lambda v: f"{sum(1 for x in v if x > 0)}/{len(v)}"),
            ("Años < 0%",   lambda v: f"{sum(1 for x in v if x < 0)}/{len(v)}"),
            ("Prom. anual", lambda v: sum(v) / len(v)),
        ]
        for name, fn in metrics:
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

    _stat_rows()
    console.print(t4)


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

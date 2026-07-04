"""
Sub-comandos de gestión de bots: bot list/enable/disable/add.
"""
from __future__ import annotations

import json

import typer
from rich.table import Table

from cli.common import console


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


def bot_enable(
    name:   str = typer.Argument(...),
    symbol: str = typer.Argument(...),
):
    """Activa un bot (lo crea si no existe)."""
    from core.database import get_session, set_bot_active, init_db
    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=True)
        bot_name = state.strategy_name
    console.print(f"[green][OK][/green] Bot [bold]{bot_name}[/bold] activado.")


def bot_disable(
    name:   str = typer.Argument(...),
    symbol: str = typer.Argument(...),
):
    """Desactiva un bot."""
    from core.database import get_session, set_bot_active, init_db
    init_db()
    with get_session() as s:
        state = set_bot_active(s, name, symbol.upper(), active=False)
        bot_name = state.strategy_name
    console.print(f"[yellow]○[/yellow] Bot [bold]{bot_name}[/bold] desactivado.")


def bot_add(
    strategy_type: str = typer.Argument(..., help="Tipo: adaptive | pro_trend | scalp | range | swing"),
    symbol: str = typer.Argument(...),
    config_json: str = typer.Option("{}", "--config", "-c"),
):
    """Registra un nuevo bot con su configuración."""
    from core.database import get_session, get_or_create_bot_state, init_db
    init_db()

    from strategies.registry import get as _get_strategy, all_aliases as _all_aliases
    t = strategy_type.lower()
    try:
        meta = _get_strategy(t)
    except ValueError:
        console.print(
            f"[red]Tipo inválido '{strategy_type}'. "
            f"Válidos: {', '.join(_all_aliases())}[/red]"
        )
        raise typer.Exit(1)

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON inválido: {exc}[/red]")
        raise typer.Exit(1)

    sym_clean = symbol.upper().replace("-", "_").lower()
    name      = f"{meta.name}_{sym_clean}"

    with get_session() as s:
        state = get_or_create_bot_state(s, name, symbol.upper(), config=config)
        state.set_config(config)

    console.print(
        f"[green][OK][/green] Bot [bold]{name}[/bold] registrado.\n"
        f"  Actívalo con: [bold]python main.py bot enable {name} {symbol.upper()}[/bold]"
    )


def register(bot_app: typer.Typer) -> None:
    bot_app.command("list")(bot_list)
    bot_app.command("enable")(bot_enable)
    bot_app.command("disable")(bot_disable)
    bot_app.command("add")(bot_add)

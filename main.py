"""
OKX Trading Bot — CLI principal.

Uso:
    python main.py start                         # Arranca todos los bots activos
    python main.py stop                          # Parada de emergencia
    python main.py status                        # Estado actual del sistema
    python main.py dashboard                     # Dashboard en vivo
    python main.py trades                        # Historial de trades
    python main.py report --year 2025            # Informe fiscal IRPF
    python main.py mode                          # Muestra el modo actual
    python main.py bot list                      # Lista de bots configurados
    python main.py bot enable NAME SYMBOL        # Activa un bot
    python main.py bot disable NAME SYMBOL       # Desactiva un bot
    python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31
    python main.py compare --strategies adaptive,pro --from 2018 --to 2024
    python main.py random-backtest --strategy pro --windows 10 --months 24

Los comandos viven en cli/ (uno por dominio); este archivo solo los registra.
Estrategias nuevas se registran en strategies/registry.py — sin tocar el CLI.
"""
from __future__ import annotations

import typer

from cli import backtest_cmds, bot_cmds, compare_cmds, live_cmds, report_cmds

app = typer.Typer(
    name="okx-trader",
    help="Bot de trading automatizado para OKX.",
    add_completion=False,
    no_args_is_help=True,
)
bot_app = typer.Typer(help="Gestión de bots individuales.", no_args_is_help=True)
app.add_typer(bot_app, name="bot")

live_cmds.register(app)
report_cmds.register(app)
backtest_cmds.register(app)
compare_cmds.register(app)
bot_cmds.register(bot_app)


if __name__ == "__main__":
    app()

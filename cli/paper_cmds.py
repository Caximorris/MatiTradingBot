"""Comandos de observabilidad del paper forward-test (plan T4.1/T5.1/T6.1/T7.1/T13.1).

Todos READ-ONLY: leen DB + data/runtime + ticker publico. No tocan la logica de trading ni
pausan bots. La logica pura vive en tools/{paper_snapshot,anomaly_check,forward_report,
data_audit,decision_explain}.py; aqui solo va el render Rich y el cableado de Telegram.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

import typer
from rich.table import Table

from cli.common import console


# ---------------------------------------------------------------------------
# T4.1 — Control center: estado de todos los bots paper
# ---------------------------------------------------------------------------

def _fmt_money(v, nd: int = 0) -> str:
    return "n/a" if v is None else f"${float(v):,.{nd}f}"


def _render_status_table(snaps: list[dict], price, now: datetime) -> Table:
    t = Table(title="Paper bots — control center", header_style="bold blue", show_lines=False)
    for col in ("Bot", "Estado", "Equity", "BTC%", "bot/B&H", "Reb", "Ult. rebalanceo",
                "Prox. eval 4H"):
        t.add_column(col, justify="right" if col in ("Equity", "BTC%", "bot/B&H", "Reb") else "left")
    for s in snaps:
        if not s["is_active"]:
            estado = "[dim]PAUSADO[/dim]"
        elif s["stale"]:
            estado = f"[red]SIN TICK {s['last_run_age_min']:.0f}m[/red]"
        elif s["last_run_age_min"] is None:
            estado = "[yellow]sin tick aun[/yellow]"
        else:
            estado = f"[green]VIVO {s['last_run_age_min']:.0f}m[/green]"
        ratio = s["bnh_ratio"]
        ratio_s = "n/a" if ratio is None else f"[{'green' if ratio >= 1 else 'red'}]{ratio:.3f}[/]"
        last = s["last_rebalance"]
        last_s = (f"{last['direction']} {last['timestamp'][:16]}" if last else "—")
        t.add_row(
            f"[bold]{s['label']}[/bold]", estado,
            _fmt_money(s["equity_usd"]),
            "n/a" if s["btc_pct"] is None else f"{s['btc_pct']:.0f}%",
            ratio_s, str(s["n_rebalances"]), last_s,
            f"{s['next_eval_utc']:%H:%M} ({s['mins_to_next_eval'] // 60}h{s['mins_to_next_eval'] % 60:02d})",
        )
    return t


def _build(now: datetime):
    """Abre DB + precio y devuelve snapshots (lista de dicts, sin ORM colgante)."""
    from core.database import get_session, init_db
    from tools.paper_snapshot import build_snapshots, fetch_spot_price
    init_db()
    price = fetch_spot_price()
    with get_session() as s:
        snaps = build_snapshots(s, price=price, now=now)
    return snaps, price


def paper_status(
    watch: int = typer.Option(0, "--watch", "-w", help="Refrescar cada N segundos (0=una vez)."),
):
    """Estado en vivo de todos los bots paper (v5/v6/legacy)."""
    def once():
        now = datetime.now(timezone.utc)
        snaps, price = _build(now)
        if watch:
            console.clear()
        console.rule(f"[bold cyan]Paper forward-test[/bold cyan] "
                     f"BTC={_fmt_money(price)}  {now:%Y-%m-%d %H:%M} UTC")
        if not snaps:
            console.print("[yellow]Sin bots swing configurados "
                          "(los datos paper viven en la VM; en local esto es normal).[/yellow]")
            return
        console.print(_render_status_table(snaps, price, now))
        if price is None:
            console.print("[dim]Precio spot no disponible: metricas monetarias en n/a.[/dim]")

    if not watch:
        once()
        return
    try:
        while True:
            once()
            time.sleep(watch)
    except KeyboardInterrupt:
        console.print("\n[dim]fin.[/dim]")


# ---------------------------------------------------------------------------
# T13.1 — Chequeo de anomalias
# ---------------------------------------------------------------------------

_SEV_COLOR = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "dim"}


def _daily_check_age_min(now: datetime) -> float | None:
    """Minutos desde el ultimo bloque de data/runtime/daily_checks.log. None si no existe."""
    from tools.anomaly_check import daily_check_age_minutes
    from tools.paper_snapshot import RUNTIME
    from tools.tg_views import parse_daily_checks
    log_path = RUNTIME / "daily_checks.log"
    if not log_path.exists():
        return None
    blocks = parse_daily_checks(log_path.read_text(encoding="utf-8"))
    return daily_check_age_minutes(blocks, now)


def anomaly_check(
    telegram: bool = typer.Option(False, "--telegram", help="Enviar CRITICAL/HIGH al chat (dedup)."),
):
    """Detecta red-flags de infra/datos/estado. Solo avisa; NUNCA cambia la estrategia."""
    from tools.anomaly_check import (check_anomalies, filter_new_alerts, format_alert_line,
                                     load_state, save_state)
    now = datetime.now(timezone.utc)
    snaps, price = _build(now)
    alerts = check_anomalies(snaps, price=price, now=now,
                             daily_check_age_min=_daily_check_age_min(now))

    if not alerts:
        console.print("[green]Sin anomalias.[/green]")
    else:
        for a in alerts:
            c = _SEV_COLOR.get(a.severity, "white")
            tag = f" [{a.bot}]" if a.bot else ""
            console.print(f"[{c}]{a.severity}{tag}[/] {a.code}: {a.message}")
            console.print(f"    [dim]-> {a.action}[/dim]")

    if telegram and alerts:
        from tools.tg_send import tg_send
        crit = [a for a in alerts if a.severity in ("CRITICAL", "HIGH")]
        state = load_state()
        to_send, new_state = filter_new_alerts(crit, state, now=now)
        if to_send:
            body = "\U0001F6A8 <b>ANOMALIAS</b>\n" + "\n".join(
                f"- {format_alert_line(a)}" for a in to_send)
            if tg_send(body, parse_mode="HTML"):
                save_state(new_state)
                console.print(f"[dim]{len(to_send)} alerta(s) enviada(s) a Telegram.[/dim]")
        else:
            console.print("[dim]Nada nuevo que enviar (dedup).[/dim]")

    raise typer.Exit(1 if any(a.severity == "CRITICAL" for a in alerts) else 0)


# ---------------------------------------------------------------------------
# T6.1 — Forward-only report
# ---------------------------------------------------------------------------

def forward_report(
    as_json: bool = typer.Option(False, "--json", help="Salida JSON en vez de Markdown."),
    out: str = typer.Option("", "--out", help="Guardar en fichero (.md/.json)."),
    telegram: bool = typer.Option(False, "--telegram", help="Enviar el .md al chat."),
):
    """Reporte que SOLO usa datos posteriores al inicio del forward-test."""
    from pathlib import Path

    from core.database import get_session, init_db
    from tools.forward_report import build_forward_report, to_json, to_markdown
    from tools.paper_snapshot import fetch_spot_price
    now = datetime.now(timezone.utc)
    init_db()
    price = fetch_spot_price()
    with get_session() as s:
        report = build_forward_report(s, price=price, now=now)

    md = to_markdown(report)
    text = to_json(report) if as_json else md
    console.print(text)

    if out:
        Path(out).write_text(text, encoding="utf-8")
        console.print(f"[dim]Guardado -> {out}[/dim]")
    if telegram:
        from tools.tg_send import tg_send_document
        fname = f"forward_report_{now:%Y%m%d}.md"
        tg_send_document(fname, md.encode("utf-8"), caption="Forward-test report")
        console.print("[dim]Enviado a Telegram.[/dim]")


# ---------------------------------------------------------------------------
# T7.1 — Data audit
# ---------------------------------------------------------------------------

def data_audit(
    symbol: str = typer.Option("BTC-USDT", "--symbol"),
    bar: str = typer.Option("1H", "--bar"),
    live: bool = typer.Option(False, "--live", help="Ademas, traer velas recientes de OKX (read-only)."),
):
    """Audita integridad del cache OHLCV (huecos/dups/outliers). Nunca re-descarga el canonico."""
    from tools.data_audit import audit_cache, audit_recent_okx, format_report
    cache = audit_cache(symbol, bar)
    live_res = audit_recent_okx(symbol, bar) if live else None
    console.print(format_report(cache, live_res))
    dirty = cache.get("exists") and not cache.get("clean")
    raise typer.Exit(1 if dirty else 0)


def explain(
    bot: str = typer.Option("", "--bot", "-b",
                            help="Etiqueta del bot (v5, v6, legacy...). Vacio = cualquiera."),
    date: str = typer.Option("", "--date", "-d",
                             help="Filtra por fecha YYYY-MM-DD. Vacio = el mas reciente."),
):
    """Explica en texto plano UN rebalanceo ya ejecutado (lee swing_rebalances.jsonl)."""
    from core.database import get_session, init_db
    from tools.decision_explain import explain_rebalance, find_rebalance
    from tools.paper_bots import resolve_bot
    from tools.paper_snapshot import discover_bots, read_rebalances

    init_db()
    with get_session() as s:
        bots = discover_bots(s)
    rebalances = read_rebalances()

    strategy_name = None
    if bot:
        matched = resolve_bot(bot, bots)
        if matched is None:
            labels = ", ".join(b["label"] for b in bots) or "ninguno"
            console.print(f"[red]Bot '{bot}' no encontrado.[/red] Bots: {labels}")
            raise typer.Exit(1)
        strategy_name = matched["name"]

    entry = find_rebalance(rebalances, strategy=strategy_name, date=date or None)
    if entry is None:
        console.print("[yellow]Sin rebalanceos que coincidan con el filtro.[/yellow]")
        raise typer.Exit(1)
    console.print(explain_rebalance(entry))


def register(app: typer.Typer) -> None:
    app.command(name="paper-status")(paper_status)
    app.command(name="anomaly-check")(anomaly_check)
    app.command(name="forward-report")(forward_report)
    app.command(name="data-audit")(data_audit)
    app.command(name="explain")(explain)

"""Deteccion de anomalias / red-flags del paper forward-test (plan T13.1).

READ-ONLY: detecta y avisa, NUNCA cambia la estrategia ni pausa bots automaticamente.
Consume snapshots de tools.paper_snapshot (misma verdad que el control center) y produce una
lista de Alert ordenada por severidad. Un envoltorio CLI (cli/paper_cmds.py) las muestra y,
con --telegram, manda las criticas al chat via tools.tg_send.

Severidades alineadas con la tabla de code-review (CRITICAL/HIGH/MEDIUM/LOW).
Dedup por (code, bot) con TTL para no spamear el chat en cada tick.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from tools.paper_snapshot import RUNTIME

# Antes de esta fecha, v6 debe ser identico a v5 en vivo (sigue en bear_onset; el overlay de
# funding solo dispara en accumulation). Divergencia antes = red flag (FORWARD_TEST_CONTRACT s.7).
V6_DIVERGENCE_DATE = datetime(2026, 10, 7, tzinfo=timezone.utc)

ANOMALY_STATE = RUNTIME / "anomaly_state.json"
DEFAULT_DEDUP_TTL_MIN = 360   # 6h: misma alerta no se reenvia antes de esto (salvo cambio de msg)

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@dataclass(frozen=True)
class Alert:
    severity: str          # CRITICAL | HIGH | MEDIUM | LOW
    code: str              # slug estable, p.ej. "bot-stale-tick"
    message: str           # que pasa, legible
    action: str            # que hacer
    bot: str = ""          # etiqueta del bot afectado ("" = global)

    @property
    def key(self) -> str:
        return f"{self.code}:{self.bot}" if self.bot else self.code


def _sev_rank(a: Alert) -> int:
    return _SEVERITY_ORDER.get(a.severity, 99)


# ---------------------------------------------------------------------------
# Reglas (cada una pura: mira snapshots + contexto, devuelve 0..N alertas)
# ---------------------------------------------------------------------------

def check_anomalies(snaps: list[dict], *, price: Decimal | None,
                    now: datetime | None = None,
                    data_gaps: int | None = None) -> list[Alert]:
    """Evalua todas las reglas y devuelve alertas ordenadas por severidad (mas grave primero).

    `data_gaps`: huecos de vela detectados por el data-audit (plan T7.1); None = no evaluado.
    """
    now = now or datetime.now(timezone.utc)
    alerts: list[Alert] = []

    # --- Conectividad OKX (precio spot) ---
    if price is None:
        alerts.append(Alert(
            "HIGH", "okx-price-unavailable",
            "Ticker spot de OKX no disponible (posible 403/rate-limit/outage).",
            "Revisar conectividad OKX; el servicio reintenta. Clasificar como infra (contrato 6b).",
        ))

    # --- Huecos de datos (si el data-audit los paso) ---
    if data_gaps:
        alerts.append(Alert(
            "HIGH", "data-gaps",
            f"{data_gaps} hueco(s) de vela en la ventana reciente.",
            "Correr data-audit; si alguna decision uso un hueco, invalidar esa ventana (6b/6c).",
        ))

    # --- Reglas por bot ---
    v_last_target: dict[str, float | None] = {}
    v_n_reb: dict[str, int] = {}
    for s in snaps:
        label = s.get("label", "?")

        if s.get("is_active") and not s.get("wallet_exists"):
            alerts.append(Alert(
                "HIGH", "wallet-missing",
                f"Bot '{label}' activo pero sin fichero de cartera ({s.get('wallet_path')}).",
                "Revisar el proceso del bot: no ha escrito estado. Posible arranque fallido.",
                bot=label,
            ))

        if s.get("stale"):
            age = s.get("last_run_age_min")
            alerts.append(Alert(
                "HIGH", "bot-stale-tick",
                f"Bot '{label}' activo pero sin tick hace {age:.0f} min (>{_liveness()} min).",
                "Revisar VM/proceso matibot; probable caida. Infra (contrato 6b).",
                bot=label,
            ))
        elif s.get("is_active") and s.get("last_run_age_min") is None:
            alerts.append(Alert(
                "MEDIUM", "no-tick-yet",
                f"Bot '{label}' activo pero sin ningun tick registrado aun.",
                "Normal si acaba de arrancar; si persiste, revisar el scheduler.",
                bot=label,
            ))

        # Balances imposibles
        for ccy, amt in s.get("balances", {}).items():
            if amt < 0:
                alerts.append(Alert(
                    "CRITICAL", "negative-balance",
                    f"Bot '{label}' tiene balance negativo: {amt} {ccy}.",
                    "Estado de cartera corrupto. Parar, investigar; invalida resultados (6c).",
                    bot=label,
                ))

        # Allocation imposible (fuera de 0..100%)
        pct = s.get("btc_pct")
        if pct is not None and (pct < -0.01 or pct > 100.01):
            alerts.append(Alert(
                "CRITICAL", "impossible-allocation",
                f"Bot '{label}' con exposicion BTC imposible: {pct:.1f}%.",
                "Bug de contabilidad o precio erroneo. Investigar; posible invalidacion (6c).",
                bot=label,
            ))

        # Recolecta para el chequeo de divergencia v5/v6
        last = s.get("last_rebalance") or {}
        v_last_target[label] = last.get("btc_pct_after")
        v_n_reb[label] = s.get("n_rebalances", 0)

    # --- Divergencia v6 vs v5 antes de tiempo ---
    if now < V6_DIVERGENCE_DATE and "v5" in v_n_reb and "v6" in v_n_reb:
        diff_count = v_n_reb["v5"] != v_n_reb["v6"]
        t5, t6 = v_last_target.get("v5"), v_last_target.get("v6")
        diff_target = (t5 is not None and t6 is not None and abs(float(t5) - float(t6)) > 1e-6)
        if diff_count or diff_target:
            alerts.append(Alert(
                "HIGH", "v6-early-divergence",
                f"v6 diverge de v5 antes de {V6_DIVERGENCE_DATE.date()} "
                f"(rebalanceos v5={v_n_reb['v5']} v6={v_n_reb['v6']}, "
                f"ultimo target v5={t5} v6={t6}).",
                "No es señal: v6 deberia ser identico a v5 hasta accumulation. Investigar bug (6c).",
            ))

    return sorted(alerts, key=_sev_rank)


def _liveness() -> int:
    from tools.paper_snapshot import LIVENESS_MAX_AGE_MIN
    return LIVENESS_MAX_AGE_MIN


# ---------------------------------------------------------------------------
# Dedup persistente (evita spam en el chat)
# ---------------------------------------------------------------------------

def load_state(path: Path = ANOMALY_STATE) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path = ANOMALY_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def filter_new_alerts(alerts: list[Alert], state: dict, *, now: datetime | None = None,
                      ttl_min: int = DEFAULT_DEDUP_TTL_MIN) -> tuple[list[Alert], dict]:
    """Devuelve (alertas_a_enviar, nuevo_estado). Reenvia una alerta solo si no se envio en
    las ultimas `ttl_min`. El mensaje cuenta: si cambia el texto, se reenvia (situacion nueva)."""
    now = now or datetime.now(timezone.utc)
    new_state = dict(state)
    to_send: list[Alert] = []
    for a in alerts:
        prev = state.get(a.key)
        fresh = True
        if prev and prev.get("message") == a.message:
            try:
                last = datetime.fromisoformat(prev["ts"])
                fresh = (now - last).total_seconds() / 60 >= ttl_min
            except (KeyError, ValueError):
                fresh = True
        if fresh:
            to_send.append(a)
            new_state[a.key] = {"ts": now.isoformat(), "message": a.message,
                                "severity": a.severity}
    return to_send, new_state


def format_alert_line(a: Alert) -> str:
    tag = f" [{a.bot}]" if a.bot else ""
    return f"{a.severity}{tag} {a.code}: {a.message} -> {a.action}"

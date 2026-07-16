"""
Contexto macro para BTC/ETH/SOL/BNB: MVRV ratio y ciclo de halving.

Fuentes de datos:
- MVRV Ratio: CoinMetrics Community API (gratuito, sin autenticacion)
  Endpoint: https://community-api.coinmetrics.io/v4/timeseries/asset-metrics
  Activos soportados con MVRV: BTC, ETH. SOL/BNB: degradacion silenciosa (sin MVRV).
- Halvings: solo BTC. Para otros activos halving_phase = "unknown".

Como se usa:
    from strategies.macro_context import load_macro_context, get_macro_signal

    load_macro_context(from_dt, to_dt, symbol="BTC-USDT")  # una vez antes del backtest
    signal = get_macro_signal(current_time)                # cada barra en run()
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from loguru import logger


# ---------------------------------------------------------------------------
# Halvings historicos (fechas exactas del bloque minado)
# ---------------------------------------------------------------------------

HALVING_DATES: list[date] = [
    date(2012, 11, 28),   # bloque 210,000  — recompensa 50 -> 25 BTC
    date(2016, 7,   9),   # bloque 420,000  — recompensa 25 -> 12.5 BTC
    date(2020, 5,  11),   # bloque 630,000  — recompensa 12.5 -> 6.25 BTC
    date(2024, 4,  20),   # bloque 840,000  — recompensa 6.25 -> 3.125 BTC
    date(2028, 3,  15),   # estimado bloque 1,050,000
]

# ---------------------------------------------------------------------------
# Umbrales MVRV historicamente significativos
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Umbrales de fase de halving (dias desde el ultimo halving)
# ---------------------------------------------------------------------------
# Configurables via set_phase_bounds() — F4 del plan de auditoria 2026-07-02.
# Los defaults reproducen el comportamiento historico EXACTO (180/540/900).
# OJO: son globales de modulo — afectan a todas las estrategias del proceso.
# El 540 es el parametro mas sensible del Swing (ver AUDITORIA_SWING_V4.md, B2).

PHASE_POST_END  = 180   # fin de post_halving
PHASE_PEAK_END  = 540   # fin de bull_peak / inicio de bear_onset
PHASE_ONSET_END = 900   # fin de bear_onset / inicio de accumulation


def set_phase_bounds(post_end: int = 180, peak_end: int = 540, onset_end: int = 900) -> None:
    """Ajusta los umbrales de fase. Solo para sensitivity/ablation — no cambiar en produccion."""
    global PHASE_POST_END, PHASE_PEAK_END, PHASE_ONSET_END
    if not (0 < post_end < peak_end < onset_end):
        raise ValueError(f"Umbrales de fase invalidos: {post_end}/{peak_end}/{onset_end}")
    if (post_end, peak_end, onset_end) != (PHASE_POST_END, PHASE_PEAK_END, PHASE_ONSET_END):
        logger.warning("Umbrales de fase halving MODIFICADOS: {}/{}/{} (default 180/540/900)",
                       post_end, peak_end, onset_end)
    PHASE_POST_END, PHASE_PEAK_END, PHASE_ONSET_END = post_end, peak_end, onset_end


# CoinMetrics asset IDs para cada activo soportado
_CM_ASSETS: dict[str, str] = {
    "BTC": "btc",
    "ETH": "eth",
    "SOL": "sol",   # MVRV no garantizado en tier gratuito; degradacion silenciosa
    "BNB": "bnb",   # idem
}

MVRV_DEEP_BEAR  = 1.0   # precio cerca/bajo coste base del mercado — fondo historico
MVRV_CHEAP      = 2.0   # zona barata — probablemente acumulacion o bull temprano
MVRV_FAIR       = 3.0   # v10: revertido de 2.5 — max historico 2018-2026 fue 2.96 (Q2 2021)
MVRV_LATE_BULL  = 3.5   # bull tardio
MVRV_EUPHORIA   = 4.5   # euforia — techos historicos

# ---------------------------------------------------------------------------
# MacroContext
# ---------------------------------------------------------------------------

class MacroContext:
    """
    Cache de datos macro cargados una vez para toda la simulacion.
    Proporciona senales por fecha sin latencia.
    """

    def __init__(self, asset: str = "BTC") -> None:
        self._asset     = asset.upper()
        self._mvrv:     dict[date, float] = {}
        self._realized: dict[date, float] = {}
        self._loaded = False
        self._loaded_from: date | None = None
        self._loaded_to:   date | None = None

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------

    def load(self, from_dt: datetime, to_dt: datetime) -> None:
        """
        Descarga datos MVRV diarios de CoinMetrics para el rango dado.
        Si el rango ya esta cubierto por una carga anterior, no vuelve a descargar.
        Si falla la conexion, opera en modo neutro (sin senales MVRV).
        """
        req_from = from_dt.date() if isinstance(from_dt, datetime) else from_dt
        req_to   = to_dt.date()   if isinstance(to_dt, datetime)   else to_dt
        if (
            self._loaded
            and self._loaded_from is not None
            and self._loaded_to is not None
            and self._loaded_from <= req_from
            and self._loaded_to   >= req_to
        ):
            return   # ya tenemos los datos necesarios

        cm_asset = _CM_ASSETS.get(self._asset, "btc")
        # PriceRealizedUSD no esta disponible en el tier gratuito de CoinMetrics.
        # Se deriva matematicamente en macro_signal(): realized = price / mvrv (equivalente exacto).
        url = (
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
            f"?assets={cm_asset}&metrics=CapMVRVCur%2CPriceUSD&frequency=1d&page_size=10000"
            f"&start_time={from_dt.strftime('%Y-%m-%d')}"
            f"&end_time={to_dt.strftime('%Y-%m-%d')}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MatiTradingBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode())
            for row in raw.get("data", []):
                t = row.get("time", "")[:10]
                try:
                    d = date.fromisoformat(t)
                    if (v := row.get("CapMVRVCur")) is not None: self._mvrv[d]      = float(v)
                    if (p := row.get("PriceUSD"))   is not None: self._realized[d] = float(p)
                except (ValueError, TypeError):
                    pass
            self._loaded_from = req_from
            self._loaded_to   = req_to
            logger.info("MacroContext[{}]: {} dias MVRV cargados ({} a {})",
                        self._asset, len(self._mvrv),
                        from_dt.strftime("%Y-%m-%d"),
                        to_dt.strftime("%Y-%m-%d"))
        except urllib.error.URLError as exc:
            logger.warning("MacroContext: no se pudo conectar a CoinMetrics ({}). "
                           "Operando sin MVRV.", exc.reason)
        except Exception as exc:
            logger.warning("MacroContext: error al cargar MVRV ({}). "
                           "Operando sin MVRV.", exc)
        finally:
            self._loaded = True

    # ------------------------------------------------------------------
    # Consultas por fecha
    # ------------------------------------------------------------------

    def _lookup(self, store: dict[date, float], dt: datetime | date) -> float | None:
        """Busca un valor en un dict por fecha, retrocediendo hasta 7 dias.

        Empieza en offset=1 (dia anterior) para evitar lookahead: el dato de
        CoinMetrics para el dia X refleja el cierre de ese dia y no esta
        disponible hasta la madrugada del dia X+1.
        """
        d = dt.date() if isinstance(dt, datetime) else dt
        for offset in range(1, 8):
            candidate = d - timedelta(days=offset)
            if candidate in store:
                return store[candidate]
        return None

    def mvrv_at(self, dt: datetime | date) -> float | None:
        return self._lookup(self._mvrv, dt)

    def realized_price_at(self, dt: datetime | date) -> float | None:
        """
        Precio Realizado BTC: precio promedio al que el mercado 'compro' BTC.
        Se deriva de PriceUSD / MVRV (equivalente exacto por definicion).
        """
        mvrv = self._lookup(self._mvrv, dt)
        price = self._lookup(self._realized, dt)   # _realized almacena PriceUSD
        if mvrv and mvrv > 0 and price and price > 0:
            return price / mvrv
        return None

    def halving_phase(self, dt: datetime | date) -> tuple[int, str]:
        """
        Devuelve (dias_desde_ultimo_halving, nombre_fase).
        Solo BTC tiene halvings. Para otros activos devuelve (0, "unknown").

        Fases BTC (umbrales = PHASE_POST_END/PHASE_PEAK_END/PHASE_ONSET_END, default 180/540/900):
          post_halving:  0-180 dias   — transicion, mercado indeciso
          bull_peak:     180-540 dias — historicamente el bull market principal
          bear_onset:    540-900 dias — inicio del bear market
          accumulation:  >900 dias    — fondo/acumulacion pre-proximo halving
        """
        if self._asset != "BTC":
            return 0, "unknown"

        d = dt.date() if isinstance(dt, datetime) else dt

        last_halving = HALVING_DATES[0]
        for h in HALVING_DATES:
            if h <= d:
                last_halving = h
            else:
                break

        days = (d - last_halving).days

        if days < PHASE_POST_END:
            phase = "post_halving"
        elif days < PHASE_PEAK_END:
            phase = "bull_peak"
        elif days < PHASE_ONSET_END:
            phase = "bear_onset"
        else:
            phase = "accumulation"

        return days, phase

    def macro_signal(self, dt: datetime | date) -> dict:
        """
        Devuelve todas las senales macro para usar en la estrategia.

        Campos:
          mvrv              float | None
          mvrv_regime       str   ("deep_bear"|"recovery"|"bull"|"late_bull"|"euphoria"|"unknown")
          days_since_halving int
          halving_phase     str
          short_allowed     bool  — False en bull markets / MVRV bajo
          long_reduce_risk  bool  — True cuando MVRV sugiere techo cercano
        """
        mvrv           = self.mvrv_at(dt)
        realized_price = self.realized_price_at(dt)
        days, phase    = self.halving_phase(dt)

        if mvrv is None:
            mvrv_regime = "unknown"
        elif mvrv < MVRV_DEEP_BEAR:
            mvrv_regime = "deep_bear"
        elif mvrv < MVRV_CHEAP:
            mvrv_regime = "recovery"
        elif mvrv < MVRV_FAIR:
            mvrv_regime = "bull"
        elif mvrv < MVRV_LATE_BULL:
            mvrv_regime = "late_bull"
        else:
            mvrv_regime = "euphoria"

        # Shorts bloqueados si:
        #   - MVRV bajo (mercado barato, no apostar contra el)
        #   - Precio cerca o bajo el Realized Price (titulares en perdidas, no shortear)
        #   - Fase halving alcista historica
        short_blocked_mvrv     = mvrv is not None and mvrv < MVRV_CHEAP
        short_blocked_halving  = phase in ("post_halving", "bull_peak")
        short_allowed          = not (short_blocked_mvrv or short_blocked_halving)

        # Reducir tamano de posicion larga cuando MVRV indica zona de techo
        long_reduce_risk = mvrv_regime in ("late_bull", "euphoria")

        return {
            "mvrv":               mvrv,
            "mvrv_regime":        mvrv_regime,
            "realized_price":     realized_price,
            "days_since_halving": days,
            "halving_phase":      phase,
            "short_allowed":      short_allowed,
            "long_reduce_risk":   long_reduce_risk,
        }


# ---------------------------------------------------------------------------
# Instancias por activo — una por símbolo, inicializadas antes del backtest
# ---------------------------------------------------------------------------

_INSTANCES:    dict[str, MacroContext] = {}
_ACTIVE_ASSET: str = "BTC"
_MANIFEST_ACCESSES: list[datetime | date] = []


def load_macro_context(
    from_dt: datetime,
    to_dt:   datetime,
    symbol:  str = "BTC-USDT",
) -> None:
    """
    Carga el contexto macro para el activo indicado.
    symbol: e.g. "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"
    """
    global _INSTANCES, _ACTIVE_ASSET, _MANIFEST_ACCESSES
    _MANIFEST_ACCESSES = []

    asset = symbol.split("-")[0].upper()
    _ACTIVE_ASSET = asset

    if asset not in _INSTANCES:
        _INSTANCES[asset] = MacroContext(asset)

    _INSTANCES[asset].load(from_dt, to_dt)


def get_macro_signal(dt: datetime | date) -> dict:
    """Consulta las senales macro para la fecha dada (activo activo del ultimo load)."""
    ctx = _INSTANCES.get(_ACTIVE_ASSET)
    if ctx is None:
        ctx = MacroContext(_ACTIVE_ASSET)
        _INSTANCES[_ACTIVE_ASSET] = ctx
    _MANIFEST_ACCESSES.append(dt)
    return ctx.macro_signal(dt)

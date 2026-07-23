"""
Registro central de estrategias.

Para añadir una nueva estrategia:
  1. Crear strategies/nueva_estrategia.py con NuevaBot(BaseStrategy) y NuevaConfig(dataclass)
     que implemente from_dict() y to_dict().
  2. Añadir un bloque StrategyMeta al final de _REGISTRY.
  3. Listo. main.py no necesita cambios.

Invariantes (CLAUDE.md):
  - Config.from_dict/to_dict OBLIGATORIOS (sin ellos --config se ignora silenciosamente).
  - pi_cycle_btc_only=True si la estrategia usa Pi Cycle Top (solo disponible para BTC).
  - warmup_days debe cubrir el indicador de periodo mas largo + buffer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyMeta:
    name:              str                # nombre canónico (clave en DB, journals, logs)
    display_name:      str                # etiqueta UI
    module:            str                # ruta de importación
    bot_cls:           str                # nombre de la clase Bot en ese módulo
    config_cls:        str                # nombre de la clase Config en ese módulo
    warmup_days:       int                # días de warmup para backtest
    output:            str                # "trade" | "allocator"
    aliases:           tuple[str, ...] = field(default_factory=tuple)
    pi_cycle_btc_only: bool            = False  # deshabilitar pi_cycle en activos no-BTC

    # ------------------------------------------------------------------
    # Helpers de instanciación (importación diferida — no carga módulos al arrancar)
    # ------------------------------------------------------------------

    def load(self) -> tuple[type, type]:
        """Devuelve (BotClass, ConfigClass) importando el módulo bajo demanda."""
        import importlib
        mod = importlib.import_module(self.module)
        return getattr(mod, self.bot_cls), getattr(mod, self.config_cls)

    def make_config(self, symbol: str, overrides: dict) -> Any:
        """Construye el objeto Config con símbolo y overrides de --config."""
        _, cfg_cls = self.load()
        cfg: dict = {"symbol": symbol}
        cfg.update(overrides)
        if self.pi_cycle_btc_only and symbol.split("-")[0].upper() != "BTC":
            cfg.setdefault("pi_cycle_enabled", False)
        return cfg_cls.from_dict(cfg)

    def make_bot(self, client: Any, config_obj: Any, session: Any,
                 risk_manager: Any = None) -> Any:
        """Instancia el Bot con su config ya construida."""
        bot_cls, _ = self.load()
        return bot_cls(client=client, config=config_obj,
                       session=session, risk_manager=risk_manager)


# ---------------------------------------------------------------------------
# Catálogo de estrategias — añadir aquí para registrar una nueva
# ---------------------------------------------------------------------------

_REGISTRY: list[StrategyMeta] = [
    StrategyMeta(
        name="adaptive_trend",   display_name="Adaptive Trend",
        module="strategies.adaptive_trend",
        bot_cls="AdaptiveTrendBot", config_cls="AdaptiveTrendConfig",
        warmup_days=240, output="trade",
        aliases=("adaptive", "trend"),
    ),
    StrategyMeta(
        name="pro_trend",        display_name="Pro Trend",
        module="strategies.pro_trend",
        bot_cls="ProTrendBot",   config_cls="ProTrendConfig",
        warmup_days=625, output="trade",
        aliases=("pro",),
        pi_cycle_btc_only=True,
    ),
    StrategyMeta(
        name="scalp_momentum",   display_name="Scalp Momentum",
        module="strategies.scalp_momentum",
        bot_cls="ScalpMomentumBot", config_cls="ScalpMomentumConfig",
        warmup_days=25, output="trade",
        aliases=("scalp",),
    ),
    StrategyMeta(
        name="range_reversion",  display_name="Range Reversion",
        module="strategies.range_reversion",
        bot_cls="RangeReversionBot", config_cls="RangeReversionConfig",
        warmup_days=240, output="trade",
        aliases=("range",),
    ),
    StrategyMeta(
        name="prop_swing",       display_name="Prop Swing (HyroTrader)",
        module="strategies.prop_swing",
        bot_cls="PropSwingBot",  config_cls="PropSwingConfig",
        warmup_days=250, output="trade",
        aliases=("prop",),
    ),
    StrategyMeta(
        name="funding_extreme",  display_name="Funding Extreme Long (N4)",
        module="strategies.funding_extreme",
        bot_cls="FundingExtremeBot", config_cls="FundingExtremeConfig",
        warmup_days=45, output="trade",
        aliases=("funding",),
    ),
    StrategyMeta(
        name="mr_regime",        display_name="MR-Regimen 1H (EXP-012)",
        module="strategies.mr_regime",
        bot_cls="MrRegimeBot",   config_cls="MrRegimeConfig",
        warmup_days=240, output="trade",
        aliases=("mr",),
    ),
    StrategyMeta(
        name="basis_carry",      display_name="Basis Carry (EXP-013)",
        module="strategies.basis_carry",
        bot_cls="BasisCarryBot", config_cls="BasisCarryConfig",
        warmup_days=45, output="trade",
        aliases=("basis",),
    ),
    StrategyMeta(
        name="swing_allocator",  display_name="Swing Allocator",
        module="strategies.swing_allocator",
        bot_cls="SwingAllocatorBot", config_cls="SwingAllocatorConfig",
        warmup_days=250, output="allocator",
        aliases=("swing",),
        pi_cycle_btc_only=True,
    ),
    StrategyMeta(
        name="swing_cycle_core", display_name="Swing Cycle Core (v7 candidate)",
        module="strategies.swing_cycle_core",
        bot_cls="SwingCycleCoreBot", config_cls="SwingCycleCoreConfig",
        # The frozen causal suite includes a 250-day completed-bar warmup.
        # Keep every CLI/report path on that same evidence contract.
        warmup_days=250, output="allocator",
        aliases=("cycle_core",),
    ),
]

# Índice: nombre canónico + alias → meta
_BY_NAME: dict[str, StrategyMeta] = {}
for _m in _REGISTRY:
    _BY_NAME[_m.name] = _m
    for _a in _m.aliases:
        _BY_NAME[_a] = _m


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get(name: str) -> StrategyMeta:
    """Lookup exacto por nombre o alias. Lanza ValueError si no existe."""
    meta = _BY_NAME.get(name.lower())
    if meta is None:
        raise ValueError(
            f"Estrategia desconocida: '{name}'. "
            f"Disponibles: {sorted(_BY_NAME)}"
        )
    return meta


def resolve(bot_name: str) -> StrategyMeta | None:
    """
    Resuelve un nombre de BotState como 'swing_allocator_btc_usdt'
    buscando por prefijo + '_' (limite de palabra) y quedandose con el candidato
    mas largo. El limite de palabra evita falsos positivos como el alias corto
    'pro' (pro_trend) casando contra 'prop_swing_btc_usdt' (bug real detectado
    2026-07-11: resolvia a pro_trend en vez de prop_swing por orden de insercion).
    Devuelve None si no hay coincidencia.
    """
    key = bot_name.lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    best: tuple[int, StrategyMeta] | None = None
    for candidate, meta in _BY_NAME.items():
        if key.startswith(candidate + "_") and (best is None or len(candidate) > best[0]):
            best = (len(candidate), meta)
    return best[1] if best else None


def display(name: str) -> str:
    """Etiqueta UI para un nombre/alias. Devuelve el nombre crudo si no existe."""
    meta = _BY_NAME.get(name.lower())
    return meta.display_name if meta else name


def all_aliases() -> list[str]:
    """Todos los nombres y alias registrados, ordenados."""
    return sorted(_BY_NAME)

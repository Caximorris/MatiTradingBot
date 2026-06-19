"""
Carga y valida la configuración desde .env.
Importar `settings` en cualquier módulo para acceder a los valores.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# Busca .env en el directorio raíz del proyecto (padre de este paquete)
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(
            f"Variable de entorno obligatoria ausente o vacía: {key}\n"
            f"Copia .env.example a .env y rellena el valor."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _decimal_env(key: str, default: str) -> Decimal:
    raw = os.getenv(key, default).strip()
    try:
        return Decimal(raw)
    except Exception:
        raise EnvironmentError(
            f"Variable '{key}' debe ser un número decimal válido. Valor recibido: '{raw}'"
        )


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        raise EnvironmentError(
            f"Variable '{key}' debe ser un entero. Valor recibido: '{raw}'"
        )


# ---------------------------------------------------------------------------
# Dataclass de configuración
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    # Credenciales OKX
    okx_api_key: str
    okx_secret_key: str
    okx_passphrase: str

    # Modo de operación
    trading_mode: str          # "paper" | "live"
    okx_sandbox: bool

    # Pares activos
    trading_pairs: list[str]

    # Riesgo global
    max_portfolio_risk_pct: Decimal
    max_open_positions: int
    daily_loss_limit_pct: Decimal

    # Fiscal
    fiscal_year: int
    cost_basis_method: str     # "FIFO"

    # Señales externas
    signal_source: str         # "none" | "tradingview_webhook" | "telegram"
    webhook_port: int
    telegram_bot_token: str
    telegram_channel_id: str

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == "paper"

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"


def _validate_trading_mode(mode: str) -> str:
    mode = mode.lower()
    if mode not in ("paper", "live"):
        raise EnvironmentError(
            f"TRADING_MODE debe ser 'paper' o 'live'. Valor recibido: '{mode}'"
        )
    return mode


def _validate_signal_source(source: str) -> str:
    source = source.lower()
    valid = ("none", "tradingview_webhook", "telegram")
    if source not in valid:
        raise EnvironmentError(
            f"SIGNAL_SOURCE debe ser uno de {valid}. Valor recibido: '{source}'"
        )
    return source


def _validate_cost_method(method: str) -> str:
    method = method.upper()
    if method not in ("FIFO",):
        raise EnvironmentError(
            f"COST_BASIS_METHOD debe ser 'FIFO' (único método válido en España). "
            f"Valor recibido: '{method}'"
        )
    return method


def _parse_pairs(raw: str) -> list[str]:
    pairs = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not pairs:
        raise EnvironmentError(
            "TRADING_PAIRS no puede estar vacío. Ejemplo: BTC-USDT,ETH-USDT"
        )
    return pairs


# ---------------------------------------------------------------------------
# Validación de credenciales en modo live
# ---------------------------------------------------------------------------

def _validate_live_credentials(
    mode: str, api_key: str, secret_key: str, passphrase: str
) -> None:
    if mode == "live":
        missing = [
            name
            for name, val in [
                ("OKX_API_KEY", api_key),
                ("OKX_SECRET_KEY", secret_key),
                ("OKX_PASSPHRASE", passphrase),
            ]
            if not val
        ]
        if missing:
            raise EnvironmentError(
                f"TRADING_MODE=live requiere las siguientes variables: "
                f"{', '.join(missing)}"
            )


# ---------------------------------------------------------------------------
# Función de carga principal
# ---------------------------------------------------------------------------

def load_settings() -> Settings:
    """
    Lee el .env, valida todas las variables y retorna un objeto Settings inmutable.
    Lanza EnvironmentError con mensaje claro si falta algo crítico.
    """
    trading_mode = _validate_trading_mode(_optional("TRADING_MODE", "paper"))

    okx_api_key = _optional("OKX_API_KEY")
    okx_secret_key = _optional("OKX_SECRET_KEY")
    okx_passphrase = _optional("OKX_PASSPHRASE")

    _validate_live_credentials(trading_mode, okx_api_key, okx_secret_key, okx_passphrase)

    signal_source = _validate_signal_source(_optional("SIGNAL_SOURCE", "none"))

    return Settings(
        okx_api_key=okx_api_key,
        okx_secret_key=okx_secret_key,
        okx_passphrase=okx_passphrase,
        trading_mode=trading_mode,
        okx_sandbox=_bool_env("OKX_SANDBOX", default=True),
        trading_pairs=_parse_pairs(_optional("TRADING_PAIRS", "BTC-USDT")),
        max_portfolio_risk_pct=_decimal_env("MAX_PORTFOLIO_RISK_PCT", "2.0"),
        max_open_positions=_int_env("MAX_OPEN_POSITIONS", 10),
        daily_loss_limit_pct=_decimal_env("DAILY_LOSS_LIMIT_PCT", "5.0"),
        fiscal_year=_int_env("FISCAL_YEAR", 2025),
        cost_basis_method=_validate_cost_method(_optional("COST_BASIS_METHOD", "FIFO")),
        signal_source=signal_source,
        webhook_port=_int_env("WEBHOOK_PORT", 8080),
        telegram_bot_token=_optional("TELEGRAM_BOT_TOKEN"),
        telegram_channel_id=_optional("TELEGRAM_CHANNEL_ID"),
    )


# Instancia global — se carga una vez al importar el módulo.
# Si hay un error de configuración, falla en el arranque (fail-fast).
settings: Settings = load_settings()

"""
Modelos SQLAlchemy y gestión de sesiones para SQLite.
Todos los importes usan Decimal. Las fechas se almacenan en UTC.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Generator

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# Ruta de la base de datos en la raíz del proyecto
_DB_PATH = Path(__file__).parent.parent / "trading.db"
_DB_URL = f"sqlite:///{_DB_PATH}"


# ---------------------------------------------------------------------------
# Base declarativa
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class Trade(Base):
    """Cada operación ejecutada (compra o venta), real o paper."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)       # "buy" | "sell"
    order_type: Mapped[str] = mapped_column(String(20), nullable=False) # "market" | "limit" | "grid" | "dca"
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False, default=Decimal("0"))
    fee_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USDT")
    order_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(precision=30, scale=10), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return (
            f"Trade(id={self.id}, {self.side} {self.quantity} {self.symbol} "
            f"@ {self.price}, strategy={self.strategy})"
        )


class Position(Base):
    """Estado actual de cada posición abierta."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)  # "long" | "short"
    entry_price: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(precision=30, scale=10), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=30, scale=10), nullable=False, default=Decimal("0")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, side={self.side}, "
            f"qty={self.quantity}, upnl={self.unrealized_pnl})"
        )


class BotState(Base):
    """Configuración y estado persistente de cada bot activo."""

    __tablename__ = "bot_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=30, scale=10), nullable=False, default=Decimal("0")
    )

    def get_config(self) -> dict:
        return json.loads(self.config_json)

    def set_config(self, config: dict) -> None:
        self.config_json = json.dumps(config)

    def __repr__(self) -> str:
        return (
            f"BotState(strategy={self.strategy_name}, symbol={self.symbol}, "
            f"active={self.is_active})"
        )


# ---------------------------------------------------------------------------
# Motor y sesión
# ---------------------------------------------------------------------------

def _make_engine(db_url: str = _DB_URL):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    # Activa WAL mode para mejor concurrencia en SQLite
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


_engine = _make_engine()
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Crea todas las tablas si no existen. Seguro de llamar múltiples veces."""
    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager para obtener una sesión de DB.

    Uso:
        with get_session() as session:
            session.add(trade)
    """
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers CRUD
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_trade(session: Session, **kwargs) -> Trade:
    if "timestamp" not in kwargs:
        kwargs["timestamp"] = _utcnow()
    trade = Trade(**kwargs)
    session.add(trade)
    session.flush()
    return trade


def get_trades(
    session: Session,
    symbol: str | None = None,
    strategy: str | None = None,
    is_paper: bool | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[Trade]:
    q = session.query(Trade)
    if symbol:
        q = q.filter(Trade.symbol == symbol)
    if strategy:
        q = q.filter(Trade.strategy == strategy)
    if is_paper is not None:
        q = q.filter(Trade.is_paper == is_paper)
    if from_dt:
        q = q.filter(Trade.timestamp >= from_dt)
    if to_dt:
        q = q.filter(Trade.timestamp <= to_dt)
    return q.order_by(Trade.timestamp).all()


def upsert_position(session: Session, symbol: str, strategy: str, **kwargs) -> Position:
    pos = (
        session.query(Position)
        .filter_by(symbol=symbol, strategy=strategy)
        .first()
    )
    if pos is None:
        kwargs.setdefault("opened_at", _utcnow())
        kwargs["updated_at"] = _utcnow()
        pos = Position(symbol=symbol, strategy=strategy, **kwargs)
        session.add(pos)
    else:
        for key, value in kwargs.items():
            setattr(pos, key, value)
        pos.updated_at = _utcnow()
    session.flush()
    return pos


def close_position(session: Session, symbol: str, strategy: str) -> None:
    session.query(Position).filter_by(symbol=symbol, strategy=strategy).delete()
    session.flush()


def get_or_create_bot_state(
    session: Session, strategy_name: str, symbol: str, config: dict | None = None
) -> BotState:
    state = (
        session.query(BotState)
        .filter_by(strategy_name=strategy_name, symbol=symbol)
        .first()
    )
    if state is None:
        state = BotState(
            strategy_name=strategy_name,
            symbol=symbol,
            is_active=False,
            config_json=json.dumps(config or {}),
            created_at=_utcnow(),
        )
        session.add(state)
        session.flush()
    return state


def set_bot_active(session: Session, strategy_name: str, symbol: str, active: bool) -> BotState:
    state = get_or_create_bot_state(session, strategy_name, symbol)
    state.is_active = active
    state.last_run = _utcnow()
    session.flush()
    return state

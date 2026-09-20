from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.models import utcnow


class Airport(Base):
    __tablename__ = "airports"

    iata_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64), default="IN")


class Carrier(Base):
    __tablename__ = "carriers"

    iata_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64), default="IN")


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("origin", "destination", "active_from", name="uq_route_window"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(3), ForeignKey("airports.iata_code"), index=True)
    destination: Mapped[str] = mapped_column(String(3), ForeignKey("airports.iata_code"), index=True)
    route_class: Mapped[str] = mapped_column(String(32), default="domestic")
    weight: Mapped[float] = mapped_column(Numeric(12, 8), default=0)
    weight_source: Mapped[str] = mapped_column(String(64), default="unspecified")
    active_from: Mapped[date] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

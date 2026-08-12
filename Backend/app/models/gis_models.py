from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class EnvironmentalStation(Base):
    __tablename__ = "environmental_stations"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    external_id = Column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
    )

    name = Column(
        String(255),
        nullable=False,
    )

    city = Column(
        String(120),
        nullable=True,
        index=True,
    )

    country = Column(
        String(120),
        nullable=True,
    )

    provider = Column(
        String(50),
        nullable=False,
        index=True,
    )

    latitude = Column(
        Float,
        nullable=False,
    )

    longitude = Column(
        Float,
        nullable=False,
    )

    geom = Column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
        ),
        nullable=False,
    )

    # Scheduler refreshes only active/recent stations.
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # Last time a user requested this station.
    last_requested_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
        index=True,
    )

    # Last successful external API update.
    last_successful_update = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    measurements = relationship(
        "StationMeasurement",
        back_populates="station",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_stations_geom",
            "geom",
            postgresql_using="gist",
        ),
        Index(
            "idx_stations_activity",
            "is_active",
            "last_requested_at",
        ),
    )


class StationMeasurement(Base):
    __tablename__ = "station_measurements"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    station_id = Column(
        Integer,
        ForeignKey(
            "environmental_stations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Pollution
    pm25 = Column(Float, nullable=True)
    pm10 = Column(Float, nullable=True)
    no2 = Column(Float, nullable=True)
    co = Column(Float, nullable=True)
    o3 = Column(Float, nullable=True)

    # Weather
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)

    station = relationship(
        "EnvironmentalStation",
        back_populates="measurements",
    )

    __table_args__ = (
        Index(
            "idx_measurements_station_timestamp",
            "station_id",
            "timestamp",
        ),
    )
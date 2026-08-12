from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.gis_models import (
    EnvironmentalStation,
    StationMeasurement,
)
from app.services.ml_engine import EnvironmentalMLEngine
from app.services.pipeline_service import ProductionDataPipeline
from app.services.station_service import StationService


router = APIRouter()


# =========================================================
# GET NEAREST ENVIRONMENTAL SOURCE
# =========================================================

@router.get("/nearby")
async def get_nearest_station(
    lat: float = Query(
        ...,
        ge=-90,
        le=90,
    ),
    lon: float = Query(
        ...,
        ge=-180,
        le=180,
    ),
    db: Session = Depends(get_db),
):
    """
    Find the nearest environmental source for the user's
    geographic location.

    Workflow:
    1. Search for an existing nearby source in PostgreSQL/PostGIS.
    2. If none exists, run the external provider pipeline.
    3. Search again after ingestion.
    4. Mark the source as active.
    5. Read the latest environmental measurement.
    6. Generate a forecast immediately when PM2.5 is available.
    """

    station_service = StationService(db)

    # -----------------------------------------------------
    # STEP 1: SEARCH EXISTING SOURCE
    # -----------------------------------------------------

    station, distance_km = station_service.find_nearest_station(
        lat=lat,
        lon=lon,
    )

    source_was_created = False

    # -----------------------------------------------------
    # STEP 2: NO SOURCE FOUND -> RUN EXTERNAL PIPELINE
    # -----------------------------------------------------

    if station is None:
        pipeline = ProductionDataPipeline(db)

        success = await pipeline.run_pipeline_for_coordinate(
            lat=lat,
            lon=lon,
            city_name=None,
        )

        if not success:
            raise HTTPException(
                status_code=503,
                detail=(
                    "No nearby environmental source was found "
                    "and external providers could not provide data."
                ),
            )

        source_was_created = True

        # Search again because the pipeline should now have
        # created or updated a source in the database.
        station, distance_km = station_service.find_nearest_station(
            lat=lat,
            lon=lon,
        )

    # -----------------------------------------------------
    # STEP 3: SOURCE STILL NOT FOUND
    # -----------------------------------------------------

    if station is None:
        raise HTTPException(
            status_code=404,
            detail="No environmental monitoring source found.",
        )

    # -----------------------------------------------------
    # STEP 4: MARK SOURCE AS ACTIVE
    # -----------------------------------------------------

    now = datetime.now(timezone.utc)

    station.last_requested_at = now
    station.is_active = True

    try:
        db.commit()
        db.refresh(station)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update environmental source state.",
        )

    # -----------------------------------------------------
    # STEP 5: GET LATEST MEASUREMENT
    # -----------------------------------------------------

    latest_measurement = (
        db.query(StationMeasurement)
        .filter(
            StationMeasurement.station_id == station.id
        )
        .order_by(
            StationMeasurement.timestamp.desc()
        )
        .first()
    )

    # -----------------------------------------------------
    # STEP 6: GENERATE FORECAST
    # -----------------------------------------------------

    forecast_generated = False
    forecast_points = 0

    if (
        latest_measurement is not None
        and latest_measurement.pm25 is not None
    ):
        try:
            ml_engine = EnvironmentalMLEngine(db)

            predictions = ml_engine.generate_72h_forecast(
                station_id=station.id
            )

            forecast_points = len(predictions)

            forecast_generated = (
                forecast_points > 0
            )

        except Exception:
            # Important:
            # never leave SQLAlchemy session in a failed
            # PendingRollback state.
            db.rollback()

            forecast_generated = False
            forecast_points = 0

    # -----------------------------------------------------
    # RESPONSE
    # -----------------------------------------------------

    return {
        "source": {
            "id": station.id,
            "external_id": station.external_id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
            "provider": station.provider,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "distance_km": distance_km,
            "last_successful_update": (
                station.last_successful_update
            ),
        },

        "latest_measurement": (
            {
                "timestamp": latest_measurement.timestamp,

                "pm25": latest_measurement.pm25,
                "pm10": latest_measurement.pm10,
                "no2": latest_measurement.no2,
                "co": latest_measurement.co,
                "o3": latest_measurement.o3,

                "temperature": (
                    latest_measurement.temperature
                ),

                "humidity": (
                    latest_measurement.humidity
                ),

                "wind_speed": (
                    latest_measurement.wind_speed
                ),
            }

            if latest_measurement is not None
            else None
        ),

        "forecast": {
            "generated": forecast_generated,
            "points_created": forecast_points,
        },

        "meta": {
            "source_was_created": source_was_created,
        },
    }


# =========================================================
# LIST ACTIVE ENVIRONMENTAL SOURCES
# =========================================================

@router.get("/stations")
def get_stations(
    db: Session = Depends(get_db),
):
    """
    Return all environmental sources currently marked
    as active in AIRPredict.
    """

    stations = (
        db.query(EnvironmentalStation)
        .filter(
            EnvironmentalStation.is_active.is_(True)
        )
        .order_by(
            EnvironmentalStation.last_requested_at.desc()
        )
        .all()
    )

    return [
        {
            "id": station.id,
            "external_id": station.external_id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
            "provider": station.provider,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "last_requested_at": (
                station.last_requested_at
            ),
            "last_successful_update": (
                station.last_successful_update
            ),
        }
        for station in stations
    ]
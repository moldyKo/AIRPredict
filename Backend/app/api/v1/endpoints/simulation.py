from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.gis_models import (
    EnvironmentalStation,
    StationMeasurement,
)
from app.services.station_service import StationService


router = APIRouter()


# =========================================================
# REQUEST SCHEMAS
# =========================================================

class SimulationPayload(BaseModel):
    station_id: int

    wind_speed_modifier: float = Field(
        default=1.0,
        ge=0.2,
        le=3.0,
        description=(
            "Relative wind-speed multiplier. "
            "1.0 means current conditions."
        ),
    )

    traffic_density_modifier: float = Field(
        default=1.0,
        ge=0.0,
        le=3.0,
        description=(
            "Relative traffic level. "
            "1.0 means current conditions."
        ),
    )

    industrial_emissions_modifier: float = Field(
        default=1.0,
        ge=0.0,
        le=3.0,
        description=(
            "Relative industrial-emissions level. "
            "1.0 means current conditions."
        ),
    )


# =========================================================
# AQI HELPER
# =========================================================

def _pm25_to_aqi(
    pm25: Optional[float],
) -> Optional[float]:

    if pm25 is None:
        return None

    concentration = max(
        0.0,
        float(pm25),
    )

    breakpoints = [
        (0.0, 9.0, 0, 50),
        (9.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 125.4, 151, 200),
        (125.5, 225.4, 201, 300),
        (225.5, 325.4, 301, 500),
    ]

    for (
        concentration_low,
        concentration_high,
        aqi_low,
        aqi_high,
    ) in breakpoints:

        if (
            concentration_low
            <= concentration
            <= concentration_high
        ):
            aqi = (
                (aqi_high - aqi_low)
                / (
                    concentration_high
                    - concentration_low
                )
                * (
                    concentration
                    - concentration_low
                )
                + aqi_low
            )

            return round(
                min(aqi, 500),
                1,
            )

    return 500.0


# =========================================================
# SCENARIO SIMULATION
# =========================================================

@router.post("/simulate-aqi")
def simulate_environmental_scenario(
    payload: SimulationPayload,
    db: Session = Depends(get_db),
):
    """
    Run a simplified what-if scenario based on the
    latest observed PM2.5 value.

    This is a scenario estimator, not a trained
    atmospheric or machine-learning model.
    """

    station = (
        db.query(EnvironmentalStation)
        .filter(
            EnvironmentalStation.id
            == payload.station_id
        )
        .first()
    )

    if station is None:
        raise HTTPException(
            status_code=404,
            detail="Environmental station not found.",
        )

    latest = (
        db.query(StationMeasurement)
        .filter(
            StationMeasurement.station_id
            == payload.station_id
        )
        .order_by(
            StationMeasurement.timestamp.desc()
        )
        .first()
    )

    if latest is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No environmental measurements are "
                "available for this station."
            ),
        )

    if latest.pm25 is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "PM2.5 is unavailable, so this scenario "
                "cannot be calculated."
            ),
        )

    current_pm25 = float(
        latest.pm25
    )

    # -----------------------------------------------------
    # SIMPLE SCENARIO MODEL
    # -----------------------------------------------------
    #
    # These coefficients are intentionally conservative.
    # They represent a prototype sensitivity model,
    # not validated atmospheric physics.
    #

    traffic_change = (
        payload.traffic_density_modifier
        - 1.0
    )

    industry_change = (
        payload.industrial_emissions_modifier
        - 1.0
    )

    traffic_effect = (
        current_pm25
        * traffic_change
        * 0.15
    )

    industry_effect = (
        current_pm25
        * industry_change
        * 0.20
    )

    source_adjusted_pm25 = (
        current_pm25
        + traffic_effect
        + industry_effect
    )

    # Higher wind generally improves dispersion.
    wind_effect = (
        1.0
        / max(
            payload.wind_speed_modifier,
            0.2,
        )
    )

    # Prevent extreme scenario amplification.
    wind_effect = min(
        max(
            wind_effect,
            0.55,
        ),
        2.0,
    )

    simulated_pm25 = max(
        0.0,
        source_adjusted_pm25
        * wind_effect,
    )

    baseline_aqi = _pm25_to_aqi(
        current_pm25
    )

    simulated_aqi = _pm25_to_aqi(
        simulated_pm25
    )

    delta_aqi = None

    if (
        baseline_aqi is not None
        and simulated_aqi is not None
    ):
        delta_aqi = round(
            simulated_aqi
            - baseline_aqi,
            1,
        )

    if delta_aqi is None:
        impact_level = "unknown"

    elif delta_aqi >= 40:
        impact_level = "strong_increase"

    elif delta_aqi >= 10:
        impact_level = "moderate_increase"

    elif delta_aqi <= -40:
        impact_level = "strong_decrease"

    elif delta_aqi <= -10:
        impact_level = "moderate_decrease"

    else:
        impact_level = "small_change"

    return {
        "station": {
            "id": station.id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
        },

        "baseline": {
            "pm25": round(
                current_pm25,
                2,
            ),

            "aqi": baseline_aqi,
        },

        "scenario": {
            "wind_speed_modifier": (
                payload.wind_speed_modifier
            ),

            "traffic_density_modifier": (
                payload.traffic_density_modifier
            ),

            "industrial_emissions_modifier": (
                payload.industrial_emissions_modifier
            ),
        },

        "result": {
            "simulated_pm25": round(
                simulated_pm25,
                2,
            ),

            "simulated_aqi": (
                simulated_aqi
            ),

            "delta_aqi": (
                delta_aqi
            ),

            "impact_level": (
                impact_level
            ),
        },

        "method": "prototype_scenario_estimator",

        "disclaimer": (
            "This result is a simplified what-if estimate "
            "and is not a validated atmospheric forecast."
        ),
    }


# =========================================================
# LOCATION CONTEXT
# =========================================================

@router.get("/location-context")
def get_location_context(
    lat: float,
    lon: float,
    db: Session = Depends(get_db),
):
    """
    Find the nearest AIRPredict station and return
    a deterministic environmental context summary.
    """

    station_service = StationService(
        db
    )

    station, distance_km = (
        station_service.find_nearest_station(
            lat=lat,
            lon=lon,
        )
    )

    if station is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No nearby environmental station "
                "is currently available."
            ),
        )

    latest = (
        db.query(StationMeasurement)
        .filter(
            StationMeasurement.station_id
            == station.id
        )
        .order_by(
            StationMeasurement.timestamp.desc()
        )
        .first()
    )

    if latest is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "The nearest station has no "
                "stored measurements."
            ),
        )

    pm25 = (
        float(latest.pm25)
        if latest.pm25 is not None
        else None
    )

    aqi = _pm25_to_aqi(
        pm25
    )

    # This is rule-based context,
    # not an AI-generated explanation.

    if aqi is None:
        status = "insufficient_data"

        summary = (
            "The nearest station is available, "
            "but PM2.5 data are currently missing."
        )

    elif aqi <= 50:
        status = "good"

        summary = (
            "The latest PM2.5 measurement indicates "
            "relatively low air-pollution levels "
            "at the nearest monitoring source."
        )

    elif aqi <= 100:
        status = "moderate"

        summary = (
            "The nearest monitoring source indicates "
            "moderate air-pollution levels."
        )

    elif aqi <= 150:
        status = "elevated"

        summary = (
            "PM2.5 levels at the nearest monitoring source "
            "are elevated compared with cleaner conditions."
        )

    else:
        status = "high"

        summary = (
            "The nearest monitoring source currently shows "
            "high PM2.5 pollution levels."
        )

    return {
        "station": {
            "id": station.id,
            "name": station.name,
            "city": station.city,
            "country": station.country,

            "latitude": (
                station.latitude
            ),

            "longitude": (
                station.longitude
            ),

            "distance_km": (
                distance_km
            ),

            "provider": (
                station.provider
            ),
        },

        "measurement": {
            "timestamp": (
                latest.timestamp
            ),

            "pm25": (
                latest.pm25
            ),

            "pm10": (
                latest.pm10
            ),

            "no2": (
                latest.no2
            ),

            "co": (
                latest.co
            ),

            "o3": (
                latest.o3
            ),

            "temperature": (
                latest.temperature
            ),

            "humidity": (
                latest.humidity
            ),

            "wind_speed": (
                latest.wind_speed
            ),

            "aqi": aqi,
        },

        "context": {
            "status": status,
            "summary": summary,
        },

        "generated_by": (
            "rule_based_environmental_context"
        ),
    }
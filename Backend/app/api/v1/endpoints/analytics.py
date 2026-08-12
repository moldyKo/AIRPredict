from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.gis_models import (
    EnvironmentalStation,
    StationMeasurement,
)
from app.models.prediction_models import (
    AQIPrediction,
    ModelPerformanceLog,
)


router = APIRouter()


# =========================================================
# AQI HELPER
# =========================================================

def _pm25_to_aqi(
    pm25: Optional[float],
) -> Optional[float]:
    """
    Convert PM2.5 concentration to an approximate AQI value.
    """

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
# LATEST MEASUREMENT
# =========================================================

@router.get("/latest/{station_id}")
def get_latest_measurement(
    station_id: int,
    db: Session = Depends(get_db),
):
    """
    Return the newest stored environmental measurement
    for a selected station/source.
    """

    station = (
        db.query(EnvironmentalStation)
        .filter(
            EnvironmentalStation.id == station_id
        )
        .first()
    )

    if station is None:
        raise HTTPException(
            status_code=404,
            detail="Environmental station not found.",
        )

    measurement = (
        db.query(StationMeasurement)
        .filter(
            StationMeasurement.station_id == station_id
        )
        .order_by(
            StationMeasurement.timestamp.desc()
        )
        .first()
    )

    if measurement is None:
        raise HTTPException(
            status_code=404,
            detail="No measurements available for this station.",
        )

    return {
        "station": {
            "id": station.id,
            "external_id": station.external_id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
            "provider": station.provider,
            "latitude": station.latitude,
            "longitude": station.longitude,
        },

        "measurement": {
            "timestamp": measurement.timestamp,

            "aqi": _pm25_to_aqi(
                measurement.pm25
            ),

            "pm25": measurement.pm25,
            "pm10": measurement.pm10,
            "no2": measurement.no2,
            "co": measurement.co,
            "o3": measurement.o3,

            "temperature": measurement.temperature,
            "humidity": measurement.humidity,
            "wind_speed": measurement.wind_speed,
        },

        "last_successful_update": (
            station.last_successful_update
        ),
    }


# =========================================================
# STATION TREND
# =========================================================

@router.get("/station-trend/{station_id}")
def get_station_trend(
    station_id: int,
    hours: int = Query(
        default=24,
        ge=1,
        le=168,
    ),
    db: Session = Depends(get_db),
):
    """
    Return environmental history plus the newest forecast
    batch for a station.

    hours:
    1 - 168 hours
    """

    station = (
        db.query(EnvironmentalStation)
        .filter(
            EnvironmentalStation.id == station_id
        )
        .first()
    )

    if station is None:
        raise HTTPException(
            status_code=404,
            detail="Environmental station not found.",
        )

    now = datetime.now(timezone.utc)

    history_start = (
        now - timedelta(hours=hours)
    )

    history = (
        db.query(StationMeasurement)
        .filter(
            StationMeasurement.station_id == station_id,
            StationMeasurement.timestamp >= history_start,
        )
        .order_by(
            StationMeasurement.timestamp.asc()
        )
        .all()
    )

    actual_points = []

    for measurement in history:
        actual_points.append(
            {
                "timestamp": measurement.timestamp,

                "type": "actual",

                "aqi": _pm25_to_aqi(
                    measurement.pm25
                ),

                "pm25": measurement.pm25,
                "pm10": measurement.pm10,
                "no2": measurement.no2,
                "co": measurement.co,
                "o3": measurement.o3,

                "temperature": measurement.temperature,
                "humidity": measurement.humidity,
                "wind_speed": measurement.wind_speed,

                "ci_lower": None,
                "ci_upper": None,
                "confidence_score": None,
            }
        )

    # -----------------------------------------------------
    # Latest forecast batch
    # -----------------------------------------------------

    latest_prediction = (
        db.query(AQIPrediction)
        .filter(
            AQIPrediction.station_id == station_id
        )
        .order_by(
            AQIPrediction.generated_at.desc()
        )
        .first()
    )

    forecast_points = []

    if latest_prediction is not None:
        forecast_batch = (
            db.query(AQIPrediction)
            .filter(
                AQIPrediction.station_id == station_id,
                AQIPrediction.generated_at
                == latest_prediction.generated_at,
            )
            .order_by(
                AQIPrediction.target_time.asc()
            )
            .all()
        )

        for prediction in forecast_batch:
            forecast_points.append(
                {
                    "timestamp": prediction.target_time,

                    "type": "forecast",

                    "horizon_hours": (
                        prediction.horizon_hours
                    ),

                    "aqi": (
                        prediction.predicted_aqi
                    ),

                    "pm25": (
                        prediction.predicted_pm25
                    ),

                    "pm10": (
                        prediction.predicted_pm10
                    ),

                    "no2": (
                        prediction.predicted_no2
                    ),

                    "co": (
                        prediction.predicted_co
                    ),

                    "o3": (
                        prediction.predicted_o3
                    ),

                    "ci_lower": prediction.ci_lower,
                    "ci_upper": prediction.ci_upper,

                    "confidence_score": (
                        prediction.confidence_score
                    ),

                    "model_name": (
                        prediction.model_name
                    ),

                    "model_version": (
                        prediction.model_version
                    ),
                }
            )

    return {
        "station": {
            "id": station.id,
            "external_id": station.external_id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
            "provider": station.provider,
            "latitude": station.latitude,
            "longitude": station.longitude,
        },

        "history_hours": hours,

        "actual": actual_points,

        "forecast": forecast_points,
    }


# =========================================================
# FORECAST
# =========================================================

@router.get("/forecast/{station_id}")
def get_station_forecast(
    station_id: int,
    db: Session = Depends(get_db),
):
    """
    Return the latest complete forecast batch
    for a station.
    """

    station = (
        db.query(EnvironmentalStation)
        .filter(
            EnvironmentalStation.id == station_id
        )
        .first()
    )

    if station is None:
        raise HTTPException(
            status_code=404,
            detail="Environmental station not found.",
        )

    latest_prediction = (
        db.query(AQIPrediction)
        .filter(
            AQIPrediction.station_id == station_id
        )
        .order_by(
            AQIPrediction.generated_at.desc()
        )
        .first()
    )

    if latest_prediction is None:
        return {
            "station": {
                "id": station.id,
                "name": station.name,
                "city": station.city,
                "country": station.country,
                "provider": station.provider,
            },

            "generated_at": None,
            "model": None,
            "predictions": [],
        }

    forecasts = (
        db.query(AQIPrediction)
        .filter(
            AQIPrediction.station_id == station_id,
            AQIPrediction.generated_at
            == latest_prediction.generated_at,
        )
        .order_by(
            AQIPrediction.target_time.asc()
        )
        .all()
    )

    return {
        "station": {
            "id": station.id,
            "name": station.name,
            "city": station.city,
            "country": station.country,
            "provider": station.provider,
        },

        "generated_at": (
            latest_prediction.generated_at
        ),

        "model": {
            "name": (
                latest_prediction.model_name
            ),

            "version": (
                latest_prediction.model_version
            ),
        },

        "predictions": [
            {
                "target_time": item.target_time,

                "horizon_hours": (
                    item.horizon_hours
                ),

                "predicted_aqi": (
                    item.predicted_aqi
                ),

                "predicted_pm25": (
                    item.predicted_pm25
                ),

                "predicted_pm10": (
                    item.predicted_pm10
                ),

                "predicted_no2": (
                    item.predicted_no2
                ),

                "predicted_co": (
                    item.predicted_co
                ),

                "predicted_o3": (
                    item.predicted_o3
                ),

                "confidence_score": (
                    item.confidence_score
                ),

                "ci_lower": (
                    item.ci_lower
                ),

                "ci_upper": (
                    item.ci_upper
                ),
            }

            for item in forecasts
        ],
    }


# =========================================================
# MODEL PERFORMANCE
# =========================================================

@router.get("/model-accuracy")
def get_model_accuracy(
    db: Session = Depends(get_db),
):
    """
    Return the newest real model evaluation result.

    If AIRPredict does not yet have enough forecast/actual
    pairs, metrics remain unavailable.
    """

    metrics = (
        db.query(ModelPerformanceLog)
        .order_by(
            desc(
                ModelPerformanceLog.evaluated_at
            )
        )
        .first()
    )

    if metrics is None:
        return {
            "available": False,

            "model_name": None,
            "model_version": None,

            "horizon_hours": None,

            "mae": None,
            "rmse": None,
            "r2_score": None,

            "sample_count": 0,

            "evaluated_at": None,
        }

    return {
        "available": True,

        "model_name": metrics.model_name,

        "model_version": (
            metrics.model_version
        ),

        "horizon_hours": (
            metrics.horizon_hours
        ),

        "mae": metrics.mae,

        "rmse": metrics.rmse,

        "r2_score": (
            metrics.r2_score
        ),

        "sample_count": (
            metrics.sample_count
        ),

        "evaluated_at": (
            metrics.evaluated_at
        ),
    }
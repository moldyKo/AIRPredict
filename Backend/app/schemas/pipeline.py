from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CoordinatesRequest(BaseModel):
    """
    Geographic coordinates received from the frontend.
    """

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
    )

    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
    )


class StationResponse(BaseModel):
    """
    Monitoring station returned to the frontend.
    """

    id: int
    external_id: str

    name: str

    city: Optional[str] = None
    country: Optional[str] = None

    provider: str

    latitude: float
    longitude: float

    distance_km: Optional[float] = None

    last_successful_update: Optional[datetime] = None


class MeasurementResponse(BaseModel):
    """
    Latest environmental measurement.
    """

    timestamp: datetime

    pm25: Optional[float] = None
    pm10: Optional[float] = None
    no2: Optional[float] = None
    co: Optional[float] = None
    o3: Optional[float] = None

    temperature: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None


class NearbyEnvironmentalResponse(BaseModel):
    """
    Full response for the user's current location.
    """

    station: StationResponse

    latest_measurement: Optional[
        MeasurementResponse
    ] = None


class ForecastResponse(BaseModel):
    """
    Forecast point generated for a station.
    """

    station_id: int

    target_time: datetime
    horizon_hours: int

    predicted_aqi: Optional[float] = None

    predicted_pm25: Optional[float] = None
    predicted_pm10: Optional[float] = None
    predicted_no2: Optional[float] = None
    predicted_co: Optional[float] = None
    predicted_o3: Optional[float] = None

    confidence_score: Optional[float] = None

    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None

    model_name: str
    model_version: Optional[str] = None
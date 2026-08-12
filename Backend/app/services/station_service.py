from datetime import datetime, timezone

from geoalchemy2.functions import ST_DistanceSphere
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.gis_models import EnvironmentalStation


class StationService:
    def __init__(self, db: Session):
        self.db = db

    def find_nearest_station(
        self,
        lat: float,
        lon: float,
    ):
        """
        Find the nearest station already known to AIRPredict.

        Returns:
            (station, distance_km)
        """

        user_point = f"SRID=4326;POINT({lon} {lat})"

        distance_expression = ST_DistanceSphere(
            EnvironmentalStation.geom,
            user_point,
        )

        result = (
            self.db.query(
                EnvironmentalStation,
                distance_expression.label("distance_meters"),
            )
            .filter(EnvironmentalStation.is_active.is_(True))
            .order_by(distance_expression.asc())
            .first()
        )

        if result is None:
            return None, None

        station, distance_meters = result

        distance_km = float(distance_meters) / 1000

        if distance_km > settings.NEAREST_STATION_RADIUS_KM:
            return None, None

        station.last_requested_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(station)

        return station, round(distance_km, 2)
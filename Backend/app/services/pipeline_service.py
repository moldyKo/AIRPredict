from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Optional

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging_config import logger
from app.models.gis_models import (
    EnvironmentalStation,
    StationMeasurement,
)


class ProductionDataPipeline:
    """
    AIRPredict environmental data pipeline.

    Main workflow:
    1. Receive user latitude and longitude.
    2. Try to find environmental data near the user.
    3. Try WAQI first for a real monitoring station.
    4. Reject the WAQI station if it is too far away.
    5. Fall back to OpenWeather data for the user's coordinates.
    6. Store the environmental source and measurement in PostgreSQL.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    # =========================================================
    # MAIN PIPELINE
    # =========================================================

    async def run_pipeline_for_coordinate(
        self,
        lat: float,
        lon: float,
        city_name: Optional[str] = None,
    ) -> bool:
        location_label = city_name or f"{lat:.4f},{lon:.4f}"

        logger.info(
            f"AIRPredict pipeline started for {location_label}"
        )

        raw_data = await self._fetch_cascade(
            lat=lat,
            lon=lon,
        )

        if raw_data is None:
            logger.error(
                f"No environmental provider returned usable data "
                f"for {location_label}."
            )
            return False

        try:
            self._write_to_database(
                raw_data=raw_data,
                requested_lat=lat,
                requested_lon=lon,
                fallback_city_name=city_name,
            )

            logger.info(
                f"AIRPredict pipeline successfully completed "
                f"for {location_label}. "
                f"Provider: {raw_data['provider_name']}"
            )

            return True

        except Exception:
            self.db.rollback()

            logger.exception(
                f"Database write failed for {location_label}."
            )

            return False

    # =========================================================
    # PROVIDER CASCADE
    # =========================================================

    async def _fetch_cascade(
        self,
        lat: float,
        lon: float,
    ) -> Optional[dict[str, Any]]:
        """
        Provider priority:

        1. WAQI
           Try to find a real monitoring station.

           The station is accepted only when it is within
           NEAREST_STATION_RADIUS_KM of the user's coordinates.

        2. OpenWeather
           Used as a geographic grid/model fallback when a suitable
           physical station is not available.
        """

        timeout = httpx.Timeout(
            10.0,
            connect=5.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:

            # =================================================
            # 1. WAQI REAL STATION
            # =================================================

            if settings.WAQI_API_KEY:
                waqi_data = await self._fetch_waqi(
                    client=client,
                    lat=lat,
                    lon=lon,
                )

                if waqi_data is not None:
                    station_lat = waqi_data.get(
                        "station_latitude"
                    )

                    station_lon = waqi_data.get(
                        "station_longitude"
                    )

                    if (
                        station_lat is not None
                        and station_lon is not None
                    ):
                        distance_km = (
                            self._haversine_distance_km(
                                lat1=lat,
                                lon1=lon,
                                lat2=float(station_lat),
                                lon2=float(station_lon),
                            )
                        )

                        logger.info(
                            f"WAQI station found: "
                            f"{waqi_data.get('station_name')}. "
                            f"Distance: {distance_km:.2f} km."
                        )

                        if (
                            distance_km
                            <= settings.NEAREST_STATION_RADIUS_KM
                        ):
                            logger.info(
                                "WAQI station accepted."
                            )

                            return waqi_data

                        logger.warning(
                            f"WAQI station rejected because it is "
                            f"{distance_km:.2f} km away. "
                            f"Maximum allowed distance: "
                            f"{settings.NEAREST_STATION_RADIUS_KM:.2f} km. "
                            f"Trying OpenWeather fallback."
                        )

                    else:
                        logger.warning(
                            "WAQI returned a station without valid "
                            "coordinates. Trying OpenWeather fallback."
                        )

            else:
                logger.warning(
                    "WAQI_API_KEY is not configured."
                )

            # =================================================
            # 2. OPENWEATHER FALLBACK
            # =================================================

            if settings.OPENWEATHER_API_KEY:
                openweather_data = (
                    await self._fetch_openweather(
                        client=client,
                        lat=lat,
                        lon=lon,
                    )
                )

                if openweather_data is not None:
                    logger.info(
                        "OpenWeather fallback accepted for "
                        f"{lat:.4f},{lon:.4f}."
                    )

                    return openweather_data

            else:
                logger.warning(
                    "OPENWEATHER_API_KEY is not configured."
                )

        logger.error(
            "All environmental providers failed."
        )

        return None

    # =========================================================
    # WAQI
    # =========================================================

    async def _fetch_waqi(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
    ) -> Optional[dict[str, Any]]:
        """
        Try to locate the monitoring station returned by WAQI
        for the requested coordinates.

        Important:
        WAQI IAQI pollutant values are not blindly stored here
        as raw concentration values because they should not be
        assumed to be µg/m³ without proper unit interpretation.

        For now WAQI is primarily used for physical station
        discovery and metadata.
        """

        try:
            response = await client.get(
                f"https://api.waqi.info/feed/geo:{lat};{lon}/",
                params={
                    "token": settings.WAQI_API_KEY,
                },
            )

            response.raise_for_status()

            payload = response.json()

            if payload.get("status") != "ok":
                logger.warning(
                    "WAQI returned status: "
                    f"{payload.get('status')}"
                )

                return None

            data = payload.get("data")

            if not isinstance(data, dict):
                logger.warning(
                    "WAQI response does not contain valid data."
                )

                return None

            station_info = data.get("city") or {}

            station_geo = (
                station_info.get("geo") or []
            )

            if (
                not isinstance(station_geo, list)
                or len(station_geo) < 2
            ):
                logger.warning(
                    "WAQI station does not contain GPS coordinates."
                )

                return None

            try:
                station_lat = float(
                    station_geo[0]
                )

                station_lon = float(
                    station_geo[1]
                )

            except (TypeError, ValueError):
                logger.warning(
                    "WAQI station coordinates are invalid."
                )

                return None

            station_name = (
                station_info.get("name")
                or "WAQI Monitoring Station"
            )

            station_id = data.get("idx")

            if station_id is not None:
                external_id = (
                    f"waqi_{station_id}"
                )

            else:
                external_id = (
                    f"waqi_"
                    f"{station_lat:.5f}_"
                    f"{station_lon:.5f}"
                )

            return {
                "provider_name": "waqi",

                "external_id": external_id,

                "station_name": station_name,

                "station_latitude": station_lat,
                "station_longitude": station_lon,

                "city": None,
                "country": None,

                # These remain None until we have a provider
                # whose units are safely normalized.
                "pm25": None,
                "pm10": None,
                "no2": None,
                "co": None,
                "o3": None,

                "temperature": None,
                "humidity": None,
                "wind_speed": None,

                "provider_aqi": data.get("aqi"),

                "is_grid_source": False,
            }

        except httpx.HTTPStatusError as exc:
            logger.warning(
                f"WAQI HTTP error: "
                f"{exc.response.status_code}"
            )

            return None

        except httpx.RequestError as exc:
            logger.warning(
                f"WAQI network error: {exc}"
            )

            return None

        except Exception:
            logger.exception(
                "Unexpected WAQI provider failure."
            )

            return None

    # =========================================================
    # OPENWEATHER
    # =========================================================

    async def _fetch_openweather(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve air-pollution and weather data for the user's
        geographic coordinates.

        OpenWeather is treated as a grid/model environmental
        source rather than a physical monitoring station.
        """

        try:

            # =================================================
            # AIR POLLUTION
            # =================================================

            air_response = await client.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": settings.OPENWEATHER_API_KEY,
                },
            )

            air_response.raise_for_status()

            air_payload = air_response.json()

            air_items = (
                air_payload.get("list") or []
            )

            if not air_items:
                logger.warning(
                    "OpenWeather returned no air-pollution data."
                )

                return None

            air_item = air_items[0]

            if not isinstance(air_item, dict):
                return None

            components = (
                air_item.get("components") or {}
            )

            # =================================================
            # WEATHER
            # =================================================

            weather_response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": settings.OPENWEATHER_API_KEY,
                    "units": "metric",
                },
            )

            weather_response.raise_for_status()

            weather_payload = (
                weather_response.json()
            )

            main = (
                weather_payload.get("main") or {}
            )

            wind = (
                weather_payload.get("wind") or {}
            )

            city_name = (
                weather_payload.get("name")
                or "Unknown location"
            )

            country = (
                (weather_payload.get("sys") or {})
                .get("country")
            )

            # Round coordinates so that nearby requests do not
            # create thousands of almost-identical grid records.
            grid_lat = round(
                float(lat),
                3,
            )

            grid_lon = round(
                float(lon),
                3,
            )

            external_id = (
                f"openweather_grid_"
                f"{grid_lat}_{grid_lon}"
            )

            return {
                "provider_name": "openweather",

                "external_id": external_id,

                "station_name": (
                    f"OpenWeather Grid - {city_name}"
                ),

                "station_latitude": grid_lat,
                "station_longitude": grid_lon,

                "city": city_name,
                "country": country,

                "pm25": self._safe_float(
                    components.get("pm2_5")
                ),

                "pm10": self._safe_float(
                    components.get("pm10")
                ),

                "no2": self._safe_float(
                    components.get("no2")
                ),

                "co": self._safe_float(
                    components.get("co")
                ),

                "o3": self._safe_float(
                    components.get("o3")
                ),

                "temperature": self._safe_float(
                    main.get("temp")
                ),

                "humidity": self._safe_float(
                    main.get("humidity")
                ),

                "wind_speed": self._safe_float(
                    wind.get("speed")
                ),

                "provider_aqi": (
                    (air_item.get("main") or {})
                    .get("aqi")
                ),

                "is_grid_source": True,
            }

        except httpx.HTTPStatusError as exc:
            logger.warning(
                f"OpenWeather HTTP error: "
                f"{exc.response.status_code}"
            )

            return None

        except httpx.RequestError as exc:
            logger.warning(
                f"OpenWeather network error: {exc}"
            )

            return None

        except Exception:
            logger.exception(
                "Unexpected OpenWeather provider failure."
            )

            return None

    # =========================================================
    # DATABASE WRITE
    # =========================================================

    def _write_to_database(
        self,
        raw_data: dict[str, Any],
        requested_lat: float,
        requested_lon: float,
        fallback_city_name: Optional[str],
    ) -> None:
        """
        Create or update the environmental source and insert
        a new measurement.
        """

        external_id = raw_data.get(
            "external_id"
        )

        if not external_id:
            raise ValueError(
                "Environmental provider did not return "
                "an external_id."
            )

        provider_name = raw_data.get(
            "provider_name"
        )

        if not provider_name:
            raise ValueError(
                "Environmental provider name is missing."
            )

        station = (
            self.db.query(EnvironmentalStation)
            .filter(
                EnvironmentalStation.external_id
                == external_id
            )
            .first()
        )

        station_latitude = raw_data.get(
            "station_latitude"
        )

        station_longitude = raw_data.get(
            "station_longitude"
        )

        if station_latitude is None:
            station_latitude = requested_lat

        if station_longitude is None:
            station_longitude = requested_lon

        station_latitude = float(
            station_latitude
        )

        station_longitude = float(
            station_longitude
        )

        if not -90 <= station_latitude <= 90:
            raise ValueError(
                "Invalid station latitude."
            )

        if not -180 <= station_longitude <= 180:
            raise ValueError(
                "Invalid station longitude."
            )

        wkt_point = (
            f"POINT("
            f"{station_longitude} "
            f"{station_latitude}"
            f")"
        )

        now = datetime.now(
            timezone.utc
        )

        city = (
            raw_data.get("city")
            or fallback_city_name
        )

        # =====================================================
        # CREATE STATION/SOURCE
        # =====================================================

        if station is None:
            station = EnvironmentalStation(
                external_id=external_id,

                name=(
                    raw_data.get("station_name")
                    or "Environmental source"
                ),

                city=city,

                country=raw_data.get(
                    "country"
                ),

                provider=provider_name,

                latitude=station_latitude,
                longitude=station_longitude,

                geom=WKTElement(
                    wkt_point,
                    srid=4326,
                ),

                is_active=True,

                last_requested_at=now,

                last_successful_update=now,
            )

            self.db.add(
                station
            )

            # Required so station.id exists before measurement
            # is created.
            self.db.flush()

        # =====================================================
        # UPDATE EXISTING STATION/SOURCE
        # =====================================================

        else:
            station.name = (
                raw_data.get("station_name")
                or station.name
            )

            if city is not None:
                station.city = city

            if raw_data.get("country") is not None:
                station.country = (
                    raw_data.get("country")
                )

            station.provider = (
                provider_name
            )

            station.latitude = (
                station_latitude
            )

            station.longitude = (
                station_longitude
            )

            station.geom = WKTElement(
                wkt_point,
                srid=4326,
            )

            station.is_active = True

            station.last_requested_at = (
                now
            )

            station.last_successful_update = (
                now
            )

        # =====================================================
        # MEASUREMENT
        # =====================================================

        measurement = StationMeasurement(
            station_id=station.id,

            timestamp=now,

            pm25=self._safe_float(
                raw_data.get("pm25")
            ),

            pm10=self._safe_float(
                raw_data.get("pm10")
            ),

            no2=self._safe_float(
                raw_data.get("no2")
            ),

            co=self._safe_float(
                raw_data.get("co")
            ),

            o3=self._safe_float(
                raw_data.get("o3")
            ),

            temperature=self._safe_float(
                raw_data.get("temperature")
            ),

            humidity=self._safe_float(
                raw_data.get("humidity")
            ),

            wind_speed=self._safe_float(
                raw_data.get("wind_speed")
            ),
        )

        self.db.add(
            measurement
        )

        try:
            self.db.commit()

            self.db.refresh(
                station
            )

        except Exception:
            self.db.rollback()
            raise

    # =========================================================
    # DISTANCE
    # =========================================================

    @staticmethod
    def _haversine_distance_km(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """
        Calculate the great-circle distance between two
        GPS coordinates in kilometres.
        """

        earth_radius_km = 6371.0088

        lat1_rad = radians(
            lat1
        )

        lon1_rad = radians(
            lon1
        )

        lat2_rad = radians(
            lat2
        )

        lon2_rad = radians(
            lon2
        )

        delta_lat = (
            lat2_rad - lat1_rad
        )

        delta_lon = (
            lon2_rad - lon1_rad
        )

        a = (
            sin(delta_lat / 2) ** 2
            + cos(lat1_rad)
            * cos(lat2_rad)
            * sin(delta_lon / 2) ** 2
        )

        # Protect against tiny floating-point errors
        # that could make `a` slightly greater than 1.
        a = min(
            1.0,
            max(
                0.0,
                a,
            ),
        )

        c = 2 * atan2(
            sqrt(a),
            sqrt(1 - a),
        )

        return (
            earth_radius_km * c
        )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> Optional[float]:
        """
        Safely convert external API values to float.
        """

        if value is None:
            return None

        try:
            result = float(
                value
            )

        except (TypeError, ValueError):
            return None

        if result < 0:
            return None

        return result
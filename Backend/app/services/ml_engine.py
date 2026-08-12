from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

from app.core.logging_config import logger
from app.models.gis_models import StationMeasurement
from app.models.prediction_models import (
    AQIPrediction,
    ModelPerformanceLog,
)


class EnvironmentalMLEngine:
    """
    AIRPredict baseline forecasting engine.

    This is currently a baseline model, not LightGBM/XGBoost.
    It creates forecasts while AIRPredict collects enough
    historical data for a trained ML model.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

        self.model_name = "environmental_baseline"
        self.model_version = "1.0"

    # =========================================================
    # FORECAST GENERATION
    # =========================================================

    def generate_72h_forecast(
        self,
        station_id: int,
    ) -> list[AQIPrediction]:

        latest = (
            self.db.query(StationMeasurement)
            .filter(
                StationMeasurement.station_id
                == station_id
            )
            .order_by(
                StationMeasurement.timestamp.desc()
            )
            .first()
        )

        if latest is None:
            logger.warning(
                f"Forecast skipped: station {station_id} "
                "has no measurements."
            )
            return []

        if latest.pm25 is None:
            logger.warning(
                f"Forecast skipped: station {station_id} "
                "has no PM2.5 measurement."
            )
            return []

        history = self._get_recent_history(
            station_id=station_id,
            hours=24,
        )

        now = datetime.now(timezone.utc)

        horizons = [
            1,
            6,
            12,
            24,
            48,
            72,
        ]

        predictions: list[AQIPrediction] = []

        for horizon in horizons:

            target_time = (
                now + timedelta(hours=horizon)
            )

            predicted_pm25 = (
                self._baseline_pm25_forecast(
                    latest=latest,
                    history=history,
                    horizon_hours=horizon,
                    target_time=target_time,
                )
            )

            predicted_pm10 = self._safe_prediction_value(
                latest.pm10
            )

            predicted_no2 = self._safe_prediction_value(
                latest.no2
            )

            predicted_co = self._safe_prediction_value(
                latest.co
            )

            predicted_o3 = self._safe_prediction_value(
                latest.o3
            )

            predicted_aqi = self._pm25_to_aqi(
                predicted_pm25
            )

            confidence = self._estimate_confidence(
                history=history,
                horizon_hours=horizon,
            )

            ci_lower, ci_upper = (
                self._estimate_prediction_interval(
                    predicted_aqi=predicted_aqi,
                    confidence_score=confidence,
                    horizon_hours=horizon,
                )
            )

            prediction = AQIPrediction(
                station_id=int(station_id),

                model_name=str(
                    self.model_name
                ),

                model_version=str(
                    self.model_version
                ),

                generated_at=now,

                target_time=target_time,

                horizon_hours=int(
                    horizon
                ),

                # IMPORTANT:
                # Everything going into PostgreSQL is explicitly
                # converted to native Python float/int.
                predicted_aqi=(
                    float(predicted_aqi)
                    if predicted_aqi is not None
                    else None
                ),

                predicted_pm25=(
                    float(predicted_pm25)
                    if predicted_pm25 is not None
                    else None
                ),

                predicted_pm10=(
                    float(predicted_pm10)
                    if predicted_pm10 is not None
                    else None
                ),

                predicted_no2=(
                    float(predicted_no2)
                    if predicted_no2 is not None
                    else None
                ),

                predicted_co=(
                    float(predicted_co)
                    if predicted_co is not None
                    else None
                ),

                predicted_o3=(
                    float(predicted_o3)
                    if predicted_o3 is not None
                    else None
                ),

                confidence_score=(
                    float(confidence)
                    if confidence is not None
                    else None
                ),

                ci_lower=(
                    float(ci_lower)
                    if ci_lower is not None
                    else None
                ),

                ci_upper=(
                    float(ci_upper)
                    if ci_upper is not None
                    else None
                ),

                feature_importance={
                    "type": "baseline_explanation",
                    "recent_pm25": 0.40,
                    "recent_trend": 0.25,
                    "wind_speed": 0.15,
                    "humidity": 0.10,
                    "hour_of_day": 0.10,
                },
            )

            predictions.append(
                prediction
            )

        try:
            self.db.add_all(
                predictions
            )

            self.db.commit()

            for prediction in predictions:
                self.db.refresh(
                    prediction
                )

        except Exception:
            # CRITICAL:
            # Never leave the shared SQLAlchemy session
            # in PendingRollback state.
            self.db.rollback()

            logger.exception(
                f"Failed to save forecasts "
                f"for station {station_id}."
            )

            return []

        logger.info(
            f"Generated {len(predictions)} forecasts "
            f"for station {station_id}."
        )

        return predictions

    # =========================================================
    # PM2.5 BASELINE
    # =========================================================

    def _baseline_pm25_forecast(
        self,
        latest: StationMeasurement,
        history: list[StationMeasurement],
        horizon_hours: int,
        target_time: datetime,
    ) -> float:

        base_pm25 = float(
            latest.pm25
        )

        trend_per_hour = (
            self._calculate_pm25_trend(
                history
            )
        )

        trend_effect = (
            trend_per_hour
            * min(horizon_hours, 12)
            * 0.35
        )

        prediction = (
            base_pm25
            + trend_effect
        )

        # -----------------------------------------------------
        # WIND
        # -----------------------------------------------------

        if latest.wind_speed is not None:
            wind_speed = max(
                0.0,
                float(latest.wind_speed),
            )

            wind_factor = max(
                0.82,
                1.0
                - min(
                    wind_speed,
                    10.0,
                )
                * 0.018,
            )

            prediction *= (
                wind_factor
            )

        # -----------------------------------------------------
        # HUMIDITY
        # -----------------------------------------------------

        if latest.humidity is not None:
            humidity = float(
                latest.humidity
            )

            if humidity > 70:
                prediction *= 1.03

        # -----------------------------------------------------
        # TIME OF DAY
        # -----------------------------------------------------

        hour = target_time.hour

        if 7 <= hour <= 10:
            prediction *= 1.03

        elif 17 <= hour <= 21:
            prediction *= 1.04

        elif 1 <= hour <= 5:
            prediction *= 0.97

        return float(
            max(
                0.0,
                prediction,
            )
        )

    # =========================================================
    # HISTORY
    # =========================================================

    def _get_recent_history(
        self,
        station_id: int,
        hours: int,
    ) -> list[StationMeasurement]:

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=hours)
        )

        return (
            self.db.query(StationMeasurement)
            .filter(
                StationMeasurement.station_id
                == station_id,

                StationMeasurement.timestamp
                >= cutoff,

                StationMeasurement.pm25.isnot(
                    None
                ),
            )
            .order_by(
                StationMeasurement.timestamp.asc()
            )
            .all()
        )

    # =========================================================
    # TREND
    # =========================================================

    @staticmethod
    def _calculate_pm25_trend(
        measurements: list[StationMeasurement],
    ) -> float:

        if len(measurements) < 2:
            return 0.0

        first = measurements[0]
        last = measurements[-1]

        if (
            first.pm25 is None
            or last.pm25 is None
        ):
            return 0.0

        elapsed_hours = (
            last.timestamp
            - first.timestamp
        ).total_seconds() / 3600.0

        if elapsed_hours <= 0:
            return 0.0

        change = (
            float(last.pm25)
            - float(first.pm25)
        )

        trend = (
            change
            / elapsed_hours
        )

        # np.clip returns numpy scalar,
        # so explicitly cast back to Python float.
        return float(
            np.clip(
                trend,
                -5.0,
                5.0,
            )
        )

    # =========================================================
    # AQI
    # =========================================================

    @staticmethod
    def _pm25_to_aqi(
        pm25: Optional[float],
    ) -> Optional[float]:

        if pm25 is None:
            return None

        concentration = float(
            max(
                0.0,
                float(pm25),
            )
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
            c_low,
            c_high,
            aqi_low,
            aqi_high,
        ) in breakpoints:

            if (
                c_low
                <= concentration
                <= c_high
            ):
                result = (
                    (aqi_high - aqi_low)
                    / (c_high - c_low)
                    * (
                        concentration
                        - c_low
                    )
                    + aqi_low
                )

                return float(
                    round(
                        min(
                            result,
                            500.0,
                        ),
                        1,
                    )
                )

        return 500.0

    # =========================================================
    # CONFIDENCE
    # =========================================================

    @staticmethod
    def _estimate_confidence(
        history: list[StationMeasurement],
        horizon_hours: int,
    ) -> Optional[float]:

        values = [
            float(item.pm25)
            for item in history
            if item.pm25 is not None
        ]

        if len(values) < 4:
            return None

        mean_value = float(
            np.mean(values)
        )

        std_value = float(
            np.std(values)
        )

        if mean_value <= 0:
            return None

        variability = (
            std_value
            / mean_value
        )

        base_confidence = (
            0.90
            - variability * 0.25
        )

        horizon_penalty = (
            horizon_hours / 72.0
        ) * 0.25

        result = (
            base_confidence
            - horizon_penalty
        )

        result = float(
            np.clip(
                result,
                0.30,
                0.95,
            )
        )

        return float(
            round(
                result,
                3,
            )
        )

    # =========================================================
    # PREDICTION INTERVAL
    # =========================================================

    @staticmethod
    def _estimate_prediction_interval(
        predicted_aqi: Optional[float],
        confidence_score: Optional[float],
        horizon_hours: int,
    ) -> tuple[
        Optional[float],
        Optional[float],
    ]:

        if predicted_aqi is None:
            return None, None

        predicted_aqi = float(
            predicted_aqi
        )

        if confidence_score is None:
            margin = (
                10.0
                + horizon_hours * 0.35
            )

        else:
            uncertainty = (
                1.0
                - float(
                    confidence_score
                )
            )

            margin = (
                predicted_aqi
                * uncertainty
                + horizon_hours * 0.15
            )

        lower = float(
            max(
                0.0,
                predicted_aqi - margin,
            )
        )

        upper = float(
            min(
                500.0,
                predicted_aqi + margin,
            )
        )

        return (
            float(
                round(
                    lower,
                    1,
                )
            ),
            float(
                round(
                    upper,
                    1,
                )
            ),
        )

    # =========================================================
    # OTHER POLLUTANTS
    # =========================================================

    @staticmethod
    def _safe_prediction_value(
        value: Optional[float],
    ) -> Optional[float]:

        if value is None:
            return None

        return float(
            round(
                max(
                    0.0,
                    float(value),
                ),
                2,
            )
        )

    # =========================================================
    # MODEL EVALUATION
    # =========================================================

    def evaluate_and_log_metrics(
        self,
        horizon_hours: int = 24,
    ) -> Optional[ModelPerformanceLog]:

        now = datetime.now(
            timezone.utc
        )

        predictions = (
            self.db.query(AQIPrediction)
            .filter(
                AQIPrediction.model_name
                == self.model_name,

                AQIPrediction.horizon_hours
                == horizon_hours,

                AQIPrediction.target_time
                <= now,

                AQIPrediction.predicted_pm25
                .isnot(None),
            )
            .order_by(
                AQIPrediction.target_time.desc()
            )
            .limit(500)
            .all()
        )

        y_true: list[float] = []
        y_pred: list[float] = []

        tolerance = timedelta(
            minutes=30
        )

        for prediction in predictions:

            lower = (
                prediction.target_time
                - tolerance
            )

            upper = (
                prediction.target_time
                + tolerance
            )

            candidates = (
                self.db.query(
                    StationMeasurement
                )
                .filter(
                    StationMeasurement.station_id
                    == prediction.station_id,

                    StationMeasurement.pm25
                    .isnot(None),

                    StationMeasurement.timestamp
                    >= lower,

                    StationMeasurement.timestamp
                    <= upper,
                )
                .all()
            )

            if not candidates:
                continue

            actual = min(
                candidates,
                key=lambda item: abs(
                    (
                        item.timestamp
                        - prediction.target_time
                    ).total_seconds()
                ),
            )

            y_true.append(
                float(actual.pm25)
            )

            y_pred.append(
                float(
                    prediction.predicted_pm25
                )
            )

        if len(y_true) < 10:
            logger.info(
                f"Not enough forecast pairs for evaluation: "
                f"{len(y_true)}/10."
            )

            return None

        true_array = np.array(
            y_true,
            dtype=float,
        )

        prediction_array = np.array(
            y_pred,
            dtype=float,
        )

        mae = float(
            mean_absolute_error(
                true_array,
                prediction_array,
            )
        )

        rmse = float(
            sqrt(
                mean_squared_error(
                    true_array,
                    prediction_array,
                )
            )
        )

        r2 = float(
            r2_score(
                true_array,
                prediction_array,
            )
        )

        performance = ModelPerformanceLog(
            model_name=self.model_name,
            model_version=self.model_version,

            evaluated_at=now,

            horizon_hours=int(
                horizon_hours
            ),

            mae=float(
                round(
                    mae,
                    4,
                )
            ),

            rmse=float(
                round(
                    rmse,
                    4,
                )
            ),

            r2_score=float(
                round(
                    r2,
                    4,
                )
            ),

            sample_count=int(
                len(true_array)
            ),
        )

        try:
            self.db.add(
                performance
            )

            self.db.commit()

            self.db.refresh(
                performance
            )

        except Exception:
            self.db.rollback()

            logger.exception(
                "Could not save model performance."
            )

            return None

        return performance
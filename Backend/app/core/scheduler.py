from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import logger


scheduler = AsyncIOScheduler(timezone="UTC")


async def scheduled_environmental_ingestion():
    """
    Refresh stations that have recently been requested
    by AIRPredict users.
    """

    logger.info(
        "--- AIRPredict environmental update started ---"
    )

    db = SessionLocal()

    try:
        from app.models.gis_models import EnvironmentalStation
        from app.services.ml_engine import EnvironmentalMLEngine
        from app.services.pipeline_service import ProductionDataPipeline

        pipeline = ProductionDataPipeline(db)
        ml_engine = EnvironmentalMLEngine(db)

        active_since = (
            datetime.now(timezone.utc)
            - timedelta(hours=settings.ACTIVE_STATION_HOURS)
        )

        stations = (
            db.query(EnvironmentalStation)
            .filter(
                EnvironmentalStation.is_active.is_(True),
                EnvironmentalStation.last_requested_at >= active_since,
            )
            .all()
        )

        logger.info(
            f"Refreshing {len(stations)} active stations."
        )

        for station in stations:
            try:
                success = await pipeline.run_pipeline_for_coordinate(
                    lat=station.latitude,
                    lon=station.longitude,
                    city_name=station.city,
                )

                if not success:
                    logger.warning(
                        f"Update failed for station {station.id}."
                    )
                    continue

                station.last_successful_update = datetime.now(
                    timezone.utc
                )

                db.commit()

                try:
                    ml_engine.generate_72h_forecast(
                        station_id=station.id
                    )

                except Exception:
                    logger.exception(
                        f"Forecast generation failed "
                        f"for station {station.id}."
                    )

            except Exception:
                logger.exception(
                    f"Environmental refresh failed "
                    f"for station {station.id}."
                )

        try:
            ml_engine.evaluate_and_log_metrics(
                horizon_hours=24
            )

        except Exception:
            logger.exception(
                "ML model evaluation failed."
            )

    except Exception:
        logger.exception(
            "Critical AIRPredict scheduler failure."
        )

    finally:
        db.close()

    logger.info(
        "--- AIRPredict environmental update finished ---"
    )


def start_scheduler():
    if scheduler.running:
        logger.warning(
            "AIRPredict scheduler is already running."
        )
        return

    scheduler.add_job(
        scheduled_environmental_ingestion,
        trigger="interval",
        minutes=settings.INGESTION_INTERVAL_MINUTES,
        id="environmental_ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    scheduler.start()

    logger.info(
        "AIRPredict scheduler started. "
        f"Interval: {settings.INGESTION_INTERVAL_MINUTES} minutes."
    )
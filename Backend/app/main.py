from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import analytics, gis, simulation
from app.core.config import settings
from app.core.database import init_db
from app.core.scheduler import scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    if settings.SCHEDULER_ENABLED:
        start_scheduler()

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description=(
        "AIRPredict API for location-aware air-quality "
        "monitoring, analytics and forecasting."
    ),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    gis.router,
    prefix=f"{settings.API_V1_STR}/gis",
    tags=["GIS"],
)

app.include_router(
    analytics.router,
    prefix=f"{settings.API_V1_STR}/analytics",
    tags=["Analytics"],
)

app.include_router(
    simulation.router,
    prefix=f"{settings.API_V1_STR}/simulation",
    tags=["Simulation"],
)


@app.get("/")
def root():
    return {
        "project": settings.PROJECT_NAME,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "scheduler_enabled": settings.SCHEDULER_ENABLED,
        "scheduler_running": scheduler.running,
    }
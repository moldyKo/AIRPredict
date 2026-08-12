import logging
import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class DataIngestionService:
    def __init__(self):
        # Приоритетный список провайдеров для каскадного опроса
        self.providers = [
            self._fetch_from_openaq,
            self._fetch_from_waqi,
            self._fetch_from_openweather
        ]

    async def get_latest_metrics(self, lat: float, lon: float) -> Dict[str, Any]:
        """Пытается собрать данные из доступных источников по цепочке"""
        for provider in self.providers:
            try:
                raw_data = await provider(lat, lon)
                if raw_data:
                    return self._normalize(raw_data, provider.__name__)
            except Exception as e:
                logger.warning(f"Провайдер {provider.__name__} временно недоступен: {str(e)}. Переключение.")
                continue
        raise RuntimeError("Критическая ошибка: Все внешние экологические API недоступны.")

    async def _fetch_from_openaq(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        headers = {"X-API-Key": settings.OPENAQ_API_KEY}
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://openaq.org{lat},{lon}", 
                headers=headers, timeout=5.0
            )
            return response.json() if response.status_code == 200 else None

    async def _fetch_from_waqi(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://waqi.info:{lat};{lon}/?token={settings.WAQI_API_KEY}", 
                timeout=5.0
            )
            return response.json() if response.status_code == 200 else None

    async def _fetch_from_openweather(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://openweathermap.org{lat}&lon={lon}&appid={settings.OPENWEATHER_API_KEY}", 
                timeout=5.0
            )
            return response.json() if response.status_code == 200 else None

    def _normalize(self, data: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Приводит разноформатные ответы API к единой структуре платформы"""
        normalized = {"pm25": 0.0, "pm10": 0.0, "no2": 0.0, "co": 0.0, "o3": 0.0}
        if source == "_fetch_from_waqi":
            iaqi = data.get("data", {}).get("iaqi", {})
            normalized["pm25"] = float(iaqi.get("pm25", {}).get("v", 0))
            normalized["pm10"] = float(iaqi.get("pm10", {}).get("v", 0))
        # Сюда добавляются аналогичные парсеры для других API при их активации
        return normalized

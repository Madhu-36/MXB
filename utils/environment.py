import time
import requests
from utils.logger import log

class EnvironmentContext:
    """
    Cached environmental context (Location & Weather) for MXB.
    Caches network API responses for 15 minutes to eliminate latency on voice commands.
    """
    _cached_context = None
    _last_fetch_time = 0.0
    _CACHE_TTL = 900.0  # 15 minutes

    @classmethod
    def get_weather_and_location(cls) -> str:
        now = time.time()
        if cls._cached_context and (now - cls._last_fetch_time) < cls._CACHE_TTL:
            return cls._cached_context

        try:
            # 1. Fast IP-based geolocation
            loc_res = requests.get("https://ipapi.co/json/", timeout=2)
            if loc_res.status_code == 200:
                loc_data = loc_res.json()
                lat, lon = loc_data.get("latitude"), loc_data.get("longitude")
                city = loc_data.get("city", "Local Area")

                # 2. Weather forecast from Open-Meteo
                if lat and lon:
                    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                    w_res = requests.get(weather_url, timeout=2)
                    if w_res.status_code == 200:
                        w_data = w_res.json().get("current_weather", {})
                        temp = w_data.get("temperature", "Unknown")
                        cls._cached_context = f"Location: {city}. Current Temperature: {temp}°C."
                        cls._last_fetch_time = now
                        log.info(f"Environment: Updated context: {cls._cached_context}")
                        return cls._cached_context

            cls._cached_context = "Location/Weather data unavailable."
            cls._last_fetch_time = now
            return cls._cached_context
        except Exception as e:
            log.warning(f"Environment: Could not refresh context: {e}")
            if cls._cached_context:
                return cls._cached_context
            return "Location/Weather data unavailable."

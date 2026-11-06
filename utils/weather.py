import re
import requests
from utils.logger import log

class WeatherProbe:
    """
    Live Weather & Meteorological Intelligence Probe for MXB.
    Fetches real-time temperature, atmospheric conditions, and humidity
    for any city worldwide without requiring proprietary API keys.
    """

    WEATHER_PATTERNS = [
        re.compile(r'(?:weather|temperature|forecast)\s+(?:in|for|at)\s+([a-zA-Z\s\-]+)', re.IGNORECASE),
        re.compile(r'how\s+is\s+the\s+weather\s+in\s+([a-zA-Z\s\-]+)', re.IGNORECASE),
        re.compile(r'what(?:\'s|\s+is)\s+the\s+weather\s+like\s+in\s+([a-zA-Z\s\-]+)', re.IGNORECASE),
        re.compile(r'what(?:\'s|\s+is)\s+the\s+temperature\s+in\s+([a-zA-Z\s\-]+)', re.IGNORECASE),
    ]

    @classmethod
    def extract_city(cls, text: str) -> str | None:
        """Extracts target city name from conversational user query."""
        clean = text.strip().rstrip('?').strip()
        for pat in cls.WEATHER_PATTERNS:
            match = pat.search(clean)
            if match:
                city = match.group(1).strip()
                if city and len(city) >= 2 and city.lower() not in ["here", "today", "now", "outside"]:
                    return city
        return None

    @classmethod
    def get_weather(cls, city: str = "") -> dict:
        """
        Retrieves real-time meteorological conditions for specified city or local IP.
        """
        clean_city = city.strip().replace(" ", "+") if city else ""
        url = f"https://wttr.in/{clean_city}?format=j1" if clean_city else "https://wttr.in/?format=j1"

        try:
            resp = requests.get(url, timeout=3.5, headers={"User-Agent": "MXB-Assistant/2.3"})
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current_condition", [{}])[0]
                area = data.get("nearest_area", [{}])[0]

                resolved_city = city or area.get("areaName", [{}])[0].get("value", "Your location")
                temp_c = int(current.get("temp_C", 0))
                temp_f = int(current.get("temp_F", 32))
                desc = current.get("weatherDesc", [{}])[0].get("value", "Clear")
                humidity = int(current.get("humidity", 0))
                feels_c = int(current.get("FeelsLikeC", temp_c))

                summary = (
                    f"The weather in {resolved_city} is {temp_c}°C ({temp_f}°F), {desc}, "
                    f"with {humidity}% humidity (feels like {feels_c}°C)."
                )

                log.info(f"WeatherProbe: {resolved_city} -> {temp_c}°C, {desc}")
                return {
                    "success": True,
                    "city": resolved_city,
                    "temp_c": temp_c,
                    "temp_f": temp_f,
                    "condition": desc,
                    "humidity": humidity,
                    "feels_like_c": feels_c,
                    "summary": summary
                }
            else:
                return {
                    "success": False,
                    "city": city or "Unknown",
                    "summary": f"Could not retrieve weather (HTTP {resp.status_code})."
                }
        except Exception as e:
            log.warning(f"WeatherProbe: Query failed for '{city}': {e}")
            return {
                "success": False,
                "city": city or "Unknown",
                "summary": "Weather service is currently unreachable or offline."
            }

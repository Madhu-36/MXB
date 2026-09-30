import requests

class EnvironmentContext:
    @staticmethod
    def get_weather_and_location() -> str:
        try:
            # 1. Get Location from IP
            loc_res = requests.get("https://ipapi.co/json/", timeout=3)
            if loc_res.status_code == 200:
                loc_data = loc_res.json()
                lat, lon = loc_data.get('latitude'), loc_data.get('longitude')
                city = loc_data.get('city', 'Unknown City')
                
                # 2. Get Weather from Open-Meteo
                if lat and lon:
                    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                    w_res = requests.get(weather_url, timeout=3)
                    if w_res.status_code == 200:
                        w_data = w_res.json().get('current_weather', {})
                        temp = w_data.get('temperature', 'Unknown')
                        return f"Location: {city}. Current Temperature: {temp}°C."
            return "Location/Weather data unavailable."
        except Exception:
            return "Location/Weather data unavailable."

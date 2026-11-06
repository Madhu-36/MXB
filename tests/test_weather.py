import unittest
from unittest.mock import patch, MagicMock
from utils.weather import WeatherProbe

class TestWeatherProbe(unittest.TestCase):

    def test_city_extraction_patterns(self):
        self.assertEqual(WeatherProbe.extract_city("what is the weather in Seattle?"), "Seattle")
        self.assertEqual(WeatherProbe.extract_city("what's the temperature in Tokyo"), "Tokyo")
        self.assertEqual(WeatherProbe.extract_city("how is the weather in San Francisco"), "San Francisco")
        self.assertEqual(WeatherProbe.extract_city("weather in London"), "London")
        self.assertIsNone(WeatherProbe.extract_city("open google chrome"))
        self.assertIsNone(WeatherProbe.extract_city("check system"))

    @patch("requests.get")
    def test_get_weather_mocked_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current_condition": [{
                "temp_C": "22",
                "temp_F": "72",
                "weatherDesc": [{"value": "Partly Cloudy"}],
                "humidity": "65",
                "FeelsLikeC": "23"
            }],
            "nearest_area": [{
                "areaName": [{"value": "London"}]
            }]
        }
        mock_get.return_value = mock_resp

        res = WeatherProbe.get_weather("London")
        self.assertTrue(res["success"])
        self.assertEqual(res["city"], "London")
        self.assertEqual(res["temp_c"], 22)
        self.assertEqual(res["temp_f"], 72)
        self.assertEqual(res["condition"], "Partly Cloudy")
        self.assertIn("22°C (72°F)", res["summary"])

    @patch("requests.get", side_effect=Exception("Network down"))
    def test_get_weather_network_fallback(self, mock_get):
        res = WeatherProbe.get_weather("Paris")
        self.assertFalse(res["success"])
        self.assertIn("unreachable or offline", res["summary"])

if __name__ == "__main__":
    unittest.main()

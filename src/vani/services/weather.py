"""
vani_weather.py — Fixed
Bug: get_current_city was async but called without await inside @tool
Fix: made get_current_city synchronous (requests is already blocking, no need for async)
"""

import os
import requests
import logging
from dotenv import load_dotenv
from langchain_core.tools import tool

from vani.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_current_city() -> str:
    """Synchronous city detection via IP — no async needed."""
    try:
        data = requests.get("https://ipinfo.io/json", timeout=5).json()
        return data.get("city", "Unknown")
    except Exception:
        return "Unknown"


@tool
async def get_weather(city: str = "") -> str:
    """
    Current weather batata hai kisi bhi city ka.
    City na do toh apne aap detect kar leta hai.

    Example prompts:
    - "Aaj ka mausam kaisa hai?"
    - "Mumbai ka weather batao"
    - "Kya barish hogi Delhi mein?"
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")

    if not api_key:
        return "❌ OPENWEATHER_API_KEY .env mein nahi hai."

    if not city:
        city = get_current_city()   # ← sync call, no await needed

    logger.info(f"Weather fetch ho raha hai city ke liye: {city}")

    try:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key, "units": "metric"},
            timeout=10
        )
        if response.status_code != 200:
            logger.error(f"OpenWeather error: {response.status_code}")
            return f"❌ {city} ka weather nahi mila. City name check karo."

        data        = response.json()
        weather     = data["weather"][0]["description"].title()
        temperature = data["main"]["temp"]
        humidity    = data["main"]["humidity"]
        wind_speed  = data["wind"]["speed"]

        return (
            f"Weather in {city}:\n"
            f"- Condition: {weather}\n"
            f"- Temperature: {temperature}°C\n"
            f"- Humidity: {humidity}%\n"
            f"- Wind Speed: {wind_speed} m/s"
        )

    except Exception as e:
        logger.exception(f"Weather fetch mein exception: {e}")
        return "❌ Weather fetch karte waqt error aaya."

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

from vani.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

CITY_TTL = 3600
WEATHER_TTL = 600
MEMORY_TTL = 300

class ContextCache:
    def __init__(self):
        self._city = None
        self._city_ts = 0
        
        self._weather = None
        self._weather_ts = 0
        
        self._memory = None
        self._memory_ts = 0
        self._cache_file = PROJECT_ROOT / "conversations" / "context_cache_state.json"
        self._load_from_disk()

    def _load_from_disk(self):
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._city = data.get("city")
                self._city_ts = data.get("city_ts", 0)
                self._weather = data.get("weather")
                self._weather_ts = data.get("weather_ts", 0)
            except Exception:
                pass

    def _save_to_disk(self):
        try:
            self._cache_file.parent.mkdir(exist_ok=True)
            tmp = str(self._cache_file) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "city": self._city,
                    "city_ts": self._city_ts,
                    "weather": self._weather,
                    "weather_ts": self._weather_ts
                }, f)
            import os as _os
            _os.replace(tmp, self._cache_file)
        except Exception:
            pass

    def get_city(self):
        now = time.time()
        if not self._city or (now - self._city_ts) > CITY_TTL:
            if not getattr(self, "_city_fetching", False):
                self._city_fetching = True
                def _fetch():
                    try:
                        from vani.services.weather import get_current_city
                        self._city = get_current_city()
                        self._city_ts = time.time()
                        self._save_to_disk()
                    except Exception:
                        self._city = self._city or "Unknown City"
                    finally:
                        self._city_fetching = False
                import threading
                threading.Thread(target=_fetch, daemon=True).start()
        return self._city or "Unknown City"

    def get_weather(self, city=None):
        now = time.time()
        target_city = city or self.get_city()
        if not self._weather or (now - self._weather_ts) > WEATHER_TTL:
            if not getattr(self, "_weather_fetching", False):
                self._weather_fetching = True
                def _fetch():
                    api_key = os.getenv("OPENWEATHER_API_KEY", "")
                    if not api_key:
                        self._weather_fetching = False
                        return
                    try:
                        r = requests.get(
                            "https://api.openweathermap.org/data/2.5/weather",
                            params={"q": target_city, "appid": api_key, "units": "metric"},
                            timeout=5,
                        )
                        if r.status_code == 200:
                            d = r.json()
                            self._weather = f"{d['weather'][0]['description'].title()}, {d['main']['temp']}°C"
                            self._weather_ts = time.time()
                            self._save_to_disk()
                    except Exception:
                        pass
                    finally:
                        self._weather_fetching = False
                import threading
                threading.Thread(target=_fetch, daemon=True).start()
        return self._weather or "weather unavailable"

    def get_memory(self, max_entries=5):
        now = time.time()
        if not self._memory or (now - self._memory_ts) > MEMORY_TTL:
            candidates = [
                PROJECT_ROOT / "conversations" / "Rudra_Vani_memory.json",
                PROJECT_ROOT / "Rudra_Vani_memory.json",
            ]
            memory_file = None
            for c in candidates:
                if c.exists():
                    memory_file = c
                    break
            if not memory_file:
                return ""
            try:
                with open(memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data:
                    self._memory = ""
                else:
                    recent = data[-max_entries:] if len(data) >= max_entries else data
                    lines = []
                    for conv in recent:
                        messages = conv.get("messages", [])
                        for msg in messages[-4:]:
                            role = msg.get("role", "")
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                            content = str(content).strip()[:100]
                            if content:
                                lines.append(f"[{role}]: {content}")
                    self._memory = "\n".join(lines[-12:])
                self._memory_ts = now
            except Exception:
                return self._memory or ""
        return self._memory

context_cache = ContextCache()

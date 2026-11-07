"""v2: історія горіння точки, пріоритет, батарея, маршрут для пожежних, сезон."""
import json
import math
import os
from datetime import datetime
from typing import Optional

import requests

import config
from firms import haversine_km

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALENDAR_PATH = os.path.join(ROOT, "data", "calendar.json")

MONTHS_UA = ["січень", "лютий", "березень", "квітень", "травень", "червень",
             "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"]


class Calendar:
    """Календар горіння з data/calendar.json (будує harmonize/build_calendar.py)."""

    def __init__(self):
        self.data: Optional[dict] = None
        self.mtime = 0.0
        self.cells = {}
        self.load()

    def load(self) -> None:
        try:
            m = os.path.getmtime(CALENDAR_PATH)
        except OSError:
            return
        if m == self.mtime:
            return
        with open(CALENDAR_PATH, encoding="utf-8") as f:
            self.data = json.load(f)
        self.mtime = m
        self.cells = {}
        for c in self.data.get("cells", []):
            self.cells[(math.floor(c["lat"] / 0.02), math.floor(c["lon"] / 0.02))] = c
        print(f"[КАЛЕНДАР] завантажено: {len(self.data.get('monthly', []))} місяців, {len(self.cells)} клітинок")

    def history(self, lat: float, lon: float) -> dict:
        """Скільки днів горіло в радіусі ~1 клітинки (3x3) за весь архів."""
        self.load()
        if not self.cells:
            return {"fire_days": 0, "years": 0, "last": None, "recurrence": "unknown"}
        ky, kx = math.floor(lat / 0.02), math.floor(lon / 0.02)
        days, years, last = 0, 0, None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                c = self.cells.get((ky + dy, kx + dx))
                if c:
                    days += c["fire_days"]
                    years = max(years, c["years"])
                    if c.get("last") and (last is None or c["last"] > last):
                        last = c["last"]
        n_years = max(1, datetime.now().year - 2001)
        rec = "first" if days == 0 else ("often" if years >= max(4, n_years // 4) else "sometimes")
        return {"fire_days": days, "years": years, "last": last, "recurrence": rec}

    def season(self, lang: str = "ua") -> Optional[dict]:
        self.load()
        if not self.data or not self.data.get("climatology"):
            return None
        clim = self.data["climatology"]
        m = datetime.now().month
        vals = sorted(c["mean"] for c in clim)
        cur = next(c for c in clim if c["month"] == m)
        rank = vals.index(cur["mean"])
        risk = "high" if rank >= 9 else ("medium" if rank >= 5 else "low")
        peak = max(clim, key=lambda c: c["mean"])
        text = {
            "high": f"Зараз сезон горіння: у {MONTHS_UA[m - 1]} в середньому {cur['mean']:.0f} точок.",
            "medium": f"Помірний сезон: у {MONTHS_UA[m - 1]} в середньому {cur['mean']:.0f} точок. Пік — {MONTHS_UA[peak['month'] - 1]}.",
            "low": f"Тихий сезон: у {MONTHS_UA[m - 1]} в середньому {cur['mean']:.0f} точок. Пік — {MONTHS_UA[peak['month'] - 1]}.",
        }[risk]
        text_en = {
            "high": f"Burning season now: {MONTHS_EN[m - 1]} averages {cur['mean']:.0f} hotspots.",
            "medium": f"Moderate season: {MONTHS_EN[m - 1]} averages {cur['mean']:.0f} hotspots. Peak — {MONTHS_EN[peak['month'] - 1]}.",
            "low": f"Quiet season: {MONTHS_EN[m - 1]} averages {cur['mean']:.0f} hotspots. Peak — {MONTHS_EN[peak['month'] - 1]}.",
        }[risk]
        return {"month_label": MONTHS_UA[m - 1], "month_label_en": MONTHS_EN[m - 1], "risk": risk,
                "text": text, "text_en": text_en}


def priority(place: dict, hist: dict) -> str:
    """Нове місце, яке ніколи не горіло, або підтверджене кількома проходами — терміново.
    Місце, що горить майже щороку (сільгосп спалювання) — нижчий пріоритет, але все одно перевіряємо."""
    score = 0
    if hist["recurrence"] == "first":
        score += 2
    elif hist["recurrence"] == "often":
        score -= 1
    if place.get("confirmed"):
        score += 1
    if (place.get("frp_max") or 0) >= 20:
        score += 1
    return "high" if score >= 2 else ("low" if score < 0 else "normal")


def mission_battery_left(dist_km: float) -> float:
    """Скільки % батареї лишиться після місії туди-огляд-назад."""
    v, c = config.DRONE_SPEED_MS, config.CLIMB_MS
    fa, ia = config.FLIGHT_ALT_M, config.INSPECT_ALT_M
    t = fa / c + 2 * dist_km * 1000 / v + 2 * (fa - ia) / c + config.INSPECT_S + fa / c
    return round(100 - t / (config.ENDURANCE_MIN * 60) * 100, 1)


BATTERY_RESERVE_PCT = 20.0

_route_cache: dict = {}


def fire_route(base: dict, lat: float, lon: float) -> dict:
    """Маршрут по дорогах від пожежної частини (у місті бази) до точки. OSRM, без ключа."""
    key = (base["id"], round(lat, 4), round(lon, 4))
    if key in _route_cache:
        return _route_cache[key]
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{base['lon']},{base['lat']};{lon},{lat}?overview=simplified&geometries=geojson")
    try:
        r = requests.get(url, timeout=8).json()
        rt = r["routes"][0]
        coords = [[round(y, 5), round(x, 5)] for x, y in rt["geometry"]["coordinates"]]
        res = {"from_name": base["name"],
               "distance_km": round(rt["distance"] / 1000, 1),
               "duration_min": round(rt["duration"] / 60), "coords": coords, "source": "osrm"}
    except Exception as e:  # немає інтернету — пряма лінія з оцінкою
        d = haversine_km(base["lat"], base["lon"], lat, lon) * 1.4
        res = {"from_name": base["name"],
               "distance_km": round(d, 1), "duration_min": round(d / 50 * 60),
               "coords": [[base["lat"], base["lon"]], [lat, lon]], "source": f"estimate ({e.__class__.__name__})"}
    _route_cache[key] = res
    return res

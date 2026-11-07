"""Зв'язок з модулем ESP32-CAM (або імітація для демо)."""
import random
from dataclasses import dataclass, field
from typing import Optional

import requests

import config


@dataclass
class ModuleReading:
    air_temp_c: Optional[float] = None
    temp_rise_c: float = 0.0
    co_detected: bool = False
    thermal_max_c: Optional[float] = None
    thermal_mean_c: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    alarm_on_board: bool = False
    photo_jpeg: Optional[bytes] = field(default=None, repr=False)


def read_module(url: str = config.MODULE_URL, timeout: float = 5, with_photo: bool = False) -> ModuleReading:
    d = requests.get(f"{url}/data", timeout=timeout).json()
    photo = None
    if with_photo:
        try:
            r = requests.get(f"{url}/capture", timeout=timeout)
            if r.ok:
                photo = r.content
        except requests.RequestException:
            pass
    return ModuleReading(
        air_temp_c=d.get("air_temp_c"),
        temp_rise_c=d.get("temp_rise_c") or 0.0,
        co_detected=bool(d.get("co_detected")),
        thermal_max_c=d.get("thermal_max_c"),
        thermal_mean_c=d.get("thermal_mean_c"),
        lat=d.get("lat"),
        lon=d.get("lon"),
        alarm_on_board=bool(d.get("alarm")),
        photo_jpeg=photo,
    )


def simulate(scenario: str, lat: float, lon: float, seed: int = 1) -> ModuleReading:
    """Імітація показань над точкою: fire / field / false."""
    rnd = random.Random(seed)
    if scenario == "fire":
        return ModuleReading(18 + rnd.uniform(5, 12), rnd.uniform(9, 15), True,
                             rnd.uniform(180, 300), 12.0, lat, lon, True)
    if scenario == "field":
        # спалювання стерні: дим і тепло є, але низьке й розкидане
        return ModuleReading(12 + rnd.uniform(1, 3), rnd.uniform(3, 6), True,
                             rnd.uniform(90, 140), 15.0, lat, lon, False)
    return ModuleReading(9 + rnd.uniform(0, 1), rnd.uniform(0, 1), False,
                         rnd.uniform(20, 35), 10.0, lat, lon, False)

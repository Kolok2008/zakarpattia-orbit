"""Бази, призначення найближчого дрона і політ (симуляція або справжній дрон через MAVLink)."""
import math
import random
import threading
import time
from typing import Dict, List, Optional

import config
from classifier import classify
from firms import haversine_km
from module_client import ModuleReading, read_module

PHASES = [
    ("takeoff", "Зліт"), ("cruise", "Політ до точки"), ("descend", "Зниження"),
    ("inspect", "Огляд"), ("return", "Повернення"), ("land", "Посадка"), ("done", "На базі"),
]
PHASE_LABEL = dict(PHASES)
HISTORY_MAX = 180


# ---------- геометрія ----------
def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def lerp_pos(a, b, f):
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def offset_m(lat, lon, north_m, east_m):
    return (lat + north_m / 111_320,
            lon + east_m / (111_320 * math.cos(math.radians(lat))))


# ---------- бази ----------
def nearest_base(lat, lon) -> tuple[Optional[dict], Optional[float]]:
    best = min(config.BASES, key=lambda b: haversine_km(lat, lon, b["lat"], b["lon"]))
    d = haversine_km(lat, lon, best["lat"], best["lon"])
    return (best, d) if d <= config.MAX_RANGE_KM else (None, d)


# ---------- модель датчиків (симуляція) ----------
SCENARIOS = {
    #        тепло вогню °C, ріст повітря °C, CO ppm, радіус диму м
    "fire":  (280.0, 15.0, 120.0, 450.0),
    "field": (135.0, 5.5, 45.0, 250.0),
    "false": (32.0, 0.6, 2.0, 50.0),
}


class SensorModel:
    def __init__(self, scenario: str, seed: int):
        self.peak_t, self.peak_rise, self.peak_co, self.smoke_r = SCENARIOS[scenario]
        self.rnd = random.Random(seed)
        self.base_air = 9.0 + self.rnd.uniform(-1, 1)

    def read(self, dist_m: float, alt_m: float) -> dict:
        n = self.rnd.gauss
        slant = math.hypot(dist_m, alt_m)
        # тепловізор бачить здалеку, але сигнал падає з відстанню (усереднення пікселів)
        vis = 1 / (1 + (slant / 350) ** 2)
        thermal_max = 12 + (self.peak_t - 12) * vis + n(0, 1.2)
        # повітря і CO — лише в шлейфі диму, низько і близько
        plume = math.exp(-dist_m / self.smoke_r) * math.exp(-max(alt_m - 20, 0) / 60)
        rise = self.peak_rise * plume + n(0, 0.15)
        co = max(0.0, self.peak_co * plume + n(0, 0.8))
        return {
            "thermal_max_c": round(thermal_max, 1),
            "thermal_mean_c": round(11 + n(0, 0.4) + 4 * vis, 1),
            "air_temp_c": round(self.base_air + rise, 1),
            "temp_rise_c": round(max(rise, 0), 1),
            "co_ppm": round(co, 1),
            "co_detected": co > 25,
        }


# ---------- місія ----------
class Mission:
    """Одна місія: база -> точка -> огляд -> база. Оновлюється в окремому потоці."""

    def __init__(self, place: dict, base: dict, scenario: str, use_module: bool):
        self.place, self.base = place, base
        self.scenario, self.use_module = scenario, use_module
        self.module_mode = "sim"
        self.sensors_model = SensorModel(scenario, seed=hash(place["id"]) & 0xFFFF)
        self.home = (base["lat"], base["lon"])
        self.target = (place["lat"], place["lon"])
        self.total_m = haversine_km(*self.home, *self.target) * 1000
        self.lock = threading.Lock()
        self.t = 0.0
        self.phase = "takeoff"
        self.pos = self.home
        self.alt = 0.0
        self.speed = 0.0
        self.heading = bearing_deg(*self.home, *self.target)
        self.battery = 100.0
        self.track: List[List[float]] = [list(self.home)]
        self.sensors = self.sensors_model.read(self.total_m, 0)
        self.history = {"t": [], "thermal": [], "air": [], "co": []}
        self.peak = {"thermal_max_c": 0.0, "thermal_mean_c": 12.0, "temp_rise_c": 0.0,
                     "co_detected": False, "air_temp_c": None}
        self.verdict = None
        self.inspect_t = 0.0
        self.leg = 0.0  # пройдений шлях на поточному відрізку, м

    # --- оцінка часу ---
    def eta_s(self) -> float:
        v, c = config.DRONE_SPEED_MS, config.CLIMB_MS
        fa, ia = config.FLIGHT_ALT_M, config.INSPECT_ALT_M
        rest = {
            "takeoff": (fa - self.alt) / c + self.total_m / v + (fa - ia) / c + config.INSPECT_S + (fa - ia) / c + self.total_m / v + fa / c,
            "cruise": (self.total_m - self.leg) / v + (fa - ia) / c + config.INSPECT_S + (fa - ia) / c + self.total_m / v + fa / c,
            "descend": (self.alt - ia) / c + config.INSPECT_S + (fa - ia) / c + self.total_m / v + fa / c,
            "inspect": config.INSPECT_S - self.inspect_t + (fa - ia) / c + self.total_m / v + fa / c,
            "return": (self.total_m - self.leg) / v + fa / c + max(fa - self.alt, 0) / c,
            "land": self.alt / c,
            "done": 0.0,
        }
        return max(0.0, rest[self.phase])

    # --- крок симуляції ---
    def step(self, dt: float) -> None:
        v, c = config.DRONE_SPEED_MS, config.CLIMB_MS
        fa, ia = config.FLIGHT_ALT_M, config.INSPECT_ALT_M
        self.t += dt
        ph = self.phase
        if ph == "takeoff":
            self.alt = min(fa, self.alt + c * dt); self.speed = c
            if self.alt >= fa: self.phase, self.leg = "cruise", 0.0
        elif ph == "cruise":
            self.leg = min(self.total_m, self.leg + v * dt); self.speed = v
            self.pos = lerp_pos(self.home, self.target, self.leg / self.total_m if self.total_m else 1)
            self.heading = bearing_deg(*self.home, *self.target)
            if self.leg >= self.total_m: self.phase = "descend"
        elif ph == "descend":
            self.alt = max(ia, self.alt - c * dt); self.speed = c
            if self.alt <= ia: self.phase, self.inspect_t = "inspect", 0.0
        elif ph == "inspect":
            self.inspect_t += dt; self.speed = 6.0
            ang = self.inspect_t / config.INSPECT_S * 2 * math.pi  # коло радіусом 60 м
            self.pos = offset_m(*self.target, 60 * math.cos(ang), 60 * math.sin(ang))
            self.heading = (math.degrees(ang) + 90) % 360
            if self.inspect_t >= config.INSPECT_S:
                self.finish_inspection()
                self.phase, self.leg = "return", 0.0
        elif ph == "return":
            if self.alt < fa:
                self.alt = min(fa, self.alt + c * dt); self.speed = c
            else:
                self.leg = min(self.total_m, self.leg + v * dt); self.speed = v
                self.pos = lerp_pos(self.target, self.home, self.leg / self.total_m if self.total_m else 1)
                self.heading = bearing_deg(*self.target, *self.home)
                if self.leg >= self.total_m: self.phase = "land"
        elif ph == "land":
            self.alt = max(0.0, self.alt - c * dt); self.speed = c
            self.pos = self.home
            if self.alt <= 0: self.phase, self.speed = "done", 0.0
        if self.phase != "done":
            self.battery = max(0.0, self.battery - dt / (config.ENDURANCE_MIN * 60) * 100)
        self.update_sensors()

    def dist_to_target_m(self) -> float:
        return haversine_km(*self.pos, *self.target) * 1000

    def update_sensors(self) -> None:
        if self.use_module:
            try:
                r = read_module(timeout=1.5)
                self.module_mode = "live"
                self.sensors = {"thermal_max_c": r.thermal_max_c, "thermal_mean_c": r.thermal_mean_c,
                                "air_temp_c": r.air_temp_c, "temp_rise_c": r.temp_rise_c,
                                "co_ppm": None, "co_detected": r.co_detected}
            except Exception:
                self.module_mode = "sim"
                self.sensors = self.sensors_model.read(self.dist_to_target_m(), self.alt)
        else:
            self.sensors = self.sensors_model.read(self.dist_to_target_m(), self.alt)
        s = self.sensors
        if self.phase in ("descend", "inspect"):
            for k in ("thermal_max_c", "temp_rise_c"):
                if s.get(k) is not None:
                    self.peak[k] = max(self.peak[k], s[k])
            self.peak["co_detected"] |= bool(s.get("co_detected"))
            self.peak["thermal_mean_c"] = s.get("thermal_mean_c") or self.peak["thermal_mean_c"]
            self.peak["air_temp_c"] = s.get("air_temp_c")
        h = self.history
        h["t"].append(round(self.t, 1)); h["thermal"].append(s.get("thermal_max_c"))
        h["air"].append(s.get("air_temp_c")); h["co"].append(s.get("co_ppm"))
        for k in h:
            del h[k][:-HISTORY_MAX]
        if not self.track or haversine_km(*self.track[-1], *self.pos) > 0.05:
            self.track.append([round(self.pos[0], 6), round(self.pos[1], 6)])

    def finish_inspection(self) -> None:
        p = self.peak
        reading = ModuleReading(air_temp_c=p["air_temp_c"], temp_rise_c=p["temp_rise_c"],
                                co_detected=p["co_detected"], thermal_max_c=p["thermal_max_c"],
                                thermal_mean_c=p["thermal_mean_c"])
        self.verdict = classify(reading)

    # --- стан для сайту ---
    def state(self) -> dict:
        return {
            "place_id": self.place["id"], "base_id": self.base["id"], "base_name": self.base["name"],
            "phase": self.phase, "phase_label": PHASE_LABEL[self.phase],
            "phases": [{"id": i, "label": l} for i, l in PHASES],
            "t_sim_s": round(self.t, 1), "eta_s": round(self.eta_s(), 1),
            "lat": round(self.pos[0], 6), "lon": round(self.pos[1], 6),
            "alt_m": round(self.alt, 1), "speed_ms": round(self.speed, 1),
            "heading_deg": round(self.heading, 1), "battery_pct": round(self.battery, 1),
            "dist_to_target_m": round(self.dist_to_target_m()),
            "dist_from_base_m": round(haversine_km(*self.pos, *self.home) * 1000),
            "track": self.track[-400:], "route": [list(self.home), list(self.target)],
            "module_mode": self.module_mode, "scenario": self.scenario,
            "sensors": self.sensors, "history": self.history,
            "verdict": verdict_json(self.verdict),
        }


VERDICT_EN = {
    "ЛІСОВА ПОЖЕЖА": ("Forest fire", "The drone confirmed burning in the forest. Firefighters are needed."),
    "СПАЛЮВАННЯ ПОЛЯ / СТЕРНІ": ("Field burning", "A field or stubble is burning, not the forest. Notify the local community."),
    "ХИБНА ТРИВОГА": ("False alarm", "No signs of burning on site. The satellite was wrong."),
}

VERDICT_STYLE = {
    "ЛІСОВА ПОЖЕЖА": ("Лісова пожежа", "#E4572E", "Дрон підтвердив горіння в лісі. Потрібен виїзд пожежників."),
    "СПАЛЮВАННЯ ПОЛЯ / СТЕРНІ": ("Спалювання поля", "#E9A23B", "Горить поле або стерня, а не ліс. Варто повідомити громаду."),
    "ХИБНА ТРИВОГА": ("Хибна тривога", "#7FB069", "На місці ознак горіння немає. Супутник помилився."),
}


def verdict_json(v) -> Optional[dict]:
    if v is None:
        return None
    title, color, summary = VERDICT_STYLE.get(v.label, (v.label.capitalize(), "#7FB069", ""))
    title_en, summary_en = VERDICT_EN.get(v.label, (title, summary))
    return {"label": v.label, "title": title, "color": color, "confidence": v.confidence,
            "summary": summary, "reasons": list(v.reasons),
            "title_en": title_en, "summary_en": summary_en, "reasons_en": list(v.reasons_en or [])}


def run_mission(m: Mission, stop: threading.Event, on_done=None, tick: float = 0.25) -> None:
    """Потік симуляції: кожні tick с реального часу -> tick*SIM_SPEEDUP с польоту."""
    while not stop.is_set() and m.phase != "done":
        with m.lock:
            m.step(tick * config.SIM_SPEEDUP)
        time.sleep(tick)
    if on_done:
        on_done(m)

"""Бази, призначення найближчого дрона і політ (симуляція або справжній дрон через MAVLink).

v3 (порада менторів): ніякого окремого модуля на дроні. Дрон сам злітає, летить до точки,
кружляє над нею і сам повертається на базу (ArduPilot: TAKEOFF -> WAYPOINT -> LOITER -> RTL).
Відео денної і теплової камери дрона йде оператору по штатному відеоканалу дрона.
Рішення («пожежа / палять поле / хибна тривога») приймає ОПЕРАТОР, система лише підказує.
"""
import math
import random
import threading
import time
from typing import List, Optional

import config
from firms import haversine_km

PHASES = [
    ("takeoff", "Автозліт"), ("cruise", "Політ до точки"), ("descend", "Зниження"),
    ("inspect", "Оператор дивиться"), ("return", "Повернення"), ("land", "Автопосадка"), ("done", "На базі"),
]
PHASE_LABEL = dict(PHASES)
PHASE_EN = {"takeoff": "Auto take-off", "cruise": "Flying to the hotspot", "descend": "Descent",
            "inspect": "Operator review", "return": "Return", "land": "Auto landing", "done": "At base"}
HISTORY_MAX = 180

FIRE, FIELD, FALSE, NONE = "fire", "field", "false", "none"


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


# ---------- тепловізор дрона (симуляція) ----------
# найгарячіша точка в кадрі, °C, коли дрон над ціллю
SCENARIOS = {"fire": 280.0, "field": 135.0, "false": 32.0}


class ThermalModel:
    """Штатний радіометричний тепловізор дрона: max температура в кадрі."""

    def __init__(self, scenario: str, seed: int):
        self.peak = SCENARIOS[scenario]
        self.rnd = random.Random(seed)

    def read(self, dist_m: float, alt_m: float) -> float:
        vis = 1 / (1 + (math.hypot(dist_m, alt_m) / 350) ** 2)
        return round(12 + (self.peak - 12) * vis + self.rnd.gauss(0, 1.2), 1)


# ---------- висновки ----------
VERDICTS = {
    FIRE:  {"title": "Лісова пожежа", "title_en": "Forest fire", "color": "#E4572E",
            "summary": "Оператор підтвердив горіння в лісі. Потрібен виїзд пожежників.",
            "summary_en": "The operator confirmed burning in the forest. Firefighters are needed."},
    FIELD: {"title": "Палять поле", "title_en": "Field burning", "color": "#E9A23B",
            "summary": "Горить поле або суха трава, не ліс. Повідомити громаду / поліцію.",
            "summary_en": "A field or dry grass is burning, not the forest. Notify the community or police."},
    FALSE: {"title": "Хибна тривога", "title_en": "False alarm", "color": "#7FB069",
            "summary": "На місці ознак горіння немає.",
            "summary_en": "No signs of burning on site."},
    NONE:  {"title": "Не перевірено", "title_en": "Not reviewed", "color": "#9FAA94",
            "summary": "Оператор не встиг відповісти. Дрон повернувся, точку варто перевірити ще раз.",
            "summary_en": "The operator did not answer in time. The drone returned; check this place again."},
}


def system_hint(thermal_max: float, history: Optional[dict]) -> dict:
    """Підказка системи оператору (не рішення): тепловізор + історія місця."""
    rec = (history or {}).get("recurrence")
    if thermal_max >= 200:
        k = FIELD if rec == "often" and thermal_max < 230 else FIRE
    elif thermal_max >= 80:
        k = FIELD
    else:
        k = FALSE
    return {"label": k, "title": VERDICTS[k]["title"], "title_en": VERDICTS[k]["title_en"],
            "color": VERDICTS[k]["color"]}


def make_verdict(label: str, by: str, thermal_max: float, hint: Optional[dict], history: Optional[dict]) -> dict:
    v = dict(VERDICTS[label])
    v["label"] = label
    v["by"] = by
    v["confidence"] = 1.0 if by == "operator" else 0.0
    r, e = [], []
    if by == "operator":
        r.append("рішення оператора за відео денної і теплової камер дрона")
        e.append("operator decision from the drone's day and thermal video")
    elif by == "auto":
        r.append("демо-режим: рішення взято з підказки системи (оператора немає)")
        e.append("demo mode: decision taken from the system hint (no operator)")
    r.append(f"тепловізор дрона: найгарячіша точка {thermal_max:.0f} °C")
    e.append(f"drone thermal camera: hottest spot {thermal_max:.0f} °C")
    if hint:
        r.append(f"підказка системи була: {hint['title']}")
        e.append(f"system hint was: {hint['title_en']}")
    h = history or {}
    if h.get("recurrence") == "often":
        r.append(f"історія NASA: тут горіло {h['fire_days']} днів за {h['years']} різних років — типове місце спалювання")
        e.append(f"NASA history: {h['fire_days']} fire days in {h['years']} different years — a typical burning site")
    elif h.get("recurrence") == "first":
        r.append("історія NASA: з 2001 року тут не було жодної гарячої точки — нетипово")
        e.append("NASA history: no hotspot here since 2001 — unusual")
    v["reasons"], v["reasons_en"] = r, e
    return v


# ---------- місія ----------
class Mission:
    """Одна місія: автозліт -> точка -> оператор дивиться -> автоповернення -> автопосадка."""

    def __init__(self, place: dict, base: dict, scenario: str, auto_operator: bool = False):
        self.place, self.base = place, base
        self.scenario, self.auto_operator = scenario, auto_operator
        self.thermal_model = ThermalModel(scenario, seed=hash(place["id"]) & 0xFFFF)
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
        self.thermal = self.thermal_model.read(self.total_m, 0)
        self.thermal_peak = 0.0
        self.history = {"t": [], "thermal": []}
        self.verdict: Optional[dict] = None
        self.hint: Optional[dict] = None
        self.inspect_t = 0.0
        self.leg = 0.0
        self.waiting_operator = False
        self.on_operator_needed = None   # callback для сповіщення

    # --- рішення оператора ---
    def decide(self, label: str, by: str = "operator") -> bool:
        if self.phase != "inspect" or self.verdict is not None or label not in VERDICTS:
            return False
        self.verdict = make_verdict(label, by, self.thermal_peak, self.hint, self.place.get("history"))
        self.waiting_operator = False
        self.phase, self.leg = "return", 0.0
        return True

    # --- оцінка часу ---
    def eta_s(self) -> float:
        v, c = config.DRONE_SPEED_MS, config.CLIMB_MS
        fa, ia = config.FLIGHT_ALT_M, config.INSPECT_ALT_M
        insp = config.INSPECT_S
        back = (fa - ia) / c + self.total_m / v + fa / c
        rest = {
            "takeoff": (fa - self.alt) / c + self.total_m / v + (fa - ia) / c + insp + back,
            "cruise": (self.total_m - self.leg) / v + (fa - ia) / c + insp + back,
            "descend": (self.alt - ia) / c + insp + back,
            "inspect": max(insp - self.inspect_t, 0) + back,
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
            if self.alt <= ia:
                self.phase, self.inspect_t, self.waiting_operator = "inspect", 0.0, True
                if self.on_operator_needed:
                    try:
                        self.on_operator_needed(self)
                    except Exception as e:
                        print(f"[СПОВІЩЕННЯ] помилка: {e}")
        elif ph == "inspect":
            # кружляє над точкою (LOITER), поки оператор не вирішить
            self.inspect_t += dt; self.speed = 6.0
            ang = self.inspect_t / config.INSPECT_S * 2 * math.pi
            self.pos = offset_m(*self.target, 60 * math.cos(ang), 60 * math.sin(ang))
            self.heading = (math.degrees(ang) + 90) % 360
            if self.inspect_t >= 8 and self.hint is None:
                self.hint = system_hint(self.thermal_peak, self.place.get("history"))
            if self.auto_operator and self.inspect_t >= config.INSPECT_S and self.hint:
                self.decide(self.hint["label"], by="auto")
            elif self.inspect_t >= config.OPERATOR_TIMEOUT_S:
                self.decide(NONE, by="timeout")
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
        self.update_thermal()

    def dist_to_target_m(self) -> float:
        return haversine_km(*self.pos, *self.target) * 1000

    def update_thermal(self) -> None:
        self.thermal = self.thermal_model.read(self.dist_to_target_m(), self.alt)
        if self.phase in ("descend", "inspect"):
            self.thermal_peak = max(self.thermal_peak, self.thermal)
        h = self.history
        h["t"].append(round(self.t, 1)); h["thermal"].append(self.thermal)
        for k in h:
            del h[k][:-HISTORY_MAX]
        if not self.track or haversine_km(*self.track[-1], *self.pos) > 0.05:
            self.track.append([round(self.pos[0], 6), round(self.pos[1], 6)])

    # --- стан для сайту ---
    def state(self) -> dict:
        return {
            "place_id": self.place["id"], "base_id": self.base["id"], "base_name": self.base["name"],
            "phase": self.phase, "phase_label": PHASE_LABEL[self.phase],
            "phases": [{"id": i, "label": l, "label_en": PHASE_EN[i]} for i, l in PHASES],
            "t_sim_s": round(self.t, 1), "eta_s": round(self.eta_s(), 1),
            "lat": round(self.pos[0], 6), "lon": round(self.pos[1], 6),
            "target": list(self.target),
            "alt_m": round(self.alt, 1), "speed_ms": round(self.speed, 1),
            "heading_deg": round(self.heading, 1), "battery_pct": round(self.battery, 1),
            "dist_to_target_m": round(self.dist_to_target_m()),
            "dist_from_base_m": round(haversine_km(*self.pos, *self.home) * 1000),
            "track": self.track[-400:], "route": [list(self.home), list(self.target)],
            "scenario": self.scenario, "thermal_c": self.thermal, "thermal_peak_c": self.thermal_peak,
            "history": self.history, "hint": self.hint,
            "waiting_operator": self.phase == "inspect" and self.verdict is None,
            "operator_left_s": round(max(config.OPERATOR_TIMEOUT_S - self.inspect_t, 0)) if self.phase == "inspect" else None,
            "auto_operator": self.auto_operator,
            "verdict": self.verdict,
        }


def run_mission(m: Mission, stop: threading.Event, on_done=None, tick: float = 0.25) -> None:
    """Потік симуляції: кожні tick с реального часу -> tick*SIM_SPEEDUP с польоту.
    Під час огляду час не прискорюється: оператор дивиться відео в реальному темпі."""
    while not stop.is_set() and m.phase != "done":
        with m.lock:
            k = 1 if (m.phase == "inspect" and not m.auto_operator) else config.SIM_SPEEDUP
            m.step(tick * k)
        time.sleep(tick)
    if on_done:
        on_done(m)

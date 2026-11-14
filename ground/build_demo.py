"""Збирає статичне демо для GitHub Pages у папку docs/ (відкривається в один клік, без Python).

Береться справжній день з архіву NASA FIRMS (22.03.2025, весняний пік), точки обробляються
тією самою логікою, що й на станції (кластери MODIS+VIIRS, бази, історія, пріоритет, батарея,
маска заводів), маршрути пожежних рахуються заздалегідь (OSRM). Політ, відео і рішення
оператора крутить у браузері docs/demo.js — та сама модель, що в mission.py.

    python ground/build_demo.py      -> docs/index.html, docs/demo.js, docs/data/*.json
"""
import glob
import json
import os
import shutil
from datetime import datetime

import pandas as pd

import config
import firms
from mission import SCENARIOS, nearest_base
from station_extras import (BATTERY_RESERVE_PCT, Calendar, RiskMap, StaticSources, fire_route,
                            mission_battery_left, priority)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
DAY = "2025-03-22"


def scenario_for(p: dict) -> str:
    """Що «побачить» тепловізор у демо (оператор усе одно вирішує сам)."""
    rec = (p.get("history") or {}).get("recurrence")
    if p["frp_max"] >= 20 or (p["confirmed"] and rec == "first"):
        return "fire"
    if rec in ("often", "sometimes"):
        return "field"
    return "false"


def main():
    frames = [pd.read_csv(f) for f in glob.glob(os.path.join(ROOT, "data", "raw", f"*_SP_{DAY[:4]}.csv"))]
    d = pd.concat(frames)
    d = d[d.acq_date == DAY].drop(columns=["type"])
    spots = firms.parse_csv(d.to_csv(index=False), "archive")
    clusters = firms.cluster(spots)
    clusters.sort(key=lambda c: -c.latest.when.timestamp())
    cal, static, risk = Calendar(), StaticSources(), RiskMap()
    places = []
    for c in clusters:
        base, dist = nearest_base(c.lat, c.lon)
        p = {"id": f"p{round(c.lat, 3)}_{round(c.lon, 3)}", "lat": round(c.lat, 5), "lon": round(c.lon, 5),
             "sensors": c.sensors, "frp_max": c.frp_max, "latest": c.latest.local_time,
             "passes": len(c.spots), "confirmed": c.confirmed,
             "base_id": base["id"] if base else None, "base_name": base["name"] if base else None,
             "dist_km": round(dist, 1)}
        p["history"] = cal.history(c.lat, c.lon)
        p["priority"] = priority(p, p["history"])
        left = mission_battery_left(dist) if base else None
        p["battery_left_pct"] = left
        p["battery_ok"] = base is not None and left >= BATTERY_RESERVE_PCT
        p["risk"] = risk.at(c.lat, c.lon, month=int(DAY[5:7]))
        if p["risk"] and p["priority"] == "normal" and p["risk"]["risk"] >= 0.2:
            p["priority"] = "high"
        p["static_source"] = static.near(c.lat, c.lon)
        if p["static_source"]:
            p["priority"] = "low"
        p["scenario"] = scenario_for(p)
        if base and not p["static_source"]:
            p["route"] = fire_route(base, c.lat, c.lon)
        places.append(p)
    os.makedirs(os.path.join(DOCS, "data"), exist_ok=True)
    meta = {"day": DAY, "built": datetime.now().isoformat(timespec="minutes"),
            "speedup": 20, "range_km": config.MAX_RANGE_KM, "bases": config.BASES,
            "drone": {"speed": config.DRONE_SPEED_MS, "climb": config.CLIMB_MS, "endurance_min": config.ENDURANCE_MIN,
                      "inspect_s": config.INSPECT_S, "operator_timeout_s": config.OPERATOR_TIMEOUT_S,
                      "flight_alt": config.FLIGHT_ALT_M, "inspect_alt": config.INSPECT_ALT_M},
            "thermal_peak": SCENARIOS, "static_sources": len(static.sites), "places": places}
    with open(os.path.join(DOCS, "data", "demo.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    shutil.copy(os.path.join(ROOT, "data", "calendar.json"), os.path.join(DOCS, "data", "calendar.json"))
    shutil.copy(os.path.join(HERE, "demo.js"), os.path.join(DOCS, "demo.js"))
    with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("<script>\n", '<script src="demo.js"></script>\n<script>\n', 1)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    inr = [p for p in places if p["base_id"]]
    print(f"{DAY}: {len(spots)} точок, {len(places)} місць, у радіусі {len(inr)}, заводів {sum(bool(p['static_source']) for p in places)}")
    print("сценарії:", pd.Series([p["scenario"] for p in inr]).value_counts().to_dict())


if __name__ == "__main__":
    main()

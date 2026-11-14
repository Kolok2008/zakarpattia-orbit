"""Маска відомих промислових (постійних) джерел тепла: труби заводів, факели, котельні.

У стандартних (SP) архівах NASA FIRMS кожна точка має поле type:
  0 — ймовірна пожежа рослинності, 2 — інше постійне наземне джерело (промисловість).
Беремо всі точки type=2, кладемо на сітку ~1 км і залишаємо клітинки, де таке джерело
бачили щонайменше у 2 різні дні. Наземна станція не відправляє дрон на точки поруч з ними.

    python harmonize/build_static_mask.py      -> data/static_sources.json
"""
import glob
import json
import math
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "static_sources.json")
STEP = 0.01      # ~1 км
MIN_DAYS = 2


def main():
    frames = []
    for f in sorted(glob.glob(os.path.join(RAW, "*_SP_*.csv"))):
        d = pd.read_csv(f)
        if "type" in d.columns:
            frames.append(d[["latitude", "longitude", "acq_date", "instrument", "type"]])
    d = pd.concat(frames, ignore_index=True)
    s = d[d["type"] == 2].copy()
    s["ky"] = (s.latitude / STEP).apply(math.floor)
    s["kx"] = (s.longitude / STEP).apply(math.floor)
    g = s.groupby(["ky", "kx"]).agg(lat=("latitude", "mean"), lon=("longitude", "mean"),
                                    n=("latitude", "size"), days=("acq_date", "nunique"),
                                    first=("acq_date", "min"), last=("acq_date", "max"),
                                    sensors=("instrument", lambda x: sorted(set(x)))).reset_index()
    g = g[g.days >= MIN_DAYS].sort_values("n", ascending=False)
    out = {
        "source": "NASA FIRMS standard archive, type = 2 (other static land source)",
        "grid_deg": STEP, "min_days": MIN_DAYS, "buffer_km": 1.0,
        "total_type2_points": int(len(s)), "all_points": int(len(d)),
        "sites": [{"lat": round(r.lat, 5), "lon": round(r.lon, 5), "n": int(r.n), "days": int(r.days),
                   "first": r["first"], "last": r["last"], "sensors": r.sensors} for _, r in g.iterrows()],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"type=2: {len(s)} з {len(d)} точок; постійних джерел (≥{MIN_DAYS} дні): {len(out['sites'])} -> {OUT}")
    for site in out["sites"][:8]:
        print("  ", site)


if __name__ == "__main__":
    main()

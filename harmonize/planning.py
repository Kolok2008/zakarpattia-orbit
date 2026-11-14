"""Планування мережі баз (порада ментора: зусилля — у планування, де і на що реагувати).

Беремо всі точки рослинності VIIRS S-NPP 2012–2026 (без промислових, type 0) і питаємо:
  * яку частку точок і місць повторного горіння покривають 13 баз (радіус MAX_RANGE_KM);
  * скільки точок у кожної бази і яка їх частка припадає на березень–квітень (коли потрібні чергування);
  * де поставити 3 нові бази, щоб покрити найбільше непокритих точок (жадібний підбір по сітці 0,05°).

    python harmonize/planning.py   -> data/planning.json і ключ "planning" у data/calendar.json
"""
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ground"))
import config  # noqa: E402

R_KM = config.MAX_RANGE_KM
NEW_BASES = 3
REGION_KM = 35      # прямокутник bbox захоплює й сусідів (Угорщина, Румунія, Івано-Франківщина):
                    # беремо лише точки ближче 35 км до якогось міста з базою — наближення області
CAND_KM = 30        # нову базу шукаємо не далі 30 км від наявної (у межах області)


def hav(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


def main():
    fs = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "VIIRS_SNPP_SP_*.csv")))
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d = d[d["type"] == 0]
    d["month"] = pd.to_datetime(d.acq_date).dt.month
    B = config.BASES
    dall = np.stack([hav(d.latitude.values, d.longitude.values, b["lat"], b["lon"]) for b in B], axis=1)
    d = d[dall.min(axis=1) <= REGION_KM]
    lat, lon = d.latitude.values, d.longitude.values
    dist = np.stack([hav(lat, lon, b["lat"], b["lon"]) for b in B], axis=1)
    near = dist.argmin(axis=1)
    covered = dist.min(axis=1) <= R_KM
    spring = d.month.isin([3, 4]).values

    with open(os.path.join(ROOT, "data", "calendar.json"), encoding="utf-8") as f:
        cal = json.load(f)
    rep = [c for c in cal.get("cells", []) if c.get("years", 0) >= 5
           and min(hav(c["lat"], c["lon"], b["lat"], b["lon"]) for b in config.BASES) <= REGION_KM]
    rl, ro = np.array([c["lat"] for c in rep]), np.array([c["lon"] for c in rep])
    rep_cov = (np.stack([hav(rl, ro, b["lat"], b["lon"]) for b in B], axis=1).min(axis=1) <= R_KM) if rep else np.array([])

    per_base = []
    for i, b in enumerate(B):
        m = (near == i) & covered
        per_base.append({"id": b["id"], "name": b["name"], "hotspots": int(m.sum()),
                         "spring_share": round(float(spring[m].mean()) if m.any() else 0, 2)})
    per_base.sort(key=lambda x: -x["hotspots"])

    # жадібний підбір нових баз серед центрів сітки 0,05°, де є непокриті точки
    un = ~covered
    ul, uo = lat[un], lon[un]
    cand = pd.DataFrame({"a": np.floor(ul / .05) * .05 + .025, "o": np.floor(uo / .05) * .05 + .025}).drop_duplicates().values
    cand = np.array([c for c in cand if min(hav(c[0], c[1], b["lat"], b["lon"]) for b in B) <= CAND_KM])
    proposals, left = [], np.ones(len(ul), bool)
    for _ in range(NEW_BASES):
        best, bi = 0, None
        for k, (ca, co) in enumerate(cand):
            n = int((left & (hav(ul, uo, ca, co) <= R_KM)).sum())
            if n > best:
                best, bi = n, k
        if bi is None:
            break
        ca, co = cand[bi]
        hit = left & (hav(ul, uo, ca, co) <= R_KM)
        left &= ~hit
        proposals.append({"lat": round(float(ca), 3), "lon": round(float(co), 3), "adds_hotspots": int(hit.sum()),
                          "adds_share": round(int(hit.sum()) / len(lat), 3)})
    new_cov = (covered.sum() + sum(p["adds_hotspots"] for p in proposals)) / len(lat)
    out = {
        "source": "VIIRS S-NPP standard archive 2012–2026, vegetation (type 0)", "radius_km": R_KM,
        "region": f"hotspots within {REGION_KM} km of a base town (proxy for Zakarpattia oblast)",
        "hotspots": int(len(lat)), "covered_share": round(float(covered.mean()), 3),
        "spring_share": round(float(spring.mean()), 3),
        "repeat_cells": int(len(rep)), "repeat_cells_covered_share": round(float(rep_cov.mean()) if len(rep) else 0, 3),
        "per_base": per_base, "proposed_bases": proposals, "covered_share_with_proposed": round(float(new_cov), 3),
    }
    with open(os.path.join(ROOT, "data", "planning.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    cal["planning"] = out
    with open(os.path.join(ROOT, "data", "calendar.json"), "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: v for k, v in out.items() if k != "per_base"}, ensure_ascii=False, indent=1))
    print(per_base[:5])


if __name__ == "__main__":
    main()

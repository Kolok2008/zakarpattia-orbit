"""Карта ризику і карта непевності (порада ментора): Random Forest на історії горіння.

Сітка 0,02° (~2 км), лише клітинки ближче 35 км до міст з базами (наближення області).
Ціль: у клітинці була точка VIIRS S-NPP (рослинність, type 0) у місяці m року Y.
Ознаки — лише те, що відомо ДО року Y (тож модель прогнозує наперед і не залежить від затримки даних):
  частка попередніх років, коли клітинка горіла в цьому місяці / в будь-якому місяці;
  те саме для сусідства 3×3; чи горіла в цьому місяці торік; місяць (sin/cos); широта, довгота.
Перевірка: навчання 2014–2022, тест 2023–2025 (наперед у часі), порівняння з простою «історичною частотою».
Непевність: розкид прогнозів між деревами лісу (std), тобто наскільки дерева не згодні між собою.

    python harmonize/risk_model.py   -> data/risk.json і ключ "risk" у data/calendar.json
"""
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ground"))
import config  # noqa: E402

STEP = 0.02
Y0, Y1 = 2012, 2025          # повні роки S-NPP
TRAIN = range(2014, 2023)
TEST = range(2023, 2026)
REGION_KM = 35
FORECAST_YEAR = 2027


def hav(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


def main():
    d = pd.concat([pd.read_csv(f) for f in glob.glob(os.path.join(ROOT, "data", "raw", "VIIRS_SNPP_SP_*.csv"))])
    d = d[d["type"] == 0]
    d["date"] = pd.to_datetime(d.acq_date)
    d = d[(d.date.dt.year >= Y0) & (d.date.dt.year <= Y1)]
    d["ky"] = np.floor(d.latitude / STEP).astype(int)
    d["kx"] = np.floor(d.longitude / STEP).astype(int)
    d["y"], d["m"] = d.date.dt.year, d.date.dt.month

    # клітинки області
    w, s, e, n = 22.1, 47.9, 24.7, 49.1
    ky = np.arange(math.floor(s / STEP), math.floor(n / STEP) + 1)
    kx = np.arange(math.floor(w / STEP), math.floor(e / STEP) + 1)
    KY, KX = np.meshgrid(ky, kx, indexing="ij")
    lat_c, lon_c = (KY + .5) * STEP, (KX + .5) * STEP
    dmin = np.min([hav(lat_c, lon_c, b["lat"], b["lon"]) for b in config.BASES], axis=0)
    inside = dmin <= REGION_KM
    H, W = KY.shape
    years = list(range(Y0, Y1 + 1))
    # куб: рік × місяць × клітинка (0/1)
    cube = np.zeros((len(years), 12, H, W), dtype=np.float32)
    iy, ix = d.ky.values - ky[0], d.kx.values - kx[0]
    ok = (iy >= 0) & (iy < H) & (ix >= 0) & (ix < W)
    cube[d.y.values[ok] - Y0, d.m.values[ok] - 1, iy[ok], ix[ok]] = 1

    def nb(a):  # максимум по сусідству 3×3
        p = np.pad(a, [(0, 0)] * (a.ndim - 2) + [(1, 1), (1, 1)])
        out = np.zeros_like(a)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                out = np.maximum(out, p[..., dy:dy + H, dx:dx + W])
        return out

    cube_nb = nb(cube)
    any_y = cube.max(axis=1)            # рік × клітинка
    any_y_nb = cube_nb.max(axis=1)

    def features(Y):
        """Ознаки для року Y з даних років < Y. Повертає (12, H, W, F)."""
        k = Y - Y0 if Y <= Y1 else len(years)
        past = slice(0, k)
        npast = max(k, 1)
        f_m = cube[past].sum(0) / npast                 # 12×H×W
        f_m_nb = cube_nb[past].sum(0) / npast
        f_any = np.broadcast_to(any_y[past].sum(0) / npast, (12, H, W))
        f_any_nb = np.broadcast_to(any_y_nb[past].sum(0) / npast, (12, H, W))
        last = cube[k - 1] if k >= 1 else np.zeros((12, H, W))
        last_nb = cube_nb[k - 1] if k >= 1 else np.zeros((12, H, W))
        mm = np.arange(12)[:, None, None] * np.ones((12, H, W))
        F = np.stack([f_m, f_m_nb, f_any, f_any_nb, last, last_nb,
                      np.sin(2 * np.pi * mm / 12), np.cos(2 * np.pi * mm / 12),
                      np.broadcast_to(lat_c, (12, H, W)), np.broadcast_to(lon_c, (12, H, W))], axis=-1)
        return F

    names = ["frac_years_this_month", "frac_years_this_month_3x3", "frac_years_any", "frac_years_any_3x3",
             "last_year_this_month", "last_year_this_month_3x3", "month_sin", "month_cos", "lat", "lon"]
    mask = np.broadcast_to(inside, (12, H, W))

    def xy(Ys):
        X, Yv = [], []
        for Y in Ys:
            F = features(Y)
            X.append(F[mask]); Yv.append(cube[Y - Y0][mask])
        return np.concatenate(X), np.concatenate(Yv)

    Xtr, ytr = xy(TRAIN)
    Xte, yte = xy(TEST)
    rf = RandomForestClassifier(n_estimators=200, min_samples_leaf=20, max_features=4, n_jobs=-1,
                                class_weight={0: 1, 1: 5}, random_state=1)
    rf.fit(Xtr, ytr)
    p = rf.predict_proba(Xte)[:, 1]
    base = Xte[:, 0]  # просто частка років з вогнем у цьому місяці
    top = lambda score: float(yte[score >= np.quantile(score, .95)].sum() / yte.sum())
    metrics = {
        "train_years": [TRAIN.start, TRAIN.stop - 1], "test_years": [TEST.start, TEST.stop - 1],
        "test_samples": int(len(yte)), "test_positive_rate": round(float(yte.mean()), 4),
        "rf_roc_auc": round(float(roc_auc_score(yte, p)), 3), "rf_avg_precision": round(float(average_precision_score(yte, p)), 3),
        "baseline_roc_auc": round(float(roc_auc_score(yte, base)), 3),
        "baseline_avg_precision": round(float(average_precision_score(yte, base)), 3),
        "rf_capture_top5pct": round(top(p), 3), "baseline_capture_top5pct": round(top(base + 1e-6 * Xte[:, 1]), 3),
        "feature_importance": {k: round(float(v), 3) for k, v in sorted(zip(names, rf.feature_importances_), key=lambda x: -x[1])},
    }
    print(json.dumps(metrics, indent=1))

    # остаточна модель на всіх роках, прогноз на FORECAST_YEAR
    Xall, yall = xy(range(2014, Y1 + 1))
    rf.fit(Xall, yall)
    F = features(FORECAST_YEAR)
    Xf = F[mask]
    trees = np.stack([t.predict_proba(Xf)[:, 1] for t in rf.estimators_])   # дерева × зразки
    risk, unc = trees.mean(0), trees.std(0)
    R = np.zeros((12, H, W)); U = np.zeros((12, H, W))
    R[mask], U[mask] = risk, unc
    months = []
    for mi in range(12):
        r, u = R[mi], U[mi]
        thr = max(np.quantile(r[inside], .9), 0.02)
        sel = inside & (r >= thr)
        cells = [{"lat": round(float(lat_c[i, j]), 3), "lon": round(float(lon_c[i, j]), 3),
                  "risk": round(float(r[i, j]), 3), "unc": round(float(u[i, j]), 3)}
                 for i, j in zip(*np.nonzero(sel))]
        cells.sort(key=lambda c: -c["risk"])
        months.append({"month": mi + 1, "mean_risk": round(float(r[inside].mean()), 4), "cells": cells[:600]})
    out = {"model": "RandomForestClassifier(200 trees)", "grid_deg": STEP, "forecast_year": FORECAST_YEAR,
           "target": "VIIRS S-NPP vegetation hotspot in the cell during the month",
           "uncertainty": "standard deviation of the 200 trees' probabilities", "metrics": metrics, "months": months}
    with open(os.path.join(ROOT, "data", "risk.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    cal_p = os.path.join(ROOT, "data", "calendar.json")
    with open(cal_p, encoding="utf-8") as f:
        cal = json.load(f)
    cal["risk"] = out
    with open(cal_p, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, separators=(",", ":"))
    print("місяці:", [(m["month"], len(m["cells"]), m["mean_risk"]) for m in months])


if __name__ == "__main__":
    main()

"""Кореляція MODIS ↔ VIIRS за спільні роки (порада ментора): у часі і в просторі.

1. Матриця 12×12: місяць MODIS × місяць VIIRS, кореляція Пірсона кількості точок за роками.
   Діагональ — чи однаково два сенсори бачать «той самий місяць»; поза діагоналлю — сезонні зв'язки.
2. Ряд за місяцями (усі місяці 2012–2026 підряд): Пірсон і Спірмен.
3. Простір: сітка 0,1° (~10 км), сума точок кожного сенсора в клітинці — кореляція.

    python harmonize/correlation.py   -> data/correlation.json, submission/figs/d_correlation.png
"""
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
Y0, Y1 = 2012, 2025          # повні роки, коли працювали обидва сенсори
GRID = 0.1


def load(pattern):
    fs = sorted(glob.glob(os.path.join(RAW, pattern)))
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    if "type" in d.columns:
        d = d[d["type"] == 0]                     # лише рослинність, без промисловості
    d["date"] = pd.to_datetime(d["acq_date"])
    return d[(d.date.dt.year >= Y0) & (d.date.dt.year <= Y1)]


def main():
    mo, vi = load("MODIS_SP_*.csv"), load("VIIRS_SNPP_SP_*.csv")
    idx = pd.MultiIndex.from_product([range(Y0, Y1 + 1), range(1, 13)], names=["y", "m"])
    cnt = lambda d: d.groupby([d.date.dt.year.rename("y"), d.date.dt.month.rename("m")]).size().reindex(idx, fill_value=0)
    cm, cv = cnt(mo), cnt(vi)

    # 1. матриця 12×12
    M = cm.unstack("m")   # роки × місяці
    V = cv.unstack("m")
    mat = np.full((12, 12), np.nan)
    for i in range(12):
        for j in range(12):
            a, b = M[i + 1].values, V[j + 1].values
            if a.std() > 0 and b.std() > 0:
                mat[i, j] = np.corrcoef(a, b)[0, 1]
    diag = [None if np.isnan(mat[i, i]) else round(float(mat[i, i]), 3) for i in range(12)]

    # 2. весь ряд
    r_month = float(np.corrcoef(cm.values, cv.values)[0, 1])
    r_month_log = float(np.corrcoef(np.log1p(cm.values), np.log1p(cv.values))[0, 1])
    rho_month = float(pd.Series(cm.values).corr(pd.Series(cv.values), method="spearman"))
    ym, yv = cm.groupby("y").sum(), cv.groupby("y").sum()
    r_year = float(np.corrcoef(ym.values, yv.values)[0, 1])

    # 3. простір
    key = lambda d: list(zip(np.floor(d.latitude / GRID).astype(int), np.floor(d.longitude / GRID).astype(int)))
    sm = pd.Series(1, index=pd.MultiIndex.from_tuples(key(mo))).groupby(level=[0, 1]).sum()
    sv = pd.Series(1, index=pd.MultiIndex.from_tuples(key(vi))).groupby(level=[0, 1]).sum()
    sp = pd.concat([sm.rename("m"), sv.rename("v")], axis=1).fillna(0)
    r_space = float(np.corrcoef(sp.m, sp.v)[0, 1])
    r_space_log = float(np.corrcoef(np.log1p(sp.m), np.log1p(sp.v))[0, 1])
    rho_space = float(sp.m.corr(sp.v, method="spearman"))

    out = {
        "years": [Y0, Y1], "modis": "MODIS Terra+Aqua (type 0)", "viirs": "VIIRS S-NPP (type 0)",
        "monthly_series": {"pearson": round(r_month, 3), "pearson_log": round(r_month_log, 3),
                           "spearman": round(rho_month, 3), "n": int(len(cm))},
        "yearly": {"pearson": round(r_year, 3), "n": int(len(ym))},
        "spatial_0_1deg": {"pearson": round(r_space, 3), "pearson_log": round(r_space_log, 3),
                           "spearman": round(rho_space, 3), "cells": int(len(sp))},
        "month_matrix_diagonal": diag,
        "month_matrix": [[None if np.isnan(x) else round(float(x), 3) for x in row] for row in mat],
    }
    with open(os.path.join(ROOT, "data", "correlation.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "month_matrix"}, ensure_ascii=False, indent=1))
    cal_p = os.path.join(ROOT, "data", "calendar.json")      # щоб сайт показав кореляцію у вкладці календаря
    if os.path.exists(cal_p):
        with open(cal_p, encoding="utf-8") as f:
            cal = json.load(f)
        cal["correlation"] = out
        with open(cal_p, "w", encoding="utf-8") as f:
            json.dump(cal, f, ensure_ascii=False, separators=(",", ":"))

    # рисунок
    ink, dim = "#14281F", "#5B6B60"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": dim,
                         "axes.labelcolor": ink, "xtick.color": dim, "ytick.color": dim})
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.2), gridspec_kw={"width_ratios": [1.15, 1, 1]}, facecolor="#F2F4EC")
    mon = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    im = ax[0].imshow(mat, cmap="RdBu_r", vmin=-1, vmax=1)
    ax[0].set_xticks(range(12), mon); ax[0].set_yticks(range(12), mon)
    ax[0].set_xlabel("VIIRS S-NPP month"); ax[0].set_ylabel("MODIS month")
    ax[0].set_title("Correlation matrix, by year 2012–2025", color=ink, fontsize=12, loc="left")
    for i in range(12):
        v = mat[i, i]
        if not np.isnan(v):
            ax[0].text(i, i, f"{v:.2f}".replace("0.", "."), ha="center", va="center", fontsize=7.5,
                       color="white" if abs(v) > .6 else ink)
    fig.colorbar(im, ax=ax[0], fraction=.046, pad=.03).set_label("Pearson r")
    for a, (x, y, title, r, rho) in zip(ax[1:], [
            (cm.values, cv.values, "Every month 2012–2025", r_month, rho_month),
            (sp.m.values, sp.v.values, "Every 0.1° cell (~10 km)", r_space, rho_space)]):
        a.scatter(x + 1, y + 1, s=14, alpha=.55, color="#C2401C", edgecolors="none")
        a.set_xscale("log"); a.set_yscale("log")
        a.set_xlabel("MODIS hotspots + 1"); a.set_ylabel("VIIRS hotspots + 1")
        a.set_title(f"{title}\nPearson r = {r:.2f}, Spearman ρ = {rho:.2f}", color=ink, fontsize=12, loc="left")
        a.set_facecolor("#F2F4EC")
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.tight_layout()
    p = os.path.join(ROOT, "submission", "figs", "d_correlation.png")
    fig.savefig(p, dpi=130, facecolor=fig.get_facecolor())
    print("->", p)


if __name__ == "__main__":
    main()

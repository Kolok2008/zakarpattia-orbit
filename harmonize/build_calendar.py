"""Гармонізація MODIS і VIIRS для Закарпаття -> data/calendar.json + графіки для слайдів.

  python harmonize/build_calendar.py

Методика — harmonize/METHODOLOGY.md.
"""
import glob
import json
import math
import os
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "calendar.json")
FIGS = os.path.join(ROOT, "submission", "figs")
BBOX = [22.1, 47.9, 24.7, 49.1]

PAIR_KM = 1.5
PAIR_MIN = 60
GRID = 0.02
BOOT = 2000
RNG = np.random.default_rng(42)
TODAY = date.today()
BASE_YEARS = list(range(2001, 2026))           # повні роки для кліматології
OVERLAP_START = pd.Period("2012-02", "M")       # перший повний місяць S-NPP
SNPP_SP_END = pd.Period("2026-07", "M")

UA_MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень",
             "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]
def plural(n, one, few, many):
    n = abs(int(round(n)))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


UA_MONTHS_GEN = ["січні", "лютому", "березні", "квітні", "травні", "червні",
                 "липні", "серпні", "вересні", "жовтні", "листопаді", "грудні"]


# ---------------- завантаження ----------------
def load(source: str) -> pd.DataFrame:
    frames = []
    for p in sorted(glob.glob(os.path.join(RAW, f"{source}_*.csv"))):
        if os.path.getsize(p) == 0:
            continue
        try:
            frames.append(pd.read_csv(p))
        except pd.errors.EmptyDataError:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["source"] = source
    df["date"] = pd.to_datetime(df["acq_date"])
    hhmm = df["acq_time"].astype(int).astype(str).str.zfill(4)
    df["t"] = pd.to_datetime(df["acq_date"] + " " + hhmm.str[:2] + ":" + hhmm.str[2:], utc=True)
    return df


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def cell_key(lat, lon, g):
    return (np.floor(lat / g).astype(int), np.floor(lon / g).astype(int))


def main():
    raw = {s: load(s) for s in ["MODIS_SP", "MODIS_NRT", "VIIRS_SNPP_SP", "VIIRS_SNPP_NRT",
                                "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"]}
    sources_info = {}
    for s, df in raw.items():
        if len(df):
            sources_info[s] = {"from": df["acq_date"].min(), "to": df["acq_date"].max(), "n": int(len(df))}

    # ---- фільтр: лише рослинні пожежі ----
    # SP має колонку type (0 = рослинний пожежа, 2 = статичне джерело, напр. завод).
    # NRT цієї колонки не має -> прибираємо точки в клітинках 0.01°, де в архіві SP
    # є статичні джерела (type=2).
    static_cells = set()
    for s in ["MODIS_SP", "VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_SP"]:
        df = raw[s]
        if len(df) and "type" in df:
            st = df[df["type"] == 2]
            static_cells |= set(zip(*cell_key(st["latitude"].values, st["longitude"].values, 0.01)))
    removed = {}
    for s, df in raw.items():
        if not len(df):
            continue
        n0 = len(df)
        if "type" in df and df["type"].notna().any():
            df = df[df["type"] == 0]
        else:
            k = list(zip(*cell_key(df["latitude"].values, df["longitude"].values, 0.01)))
            df = df[[c not in static_cells for c in k]]
        removed[s] = n0 - len(df)
        raw[s] = df.copy()

    modis = pd.concat([raw["MODIS_SP"], raw["MODIS_NRT"]], ignore_index=True)
    snpp = pd.concat([raw["VIIRS_SNPP_SP"], raw["VIIRS_SNPP_NRT"]], ignore_index=True)
    n20 = pd.concat([raw["VIIRS_NOAA20_SP"], raw["VIIRS_NOAA20_NRT"]], ignore_index=True)
    n21 = pd.concat([raw["VIIRS_NOAA21_SP"], raw["VIIRS_NOAA21_NRT"]], ignore_index=True)
    # уникнути подвійних точок SP/NRT на межі
    for d in (modis, snpp, n20, n21):
        d.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time"], inplace=True)

    # ---------------- пари Aqua MODIS <-> S-NPP VIIRS ----------------
    aqua = modis[(modis["satellite"] == "Aqua") & (modis["date"] >= "2012-02-01") & (modis["date"] <= "2026-07-31")]
    sv = snpp[snpp["date"] <= "2026-07-31"]
    sv_by_day = {d: g for d, g in sv.groupby("acq_date")}
    n_pairs, vpm, offsets, frp_m, frp_v = 0, [], [], [], []
    for _, row in aqua.iterrows():
        g = sv_by_day.get(row["acq_date"])
        if g is None:
            continue
        dt = (g["t"] - row["t"]).abs().dt.total_seconds() / 60
        g = g[dt <= PAIR_MIN]
        if not len(g):
            continue
        dist = haversine_m(row["latitude"], row["longitude"], g["latitude"].values, g["longitude"].values)
        near = g[dist <= PAIR_KM * 1000]
        if not len(near):
            continue
        n_pairs += 1
        vpm.append(len(near))
        offsets.append(float(dist.min()))
        if row["frp"] > 0 and near["frp"].sum() > 0:
            frp_m.append(row["frp"])
            frp_v.append(near["frp"].sum())
    slope = intercept = float("nan")
    if len(frp_m) >= 10:
        slope, intercept = np.polyfit(np.log10(frp_m), np.log10(frp_v), 1)
    pairs = {
        "n_modis": int(len(aqua)), "n_pairs": int(n_pairs),
        "match_rate": round(n_pairs / len(aqua), 3) if len(aqua) else 0.0,
        "viirs_per_modis": round(float(np.mean(vpm)), 2) if vpm else 0.0,
        "median_offset_m": int(np.median(offsets)) if offsets else 0,
        "frp_slope": round(float(slope), 3), "frp_intercept": round(float(intercept), 3),
    }
    # зворотний напрямок: скільки VIIRS-точок мають MODIS-пару (для пояснення різниці чутливості)
    print("pairs", pairs)

    # ---------------- місячні ряди ----------------
    end_p = pd.Period(TODAY, "M")
    months = pd.period_range("2001-01", end_p, freq="M")

    def monthly(df):
        if not len(df):
            return pd.Series(0, index=months)
        return df.groupby(df["date"].dt.to_period("M")).size().reindex(months, fill_value=0)

    m_modis = monthly(modis)
    m_snpp = monthly(snpp)
    m_n20 = monthly(n20)
    m_n21 = monthly(n21)
    snpp_first = pd.Period(snpp["date"].min(), "M") if len(snpp) else None
    snpp_last = pd.Period(snpp["date"].max(), "M") if len(snpp) else None
    n20_first = pd.Period("2023-01", "M")  # NOAA-20 скачано з 2023 (економія ліміту)

    # перекриття MODIS і S-NPP: повні місяці
    ov = [p for p in months if OVERLAP_START <= p <= SNPP_SP_END]
    ov_df = pd.DataFrame({"m": [p.month for p in ov], "y": [p.year for p in ov],
                          "modis": [m_modis[p] for p in ov], "viirs": [m_snpp[p] for p in ov]})

    def ratio_for(df, month):
        d = df[df["m"] == month]
        sm, sv_ = d["modis"].sum(), d["viirs"].sum()
        return (sv_ / sm) if sm > 0 else np.nan, d

    global_ratio = ov_df["viirs"].sum() / max(ov_df["modis"].sum(), 1)
    gb = []
    all_years = ov_df["y"].unique()
    for _ in range(BOOT):
        ys = RNG.choice(all_years, size=len(all_years), replace=True)
        bd = pd.concat([ov_df[ov_df["y"] == y] for y in ys])
        if bd["modis"].sum() > 0:
            gb.append(bd["viirs"].sum() / bd["modis"].sum())
    global_ci = tuple(np.percentile(gb, [10, 90]))
    factors = []
    for mth in range(1, 13):
        r, d = ratio_for(ov_df, mth)
        years = d["y"].unique()
        boots = []
        for _ in range(BOOT):
            ys = RNG.choice(years, size=len(years), replace=True)
            bd = pd.concat([d[d["y"] == y] for y in ys])
            sm = bd["modis"].sum()
            if sm > 0:
                boots.append(bd["viirs"].sum() / sm)
        if np.isnan(r) or d["modis"].sum() < 20:
            # мало MODIS-точок у цьому місяці -> загальний коефіцієнт і його інтервал
            r, (lo, hi) = global_ratio, global_ci
        else:
            lo, hi = (np.percentile(boots, [10, 90]) if boots else (r, r))
        factors.append({"month": mth, "ratio": round(float(r), 3), "lo": round(float(lo), 3),
                        "hi": round(float(hi), 3), "n_years": int(len(years))})
    fac = {f["month"]: f for f in factors}

    # NOAA-20 -> S-NPP: коефіцієнт по перекриттю 2018-04..2026-07
    ovn = [p for p in months if n20_first <= p <= SNPP_SP_END]
    nd = pd.DataFrame({"y": [p.year for p in ovn], "n20": [m_n20[p] for p in ovn], "snpp": [m_snpp[p] for p in ovn]})
    noaa_ratio = nd["snpp"].sum() / max(nd["n20"].sum(), 1)
    boots = []
    yrs = nd["y"].unique()
    for _ in range(BOOT):
        ys = RNG.choice(yrs, size=len(yrs), replace=True)
        bd = pd.concat([nd[nd["y"] == y] for y in ys])
        if bd["n20"].sum() > 0:
            boots.append(bd["snpp"].sum() / bd["n20"].sum())
    nlo, nhi = np.percentile(boots, [10, 90]) if boots else (noaa_ratio, noaa_ratio)
    noaa_factor = {"ratio": round(float(noaa_ratio), 3), "lo": round(float(nlo), 3), "hi": round(float(nhi), 3)}

    # гармонізований ряд (VIIRS S-NPP еквівалент)
    monthly_rows, harm = [], {}
    for p in months:
        modis_n = int(m_modis[p])
        viirs_n = int(m_snpp[p]) if (snpp_first and snpp_first <= p <= snpp_last) else None
        n20_n = int(m_n20[p]) if p >= n20_first else None
        if p >= OVERLAP_START and viirs_n is not None and p <= snpp_last and not (p == snpp_last and snpp_last > SNPP_SP_END and p == end_p):
            basis, h, lo, hi = "viirs", float(viirs_n), float(viirs_n), float(viirs_n)
        elif p > SNPP_SP_END and n20_n is not None:
            basis = "noaa_scaled"
            h = n20_n * noaa_factor["ratio"]
            lo, hi = n20_n * noaa_factor["lo"], n20_n * noaa_factor["hi"]
        else:
            f = fac[p.month]
            basis, h, lo, hi = "modis_scaled", modis_n * f["ratio"], modis_n * f["lo"], modis_n * f["hi"]
        harm[p] = h
        monthly_rows.append({"ym": str(p), "modis": modis_n, "viirs": viirs_n, "noaa20": n20_n,
                             "harmonized": round(h, 2), "harmonized_lo": round(lo, 2),
                             "harmonized_hi": round(hi, 2), "basis": basis})

    # ---------------- перевірка leave-one-year-out ----------------
    preds, obs, preds_naive = [], [], []
    yearly_obs, yearly_pred, yearly_naive = [], [], []
    for y in sorted(ov_df["y"].unique()):
        train = ov_df[ov_df["y"] != y]
        test = ov_df[ov_df["y"] == y]
        g = train["viirs"].sum() / max(train["modis"].sum(), 1)
        ys_pred = ys_obs = ys_naive = 0.0
        for _, r in test.iterrows():
            tm = train[train["m"] == r["m"]]
            rr = tm["viirs"].sum() / tm["modis"].sum() if tm["modis"].sum() >= 20 else g
            pr = r["modis"] * rr
            ys_pred += pr; ys_obs += r["viirs"]; ys_naive += r["modis"]
            if r["viirs"] > 0:
                preds.append(pr); obs.append(r["viirs"]); preds_naive.append(r["modis"])
        if test["m"].nunique() == 12:
            yearly_obs.append(ys_obs); yearly_pred.append(ys_pred); yearly_naive.append(ys_naive)
    preds, obs, preds_naive = map(np.array, (preds, obs, preds_naive))

    def mape(p, o):
        m = o > 0
        return float(np.mean(np.abs(p[m] - o[m]) / o[m]) * 100)

    def r2(p, o):
        ss = np.sum((o - o.mean()) ** 2)
        return float(1 - np.sum((o - p) ** 2) / ss) if ss > 0 else float("nan")

    validation = {"method": "leave-one-year-out", "mape": round(mape(preds, obs), 1),
                  "r2": round(r2(preds, obs), 3), "n": int(len(obs))}
    yo, yp, yn = map(np.array, (yearly_obs, yearly_pred, yearly_naive))
    extra_val = {
        "monthly_wape": round(float(np.sum(np.abs(preds - obs)) / np.sum(obs) * 100), 1),
        "monthly_naive_wape": round(float(np.sum(np.abs(preds_naive - obs)) / np.sum(obs) * 100), 1),
        "monthly_naive_mape": round(mape(preds_naive, obs), 1),
        "monthly_naive_r2": round(r2(preds_naive, obs), 3),
        "yearly_mape": round(mape(yp, yo), 1) if len(yo) else None,
        "yearly_r2": round(r2(yp, yo), 3) if len(yo) else None,
        "yearly_naive_mape": round(mape(yn, yo), 1) if len(yo) else None,
        "n_years": int(len(yo)),
    }
    print("validation", validation, extra_val)

    # ---------------- кліматологія ----------------
    hs = pd.Series(harm)
    clim = []
    stats = {}
    for mth in range(1, 13):
        vals = np.array([hs[pd.Period(f"{y}-{mth:02d}", "M")] for y in BASE_YEARS])
        stats[mth] = (vals.mean(), vals.std(ddof=1))
        clim.append({"month": mth, "mean": round(float(vals.mean()), 2),
                     "p10": round(float(np.percentile(vals, 10)), 2),
                     "p90": round(float(np.percentile(vals, 90)), 2)})

    # ---------------- критичні вікна (по днях року) ----------------
    def daily(df):
        return df.groupby("date").size()

    d_modis, d_snpp = daily(modis), daily(snpp)
    days = pd.date_range("2001-01-01", "2025-12-31", freq="D")
    dh = []
    for d in days:
        p = pd.Period(d, "M")
        if OVERLAP_START <= p <= SNPP_SP_END:
            dh.append(d_snpp.get(d, 0))
        else:
            dh.append(d_modis.get(d, 0) * fac[d.month]["ratio"])
    dhs = pd.Series(dh, index=days)
    doy = dhs.groupby(dhs.index.dayofyear).mean().reindex(range(1, 367), fill_value=0)
    doy = doy.iloc[:365]
    smooth = pd.Series(np.convolve(np.r_[doy.values[-7:], doy.values, doy.values[:7]], np.ones(15) / 15, "valid"),
                       index=doy.index)
    thr = smooth.mean() * 1.5
    hot = smooth >= thr
    windows, start = [], None
    for dd in list(smooth.index) + [None]:
        on = dd is not None and hot[dd]
        if on and start is None:
            start = dd
        if not on and start is not None:
            end = (dd - 1) if dd else 365
            if end - start >= 6:
                windows.append((start, end))
            start = None

    def doy_md(n):
        d = date(2025, 1, 1).toordinal() + n - 1
        return date.fromordinal(d).strftime("%m-%d")

    def label(s, e):
        mid = date.fromordinal(date(2025, 1, 1).toordinal() + (s + e) // 2 - 1).month
        if mid in (2, 3, 4, 5):
            return "Весняне спалювання сухої трави й стерні"
        if mid in (6, 7, 8):
            return "Літній сезон: жнива й сухостій"
        if mid in (9, 10, 11):
            return "Осіннє спалювання листя й рослинних решток"
        return "Зимові підпали"

    critical = []
    for s, e in windows:
        peak = float(smooth.loc[s:e].max())
        critical.append({"from": doy_md(s), "to": doy_md(e), "label": label(s, e)})

    # ---------------- аномалія 2026 ----------------
    cy = TODAY.year
    cur = []
    for mth in range(1, TODAY.month + 1):
        p = pd.Period(f"{cy}-{mth:02d}", "M")
        v = float(hs.get(p, 0.0))
        mu, sd = stats[mth]
        z = (v - mu) / sd if sd > 0 else 0.0
        cur.append({"month": mth, "value": round(v, 2), "z": round(float(z), 2)})

    # ---------------- клітинки повторюваності ----------------
    allp = pd.concat([modis, snpp, n20, n21], ignore_index=True)
    ci, cj = cell_key(allp["latitude"].values, allp["longitude"].values, GRID)
    allp = allp.assign(ci=ci, cj=cj)
    cells = []
    for (i, j), g in allp.groupby(["ci", "cj"]):
        cells.append({"lat": round((i + 0.5) * GRID, 4), "lon": round((j + 0.5) * GRID, 4),
                      "fire_days": int(g["acq_date"].nunique()),
                      "years": int(g["date"].dt.year.nunique()),
                      "last": g["acq_date"].max()})
    cells.sort(key=lambda c: -c["fire_days"])

    # ---------------- висновки ----------------
    peak_m = max(clim, key=lambda c: c["mean"])
    total_mean = sum(c["mean"] for c in clim)
    spring = sum(c["mean"] for c in clim if c["month"] in (3, 4))
    ann = {y: sum(hs[pd.Period(f"{y}-{m:02d}", "M")] for m in range(1, 13)) for y in BASE_YEARS}
    raw_modis_y = {y: int(m_modis[[p for p in months if p.year == y]].sum()) for y in BASE_YEARS}
    raw_snpp_y = {y: int(m_snpp[[p for p in months if p.year == y]].sum()) for y in range(2012, 2026)}
    jump = (np.mean([raw_snpp_y[y] for y in range(2013, 2026)]) /
            max(np.mean([raw_modis_y[y] for y in range(2001, 2012)]), 1))
    top_y = max(ann, key=ann.get)
    rep = [c for c in cells if c["years"] >= 5]
    insights = [
        f"VIIRS (375 м) бачить у {global_ratio:.1f} раза більше точок, ніж MODIS (1 км), над тим самим Закарпаттям у 2012–2026 роках.",
        f"Без гармонізації склеєний ряд «MODIS до 2011, VIIRS з 2012» дає стрибок ×{jump:.1f} — це зміна сенсора, а не реальне зростання пожеж.",
        f"Пік горіння — {UA_MONTHS[peak_m['month'] - 1]}: у середньому {peak_m['mean']:.0f} {plural(peak_m['mean'], 'точка', 'точки', 'точок')} (VIIRS-еквівалент) за місяць.",
        f"Березень і квітень дають {spring / total_mean * 100:.0f}% усіх точок року — це весняне спалювання сухої трави.",
        f"Перевірка «без одного року»: річну кількість точок VIIRS вдається відновити з MODIS із похибкою {extra_val['yearly_mape']:.0f}% (без гармонізації — {extra_val['yearly_naive_mape']:.0f}%).",
        f"{len(rep)} {plural(len(rep), 'клітинка', 'клітинки', 'клітинок')} 2×2 км горіли щонайменше в 5 різних роках — повторні місця спалювання, які варто патрулювати першими.",
    ]
    EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
                 "September", "October", "November", "December"]
    insights_en = [
        f"VIIRS (375 m) sees {global_ratio:.1f}× more hotspots than MODIS (1 km) over the same Zakarpattia, 2012–2026.",
        f"Without harmonization, the spliced series “MODIS until 2011, VIIRS from 2012” jumps ×{jump:.1f} — a sensor change, not more fires.",
        f"Peak burning month is {EN_MONTHS[peak_m['month'] - 1]}: on average {peak_m['mean']:.0f} hotspots (VIIRS-equivalent) per month.",
        f"March and April account for {spring / total_mean * 100:.0f}% of all hotspots in a year — spring burning of dry grass.",
        f"Leave-one-year-out check: annual VIIRS counts are recovered from MODIS with {extra_val['yearly_mape']:.0f}% error (without harmonization — {extra_val['yearly_naive_mape']:.0f}%).",
        f"{len(rep)} grid cells of 2×2 km burned in at least 5 different years — repeat burning sites to patrol first.",
    ]
    LABEL_EN = {"Весняне спалювання сухої трави й стерні": "Spring burning of dry grass and stubble",
                "Осіннє спалювання листя й рослинних решток": "Autumn burning of leaves and crop residue",
                "Зимові підпали": "Winter burning",
                "Літній сезон: жнива й сухостій": "Summer: harvest and dry vegetation"}
    for c in critical:
        c["label_en"] = LABEL_EN.get(c["label"], c["label"])
    if False:
        insights.append(
            f"У {pairs['match_rate'] * 100:.0f}% випадків, коли MODIS Aqua бачив вогонь, S-NPP VIIRS бачив його теж "
            f"(у середньому {pairs['viirs_per_modis']:.1f} точки VIIRS на одну точку MODIS).")

    out = {
        "region": "Закарпаття", "bbox": BBOX,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources_info, "monthly": monthly_rows, "factors": factors,
        "noaa_factor": noaa_factor, "validation": {**validation, "yearly_mape": round(extra_val["yearly_mape"], 1), "yearly_naive_mape": round(extra_val["yearly_naive_mape"], 1), "yearly_r2": round(extra_val["yearly_r2"], 3)}, "pairs": pairs,
        "climatology": clim, "critical_windows": critical,
        "current_year": {"year": cy, "months": cur},
        "cells": cells, "insights": insights, "insights_en": insights_en,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(ROOT, "data", "validation_extra.json"), "w", encoding="utf-8") as f:
        json.dump({"validation_extra": extra_val, "filtered_out": removed,
                   "annual_harmonized": {y: round(v, 1) for y, v in ann.items()},
                   "annual_raw_modis": raw_modis_y, "annual_raw_snpp": raw_snpp_y,
                   "global_ratio": round(float(global_ratio), 3), "jump_naive": round(float(jump), 2)},
                  f, ensure_ascii=False, indent=1)
    print("insights:"); [print(" -", s) for s in insights]
    print(f"cells: {len(cells)}, critical: {critical}")
    make_figs(months, m_modis, m_snpp, hs, monthly_rows, clim, ann, raw_modis_y, raw_snpp_y)


# ---------------- графіки ----------------
def make_figs(months, m_modis, m_snpp, hs, monthly_rows, clim, ann, raw_modis_y, raw_snpp_y):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(FIGS, exist_ok=True)
    SPRUCE, EMBER, AMBER, FRESH, LICHEN, GREY = "#0E2620", "#E4572E", "#E9A23B", "#7FB069", "#D8DEC8", "#8A958A"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13, "axes.edgecolor": GREY,
                         "axes.labelcolor": SPRUCE, "xtick.color": SPRUCE, "ytick.color": SPRUCE,
                         "axes.spines.top": False, "axes.spines.right": False})

    # (a) ступенька
    years = list(range(2001, 2026))
    naive = [raw_modis_y[y] if y < 2012 else raw_snpp_y.get(y, 0) for y in years]
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=150)
    ax.plot(years, [raw_modis_y[y] for y in years], color=GREY, lw=2, label="MODIS raw (1 km)")
    ax.plot(years, naive, color=SPRUCE, lw=2.2, ls=(0, (5, 3)), label="Naive splice: MODIS until 2011, VIIRS after")
    ax.plot(years, [ann[y] for y in years], color=EMBER, lw=3.2, label="Harmonized, VIIRS-equivalent (= VIIRS from 2012)")
    pre = np.mean([raw_modis_y[y] for y in range(2001, 2012)])
    post = np.mean([raw_snpp_y[y] for y in range(2013, 2026)])
    ax.annotate(f"×{post / pre:.1f} jump in the naive series:\nsensor change, not more fires",
                xy=(2011.6, 900), xytext=(2003.2, 1250), color=SPRUCE, fontsize=12,
                arrowprops=dict(arrowstyle="->", color=SPRUCE, lw=1.2))
    ax.axvline(2012, color=LICHEN, lw=6, zorder=0)
    ax.annotate("VIIRS starts (2012)", xy=(2012, 0), xytext=(2012.25, ax.get_ylim()[1] * 0.04),
                color=SPRUCE, fontsize=11)
    ax.set_ylabel("Hotspots per year, Zakarpattia")
    ax.set_title("Harmonization removes the 2012 sensor step", loc="left", fontsize=17, color=SPRUCE, fontweight="bold")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=3, fontsize=10.5)
    ax.set_xlim(2000.5, 2025.5)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "a_sensor_step.png")); plt.close(fig)

    # (b) календар рік × місяць
    yrs = list(range(2001, TODAY.year + 1))
    grid = np.full((len(yrs), 12), np.nan)
    for r in monthly_rows:
        y, m = int(r["ym"][:4]), int(r["ym"][5:])
        if pd.Period(r["ym"], "M") <= pd.Period(TODAY, "M"):
            grid[yrs.index(y), m - 1] = r["harmonized"]
    cmap = LinearSegmentedColormap.from_list("fire", ["#F4F6EF", LICHEN, AMBER, EMBER, "#7A1F0B"])
    fig, ax = plt.subplots(figsize=(10, 9), dpi=150)
    im = ax.imshow(np.log1p(grid), aspect="auto", cmap=cmap)
    ax.set_xticks(range(12)); ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(yrs))); ax.set_yticklabels(yrs, fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    ticks = [0, 10, 50, 200, 1000]
    cb.set_ticks(np.log1p(ticks)); cb.set_ticklabels([str(t) for t in ticks])
    cb.set_label("Hotspots / month (VIIRS-equivalent)")
    ax.set_title("Burning-activity calendar, Zakarpattia 2001–2026", loc="left", fontsize=17, color=SPRUCE, fontweight="bold")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "b_calendar.png")); plt.close(fig)

    # (c) кліматологія
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=150)
    mx = np.arange(1, 13)
    mean = [c["mean"] for c in clim]
    ax.bar(mx, mean, color=[EMBER if m in (3, 4) else LICHEN for m in mx], width=0.7)
    ax.errorbar(mx, mean, yerr=[[m - c["p10"] for m, c in zip(mean, clim)], [c["p90"] - m for m, c in zip(mean, clim)]],
                fmt="none", ecolor=SPRUCE, elinewidth=1.4, capsize=5)
    ax.set_xticks(mx); ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_ylabel("Hotspots / month (mean, 2001–2025)")
    ax.set_title("Spring is fire season: mean with 10–90% range", loc="left", fontsize=17, color=SPRUCE, fontweight="bold")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "c_climatology.png")); plt.close(fig)
    print("figs ->", FIGS)


if __name__ == "__main__":
    main()

"""Перевірка геометрії пікселів (поля scan/track FIRMS) і день/ніч для MODIS і VIIRS S-NPP.

    python harmonize/sensor_check.py   -> data/sensor_check.json
"""
import glob
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    d = pd.concat([pd.read_csv(f) for f in glob.glob(os.path.join(ROOT, "data", "raw", p))])
    d = d[d["type"] == 0]
    d["date"] = pd.to_datetime(d.acq_date)
    d["area"] = d.scan * d.track
    return d


def main():
    m, v = load("MODIS_SP_*.csv"), load("VIIRS_SNPP_SP_*.csv")
    out = {}
    for n, d in (("modis", m), ("viirs_snpp", v)):
        a = d.area
        out[n] = {"pixel_area_km2_median": round(float(a.median()), 3), "p90": round(float(a.quantile(.9)), 2),
                  "max": round(float(a.max()), 2), "share_over_2x_nadir": round(float((a > 2 * a.min()).mean()), 3),
                  "day_share": round(float((d.daynight == "D").mean()), 3)}
    ov = lambda d: d[(d.date.dt.year >= 2012) & (d.date.dt.year <= 2025)]
    mo, vo = ov(m), ov(v)
    g = lambda d: d.groupby([d.date.dt.year.rename("y"), d.date.dt.month.rename("mo")])
    c = pd.DataFrame({"m": g(mo).size(), "v": g(vo).size(), "ma": g(mo).area.mean(), "va": g(vo).area.mean()}).dropna()
    c = c[c.m >= 5]
    c["r"] = np.log(c.v / c.m)
    c["res"] = c.r - c.groupby(level="mo").r.transform("mean")
    out["monthly_ratio_residual_vs_area"] = {"n_months": int(len(c)),
                                             "r_modis_area": round(float(np.corrcoef(c.res, c.ma)[0, 1]), 3),
                                             "r_viirs_area": round(float(np.corrcoef(c.res, c.va)[0, 1]), 3)}
    with open(os.path.join(ROOT, "data", "sensor_check.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

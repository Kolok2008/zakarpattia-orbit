"""Завантаження архіву NASA FIRMS по Закарпаттю (2001 — сьогодні).

Кешує сирі CSV у data/raw/{SOURCE}_{YYYY}.csv. Перезапуск докачує лише відсутні роки
(рік вважається готовим, коли є файл з позначкою повноти data/raw/{SOURCE}_{YYYY}.done).

  python harmonize/fetch_archive.py
  FIRMS_MAP_KEY=... python harmonize/fetch_archive.py
"""
import csv
import io
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

KEY = os.environ.get("FIRMS_MAP_KEY", "")  # задай свій ключ: set FIRMS_MAP_KEY=...
BBOX = "22.1,47.9,24.7,49.1"
API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{bbox}/{days}/{d}"
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "raw")

# Доступність джерел (з /api/data_availability, 2026-11-07)
SOURCES = {
    "MODIS_SP": ("2001-01-01", "2026-08-31"),
    "VIIRS_SNPP_SP": ("2012-01-20", "2026-07-31"),
    # NOAA-20: лише для калібрування до S-NPP (вистачає 2023-2026, щоб берегти ліміт)
    "VIIRS_NOAA20_SP": ("2023-01-01", "2026-07-31"),
    "MODIS_NRT": ("2026-09-01", None),
    "VIIRS_SNPP_NRT": ("2026-08-01", None),
    "VIIRS_NOAA20_NRT": ("2026-08-01", None),
    "VIIRS_NOAA21_NRT": ("2026-08-01", None),
}

# Ліміт NASA: 5000 "транзакцій" / 10 хв; запит на N днів коштує ~2N транзакцій (виміряно)
MAX_PER_10MIN = 4600
THREADS = 6


class RateLimiter:
    def __init__(self, n, window=600):
        self.n, self.window, self.t = n, window, deque()
        self.lock = threading.Lock()
        self.total = 0

    def wait(self, cost=1):
        while True:
            with self.lock:
                now = time.time()
                while self.t and now - self.t[0][0] > self.window:
                    self.t.popleft()
                if sum(c for _, c in self.t) + cost <= self.n:
                    self.t.append((now, cost))
                    self.total += 1
                    return
                sleep = self.window - (now - self.t[0][0]) + 1
            print(f"  ліміт: чекаю {sleep:.0f} с", flush=True)
            time.sleep(min(sleep, 30))


RL = RateLimiter(MAX_PER_10MIN)


def get(src, d, days):
    url = API.format(key=KEY, src=src, bbox=BBOX, days=days, d=d.isoformat())
    for attempt in range(8):
        RL.wait(2 * days + 1)
        try:
            r = requests.get(url, timeout=60)
            txt = r.text
            if r.status_code == 200 and not txt.lstrip().lower().startswith(("invalid", "exceeded", "error")):
                return txt
            print(f"  {src} {d}: {r.status_code} {txt[:80]!r}", flush=True)
            if "exceed" in txt.lower() or r.status_code == 429:
                time.sleep(120)
        except requests.RequestException as e:
            print(f"  {src} {d}: {e}", flush=True)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"не вдалося {src} {d}")


def fetch_year(src, year, start, end):
    path = os.path.join(RAW, f"{src}_{year}.csv")
    done = path.replace(".csv", ".done")
    is_current = end >= date.today() - timedelta(days=1)
    if os.path.exists(done) and not is_current:
        return 0
    lo = max(start, date(year, 1, 1))
    hi = min(end, date(year, 12, 31))
    chunks = []
    d = lo
    while d <= hi:
        days = min(5, (hi - d).days + 1)
        chunks.append((d, days))
        d += timedelta(days=days)
    header, rows = None, []
    with ThreadPoolExecutor(THREADS) as ex:
        for txt in ex.map(lambda c: get(src, c[0], c[1]), chunks):
            lines = txt.strip().splitlines()
            if not lines:
                continue
            if header is None:
                header = lines[0]
            rows += [ln for ln in lines[1:] if ln.strip()]
    with open(path, "w", encoding="utf-8") as f:
        if header:
            f.write(header + "\n")
            f.write("\n".join(sorted(set(rows))) + ("\n" if rows else ""))
    if not is_current:
        open(done, "w").close()
    print(f"{src} {year}: {len(chunks)} запитів, {len(set(rows))} точок", flush=True)
    return len(chunks)


def main():
    os.makedirs(RAW, exist_ok=True)
    today = date.today()
    for src, (a, b) in SOURCES.items():
        start = date.fromisoformat(a)
        end = date.fromisoformat(b) if b else today
        for year in range(start.year, end.year + 1):
            fetch_year(src, year, start, end)
    print(f"Готово. Запитів до NASA за запуск: {RL.total}")


if __name__ == "__main__":
    sys.exit(main())

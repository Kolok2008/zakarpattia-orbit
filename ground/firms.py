"""Гарячі точки NASA FIRMS + об'єднання MODIS і VIIRS (суть задачі хакатону)."""
import csv
import io
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import requests

import config

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}"

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # Windows без tzdata
    KYIV = None


@dataclass
class Hotspot:
    lat: float
    lon: float
    date: str
    time_utc: str
    satellite: str
    instrument: str
    confidence: str
    frp_mw: float
    source: str

    @property
    def when(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.time_utc}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)

    @property
    def local_time(self) -> str:
        t = self.when.astimezone(KYIV) if KYIV else self.when
        return t.strftime("%d.%m %H:%M") + ("" if KYIV else " UTC")

    @property
    def sensor(self) -> str:
        return {"N21": "VIIRS NOAA-21", "N20": "VIIRS NOAA-20", "N": "VIIRS Suomi NPP",
                "Terra": "MODIS Terra", "Aqua": "MODIS Aqua"}.get(self.satellite, f"{self.instrument} {self.satellite}")

    def distance_km(self, lat: float, lon: float) -> float:
        return haversine_km(self.lat, self.lon, lat, lon)


@dataclass
class Cluster:
    """Одне місце, яке бачили один або кілька супутників."""
    spots: List[Hotspot] = field(default_factory=list)

    @property
    def lat(self): return sum(s.lat for s in self.spots) / len(self.spots)

    @property
    def lon(self): return sum(s.lon for s in self.spots) / len(self.spots)

    @property
    def instruments(self): return sorted({s.instrument for s in self.spots})

    @property
    def sensors(self): return sorted({s.sensor for s in self.spots})

    @property
    def latest(self) -> Hotspot: return max(self.spots, key=lambda s: s.when)

    @property
    def frp_max(self): return max(s.frp_mw for s in self.spots)

    @property
    def confirmed(self) -> bool:
        """Підтверджено і MODIS, і VIIRS — або кількома проходами."""
        return len(self.instruments) > 1 or len(self.spots) > 1

    def distance_km(self, lat, lon): return haversine_km(self.lat, self.lon, lat, lon)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_csv(text: str, source: str) -> List[Hotspot]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if "latitude" not in row:
            continue
        out.append(Hotspot(
            lat=float(row["latitude"]), lon=float(row["longitude"]),
            date=row.get("acq_date", ""), time_utc=row.get("acq_time", "0000").zfill(4),
            satellite=row.get("satellite", ""), instrument=row.get("instrument", ""),
            confidence=str(row.get("confidence", "")), frp_mw=float(row.get("frp") or 0),
            source=source))
    return out


def fetch_hotspots() -> List[Hotspot]:
    key = os.environ.get("FIRMS_MAP_KEY") or config.FIRMS_MAP_KEY
    if not key:
        raise RuntimeError("Немає ключа FIRMS_MAP_KEY у config.py")
    bbox = ",".join(str(v) for v in config.AREA_BBOX)
    spots: List[Hotspot] = []
    for src in config.FIRMS_SOURCES:
        r = requests.get(API.format(key=key, source=src, bbox=bbox, days=config.DAY_RANGE), timeout=30)
        r.raise_for_status()
        if r.text.lstrip().lower().startswith("invalid"):
            raise RuntimeError(f"FIRMS відповів: {r.text.strip()[:120]}")
        spots += parse_csv(r.text, src)
    return spots


def load_sample(path: str) -> List[Hotspot]:
    with open(path, encoding="utf-8") as f:
        return parse_csv(f.read(), "sample")


def cluster(spots: List[Hotspot], radius_km: float = config.CLUSTER_KM) -> List[Cluster]:
    """Гармонізація: точки MODIS (1 км) і VIIRS (375 м) поруч — це одне місце."""
    clusters: List[Cluster] = []
    for s in sorted(spots, key=lambda s: s.when):
        for c in clusters:
            if c.distance_km(s.lat, s.lon) <= radius_km:
                c.spots.append(s)
                break
        else:
            clusters.append(Cluster([s]))
    return clusters


def pick_target(clusters: List[Cluster]) -> Optional[Cluster]:
    """Спершу підтверджені кількома супутниками, потім найсвіжіші, потім найближчі."""
    reach = [c for c in clusters if c.distance_km(config.BASE_LAT, config.BASE_LON) <= config.MAX_RANGE_KM]
    if not reach:
        return None
    return sorted(reach, key=lambda c: (not c.confirmed, -c.latest.when.timestamp(),
                                        c.distance_km(config.BASE_LAT, config.BASE_LON)))[0]

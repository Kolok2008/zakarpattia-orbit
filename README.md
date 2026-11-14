# Zakarpattia Orbit

NASA Space Apps Challenge 2026 · challenge **Harmonization of MODIS and VIIRS Hot Spots** · team Zakarpattia Orbit (Serhii Medulych, Zakarpattia, Ukraine; Kyiv local event, online).

**Live demo, one click, no install:** https://kolok2008.github.io/zakarpattia-orbit/
(the station replays a real NASA FIRMS day, 22 March 2025; the drone takes off by itself, you act as the operator).

## What it does

1. **Harmonization.** The full NASA FIRMS archive for Zakarpattia (2001–2026): MODIS (1 km) and VIIRS (375 m) are merged
   into one consistent monthly series. VIIRS sees 3.4× more hotspots, so a naive record jumps 4.4× in 2012. We pair
   same-orbit detections (Aqua MODIS ↔ S-NPP VIIRS, ≤ 1.5 km, ≤ 60 min), learn a VIIRS/MODIS ratio for each calendar
   month and convert MODIS-only years. Leave-one-year-out check: yearly error **10 %** (74 % without harmonization), R² 0.95.
   NOAA-20/21 are calibrated to S-NPP so the record continues. Method: `harmonize/METHODOLOGY.md`.
2. **Correlation of the two datasets** (`harmonize/correlation.py`, figure `submission/figs/d_correlation.png`):
   12×12 month-by-month correlation matrix MODIS × VIIRS; Pearson r = 0.97 for monthly counts, 0.93 yearly,
   0.92 across 10 km cells (Spearman 0.94).
3. **Burning calendar**: year × month heatmap, typical year, the March–April window (63 % of hotspots), 893 cells that burned
   in 5+ different years.
4. **Planning** (`harmonize/planning.py`): 13 town drone bases with a 15 km radius cover 62 % of VIIRS hotspots and 65 % of
   repeat-burning sites; three candidate new bases would raise coverage to 80 %.
5. **Risk and uncertainty maps** (`harmonize/risk_model.py`): Random Forest on the burning history (2 km cells);
   tested ahead in time on 2023–2025, ROC AUC 0.84 vs 0.671 for history alone. Uncertainty is the spread of
   200 trees. Both are shown in the Calendar tab (month by month for 2027) and risk feeds drone priority.
6. **Known industrial heat sources are ignored** (`harmonize/build_static_mask.py`): 106 sites from NASA's own
   `type = 2` flag (factory stacks, flares). The station never sends a drone there.
7. **Response with a human in the loop.** New hotspot → notification (console / Telegram bot) → the drone **takes off by
   itself** (ArduPilot over MAVLink: TAKEOFF → WAYPOINT → LOITER → RTL) → the operator watches the drone's own day / thermal
   video and presses **Forest fire / Field burning / False alarm** → the drone **returns and lands by itself**.
   A forest fire raises an alarm with a road route from the fire station (OSRM) and a ready message for the fire service.

Honest limits: satellite data reach FIRMS **1–3 hours** after the overpass (ultra-real-time is only for the US/Canada), so the
system suits wildfires and grass burning, not urban emergencies. Monthly counts are noisy (69 % monthly error; correlation is
weakest in January and June when there are few hotspots). The flight and the video in the demo are simulated; NASA data are real.

## Run the full station locally

```
cd ground
pip install -r requirements.txt
python server.py                  # live NASA data (set FIRMS_MAP_KEY), simulated drone
python server.py --sample         # offline
python server.py --auto-operator  # demo without a person: decision taken from the system hint
```
Open http://localhost:8000 (English: `?lang=en`). Telegram: set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.
Real drone: `ground/drone_mission.py` uploads the mission to ArduPilot / SITL over MAVLink (`MAVLINK_URL` in `config.py`).

## Rebuild the data

```
pip install pandas matplotlib scikit-learn
python harmonize/fetch_archive.py      # or unzip data/raw.zip into data/raw
python harmonize/build_calendar.py     # harmonization, calendar, figures a–c
python harmonize/correlation.py        # correlation matrix, figure d
python harmonize/build_static_mask.py  # industrial sources
python harmonize/planning.py           # base coverage and candidates
python harmonize/sensor_check.py       # pixel size (scan × track) and day/night check
python harmonize/risk_model.py         # risk + uncertainty maps (~2 min)
python ground/build_demo.py            # static demo into docs/ (GitHub Pages)
```

## Data
NASA FIRMS: MODIS Collection 6.1 (Terra, Aqua) and VIIRS 375 m (Suomi NPP, NOAA-20, NOAA-21), standard archive and near real-time.
Map imagery: Esri World Imagery. Roads: OpenStreetMap + OSRM.

## Timeline
A first prototype (archive download, first harmonization, station) was made before the hackathon weekend. During the
hackathon (14–15 Nov 2026), after mentor feedback, we added: operator-in-the-loop with automatic take-off/landing instead of
an on-board sensor module, the industrial-source mask, the MODIS–VIIRS correlation analysis, base planning and the
one-click web demo. See the commit history.

---

## Українською коротко

Демо в один клік: https://kolok2008.github.io/zakarpattia-orbit/ . Повна станція: `cd ground && python server.py`.
Схема v3 (після порад менторів 14.11): дрон сам злітає і сідає, рішення приймає оператор за відео денної/теплової
камери дрона; окремий модуль ESP32 на дроні не потрібен (опис старого модуля — `firmware/README_UA.md`).
Заводські труби (NASA type 2) не перевіряються. Затримка супутникових даних 1–3 год: система для природних пожеж і
палів трави, не для міських надзвичайних ситуацій.

License: MIT.

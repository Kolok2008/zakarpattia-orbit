# Zakarpattia Orbit — project page text (paste into the Space Apps "Project" tab)

## Project name
Zakarpattia Orbit

## Team
Serhii Medulych — Zakarpattia, Ukraine (Kyiv local event, virtual)

## High-level summary
Zakarpattia Orbit turns NASA's MODIS and VIIRS active-fire records into one consistent burning calendar for Zakarpattia,
Ukraine (2001–2026), and uses it to plan and run fire response. VIIRS (375 m) detects 3.4× more hotspots than MODIS (1 km),
so a naive record jumps 4.4× in 2012 — a sensor change, not more fires. We pair same-orbit detections (Aqua MODIS, S-NPP
VIIRS), learn a VIIRS/MODIS ratio for each calendar month and convert MODIS-only years. Leave-one-year-out validation
recovers yearly VIIRS counts with 10% error (74% without harmonization); the two datasets correlate at r = 0.97 by month
and 0.92 across 10 km cells. The calendar shows that 63% of hotspots fall in March–April and marks 893 repeat-burning cells.
For planning, it shows that 13 town drone bases cover 62% of hotspots and where 3 more would raise this to 80%. A web ground
station ignores 106 known industrial heat sources, sends the nearest drone on automatic take-off, lets an operator confirm
the fire from the drone's day/thermal video, and gives firefighters a road route.

## Link to project demo
- One-click web demo (no install): https://kolok2008.github.io/zakarpattia-orbit/
- 30-second video: https://youtu.be/jAA4rQgt9E0
- Slides (7): https://drive.google.com/file/d/1w9I66QULqMNMUTJD3Hw8YgI_na29sB0a/view?usp=sharing

## Link to final project
https://github.com/Kolok2008/zakarpattia-orbit

## Detailed project description
**What it does.** (1) Harmonization: downloads the full NASA FIRMS archive for the region, keeps vegetation fires,
pairs MODIS and VIIRS detections (≤ 1.5 km, ≤ 60 min: 56% of Aqua MODIS hotspots matched, 2.2 VIIRS per MODIS, median
offset 550 m) and builds one monthly series with 80% bootstrap intervals. NOAA-20/21 are calibrated to S-NPP (ratio 0.93)
so the record continues after S-NPP. (2) Correlation analysis of the two datasets: a 12×12 month-by-month correlation
matrix (MODIS month × VIIRS month, across 2012–2025), Pearson r = 0.97 for monthly counts, 0.93 for yearly counts and
0.92 across 0.1° cells (Spearman 0.94); agreement is weakest in January and June, when there are only a few hotspots.
(3) Calendar: year × month heatmap, typical year with 10–90% range, the critical window (1 March – 28 April), anomaly of the
current year and a 2×2 km recurrence grid. (4) Planning: coverage of hotspots and repeat-burning sites by the 13 bases
(15 km radius), share of each base's hotspots in spring (when duty shifts are needed) and three candidate new bases chosen
greedily for maximum extra coverage. (5) Known industrial heat sources: 106 sites built from NASA's own "type 2" flag
(static land sources such as factory stacks) are excluded, so no drone is wasted on them. (6) Response with a human in
the loop: every 15 minutes the station takes live FIRMS data, merges nearby MODIS/VIIRS detections, ranks places by their
burning history, checks the battery, and the nearest drone takes off automatically (ArduPilot mission over MAVLink:
take-off, fly, loiter, return to launch). While it circles the hotspot, the operator watches the drone's own day and thermal
video, sees a system hint and presses Forest fire / Field burning / False alarm; the drone lands by itself. A forest fire
raises an alarm with an OSRM road route from the fire station and a message ready for the State Emergency Service; the
operator can be notified through a Telegram bot. Interface in Ukrainian and English. (7) Sensor check: using the real pixel size FIRMS gives for each detection (scan × track),
MODIS pixels here reach 9.6 km² off-nadir (median 1.32 km², VIIRS 0.19 km²), but the residual of the monthly VIIRS/MODIS
ratio does not correlate with pixel size (r = −0.05), so viewing geometry does not bias our monthly factors; VIIRS also
records 11% night detections against 1% for MODIS. (8) Risk and uncertainty maps: a Random Forest trained on the burning history
of 2 km cells (2014–2022) and tested ahead in time on 2023–2025 reaches ROC AUC 0.84 against 0.671 for history alone;
the spread of its 200 trees is the uncertainty map. Both are shown month by month for 2027, and risk raises drone priority.

**Benefits.** A comparable 26-year fire record for local planning; patrols focused on the spring window and on repeat
sites; drone bases placed where fires actually happen; no flights to factories; fewer people needed per check, because the
drone flies by itself and one operator only confirms.

**Mentor feedback we acted on during the hackathon.** Mentors advised showing a correlation matrix between the two
datasets, building risk and uncertainty maps, checking the satellites' sensor characteristics, not building an extra sensor board for the drone (the drone already has cameras and a video link, and a person
should decide), focusing on planning and on ignoring known industrial sources, and giving judges a one-click demo. All of these
were added on 14–15 November.

**Tools.** Python (pandas, numpy, matplotlib, scikit-learn), Leaflet, JavaScript, ArduPilot/MAVLink mission code (pymavlink), OSRM.

**Honest limitations.** FIRMS data arrive 1–3 hours after the satellite overpass in Ukraine (ultra-real-time exists only
for the US and Canada), so the system suits wildfires and grass burning, not urban emergencies. Monthly counts are noisy
(69% monthly error) — the harmonization is reliable at yearly and seasonal scale. The study box also covers border areas of
neighbouring countries; planning uses points within 35 km of base towns as a proxy for the oblast. In the demo the drone
flight and video are simulated; NASA data are real. Fire stations are approximated by town centres; candidate bases need
checking on the ground. A first prototype existed before the hackathon; the items above were added during it.

## Space agency data
- NASA FIRMS — MODIS Collection 6.1 active fires (Terra, Aqua), standard and near real-time, 2001–2026
- NASA FIRMS — VIIRS 375 m active fires: Suomi NPP (2012–2026), NOAA-20, NOAA-21, standard and near real-time
- FIRMS data availability and FAQ documentation

## References
- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov
- Esri World Imagery (map background); OpenStreetMap + OSRM (road routing); Google Fonts (Unbounded, Manrope)

## Use of artificial intelligence
We used Claude (Anthropic) as an AI assistant to help write code, analyse data and draft text and slides.
All figures come from NASA FIRMS data processed by our scripts; no AI-generated images are presented as real data.

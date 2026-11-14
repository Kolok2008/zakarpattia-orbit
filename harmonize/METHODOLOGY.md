# Гармонізація MODIS і VIIRS для Закарпаття

Мета — один узгоджений календар горіння за 2001–2026 роки. Два сенсори бачать вогонь по-різному: VIIRS (375 м) помічає менші й холодніші пожежі, ніж MODIS (1 км). Тому, якщо просто склеїти «MODIS до 2011, VIIRS з 2012», у 2012 році з'являється штучна сходинка. До того ж дані S-NPP VIIRS від NASA закінчуються 1 листопада 2026 року, а MODIS виводять з роботи, тож ряд доведеться продовжувати через NOAA-20 і NOAA-21.

## Дані

Джерело — NASA FIRMS, area API, прямокутник 22.1–24.7° сх. д., 47.9–49.1° пн. ш.

| Джерело | Період | Точок (сирі) |
| --- | --- | --- |
| MODIS_SP (Terra + Aqua) | 2001-03 … 2026-08 | 6 942 |
| MODIS_NRT | 2026-09 … 2026-11 | 17 |
| VIIRS_SNPP_SP | 2012-03 … 2026-07 | 13 635 |
| VIIRS_SNPP_NRT | 2026-08 … 2026-10 | 177 |
| VIIRS_NOAA20_SP | 2023-01 … 2026-07 | 1 471 |
| VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT | 2026-08 … 2026-11 | 173, 195 |

Завантаження: `harmonize/fetch_archive.py` — 2 843 запити по 1–5 днів. Ліміт FIRMS 5 000 транзакцій за 10 хвилин; запит на N днів коштує приблизно 2N транзакцій (виміряно).

Обмеження з економії ліміту: NOAA-20 SP завантажено лише з 2023 року. Цього вистачає для калібрування до S-NPP (43 місяці перекриття).

**Фільтр.** У SP-даних залишаємо тільки `type = 0` (рослинний пожежа). Так прибрано 612 точок MODIS статичних джерел. У NRT колонки `type` немає, тому прибираємо точки в клітинках 0.01°, де в архіві SP є статичні джерела (`type = 2`): мінус 3–13 точок на джерело.

## 1. Пари Aqua MODIS ↔ S-NPP VIIRS

Обидва супутники проходять над регіоном близько 13:30 за місцевим часом, тож бачать ту саму пожежу майже одночасно. Пара — це точки, між якими ≤ 1.5 км і ≤ 60 хв.

- Точок Aqua MODIS у період перекриття — 2 713, з них 1 522 мають пару VIIRS (56%).
- На одну точку MODIS припадає в середньому 2.2 точки VIIRS: один піксель MODIS накриває кілька пікселів VIIRS.
- Медіанне зміщення до найближчої точки VIIRS — 550 м, у межах пікселя MODIS.
- Потужність вогню (FRP) у логарифмах: log10(ΣFRP_VIIRS) = 0.47 + 0.55 · log10(FRP_MODIS). Залежність слабша за пропорційну (нахил < 1): на малих пожежах VIIRS дає відносно більше.

## 2. Календар і коефіцієнти

- Місячні кількості точок рахуємо окремо для MODIS (Terra + Aqua), S-NPP і NOAA-20.
- Період перекриття MODIS і S-NPP: 2012-02 … 2026-07.
- Для кожного місяця року рахуємо коефіцієнт r = ΣVIIRS / ΣMODIS — відношення сум, бо воно стійке до нулів.
- 80% інтервал — бутстреп по роках, 2 000 вибірок.
- Якщо в місяці року менше 20 точок MODIS за все перекриття (червень, грудень), беремо загальний коефіцієнт 3.37 [3.12–3.67].
- Коефіцієнти за місяцями: від 2.75 (березень) до 7.0 (липень).
- Гармонізований ряд — у «еквіваленті S-NPP VIIRS»:
  - 2001–2012-01: MODIS × r(місяць) з інтервалом lo–hi (`basis = modis_scaled`);
  - 2012-02 … 2026-10: фактичні точки S-NPP (`viirs`);
  - з 2026-11 (S-NPP більше немає): NOAA-20 × 0.93 [0.86–1.02] (`noaa_scaled`). NOAA-20 бачить приблизно стільки ж, скільки S-NPP.

## 3. Перевірка (leave-one-year-out)

Кожен рік перекриття по черзі виключаємо, рахуємо коефіцієнти без нього і передбачаємо його VIIRS із MODIS.

| Рівень | Гармонізація | Без гармонізації (MODIS як є) |
| --- | --- | --- |
| Річна сума, MAPE (13 років) | **9.8%** | 73.8% |
| Річна сума, R² | 0.95 | — |
| Місяці, WAPE (Σ\|похибок\| / Σ) | 27.5% | 70.4% |
| Місяці, R² | 0.91 | 0.47 |
| Місяці, MAPE (у `calendar.json`) | 68.5% | 77.7% |

Чесно: помісячна MAPE висока, бо в спокійні місяці на весь регіон буває 1–5 точок, і похибка в 2 точки дає 50–100%. Річні суми й сезонна картина надійні, окремий тихий місяць — ні. Тому в інтерфейсі показуємо інтервал lo–hi.

## 4. Кліматологія, критичні вікна, аномалія

- **Кліматологія** — середнє, p10 і p90 гармонізованого ряду для кожного місяця за 2001–2025 роки.
- **Критичні вікна.** Беремо денний гармонізований ряд, згладжуємо його 15-денним середнім і шукаємо вікна, де рівень вищий за 1.5× середнього, тривалістю ≥ 7 днів. Знайдено одне вікно: **02.03 – 28.04**, весняне спалювання сухої трави й стерні; у середньому до 14.7 точки на день.
- **Аномалія 2026 року** — z-оцінка місяця відносно 2001–2025. Листопад 2026 ще не закінчився (`partial = true`).

## 5. Повторюваність (сітка 0.02°, ≈ 2 × 1.5 км)

Для кожної клітинки рахуємо дні з вогнем за всіма сенсорами, кількість різних років і останню дату. Усього 3 872 клітинки. 893 з них горіли щонайменше в 5 різних роках: це повторні місця спалювання.

Станція використовує це як апріорну оцінку для нової точки:
- часто горить → імовірно, спалювання поля;
- горить уперше в лісовій клітинці → вища пріоритетність вильоту.

## Обмеження

- Регіон малий, тож місячні числа малі й шумні (див. перевірку).
- Коефіцієнт рахується для кількості точок, а не для площі чи потужності вогню. Для FRP дано лише оцінку зв'язку з пар.
- Хмарність і час прольоту впливають на обидва сенсори по-різному. Модель цього окремо не враховує: усе потрапляє в сезонний коефіцієнт.
- NOAA-20 откалібровано лише за 2023–2026 роки.

---

## Summary (English)

**Goal.** One consistent burning-activity calendar for Zakarpattia (Ukraine), 2001–2026, that does not jump in 2012 when VIIRS starts.

**Data.** NASA FIRMS archive (MODIS_SP, VIIRS_SNPP_SP, VIIRS_NOAA20_SP) plus NRT feeds. Vegetation fires only: `type = 0`; static sources removed from NRT.

**Matching.** Aqua MODIS and S-NPP VIIRS points are paired within 1.5 km and 60 min:
- 56% of MODIS points have a VIIRS match;
- each matched MODIS point has 2.2 VIIRS points on average;
- median offset 550 m.

**Harmonization.**
- Per calendar month, the VIIRS/MODIS count ratio over 2012–2026, with an 80% interval from a bootstrap by year. Ratios range from 2.75 in March to 7.0 in July; overall 3.4.
- MODIS-era months are scaled to a VIIRS-equivalent.
- After S-NPP ends (Nov 2026), NOAA-20 × 0.93 continues the series.

**Validation (leave-one-year-out).**
- Annual totals are recovered with 9.8% MAPE (naive: 73.8%).
- Monthly R² is 0.91 (naive: 0.47).
- Monthly MAPE stays high because quiet months have only a few points.

**Results.**
- The naive splice shows a ×4.4 jump that is a sensor artefact.
- The fire season is 2 March – 28 April (spring grass and stubble burning): March and April give 63% of all yearly hotspots.
- 893 grid cells (~2 × 1.5 km) burned in at least 5 different years. These are priority patrol spots for the drone station.

## Sensor characteristics (payload) and what they mean for harmonization

Added on 14 Nov 2026 after mentor feedback ("check the payload specs of the satellites").

| | MODIS (Terra, Aqua) | VIIRS 375 m (S-NPP, NOAA-20, NOAA-21) |
|---|---|---|
| Orbit | ~705 km, Aqua ~13:30 local, Terra ~10:30 | ~824 km, ~13:30 local |
| Swath | 2330 km | 3060 km |
| Fire pixel at nadir | 1 km (bands 21/22 ≈ 4 µm, 31 ≈ 11 µm) | 375 m (I4 3.74 µm, I5 11.5 µm) |
| Pixel off-nadir | grows toward the scan edge | grows less (aggregation and bow-tie deletion) |

FIRMS gives the real pixel size of every detection in the `scan` and `track` fields. In our Zakarpattia archive
(`harmonize/sensor_check.py`):

* MODIS fire-pixel area: median 1.32 km², 90th percentile 3.1 km², maximum 9.6 km²; 22 % of MODIS detections
  have a pixel more than twice the nadir size. VIIRS: median 0.19 km², maximum 0.62 km².
* Does the viewing geometry bias our monthly VIIRS/MODIS ratio? We took the log ratio of each month (2012–2025,
  months with ≥ 5 MODIS hotspots), removed the calendar-month mean and correlated the residual with the mean pixel
  area of that month: r = −0.05 for MODIS and 0.07 for VIIRS. So, at monthly scale, scan geometry does not explain the
  noise; per-month ratios are not biased by it. Per-detection matching still uses the 1.5 km radius, which covers
  the median MODIS pixel.
* Day/night: 99 % of MODIS detections here are daytime, against 89 % for VIIRS (VIIRS 375 m sees many more small
  night fires). A day-only harmonization is a natural next test.

Sources: NASA Earthdata, VIIRS I-Band 375 m Active Fire Data (attribute table: scan and track reflect actual pixel size);
FIRMS MCD14DL NRT product page (1 km at nadir); MOD14 product page, LAADS DAAC; Schroeder et al. 2014, RSE 143, 85–96.


## Risk and uncertainty maps (Random Forest)

Added on 14 Nov 2026 after mentor feedback (risk heat map + uncertainty map as the basis for drone priority).
`harmonize/risk_model.py`: 0.02° grid (~2 km) within 35 km of base towns; target = a VIIRS S-NPP vegetation hotspot in the
cell during a month. Features use only earlier years: share of past years the cell (and its 3×3 neighbourhood) burned in
that month and in any month, whether it burned in that month last year, month (sin/cos), latitude, longitude.
Trained on 2014–2022, tested ahead in time on 2023–2025: ROC AUC 0.84 (history-only baseline 0.671),
average precision 0.02 vs 0.013; the riskiest 5 % of cells catch 39 % of
test fires (38 % for history only). Fires are rare (0.22 % of cell-months), so precision stays low:
the map says where to look, not where a fire will be. Uncertainty = standard deviation of the 200 trees' probabilities.
The final model (2014–2025) gives a month-by-month forecast for 2027; the station uses the current month's risk in priority.

Notes on mentor questions: Terra, Aqua, S-NPP, NOAA-20 and NOAA-21 are polar orbiters with 2330–3060 km swaths, so each
passes over Zakarpattia about twice a day; the multi-day revisit applies to high-resolution imagers (Landsat, Sentinel-2).
Gaps in our record come from clouds and fires that are not burning at overpass time, not from revisit. Day-of-week check
(VIIRS S-NPP 2012–2026): Monday 16.4 %, Saturday 15.8 %, Wednesday/Thursday 12.5–12.6 % (uniform = 14.3 %) — a human
weekend-burning signal, not an overpass artefact. Gap-filling of cloudy days is a next step.

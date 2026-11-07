"""Zakarpattia Orbit — головна програма наземної станції.

  python main.py                  # живі дані NASA, модуль імітується
  python main.py --watch          # те саме, оновлення кожні WATCH_MINUTES хв (Ctrl+C — стоп)
  python main.py --module         # + справжній модуль ESP32-CAM
  python main.py --module --fly   # + політ у симуляторі SITL
  python main.py --sample         # без інтернету: збережена точка NASA
  python main.py --scenario field # яку картину імітує модуль: fire / field / false
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import config
import firms
from classifier import classify
from drone_mission import build_mission, fly, print_mission
from module_client import read_module, simulate
from report import make_report

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_data", "firms_sample.csv")


def run_once(a) -> None:
    print(f"\n=== Zakarpattia Orbit · {datetime.now():%d.%m.%Y %H:%M} ===")

    # 1. Супутники
    source_note = ""
    if a.sample:
        spots, source = firms.load_sample(SAMPLE), "sample"
    else:
        try:
            print(f"1. Беру живі дані NASA FIRMS за {config.DAY_RANGE} дн. (VIIRS + MODIS)...")
            spots, source = firms.fetch_hotspots(), "live"
        except Exception as e:
            print(f"   Не вдалося отримати живі дані: {e}")
            print("   Беру збережену точку.")
            spots, source, source_note = firms.load_sample(SAMPLE), "sample", str(e)

    clusters = firms.cluster(spots)
    confirmed = sum(c.confirmed for c in clusters)
    print(f"   Сирих точок: {len(spots)}, місць після об'єднання MODIS+VIIRS: {len(clusters)}, "
          f"підтверджених кількома проходами: {confirmed}")
    for c in sorted(clusters, key=lambda c: -c.latest.when.timestamp()):
        d = c.distance_km(config.BASE_LAT, config.BASE_LON)
        print(f"   - {c.lat:.4f}, {c.lon:.4f}  {', '.join(c.sensors)}  {c.latest.local_time}  "
              f"{c.frp_max} МВт  {d:.0f} км від бази")

    target = firms.pick_target(clusters)
    reading = verdict = None
    module_mode = "none"
    if target is None:
        print(f"2. Немає місць у радіусі {config.MAX_RANGE_KM:.0f} км від бази — дрон не летить.")
    else:
        d = target.distance_km(config.BASE_LAT, config.BASE_LON)
        print(f"2. Ціль дрона: {target.lat:.5f}, {target.lon:.5f} ({d:.1f} км)")
        mission = build_mission(target.lat, target.lon)
        print_mission(mission)
        if a.fly:
            fly(mission)

        print("3. Дані модуля над точкою:")
        if a.module:
            try:
                reading, module_mode = read_module(), "live"
            except Exception as e:
                print(f"   Модуль не відповідає ({e}). Перевір Wi-Fi і MODULE_URL у config.py.")
        if reading is None:
            reading, module_mode = simulate(a.scenario, target.lat, target.lon), "sim"
            print(f"   (імітація модуля, сценарій '{a.scenario}' — заліза ще немає)")
        verdict = classify(reading)
        print("4. ВИСНОВОК:", verdict.label, f"({verdict.confidence * 100:.0f}%)")
        for r in verdict.reasons:
            print("   -", r)

    path = make_report(clusters, target, verdict, reading, a.report,
                       source=source, source_note=source_note, module_mode=module_mode,
                       refresh_min=config.WATCH_MINUTES if a.watch else 0)
    with open(os.path.splitext(path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({
            "source": source,
            "places": [{"lat": c.lat, "lon": c.lon, "sensors": c.sensors, "frp_max": c.frp_max,
                        "latest": c.latest.local_time, "confirmed": c.confirmed} for c in clusters],
            "target": None if target is None else {"lat": target.lat, "lon": target.lon},
            "verdict": None if verdict is None else verdict.__dict__,
            "module": module_mode,
        }, f, ensure_ascii=False, indent=2)
    print(f"Звіт: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Zakarpattia Orbit: супутник + дрон + ШІ")
    ap.add_argument("--sample", action="store_true", help="без інтернету: збережена точка NASA")
    ap.add_argument("--module", action="store_true", help="читати справжній модуль ESP32-CAM")
    ap.add_argument("--fly", action="store_true", help="запустити політ (SITL або дрон)")
    ap.add_argument("--scenario", choices=["fire", "field", "false"], default="fire",
                    help="що імітує модуль, поки немає заліза")
    ap.add_argument("--demo", choices=["fire", "field", "false"], help="старий режим: --sample + сценарій")
    ap.add_argument("--watch", action="store_true", help="оновлювати дані кожні WATCH_MINUTES хв")
    ap.add_argument("--report", default=os.path.join(HERE, "report.html"))
    a = ap.parse_args()
    if a.demo:
        a.sample, a.scenario = True, a.demo

    if not a.watch:
        run_once(a)
        return 0
    print(f"Режим спостереження: оновлення кожні {config.WATCH_MINUTES} хв. Ctrl+C — зупинити.")
    try:
        while True:
            run_once(a)
            time.sleep(config.WATCH_MINUTES * 60)
    except KeyboardInterrupt:
        print("\nЗупинено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

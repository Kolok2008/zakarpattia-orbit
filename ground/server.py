"""Наземна станція Zakarpattia Orbit — живий сайт.

  python server.py                    # живі дані NASA, дрон-симуляція, відкриє браузер
  python server.py --scenario field   # що імітує модуль: fire / field / false
  python server.py --module           # брати показання зі справжнього модуля ESP32-CAM
  python server.py --sample           # без інтернету: збережена точка NASA
  python server.py --no-auto          # не відправляти дрон автоматично

Відкрий http://localhost:8000
"""
import argparse
import json
import os
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import firms
from mission import Mission, nearest_base, run_mission, verdict_json
from station_extras import (BATTERY_RESERVE_PCT, Calendar, fire_route, mission_battery_left,
                            priority)

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web", "index.html")
SAMPLE = os.path.join(HERE, "sample_data", "firms_sample.csv")


class Station:
    def __init__(self, args):
        self.args = args
        self.lock = threading.RLock()
        self.places = []          # список dict
        self.clusters = {}        # id -> Cluster
        self.results = {}         # place_id -> verdict json (за ключем координат)
        self.source, self.source_note, self.updated_at = "sample", "", ""
        self.mission = None
        self.calendar = Calendar()
        self.alarm = None
        self.log = []
        self.stop = threading.Event()
        self.thread = None

    # ---------- NASA ----------
    def refresh(self) -> None:
        note = ""
        if self.args.sample:
            spots, source = firms.load_sample(SAMPLE), "sample"
        else:
            try:
                spots, source = firms.fetch_hotspots(), "live"
            except Exception as e:
                spots, source, note = firms.load_sample(SAMPLE), "sample", str(e)
                print(f"[NASA] живі дані недоступні: {e}")
        clusters = firms.cluster(spots)
        clusters.sort(key=lambda c: -c.latest.when.timestamp())
        places, cmap = [], {}
        for c in clusters:
            pid = f"p{round(c.lat, 3)}_{round(c.lon, 3)}"
            base, d = nearest_base(c.lat, c.lon)
            cmap[pid] = c
            places.append({
                "id": pid, "lat": round(c.lat, 5), "lon": round(c.lon, 5),
                "sensors": c.sensors, "frp_max": c.frp_max, "latest": c.latest.local_time,
                "passes": len(c.spots), "confirmed": c.confirmed,
                "base_id": base["id"] if base else None, "base_name": base["name"] if base else None,
                "dist_km": round(d, 1),
            })
            hist = self.calendar.history(c.lat, c.lon)
            places[-1]["history"] = hist
            places[-1]["priority"] = priority(places[-1], hist)
            left = mission_battery_left(d) if base else None
            places[-1]["battery_left_pct"] = left
            places[-1]["battery_ok"] = base is not None and left >= BATTERY_RESERVE_PCT
        with self.lock:
            self.places, self.clusters = places, cmap
            self.source, self.source_note = source, note
            self.updated_at = datetime.now().strftime("%H:%M")
        print(f"[NASA] {source}: {len(spots)} точок, {len(places)} місць, "
              f"у радіусі баз: {sum(p['base_id'] is not None for p in places)}")

    # ---------- дрон ----------
    def busy(self) -> bool:
        return self.mission is not None and self.mission.phase != "done"

    def dispatch(self, place_id: str) -> dict:
        with self.lock:
            if self.busy():
                return {"ok": False, "error": "Дрон уже в польоті. Дочекайся повернення."}
            place = next((p for p in self.places if p["id"] == place_id), None)
            if place is None:
                return {"ok": False, "error": "Такої точки вже немає в даних NASA."}
            if place["base_id"] is None:
                return {"ok": False, "error": f"Точка за {place['dist_km']} км від найближчої бази — поза радіусом."}
            if not place.get("battery_ok", True):
                return {"ok": False, "error": f"Не вистачить батареї: після польоту лишиться {place['battery_left_pct']}%, потрібно ≥ {BATTERY_RESERVE_PCT:.0f}%."}
            base = next(b for b in config.BASES if b["id"] == place["base_id"])
            self.mission = Mission(place, base, self.args.scenario, self.args.module)
            self.thread = threading.Thread(target=run_mission, args=(self.mission, self.stop, self.on_done), daemon=True)
            self.thread.start()
        print(f"[ДРОН] з бази {base['name']} до {place['lat']}, {place['lon']} ({place['dist_km']} км)")
        return {"ok": True}

    def on_done(self, m: Mission) -> None:
        vj = verdict_json(m.verdict)
        hist = m.place.get("history") or {}
        if vj and hist.get("recurrence") == "often":
            vj["reasons"].append(f"історія NASA: тут горіло {hist['fire_days']} днів за {hist['years']} різних років — типове місце спалювання")
            vj["reasons_en"].append(f"NASA history: {hist['fire_days']} fire days in {hist['years']} different years here — a typical burning site")
        elif vj and hist.get("recurrence") == "first":
            vj["reasons"].append("історія NASA: з 2001 року тут не було жодної гарячої точки — нетипово")
            vj["reasons_en"].append("NASA history: no hotspot here since 2001 — unusual")
        now = datetime.now().strftime("%H:%M")
        alarm = None
        if m.verdict and m.verdict.label == "ЛІСОВА ПОЖЕЖА":
            alarm = {"place_id": m.place["id"], "title": vj["title"], "color": vj["color"],
                     "lat": m.place["lat"], "lon": m.place["lon"], "base_name": m.base["name"],
                     "at": now, "acknowledged": False,
                     "route": fire_route(m.base, m.place["lat"], m.place["lon"])}
        with self.lock:
            self.results[m.place["id"]] = vj
            if alarm:
                self.alarm = alarm
            self.log.insert(0, {"at": now, "place_id": m.place["id"], "base_name": m.base["name"],
                                "lat": m.place["lat"], "lon": m.place["lon"],
                                "title": vj["title"] if vj else "—", "color": vj["color"] if vj else "#9FAA94",
                                "confidence": vj["confidence"] if vj else 0,
                                "flight_min": round(m.t / 60, 1), "battery_end_pct": round(m.battery, 1)})
            del self.log[50:]
        if alarm:
            print(f"[ТРИВОГА] {vj['title']} {m.place['lat']}, {m.place['lon']} — маршрут {alarm['route']['distance_km']} км")
        print(f"[ДРОН] повернувся на базу {m.base['name']}. Висновок: {m.verdict.label if m.verdict else '—'}")
        if not self.args.no_auto:  # за 15 с — до наступної неперевіреної точки
            threading.Timer(15, self.auto_dispatch).start()

    def auto_dispatch(self) -> None:
        """Перша непідтверджена точка в радіусі: спершу бачені кількома проходами, потім найсвіжіші."""
        with self.lock:
            todo = [p for p in self.places if p["base_id"] and p.get("battery_ok") and p["id"] not in self.results]
            rank = {"high": 0, "normal": 1, "low": 2}
            todo.sort(key=lambda p: (rank.get(p.get("priority"), 1), not p["confirmed"]))
        if todo and not self.busy():
            self.dispatch(todo[0]["id"])

    # ---------- стан для сайту ----------
    def state(self) -> dict:
        with self.lock:
            m = self.mission
            places = []
            for p in self.places:
                q = dict(p)
                if m is not None and m.place["id"] == p["id"] and m.phase != "done":
                    q["status"] = "flying"
                elif p["id"] in self.results:
                    q["status"] = "checked"
                elif p["base_id"] is None:
                    q["status"] = "out_of_range"
                else:
                    q["status"] = "new"
                q["verdict"] = self.results.get(p["id"])
                places.append(q)
            busy_base = m.base["id"] if self.busy() else None
            bases = [{**b, "status": "busy" if b["id"] == busy_base else "ready"} for b in config.BASES]
            mstate = None
            if m is not None:
                with m.lock:
                    mstate = m.state()
            return {
                "now": datetime.now().isoformat(timespec="seconds"),
                "source": self.source, "source_note": self.source_note, "updated_at": self.updated_at,
                "speedup": config.SIM_SPEEDUP, "range_km": config.MAX_RANGE_KM,
                "bases": bases, "places": places, "mission": mstate,
                "alarm": self.alarm, "log": self.log, "season": self.calendar.season(),
            }

    def ack_alarm(self) -> dict:
        with self.lock:
            if self.alarm:
                self.alarm["acknowledged"] = True
        return {"ok": True}


def make_handler(st: Station):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # тихо в консолі
            pass

        def send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def json(self, obj, code=200):
            self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route in ("/", "/index.html"):
                try:
                    with open(WEB, "rb") as f:
                        self.send(200, f.read(), "text/html; charset=utf-8")
                except FileNotFoundError:
                    self.send(500, "web/index.html не знайдено".encode(), "text/plain; charset=utf-8")
            elif route == "/api/state":
                self.json(st.state())
            elif route == "/api/calendar":
                st.calendar.load()
                if st.calendar.data:
                    self.json(st.calendar.data)
                else:
                    self.json({"ok": False, "error": "Календар ще не побудовано: запусти python harmonize/build_calendar.py"}, 404)
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                body = {}
            if self.path == "/api/dispatch":
                self.json(st.dispatch(str(body.get("place_id", ""))))
            elif self.path == "/api/alarm/ack":
                self.json(st.ack_alarm())
            elif self.path == "/api/refresh":
                try:
                    st.refresh()
                    self.json({"ok": True})
                except Exception as e:
                    self.json({"ok": False, "error": str(e)})
            else:
                self.json({"ok": False, "error": "невідомий запит"}, 404)

    return H


def main():
    ap = argparse.ArgumentParser(description="Zakarpattia Orbit — наземна станція")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--module", action="store_true")
    ap.add_argument("--scenario", choices=["fire", "field", "false"], default="fire")
    ap.add_argument("--no-auto", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    st = Station(a)
    st.refresh()
    if not a.no_auto:
        st.auto_dispatch()

    def watcher():
        while True:
            time.sleep(config.WATCH_MINUTES * 60)
            try:
                st.refresh()
                if not a.no_auto:
                    st.auto_dispatch()
            except Exception as e:
                print(f"[NASA] помилка оновлення: {e}")

    threading.Thread(target=watcher, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(st))
    url = f"http://localhost:{a.port}"
    print(f"Наземна станція працює: {url}  (Ctrl+C — зупинити)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nЗупинено.")
        st.stop.set()


if __name__ == "__main__":
    main()

"""Завдання дрону через MAVLink (ArduPilot / симулятор SITL).

Маршрут: зліт -> політ до гарячої точки на FLIGHT_ALT_M -> зниження до INSPECT_ALT_M ->
огляд 30 с -> повернення на базу (RTL).
Захист при втраті зв'язку: параметр FS_GCS_ENABLE=1 -> дрон сам повертається на базу
(координати бази записані в дроні як home ще перед злетом, GPS працює без мобільної мережі).
"""
import time
from dataclasses import dataclass
from typing import List

import config


@dataclass
class MissionItem:
    command: str
    lat: float
    lon: float
    alt: float
    param1: float = 0


def build_mission(lat: float, lon: float) -> List[MissionItem]:
    return [
        MissionItem("TAKEOFF", 0, 0, config.FLIGHT_ALT_M),
        MissionItem("WAYPOINT", lat, lon, config.FLIGHT_ALT_M),
        MissionItem("WAYPOINT", lat, lon, config.INSPECT_ALT_M),
        MissionItem("LOITER_TIME", lat, lon, config.INSPECT_ALT_M, param1=30),
        MissionItem("RETURN_TO_LAUNCH", 0, 0, 0),
    ]


def print_mission(items: List[MissionItem]) -> None:
    print("  Маршрут дрона:")
    for i, it in enumerate(items, 1):
        extra = f", огляд {it.param1:.0f} с" if it.command == "LOITER_TIME" else ""
        where = "" if it.lat == 0 else f" -> {it.lat:.5f}, {it.lon:.5f}"
        print(f"   {i}. {it.command}{where}, висота {it.alt:.0f} м{extra}")
    print("  Втрата зв'язку: FS_GCS_ENABLE=1 -> повернення на базу (RTL)")


def fly(items: List[MissionItem], url: str = config.MAVLINK_URL, timeout_s: int = 900) -> None:
    """Завантажує маршрут у дрон/симулятор і запускає. Потрібен pymavlink."""
    from pymavlink import mavutil

    cmd_ids = {
        "TAKEOFF": mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        "WAYPOINT": mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        "LOITER_TIME": mavutil.mavlink.MAV_CMD_NAV_LOITER_TIME,
        "RETURN_TO_LAUNCH": mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
    }

    m = mavutil.mavlink_connection(url)
    print("  Чекаю зв'язку з дроном...")
    m.wait_heartbeat(timeout=30)
    print(f"  Зв'язок є: система {m.target_system}")

    # захист: при втраті зв'язку з наземною станцією — додому
    m.mav.param_set_send(m.target_system, m.target_component, b"FS_GCS_ENABLE", 1,
                         mavutil.mavlink.MAV_PARAM_TYPE_INT8)

    # --- завантаження маршруту (item 0 = home, ArduPilot його перезапише) ---
    seq_items = [MissionItem("WAYPOINT", 0, 0, 0)] + items
    m.mav.mission_count_send(m.target_system, m.target_component, len(seq_items))
    sent = 0
    while sent < len(seq_items):
        req = m.recv_match(type=["MISSION_REQUEST_INT", "MISSION_REQUEST"], blocking=True, timeout=10)
        if req is None:
            raise RuntimeError("Дрон не просить точки маршруту")
        it = seq_items[req.seq]
        frame = (mavutil.mavlink.MAV_FRAME_GLOBAL if req.seq == 0
                 else mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT)
        m.mav.mission_item_int_send(
            m.target_system, m.target_component, req.seq, frame,
            cmd_ids.get(it.command, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT),
            0, 1, it.param1, 0, 0, 0,
            int(it.lat * 1e7), int(it.lon * 1e7), it.alt)
        sent = max(sent, req.seq + 1)
    ack = m.recv_match(type="MISSION_ACK", blocking=True, timeout=10)
    print(f"  Маршрут завантажено: {ack}")

    # --- старт: GUIDED, armed, зліт, потім AUTO ---
    m.set_mode("GUIDED")
    m.arducopter_arm()
    m.motors_armed_wait()
    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                            0, 0, 0, 0, 0, 0, config.FLIGHT_ALT_M)
    time.sleep(5)
    m.set_mode("AUTO")
    print("  Дрон летить. Стежу за позицією...")

    start = time.time()
    while time.time() - start < timeout_s:
        msg = m.recv_match(type=["GLOBAL_POSITION_INT", "HEARTBEAT"], blocking=True, timeout=5)
        if msg and msg.get_type() == "GLOBAL_POSITION_INT":
            print(f"   {msg.lat / 1e7:.5f}, {msg.lon / 1e7:.5f}, висота {msg.relative_alt / 1000:.0f} м", end="\r")
        if msg and msg.get_type() == "HEARTBEAT" and not (
                msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
            print("\n  Дрон приземлився.")
            return
    print("\n  Час вийшов — перевір дрон у Mission Planner.")

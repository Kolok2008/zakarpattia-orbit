"""Сповіщення оператору: Telegram-бот (якщо задано TELEGRAM_TOKEN і TELEGRAM_CHAT_ID) + консоль.

Події: дрон вилетів на нову точку; дрон над точкою — оператор, глянь відео; тривога.
Як отримати токен: напиши @BotFather у Telegram -> /newbot. chat_id: напиши боту, потім
відкрий https://api.telegram.org/bot<TOKEN>/getUpdates.
"""
import threading

import requests

import config


def send(text: str) -> None:
    print(f"[СПОВІЩЕННЯ] {text}")
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        return

    def go():
        try:
            requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception as e:
            print(f"[СПОВІЩЕННЯ] Telegram недоступний: {e}")

    threading.Thread(target=go, daemon=True).start()

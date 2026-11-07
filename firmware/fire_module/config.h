// ===== Налаштування модуля Zakarpattia Orbit =====
#pragma once

// --- Wi-Fi (для тесту: точка доступу ноутбука або телефону) ---
#define WIFI_SSID     "YOUR_WIFI"
#define WIFI_PASSWORD "YOUR_PASSWORD"

// --- Піни (плата AI-Thinker ESP32-CAM) ---
// Камера займає більшість пінів. Вільні: 2, 12, 13, 14, 15.
#define PIN_I2C_SDA   14   // BME280 + MLX90640
#define PIN_I2C_SCL   15
#define PIN_GPS_RX    13   // TX модуля GPS -> GPIO13
#define PIN_MQ7_DOUT   2   // цифровий вихід MQ-7 через дільник 5V -> 3.3V
#define PIN_FLASH_LED  4   // вбудований спалах

// --- Чи підключений тепловізор MLX90640 ---
#define USE_MLX90640  0    // 1 = є тепловізор, 0 = немає

// --- Пороги тривоги ---
#define TEMP_RISE_C          8.0   // ріст температури повітря за вікно, °C
#define THERMAL_ABS_C      100.0   // найгарячіша точка тепловізора, °C (максимум сенсора 300)
#define THERMAL_DELTA_C     45.0   // точка гарячіша за фон на стільки, °C
#define WINDOW_SAMPLES        10   // скільки вимірів пам'ятати (вікно росту)
#define MIN_FACTORS            2   // скільки ознак мають збігтися для тривоги

// --- Частота ---
#define MEASURE_EVERY_MS   10000UL      // вимір кожні 10 с (у полі: 2-5 хв)
#define HEARTBEAT_EVERY_MS 10800000UL   // статус "живий" кожні 3 год

/*
  Zakarpattia Orbit — модуль виявлення пожежі (ESP32-CAM)
  ------------------------------------------------------
  Що робить:
   - кожні MEASURE_EVERY_MS міряє: температуру/вологість (BME280),
     чадний газ (MQ-7, цифровий вихід), координати (GPS NEO-6M),
     найгарячішу точку (тепловізор MLX90640, якщо USE_MLX90640 = 1);
   - рахує, скільки ознак пожежі збіглося, і ставить тривогу;
   - віддає дані по Wi-Fi:
       GET /data    -> JSON з показаннями і тривогою
       GET /capture -> фото JPEG з камери
       GET /thermal -> 768 температур тепловізора (якщо є)

  Бібліотеки (Arduino IDE -> Library Manager):
   - Adafruit BME280 Library (+ Adafruit Unified Sensor)
   - TinyGPSPlus
   - Adafruit MLX90640 (лише якщо USE_MLX90640 = 1)
  Плата: "AI Thinker ESP32-CAM" (пакет esp32 by Espressif).
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include "esp_camera.h"
#include <Adafruit_BME280.h>
#include <TinyGPSPlus.h>
#include "config.h"

#if USE_MLX90640
#include <Adafruit_MLX90640.h>
Adafruit_MLX90640 mlx;
float thermalFrame[32 * 24];
#endif

// ---------- піни камери AI-Thinker ----------
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);
Adafruit_BME280 bme;
TinyGPSPlus gps;
HardwareSerial gpsSerial(1);

bool bmeOk = false;
bool mlxOk = false;

// ---------- поточні показання ----------
struct Reading {
  float airTempC = NAN;
  float humidity = NAN;
  bool  coDetected = false;
  float thermalMaxC = NAN;
  float thermalMeanC = NAN;
  double lat = NAN, lon = NAN;
  int   satellites = 0;
  int   factors = 0;
  bool  alarm = false;
  unsigned long millisAt = 0;
} cur;

float tempHistory[WINDOW_SAMPLES];
int   histCount = 0, histPos = 0;
unsigned long lastMeasure = 0, lastHeartbeat = 0;

// ---------- камера ----------
bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM; c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_VGA;      // 640x480 — досить для ШІ
  c.jpeg_quality = 12;
  c.fb_count = 1;
  c.grab_mode = CAMERA_GRAB_LATEST;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  return esp_camera_init(&c) == ESP_OK;
}

// ---------- вимірювання ----------
float tempRise() {
  // різниця між найновішим і найстарішим виміром у вікні
  if (histCount < 2) return 0;
  int newest = (histPos - 1 + WINDOW_SAMPLES) % WINDOW_SAMPLES;
  int oldest = (histCount < WINDOW_SAMPLES) ? 0 : histPos;
  return tempHistory[newest] - tempHistory[oldest];
}

void measure() {
  if (bmeOk) {
    cur.airTempC = bme.readTemperature();
    cur.humidity = bme.readHumidity();
    tempHistory[histPos] = cur.airTempC;
    histPos = (histPos + 1) % WINDOW_SAMPLES;
    if (histCount < WINDOW_SAMPLES) histCount++;
  }

  // MQ-7: модуль тягне DOUT у LOW, коли газу більше за поріг потенціометра
  cur.coDetected = (digitalRead(PIN_MQ7_DOUT) == LOW);

#if USE_MLX90640
  if (mlxOk && mlx.getFrame(thermalFrame) == 0) {
    float mx = -100, sum = 0;
    for (int i = 0; i < 32 * 24; i++) {
      sum += thermalFrame[i];
      if (thermalFrame[i] > mx) mx = thermalFrame[i];
    }
    cur.thermalMaxC = mx;
    cur.thermalMeanC = sum / (32 * 24);
  }
#endif

  if (gps.location.isValid()) {
    cur.lat = gps.location.lat();
    cur.lon = gps.location.lng();
  }
  cur.satellites = gps.satellites.isValid() ? gps.satellites.value() : 0;

  // ---- скільки ознак пожежі збіглося ----
  int f = 0;
  if (cur.coDetected) f++;
  if (tempRise() >= TEMP_RISE_C) f++;
  if (!isnan(cur.thermalMaxC) &&
      (cur.thermalMaxC >= THERMAL_ABS_C ||
       cur.thermalMaxC - cur.thermalMeanC >= THERMAL_DELTA_C)) f++;
  cur.factors = f;
  cur.alarm = (f >= MIN_FACTORS);
  cur.millisAt = millis();

  Serial.printf("T=%.1fC rise=%.1f CO=%d thermalMax=%.1f GPS=%.5f,%.5f factors=%d ALARM=%d\n",
                cur.airTempC, tempRise(), cur.coDetected, cur.thermalMaxC,
                cur.lat, cur.lon, cur.factors, cur.alarm);
}

// ---------- HTTP ----------
String num(float v, int d = 2) { return isnan(v) ? "null" : String(v, d); }
String num6(double v) { return isnan(v) ? "null" : String(v, 6); }

void handleData() {
  String j = "{";
  j += "\"air_temp_c\":" + num(cur.airTempC) + ",";
  j += "\"humidity\":" + num(cur.humidity) + ",";
  j += "\"temp_rise_c\":" + num(tempRise()) + ",";
  j += "\"co_detected\":" + String(cur.coDetected ? "true" : "false") + ",";
  j += "\"thermal_max_c\":" + num(cur.thermalMaxC) + ",";
  j += "\"thermal_mean_c\":" + num(cur.thermalMeanC) + ",";
  j += "\"lat\":" + num6(cur.lat) + ",";
  j += "\"lon\":" + num6(cur.lon) + ",";
  j += "\"satellites\":" + String(cur.satellites) + ",";
  j += "\"factors\":" + String(cur.factors) + ",";
  j += "\"alarm\":" + String(cur.alarm ? "true" : "false") + ",";
  j += "\"uptime_s\":" + String(millis() / 1000);
  j += "}";
  server.send(200, "application/json", j);
}

void handleCapture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { server.send(503, "text/plain", "camera error"); return; }
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  server.client().write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleThermal() {
#if USE_MLX90640
  String j = "[";
  for (int i = 0; i < 32 * 24; i++) {
    j += String(thermalFrame[i], 1);
    if (i < 32 * 24 - 1) j += ",";
  }
  j += "]";
  server.send(200, "application/json", j);
#else
  server.send(404, "text/plain", "no thermal camera");
#endif
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_MQ7_DOUT, INPUT);
  pinMode(PIN_FLASH_LED, OUTPUT);
  digitalWrite(PIN_FLASH_LED, LOW);

  Serial.println(initCamera() ? "Camera OK" : "Camera FAIL");

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  bmeOk = bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire);
  Serial.println(bmeOk ? "BME280 OK" : "BME280 not found");

#if USE_MLX90640
  mlxOk = mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire);
  if (mlxOk) {
    mlx.setMode(MLX90640_CHESS);
    mlx.setResolution(MLX90640_ADC_18BIT);
    mlx.setRefreshRate(MLX90640_2_HZ);
  }
  Serial.println(mlxOk ? "MLX90640 OK" : "MLX90640 not found");
#endif

  gpsSerial.begin(9600, SERIAL_8N1, PIN_GPS_RX, -1);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("IP модуля: "); Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi не підключився — модуль міряє і пише в Serial");
  }

  server.on("/data", handleData);
  server.on("/capture", handleCapture);
  server.on("/thermal", handleThermal);
  server.begin();
}

void loop() {
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
  server.handleClient();

  unsigned long now = millis();
  if (now - lastMeasure >= MEASURE_EVERY_MS) {
    lastMeasure = now;
    measure();
    // спалах блимає при тривозі — видно на демо
    digitalWrite(PIN_FLASH_LED, cur.alarm ? HIGH : LOW);
  }
  if (now - lastHeartbeat >= HEARTBEAT_EVERY_MS) {
    lastHeartbeat = now;
    Serial.println("HEARTBEAT: модуль живий");
  }
}

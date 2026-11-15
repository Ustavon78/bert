// SPDX-License-Identifier: GPL-3.0-or-later
// Bert display firmware.
//
// Flow after every wake-up:
//   WiFi -> POST /api/checkin -> (image: GET /api/image, draw, remember hash) -> deep sleep

#include <Arduino.h>
#include <WiFi.h>
#include <esp_sleep.h>

#include "api.h"
#include "config.h"
#include "display.h"
#include "settings.h"

static void wifiOff() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

[[noreturn]] static void sleepFor(uint32_t seconds) {
  seconds = constrain(seconds, (uint32_t)MIN_SLEEP_SECONDS, (uint32_t)MAX_SLEEP_SECONDS);
  Serial.printf("Sleeping for %u s\n", (unsigned)seconds);
  Serial.flush();
  wifiOff();
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_deep_sleep_start();
  while (true) {}  // never reached
}

static bool connectWifi(const Settings &s) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(s.ssid.c_str(), s.pass.c_str());
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > WIFI_TIMEOUT_MS) return false;
    delay(100);
  }
  Serial.printf("WiFi connected, RSSI %d dBm\n", WiFi.RSSI());
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\nBert firmware %s\n", FW_VERSION);

  Settings settings;
  loadSettings(settings);

  // The console opens only after power-on/reset, not after a timer wake-up (saves energy).
  bool coldStart = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_UNDEFINED;
  if (coldStart || !settingsComplete(settings)) {
    runSerialSetup(!settingsComplete(settings));
    loadSettings(settings);
  }

  // Reserve the image buffer before WiFi starts, while the heap is not fragmented yet.
  uint8_t *imageBuffer = displayAllocBuffer();

  if (!connectWifi(settings)) {
    Serial.println(F("WiFi connection failed"));
    sleepFor(RETRY_SLEEP_SECONDS);
  }

  String currentHash = loadHash();
  CheckinResult result = checkin(settings, currentHash);
  if (!result.ok) sleepFor(RETRY_SLEEP_SECONDS);

  switch (result.action) {
    case Action::Image: {
      Serial.printf("Action: image (desired %s)\n", result.hash.c_str());
      if (!imageBuffer) {
        Serial.println(F("Not enough memory for the image"));
        break;
      }
      String receivedHash;
      if (downloadImage(settings, imageBuffer, IMAGE_SIZE_BYTES, receivedHash)) {
        wifiOff();  // the radio is not needed while the panel refreshes
        Serial.println(F("Drawing (takes about 20 seconds)..."));
        displayShow(imageBuffer, imageBuffer + IMAGE_PLANE_BYTES);
        // Store the hash from the download header, not from the check-in answer: the server
        // may have rendered a newer image in between. Only after the panel is done.
        saveHash(receivedHash);
        Serial.printf("Hash stored: %s\n", receivedHash.c_str());
      } else {
        Serial.println(F("Image download failed, will retry at next wake-up"));
      }
      break;
    }
    case Action::Ota:
      Serial.printf("Action: ota to %s (not implemented yet)\n", result.fw.c_str());
      break;
    case Action::Deactivated:
      Serial.println(F("Action: deactivated"));
      break;
    case Action::None:
      Serial.println(F("Action: none"));
      break;
  }

  sleepFor(result.sleepSeconds);
}

void loop() {}
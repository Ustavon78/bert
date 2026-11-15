// SPDX-License-Identifier: GPL-3.0-or-later
// Bert display firmware, version 0.1: check-in and hash logic only (no display output yet).
//
// Flow after every wake-up:
//   WiFi -> POST /api/checkin -> (image: GET /api/image, remember hash) -> deep sleep

#include <Arduino.h>
#include <WiFi.h>
#include <esp_sleep.h>

#include "api.h"
#include "config.h"
#include "settings.h"

[[noreturn]] static void sleepFor(uint32_t seconds) {
  seconds = constrain(seconds, (uint32_t)MIN_SLEEP_SECONDS, (uint32_t)MAX_SLEEP_SECONDS);
  Serial.printf("Sleeping for %u s\n", (unsigned)seconds);
  Serial.flush();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
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
      String receivedHash;
      if (downloadImage(settings, receivedHash)) {
        // Store the hash from the download header, not from the check-in answer: the server
        // may have rendered a newer image in between. With a display this happens after drawing.
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
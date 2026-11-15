// SPDX-License-Identifier: GPL-3.0-or-later
#include "api.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"

static void addAuthHeaders(HTTPClient &http, const Settings &s) {
  http.addHeader("X-Device-Id", s.id);
  http.addHeader("X-Token", s.token);
}

CheckinResult checkin(const Settings &s, const String &currentHash) {
  CheckinResult result;

  // Only plain HTTP for now. HTTPS (with the school CA certificate) comes later.
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client, s.server + "/api/checkin")) {
    Serial.println(F("checkin: invalid server URL"));
    return result;
  }
  http.addHeader("Content-Type", "application/json");
  addAuthHeaders(http, s);

  JsonDocument body;
  body["hash"] = currentHash;
  body["fw"] = FW_VERSION;
  body["rssi"] = WiFi.RSSI();  // no battery value yet (sensor differs per board)
  String payload;
  serializeJson(body, payload);

  result.httpCode = http.POST(payload);
  if (result.httpCode != 200) {
    Serial.printf("checkin: HTTP %d\n", result.httpCode);
    http.end();
    return result;
  }

  JsonDocument answer;
  DeserializationError error = deserializeJson(answer, http.getString());
  http.end();
  if (error) {
    Serial.printf("checkin: bad JSON (%s)\n", error.c_str());
    return result;
  }

  String action = answer["action"] | "none";
  if (action == "image") result.action = Action::Image;
  else if (action == "ota") result.action = Action::Ota;
  else if (action == "deactivated") result.action = Action::Deactivated;
  else result.action = Action::None;
  result.sleepSeconds = answer["sleep"] | 0;
  result.hash = answer["hash"] | "";
  result.fw = answer["fw"] | "";
  result.ok = true;
  return result;
}

bool downloadImage(const Settings &s, String &imageHash) {
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client, s.server + "/api/image")) return false;
  addAuthHeaders(http, s);
  const char *wanted[] = {"X-Image-Hash"};
  http.collectHeaders(wanted, 1);

  int code = http.GET();
  if (code != 200) {
    Serial.printf("image: HTTP %d\n", code);
    http.end();
    return false;
  }
  int length = http.getSize();
  if (length != IMAGE_SIZE_BYTES) {
    Serial.printf("image: unexpected size %d\n", length);
    http.end();
    return false;
  }

  WiFiClient *stream = http.getStreamPtr();
  uint8_t buffer[512];
  size_t total = 0;
  unsigned long lastData = millis();
  while ((http.connected() || stream->available()) && total < (size_t)length) {
    size_t available = stream->available();
    if (available) {
      size_t n = stream->readBytes(buffer, min(available, sizeof(buffer)));
      // TODO: pass buffer[0..n) to the display driver (black plane first, then red plane).
      total += n;
      lastData = millis();
    } else if (millis() - lastData > HTTP_TIMEOUT_MS) {
      break;
    } else {
      delay(1);
    }
  }
  imageHash = http.header("X-Image-Hash");
  http.end();

  Serial.printf("image: received %u bytes\n", (unsigned)total);
  return total == (size_t)length && imageHash.length() > 0;
}
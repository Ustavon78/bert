// SPDX-License-Identifier: GPL-3.0-or-later
#include "api.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"
#include "net.h"
#include "ota.h"

static void addAuthHeaders(HTTPClient &http, const Settings &s) {
  http.addHeader("X-Device-Id", s.id);
  http.addHeader("X-Token", s.token);
}

CheckinResult checkin(const Settings &s, const String &currentHash) {
  CheckinResult result;

  WiFiClient *client = netClient(s);  // TLS if the server address starts with https://
  if (!client) return result;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(*client, s.server + "/api/checkin")) {
    Serial.println(F("checkin: invalid server URL"));
    return result;
  }
  http.addHeader("Content-Type", "application/json");
  addAuthHeaders(http, s);

  JsonDocument body;
  body["hash"] = currentHash;
  body["fw"] = FW_VERSION;
  body["rssi"] = WiFi.RSSI();  // no battery value yet (sensor differs per board)
  body["board"] = BOARD_NAME;
  String lastError = otaLastError();
  if (lastError.length()) body["err"] = lastError;
  String payload;
  serializeJson(body, payload);

  result.httpCode = http.POST(payload);
  if (result.httpCode != 200) {
    Serial.printf("checkin: HTTP %d\n", result.httpCode);
    if (result.httpCode < 0 && s.server.startsWith("https://"))
      Serial.println(F("hint: the stored CA must be the one of this server and the server address must be in its certificate (see 'show')"));
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
  result.sha256 = answer["sha256"] | "";
  result.size = answer["size"] | 0;
  result.ok = true;
  if (lastError.length()) otaClearError();  // the server has received it
  return result;
}

bool downloadImage(const Settings &s, uint8_t *buffer, size_t bufferSize, String &imageHash) {
  WiFiClient *client = netClient(s);
  if (!client) return false;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(*client, s.server + "/api/image")) return false;
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
  if (length != IMAGE_SIZE_BYTES || bufferSize < (size_t)length) {
    Serial.printf("image: unexpected size %d\n", length);
    http.end();
    return false;
  }

  WiFiClient *stream = http.getStreamPtr();
  size_t total = 0;
  unsigned long lastData = millis();
  while ((http.connected() || stream->available()) && total < (size_t)length) {
    size_t available = stream->available();
    if (available) {
      size_t n = stream->readBytes(buffer + total, min(available, (size_t)length - total));
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
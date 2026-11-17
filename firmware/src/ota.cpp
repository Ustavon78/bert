// SPDX-License-Identifier: GPL-3.0-or-later
#include "ota.h"

#include <HTTPClient.h>
#include <Preferences.h>
#include <Update.h>
#include <WiFi.h>
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>

#include "config.h"

// mbedTLS 3 renamed the SHA-256 functions.
#if MBEDTLS_VERSION_MAJOR >= 3
#define SHA256_START(ctx) mbedtls_sha256_starts(ctx, 0)
#define SHA256_UPDATE(ctx, data, length) mbedtls_sha256_update(ctx, data, length)
#define SHA256_FINISH(ctx, out) mbedtls_sha256_finish(ctx, out)
#else
#define SHA256_START(ctx) mbedtls_sha256_starts_ret(ctx, 0)
#define SHA256_UPDATE(ctx, data, length) mbedtls_sha256_update_ret(ctx, data, length)
#define SHA256_FINISH(ctx, out) mbedtls_sha256_finish_ret(ctx, out)
#endif

// State in the NVS flash (namespace "bert"):
//   ota_pend   1 = a new firmware was installed and is not confirmed yet
//   ota_crash  crashes of the unconfirmed firmware
//   ota_to     version that was installed last
//   ota_fv     version of the last failed install, ota_fc = number of failures
//   last_err   text for the server
static const char *NAMESPACE = "bert";
static Preferences store;

// Helpers: read only existing keys (a missing key would only log an error message).
static uint8_t getByte(const char *key) { return store.isKey(key) ? store.getUChar(key, 0) : 0; }
static String getText(const char *key) { return store.isKey(key) ? store.getString(key, "") : String(""); }
static void removeKey(const char *key) {
  if (store.isKey(key)) store.remove(key);
}

static void setError(const String &text) {
  store.putString("last_err", text.substring(0, 90));
}

// ---------------------------------------------------------------------------
// Rollback
// ---------------------------------------------------------------------------
// store must be open. Switches to the previous firmware and restarts, if one exists.
static void rollback() {
  String target = getText("ota_to");
  const esp_partition_t *previous = esp_ota_get_next_update_partition(nullptr);
  esp_app_desc_t description;
  bool previousValid = previous != nullptr && esp_ota_get_partition_description(previous, &description) == ESP_OK;

  // Never try this version again, whatever happens next.
  store.putString("ota_fv", target);
  store.putUChar("ota_fc", OTA_MAX_FAILS);
  store.putUChar("ota_pend", 0);
  store.putUChar("ota_crash", 0);
  setError("rollback from " + target);

  if (previousValid && esp_ota_set_boot_partition(previous) == ESP_OK) {
    Serial.println(F("OTA: new firmware keeps crashing, going back to the previous one"));
    store.end();
    delay(100);
    esp_restart();
  }
  Serial.println(F("OTA: no previous firmware available"));
}

void otaBootCheck() {
  store.begin(NAMESPACE, false);
  if (getByte("ota_pend") == 1) {
    esp_reset_reason_t reason = esp_reset_reason();
    bool crashed = reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT ||
                   reason == ESP_RST_TASK_WDT || reason == ESP_RST_WDT;
    if (crashed) {
      uint8_t crashes = getByte("ota_crash") + 1;
      store.putUChar("ota_crash", crashes);
      Serial.printf("OTA: the new firmware crashed (%u of %u)\n", crashes, OTA_MAX_CRASHES);
      if (crashes >= OTA_MAX_CRASHES) rollback();
    }
  }
  store.end();
}

void otaMarkGood() {
  store.begin(NAMESPACE, false);
  if (getByte("ota_pend") == 1) {
    Serial.println(F("OTA: new firmware confirmed"));
    store.putUChar("ota_pend", 0);
    store.putUChar("ota_crash", 0);
    removeKey("ota_fv");
    removeKey("ota_fc");
  }
  store.end();
}

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------
static bool failed(const String &version, const String &message) {
  Serial.printf("OTA failed: %s\n", message.c_str());
  store.begin(NAMESPACE, false);
  uint8_t count = getText("ota_fv") == version ? getByte("ota_fc") + 1 : 1;
  store.putString("ota_fv", version);
  store.putUChar("ota_fc", count);
  setError("ota " + version + ": " + message);
  store.end();
  return false;
}

static bool tooManyFailures(const String &version) {
  store.begin(NAMESPACE, false);
  bool blocked = getText("ota_fv") == version && getByte("ota_fc") >= OTA_MAX_FAILS;
  store.end();
  return blocked;
}

static String toHex(const unsigned char *data, size_t length) {
  static const char digits[] = "0123456789abcdef";
  String out;
  out.reserve(length * 2);
  for (size_t i = 0; i < length; i++) {
    out += digits[data[i] >> 4];
    out += digits[data[i] & 15];
  }
  return out;
}

bool otaInstall(const Settings &s, const String &version, const String &sha256, size_t size) {
  if (tooManyFailures(version)) {
    Serial.printf("OTA: version %s failed too often, skipped\n", version.c_str());
    return false;
  }
  Serial.printf("OTA: installing %s (%u bytes)\n", version.c_str(), (unsigned)size);

  // Only plain HTTP for now (see api.cpp). The SHA-256 from the server protects against
  // transfer errors, not against an attacker. HTTPS and signed firmware come later.
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  String url = s.server + "/api/firmware/" + BOARD_NAME + "/" + version;
  if (!http.begin(client, url)) return failed(version, "bad url");
  http.addHeader("X-Device-Id", s.id);
  http.addHeader("X-Token", s.token);

  int code = http.GET();
  if (code != 200) {
    http.end();
    return failed(version, "http " + String(code));
  }
  int length = http.getSize();
  if (length <= 0 || (size_t)length != size) {
    http.end();
    return failed(version, "size mismatch");
  }
  if (!Update.begin(length)) {
    http.end();
    return failed(version, String("no space: ") + Update.errorString());
  }

  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  SHA256_START(&sha);
  WiFiClient *stream = http.getStreamPtr();
  uint8_t buffer[1024];
  size_t total = 0;
  bool writeError = false;
  unsigned long lastData = millis();
  while ((http.connected() || stream->available()) && total < (size_t)length) {
    watchdogFeed();
    size_t available = stream->available();
    if (available) {
      size_t want = min(min(available, sizeof(buffer)), (size_t)length - total);
      size_t n = stream->readBytes(buffer, want);
      if (Update.write(buffer, n) != n) {
        writeError = true;
        break;
      }
      SHA256_UPDATE(&sha, buffer, n);
      total += n;
      lastData = millis();
    } else if (millis() - lastData > OTA_STALL_MS) {
      break;
    } else {
      delay(1);
    }
  }
  http.end();
  unsigned char digest[32];
  SHA256_FINISH(&sha, digest);
  mbedtls_sha256_free(&sha);

  if (writeError) {
    Update.abort();
    return failed(version, "flash write failed");
  }
  if (total != (size_t)length) {
    Update.abort();
    return failed(version, "download incomplete");
  }
  // Check before the new slot is activated.
  if (!toHex(digest, sizeof(digest)).equalsIgnoreCase(sha256)) {
    Update.abort();
    return failed(version, "sha256 mismatch");
  }
  if (!Update.end(false)) {  // checks the image and activates the new slot
    return failed(version, String("finish: ") + Update.errorString());
  }

  store.begin(NAMESPACE, false);
  store.putUChar("ota_pend", 1);
  store.putUChar("ota_crash", 0);
  store.putString("ota_to", version);
  store.end();
  Serial.println(F("OTA: installed, restarting into the new firmware"));
  return true;
}

// ---------------------------------------------------------------------------
// Error text and watchdog
// ---------------------------------------------------------------------------
String otaLastError() {
  store.begin(NAMESPACE, false);
  String text = getText("last_err");
  store.end();
  return text;
}

void otaClearError() {
  store.begin(NAMESPACE, false);
  removeKey("last_err");
  store.end();
}

void watchdogStart() {
  esp_task_wdt_init(WATCHDOG_SECONDS, true);  // true = restart the device
  esp_task_wdt_add(nullptr);                  // watch the current task
}

void watchdogFeed() { esp_task_wdt_reset(); }
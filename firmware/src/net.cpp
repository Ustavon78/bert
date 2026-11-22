// SPDX-License-Identifier: GPL-3.0-or-later
#include "net.h"

#include <WiFiClientSecure.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>
#include <sys/time.h>
#include <time.h>

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

static WiFiClientSecure secureClient;
static WiFiClient plainClient;
static String caPem;  // must stay alive: setCACert() only keeps the pointer

void clockInit() {
  static const char *months = "JanFebMarAprMayJunJulAugSepOctNovDec";
  char monthName[4] = {0};
  int day = 0, year = 0, hour = 0, minute = 0, second = 0;
  sscanf(__DATE__, "%3s %d %d", monthName, &day, &year);  // e.g. "Nov 19 2026"
  sscanf(__TIME__, "%d:%d:%d", &hour, &minute, &second);
  const char *found = strstr(months, monthName);

  struct tm built = {};
  built.tm_year = year - 1900;
  built.tm_mon = found ? (int)(found - months) / 3 : 0;
  built.tm_mday = day;
  built.tm_hour = hour;
  built.tm_min = minute;
  built.tm_sec = second;
  time_t buildTime = mktime(&built);  // the time zone of the ESP32 is UTC unless set

  struct timeval now;
  gettimeofday(&now, nullptr);
  if (now.tv_sec < buildTime) {  // after a power-up the clock starts at 1970
    now.tv_sec = buildTime;
    now.tv_usec = 0;
    settimeofday(&now, nullptr);
  }
}

// The CA is stored as one line of base64 (the DER certificate). A PEM file is the same text
// with a header, a footer and a line break every 64 characters.
static String toPem(const String &base64) {
  String pem = "-----BEGIN CERTIFICATE-----\n";
  for (size_t i = 0; i < base64.length(); i += 64) {
    pem += base64.substring(i, i + 64);
    pem += "\n";
  }
  pem += "-----END CERTIFICATE-----\n";
  return pem;
}

WiFiClient *netClient(const Settings &s) {
  if (!s.server.startsWith("https://")) return &plainClient;

  if (s.ca.length() == 0) {
    Serial.println(F("https:// needs the CA certificate: set ca <content of ca.b64>"));
    return nullptr;
  }
  if (caPem.length() == 0) caPem = toPem(s.ca);
  secureClient.setCACert(caPem.c_str());  // the server certificate must be signed by this CA
  return &secureClient;
}

String sha256Prefix(const String &text) {
  mbedtls_sha256_context context;
  mbedtls_sha256_init(&context);
  SHA256_START(&context);
  SHA256_UPDATE(&context, (const unsigned char *)text.c_str(), text.length());
  unsigned char digest[32];
  SHA256_FINISH(&context, digest);
  mbedtls_sha256_free(&context);
  char out[9];
  snprintf(out, sizeof(out), "%02x%02x%02x%02x", digest[0], digest[1], digest[2], digest[3]);
  return String(out);
}
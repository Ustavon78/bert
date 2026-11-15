// SPDX-License-Identifier: GPL-3.0-or-later
#include "settings.h"

#include <Preferences.h>

#include "config.h"

static Preferences prefs;
// Always opened read/write: this creates the namespace on first use. A read-only open
// of a missing namespace fails with NOT_FOUND and floods the log.
static const char *NAMESPACE = "bert";

// Read a string key, or "" if it does not exist. Must be called while prefs is open.
// (getString() on a missing key works, but logs an error message.)
static String getOrEmpty(const char *key) {
  return prefs.isKey(key) ? prefs.getString(key, "") : String("");
}

void loadSettings(Settings &s) {
  prefs.begin(NAMESPACE, false);
  s.ssid = getOrEmpty("ssid");
  s.pass = getOrEmpty("pass");
  s.server = getOrEmpty("server");
  s.id = getOrEmpty("id");
  s.token = getOrEmpty("token");
  prefs.end();
}

bool settingsComplete(const Settings &s) {
  return s.ssid.length() && s.server.length() && s.id.length() && s.token.length();
}

String loadHash() {
  prefs.begin(NAMESPACE, false);
  String hash = getOrEmpty("hash");
  prefs.end();
  return hash;
}

void saveHash(const String &hash) {
  prefs.begin(NAMESPACE, false);
  prefs.putString("hash", hash);
  prefs.end();
}

static void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  show                 show the current settings"));
  Serial.println(F("  set ssid <value>     WiFi name"));
  Serial.println(F("  set pass <value>     WiFi password"));
  Serial.println(F("  set server <url>     e.g. http://192.168.1.10:8000"));
  Serial.println(F("  set id <value>       device id"));
  Serial.println(F("  set token <value>    device token"));
  Serial.println(F("  reset-hash           forget the shown image (forces a new download)"));
  Serial.println(F("  factory-reset        delete all settings"));
  Serial.println(F("  start                leave the console and continue"));
}

static void showSettings() {
  Settings s;
  loadSettings(s);
  Serial.printf("ssid:   %s\n", s.ssid.c_str());
  Serial.printf("pass:   %s\n", s.pass.length() ? "(set)" : "(empty)");
  Serial.printf("server: %s\n", s.server.c_str());
  Serial.printf("id:     %s\n", s.id.c_str());
  Serial.printf("token:  %s\n", s.token.length() ? "(set)" : "(empty)");
  Serial.printf("hash:   %s\n", loadHash().c_str());
}

// Returns true if the console should be left ("start").
static bool handleCommand(String line) {
  line.trim();
  if (line == "help") {
    printHelp();
  } else if (line == "show") {
    showSettings();
  } else if (line == "start") {
    return true;
  } else if (line == "reset-hash") {
    prefs.begin(NAMESPACE, false);
    prefs.remove("hash");
    prefs.end();
    Serial.println(F("OK hash removed"));
  } else if (line == "factory-reset") {
    prefs.begin(NAMESPACE, false);
    prefs.clear();
    prefs.end();
    Serial.println(F("OK all settings deleted"));
  } else if (line.startsWith("set ")) {
    String rest = line.substring(4);
    int space = rest.indexOf(' ');
    if (space < 1) {
      Serial.println(F("ERROR usage: set <key> <value>"));
      return false;
    }
    String key = rest.substring(0, space);
    String value = rest.substring(space + 1);
    if (key != "ssid" && key != "pass" && key != "server" && key != "id" && key != "token") {
      Serial.println(F("ERROR unknown key"));
      return false;
    }
    while (key == "server" && value.endsWith("/")) value.remove(value.length() - 1);
    prefs.begin(NAMESPACE, false);
    prefs.putString(key.c_str(), value);
    prefs.end();
    Serial.printf("OK %s saved\n", key.c_str());
  } else if (line.length()) {
    Serial.println(F("ERROR unknown command, type 'help'"));
  }
  return false;
}

void runSerialSetup(bool stayUntilComplete) {
  Serial.println(F("Setup console ('help' for commands). Starting normally if idle..."));
  Settings current;
  loadSettings(current);
  bool complete = settingsComplete(current);
  String line;
  unsigned long lastInput = millis();
  unsigned long lastHint = 0;
  while (true) {
    while (Serial.available()) {
      char c = Serial.read();
      lastInput = millis();
      if (c == '\n' || c == '\r') {
        if (line.length()) {
          bool start = handleCommand(line);
          line = "";
          loadSettings(current);  // only after a command, not in every loop pass
          complete = settingsComplete(current);
          if (start) {
            if (complete || !stayUntilComplete) return;
            Serial.println(F("Settings incomplete, cannot start yet."));
          }
        }
      } else if (line.length() < 200) {
        line += c;
      }
    }
    if (millis() - lastInput > SERIAL_SETUP_WINDOW_MS) {
      if (!stayUntilComplete || complete) return;
      if (millis() - lastHint > 3000) {
        Serial.println(F("Settings incomplete. Type 'help'."));
        lastHint = millis();
      }
    }
    delay(10);
  }
}
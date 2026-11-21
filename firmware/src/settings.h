// SPDX-License-Identifier: GPL-3.0-or-later
// Persistent settings (NVS flash) and the serial setup console.
#pragma once

#include <Arduino.h>

struct Settings {
  String ssid;
  String pass;
  String server;  // base URL without trailing slash, e.g. http://192.168.1.10:8000
  String id;      // device id
  String token;   // device token
  String ca;      // CA certificate of the server (DER as base64, one line), needed for https://
};

void loadSettings(Settings &s);
bool settingsComplete(const Settings &s);

// Hash of the image currently shown on the display ("" = unknown).
String loadHash();
void saveHash(const String &hash);

// Serial console to enter the settings. Runs for a short window; with
// stayUntilComplete = true it waits until all settings are present.
void runSerialSetup(bool stayUntilComplete);
// SPDX-License-Identifier: GPL-3.0-or-later
// Firmware updates over WiFi (OTA) and the safety nets around them.
//
// The device has two firmware slots. A new firmware is written into the inactive slot, checked
// (size, SHA-256) and only then activated. If the new firmware crashes right after the first
// start, the device switches back to the previous slot by itself.
#pragma once

#include <Arduino.h>

#include "settings.h"

// Call first thing in setup(): detects crashes of a freshly installed firmware and goes back
// to the previous firmware if needed (restarts the device in that case).
void otaBootCheck();

// Call when the firmware has proven to work (check-in done, image drawn).
void otaMarkGood();

// Download and install a firmware into the inactive slot. Returns true if it is installed
// and the device has to restart now. Returns false on any problem (the reason is remembered
// and reported to the server with the next check-in).
bool otaInstall(const Settings &s, const String &version, const String &sha256, size_t size);

// Last error for the server ("" = none). Clear it after it was sent.
String otaLastError();
void otaClearError();

// Watchdog: restarts the device if the firmware hangs.
void watchdogStart();
void watchdogFeed();
// SPDX-License-Identifier: GPL-3.0-or-later
// Calls to the Bert server API.
#pragma once

#include <Arduino.h>

#include "settings.h"

enum class Action { None, Image, Ota, Deactivated };

struct CheckinResult {
  bool ok = false;            // false = request failed (see httpCode)
  int httpCode = 0;
  Action action = Action::None;
  uint32_t sleepSeconds = 0;
  String hash;                // desired image hash (action == Image)
  String fw;                  // desired firmware version (action == Ota)
};

// POST /api/checkin
CheckinResult checkin(const Settings &s, const String &currentHash);

// GET /api/image. Streams the image and returns its hash from the X-Image-Hash header.
// Later the received chunks go to the display driver (see TODO in api.cpp).
bool downloadImage(const Settings &s, String &imageHash);
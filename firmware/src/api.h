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
  String sha256;              // SHA-256 of that firmware (action == Ota)
  uint32_t size = 0;          // size of that firmware in bytes (action == Ota)
};

// POST /api/checkin
CheckinResult checkin(const Settings &s, const String &currentHash);

// GET /api/image. Reads the complete image (IMAGE_SIZE_BYTES) into buffer and returns the
// hash from the X-Image-Hash header.
bool downloadImage(const Settings &s, uint8_t *buffer, size_t bufferSize, String &imageHash);
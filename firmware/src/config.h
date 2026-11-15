// SPDX-License-Identifier: GPL-3.0-or-later
// Compile-time settings, identical for every device.
// Per-device values (WiFi, server, id, token) are NOT stored here. They live in the
// flash (NVS) and are set over the serial console, see settings.cpp.
#pragma once

#define FW_VERSION "0.1.2"

// Timing
#define WIFI_TIMEOUT_MS 15000
#define HTTP_TIMEOUT_MS 15000
#define RETRY_SLEEP_SECONDS 900       // sleep time after an error (WiFi/server problem)
#define MIN_SLEEP_SECONDS 10          // raise for production: protects the battery if the server sends 0
#define MAX_SLEEP_SECONDS 604800      // 7 days
#define SERIAL_SETUP_WINDOW_MS 3000   // console window after power-on (not after timer wake-ups)

// Image: two bit planes (black, red) of 800x480 pixels, 1 bit per pixel
#define IMAGE_SIZE_BYTES 96000

// Board-specific pins (display wiring) will be added here later.
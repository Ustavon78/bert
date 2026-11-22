// SPDX-License-Identifier: GPL-3.0-or-later
// Compile-time settings, identical for every device of a board type.
// Per-device values (WiFi, server, id, token) are NOT stored here. They live in the
// flash (NVS) and are set over the serial console, see settings.cpp.
#pragma once

#ifndef FW_VERSION
#define FW_VERSION "0.4.2"
#endif

// Timing
#define WIFI_TIMEOUT_MS 15000
#define HTTP_TIMEOUT_MS 15000
#define RETRY_SLEEP_SECONDS 900       // sleep time after an error (WiFi/server problem)
#define MIN_SLEEP_SECONDS 10          // raise for production: protects the battery if the server sends 0
#define MAX_SLEEP_SECONDS 604800      // 7 days
#define SERIAL_SETUP_WINDOW_MS 10000  // console window after power-on (not after timer wake-ups)
#define SERIAL_LINE_MAX 1500          // longest console line (the CA certificate is about 550 characters)

// ---------------------------------------------------------------------------
// Safety (updates and hangs)
// ---------------------------------------------------------------------------
#define WATCHDOG_SECONDS 180   // restart the device if the firmware hangs for this long
#define OTA_STALL_MS 15000     // abort a firmware download if no data arrives for this long
#define OTA_MAX_FAILS 3        // give up on a firmware version after this many failed installs
#define OTA_MAX_CRASHES 2      // crashes of a freshly installed firmware before going back

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------
// GxEPD2 driver class of the panel. Default: 7.5" black/white/red, 800x480 (GDEW075Z08,
// Waveshare 7.5inch e-Paper (B) V2). Other 800x480 tri-color panels, e.g. GDEY075Z08, use
// GxEPD2_750c_GDEY075Z08. See the GxEPD2 README for the matching class.
#define EPD_DRIVER GxEPD2_750c_Z08
#define EPD_WIDTH 800
#define EPD_HEIGHT 480

// The server sends two bit planes (black, then red), 1 bit per pixel, 1 = ink.
// GxEPD2 expects 0 = ink, so the planes are inverted when drawing. If black and white
// (or red and white) look swapped in the 'test' pattern, set this to 0.
#define EPD_INVERT 1

#define IMAGE_PLANE_BYTES ((EPD_WIDTH / 8) * EPD_HEIGHT)  // 48000
#define IMAGE_SIZE_BYTES (2 * IMAGE_PLANE_BYTES)          // 96000

// ---------------------------------------------------------------------------
// Board specific pins
// ---------------------------------------------------------------------------
#if defined(BOARD_WAVESHARE_ESP32)
// Waveshare e-Paper ESP32 driver board
#define BOARD_NAME "waveshare_esp32"  // selects the firmware file <board>_<version>.bin
#define PIN_EPD_SCK 13
#define PIN_EPD_MISO 12
#define PIN_EPD_MOSI 14
#define PIN_EPD_CS 15
#define PIN_EPD_DC 27
#define PIN_EPD_RST 26
#define PIN_EPD_BUSY 25
#elif defined(BOARD_XIAO_EE05)
#define BOARD_NAME "xiao_ee05"
#error "Set the display pins for the XIAO EE05 here (see the Seeed wiki for the pin map)."
#else
#error "No board selected. Use one of the environments in platformio.ini."
#endif
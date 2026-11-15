// SPDX-License-Identifier: GPL-3.0-or-later
#include "display.h"

#include <GxEPD2_3C.h>
#include <SPI.h>
#include <esp_heap_caps.h>

#include "config.h"

// We write complete planes to the controller, so the page buffer of the GFX layer is not used.
// A small page height keeps its static buffers tiny.
static GxEPD2_3C<EPD_DRIVER, 8> display(EPD_DRIVER(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

uint8_t *displayAllocBuffer() {
  void *memory = heap_caps_malloc(IMAGE_SIZE_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!memory) memory = heap_caps_malloc(IMAGE_SIZE_BYTES, MALLOC_CAP_8BIT);
  return static_cast<uint8_t *>(memory);
}

void displayShow(const uint8_t *blackPlane, const uint8_t *redPlane) {
  SPI.end();
  SPI.begin(PIN_EPD_SCK, PIN_EPD_MISO, PIN_EPD_MOSI, PIN_EPD_CS);
  // initial = false: the whole screen is written anyway, no extra clearing pass needed.
  display.init(0, false, 2, false);
  display.epd2.writeImage(blackPlane, redPlane, 0, 0, EPD_WIDTH, EPD_HEIGHT, EPD_INVERT != 0, false, false);
  display.epd2.refresh(false);  // full refresh, blocks until the panel is done
  display.hibernate();
}

void displayTestPattern() {
  uint8_t *buffer = displayAllocBuffer();
  if (!buffer) {
    Serial.println(F("test: not enough memory"));
    return;
  }
  uint8_t *black = buffer;
  uint8_t *red = buffer + IMAGE_PLANE_BYTES;
  memset(black, 0x00, IMAGE_PLANE_BYTES);  // 0 = no ink
  memset(red, 0x00, IMAGE_PLANE_BYTES);

  const int bytesPerRow = EPD_WIDTH / 8;
  for (int y = 0; y < EPD_HEIGHT; y++) {
    for (int bx = 0; bx < bytesPerRow; bx++) {
      if (bx < bytesPerRow / 2) black[y * bytesPerRow + bx] = 0xFF;
      else red[y * bytesPerRow + bx] = 0xFF;
    }
  }
  // White notch (60 rows x 64 pixels) in the top-left corner shows the orientation.
  for (int y = 0; y < 60; y++)
    for (int bx = 0; bx < 8; bx++) black[y * bytesPerRow + bx] = 0x00;

  Serial.println(F("test: drawing pattern (takes about 20 seconds)..."));
  displayShow(black, red);
  Serial.println(F("test: done"));
  heap_caps_free(buffer);
}
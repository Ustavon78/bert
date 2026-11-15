// SPDX-License-Identifier: GPL-3.0-or-later
// E-paper output (GxEPD2).
#pragma once

#include <Arduino.h>

// Allocate the buffer for one image (two planes). Uses PSRAM if available.
// Call it early, before WiFi starts, while the heap is not fragmented. Returns nullptr on failure.
uint8_t *displayAllocBuffer();

// Show an image given as two planes (black, red) of IMAGE_PLANE_BYTES each, 1 = ink.
// Blocks until the refresh is finished (about 20 seconds), then puts the panel to sleep.
void displayShow(const uint8_t *blackPlane, const uint8_t *redPlane);

// Draw a test pattern: left half black with a white notch in the top-left corner, right half red.
void displayTestPattern();
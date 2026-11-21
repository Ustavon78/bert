// SPDX-License-Identifier: GPL-3.0-or-later
// Network client for the server: plain HTTP or HTTPS with the school's own CA.
#pragma once

#include <WiFiClient.h>

#include "settings.h"

// The display has no reliable clock. Certificates are checked against the date, so the clock is
// set to the build date of the firmware if it is earlier (the certificates created by
// make_certs.py are valid from 2020 on purpose). Call once at the start.
void clockInit();

// The client for the server from the settings: TLS with the stored CA certificate for
// https://, a plain client for http://. Returns nullptr if https:// is configured without a CA
// (without a CA the connection would not be verified, that is never allowed).
WiFiClient *netClient(const Settings &s);
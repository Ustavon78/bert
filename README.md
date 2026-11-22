# BERT – Battery-powered E-Paper Room Timetable

**BERT** is a low-power digital door signage system built as part of a German high school research project (*BeLL – Besondere Lernleistung*) for [Gymnasium Olbernhau](https://www.gymnasium-olbernhau.de/).
It was originally built for the [EDUARD](https://github.com/realrdbr/eduard) School Project by realrdbr, but has now been converted for a stand-alone use case with VPMobil24.

It displays daily room schedules and live timetable changes (highlighted in red) on a tri-color e-paper displays outside the classrooms, fetching pre-rendered data from a central Server connected to **VpMobil24**.

### NOTE:  This documentation applies to the software only. If you are also interested in the hardware, read  the _hardware.md_ or visit my website for detailed information (also in German)

## Key Features 
- DeepSleep for the ESP32 
- **Server-Side Rendering:** The Raspberry Pi renders ready-to-display black/red bitmaps to save battery and CPU time on the clients.
- **Smart Sync:** Displays only refresh the e-paper panel when the room schedule actually changed (hash comparison).
- **Change Highlighting:** Substitutions, room changes, and cancellations are highlighted using the 3rd display color (red).

## Installation
1. clone repo `git clone https://github.com/Ustavon78/bert`
2. install venv
3. install all requirements
```bash
git clone https://github.com/Ustavon78/bert
cd bert/backend
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt```


uvicorn app:app --reload

curl -X POST http://127.0.0.1:8000/api/checkin \
  -H "X-Device-Id: 557552" -H "X-Token: GlGSFhq8tM19iF84gOMgo1Lg8TC57b3xqgsPoFCn-zY" \
  -H "Content-Type: application/json" -d '{"hash":"","fw":"1.0.0"}'

uvicorn app:app --host 0.0.0.0 --port 8000
pio device monitor
pio run
pio run -t upload
set server https://192.168.1.131
set ca MIIBmDCCAT2gAwIBAgIUR5FaH8HqZR74UM1+qWIb4Xr/tiswCgYIKoZIzj0EAwIwJzENMAsGA1UECgwEQmVydDEWMBQGA1UEAwwNQmVydCBsb2NhbCBDQTAgFw0yMDAxMDEwMDAwMDBaGA8yMDYwMDEwMTAwMDAwMFowJzENMAsGA1UECgwEQmVydDEWMBQGA1UEAwwNQmVydCBsb2NhbCBDQTBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABKbcHeliCYXbSo0hVFckheQeso0UsQoz+MqwE5G6l9knROh1Fp9SdPZZqlLCPKxx3Veic6XrjO58hYtA320HglujRTBDMBIGA1UdEwEB/wQIMAYBAf8CAQAwDgYDVR0PAQH/BAQDAgEGMB0GA1UdDgQWBBRVhyHN/iPPkYg5NrRuRqPE/BvvajAKBggqhkjOPQQDAgNJADBGAiEAx2nZxU4NDjRImCwQjLPPE8a83oVGqCuBzJgdBCYfabICIQDVon+32GudH7e5DmeMiWeXC7Cs+KaDviHRGBFnYpFg3w==

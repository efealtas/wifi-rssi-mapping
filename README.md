# wifi-rssi-mapping

Interactive Python tool to map WiFi signal measurements while walking around a room or even a whole house and accurately estimate where the router is.

## Features
- RSSI sampling on each `done` step
- Works for room-scale mapping and larger house-scale mapping
- Corner-by-corner mapping flow
- Support for non-straight edges via per-step turns
- Accurate router location estimation from collected measurements
- Matplotlib map output at each stage

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install matplotlib
```

## Run
```bash
python wifi_signal.py
```

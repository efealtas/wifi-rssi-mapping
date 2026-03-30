# wifi-rssi-mapping

This project is designed for indoor WiFi mapping at both room scale and whole-house scale using RSSI (Received Signal Strength Indicator) sampling. It guides measurement collection during movement and produces a data-driven estimate of router location with visual map outputs.

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

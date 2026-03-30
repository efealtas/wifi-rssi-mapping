# wifi-rssi-mapping

Interactive Python tool to map WiFi signal measurements while walking around a room and estimate router position.

## Features
- RSSI sampling on each `done` step
- Corner-by-corner mapping flow
- Support for non-straight edges via per-step turns
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

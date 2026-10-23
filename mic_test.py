#!/usr/bin/python3
"""
Step 1: prove the microphone works, with no LED matrix involved.

Setup on the Pi:
    sudo apt install libportaudio2
    pip install sounddevice numpy

Run:
    python mic_test.py            # lists devices, then prints a live level meter
    python mic_test.py 2          # use input device index 2

Talk and watch the numbers. Note the "quiet" and "talking" dBFS values;
they become NOISE_FLOOR_DB and CEILING_DB in voice_bar.py.
"""

import sys

import numpy as np
import sounddevice as sd

print(sd.query_devices())

device = int(sys.argv[1]) if len(sys.argv) > 1 else None
info = sd.query_devices(device, "input")
rate = int(info["default_samplerate"])
print(f"\nUsing: {info['name']} @ {rate} Hz  (Ctrl-C to quit)\n")


def callback(indata, frames, time, status):
    rms = np.sqrt(np.mean(indata[:, 0] ** 2))
    db = 20 * np.log10(max(rms, 1e-6))  # dBFS: 0 is max, about -60 is quiet room
    bar = "#" * max(0, int((db + 70) / 70 * 50))
    print(f"\r{db:6.1f} dBFS {bar:<50}", end="", flush=True)


with sd.InputStream(device=device, channels=1, samplerate=rate,
                    blocksize=rate // 30, callback=callback):
    try:
        while True:
            sd.sleep(1000)
    except KeyboardInterrupt:
        print()

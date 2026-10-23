#!/usr/bin/python3
"""
Step 2: a centered, segmented equalizer-style bar on the LED matrix that
grows outward from the middle with mic volume.

Run (after mic_test.py works):
    python voice_bar.py            # default input device
    python voice_bar.py 2          # input device index 2
"""

import sys
import time

import numpy as np
import sounddevice as sd

import adafruit_blinka_raspberry_pi5_piomatter as piomatter

# --- Display (same geometry as single_panel_simpletest.py) ---
WIDTH = 32
HEIGHT = 16
BAR_HEIGHT = 8          # rows tall, centered vertically
SEG_W = 2               # pixels per segment
SEG_GAP = 1             # dark pixels between segments
HALF = WIDTH // 2
N_SEG = (HALF + SEG_GAP) // (SEG_W + SEG_GAP)  # segments per side

# Color of each segment, center -> edge. Louder speech lights more of them,
# so the bar goes green -> yellow -> red as volume rises.
SEG_COLORS = [
    (0, 200, 0),
    (0, 200, 0),
    (200, 200, 0),
    (255, 90, 0),
    (255, 0, 0),
]
assert len(SEG_COLORS) == N_SEG, f"need {N_SEG} colors"
IDLE_COLOR = (0, 25, 0)  # dim center segment so it's clear the thing is on

# --- Audio tuning: set these from what mic_test.py showed you ---
NOISE_FLOOR_DB = -40.0  # at/below this, nothing lit
CEILING_DB = -10.0      # at/above this, all segments lit
SENSITIVITY_DB = 0.0    # added to the measured level; the pot will drive this
ATTACK = 0.7            # 0..1, higher = rises faster
RELEASE = 0.15          # 0..1, higher = falls faster
FPS = 30


def read_sensitivity_db():
    """Extra gain in dB. Swap this for a pot reading later (e.g. +/-15 dB)."""
    return SENSITIVITY_DB


device = int(sys.argv[1]) if len(sys.argv) > 1 else None
rate = int(sd.query_devices(device, "input")["default_samplerate"])

raw_db = -100.0  # latest measured level, written by the audio thread


def audio_callback(indata, frames, time_info, status):
    global raw_db
    rms = np.sqrt(np.mean(indata[:, 0] ** 2))
    raw_db = 20 * np.log10(max(rms, 1e-6))


geometry = piomatter.Geometry(width=WIDTH, height=HEIGHT, n_addr_lines=3,
                              rotation=piomatter.Orientation.Normal)
framebuffer = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
matrix = piomatter.PioMatter(colorspace=piomatter.Colorspace.RGB888Packed,
                             pinout=piomatter.Pinout.AdafruitMatrixBonnet,
                             framebuffer=framebuffer,
                             geometry=geometry)


def draw_bars(smoothed):
    """smoothed is 0..1; lights smoothed * N_SEG segments each side of center."""
    framebuffer[:] = 0
    top = (HEIGHT - BAR_HEIGHT) // 2
    rows = slice(top, top + BAR_HEIGHT)
    lit = smoothed * N_SEG
    for i in range(N_SEG):
        # last partial segment is dimmed so motion looks smooth
        brightness = float(np.clip(lit - i, 0, 1))
        if i == 0 and brightness == 0:
            color = IDLE_COLOR
        else:
            color = tuple(int(c * brightness) for c in SEG_COLORS[i])
        offset = i * (SEG_W + SEG_GAP)
        framebuffer[rows, HALF + offset:HALF + offset + SEG_W] = color              # right
        framebuffer[rows, HALF - offset - SEG_W:HALF - offset] = color              # left
    matrix.show()


smoothed = 0.0
with sd.InputStream(device=device, channels=1, samplerate=rate,
                    blocksize=rate // FPS, callback=audio_callback):
    print("Running. Ctrl-C to quit.")
    try:
        while True:
            db = raw_db + read_sensitivity_db()
            level = float(np.clip((db - NOISE_FLOOR_DB) / (CEILING_DB - NOISE_FLOOR_DB), 0, 1))
            # fast attack, slow release so it feels punchy but not flickery
            k = ATTACK if level > smoothed else RELEASE
            smoothed += (level - smoothed) * k
            draw_bars(smoothed)
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        pass

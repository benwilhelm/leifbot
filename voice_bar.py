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
NOISE_FLOOR_DB = -35.0  # at/below this, nothing lit
CEILING_DB = 0.0      # at/above this, all segments lit
SENSITIVITY_DB = 0.0    # added to the measured level; the pot will drive this
ATTACK = 0.7            # 0..1, higher = rises faster
RELEASE = 0.15          # 0..1, higher = falls faster
FPS = 30


def read_sensitivity_db():
    """Extra gain in dB. Swap this for a pot reading later (e.g. +/-15 dB)."""
    return SENSITIVITY_DB


if len(sys.argv) > 1:
    in_dev = out_dev = int(sys.argv[1])
else:
    in_dev, out_dev = sd.default.device  # system defaults; may be -1 if unset
device = (in_dev, out_dev)
rate = int(sd.query_devices(in_dev, "input")["default_samplerate"])
out_channels = min(2, sd.query_devices(out_dev, "output")["max_output_channels"])

# --- Voice effect (robot voice) ---
EFFECT_ON = True
INPUT_GAIN = 3.0        # boosts the voice before the effect; more = louder + grittier
OUTPUT_GAIN = 1.5       # final speaker volume; clipped at full scale. Watch for feedback
RING_FREQ_HZ = 50.0     # lower = gruffer/buzzier, higher = more metallic
RING_MIX = 0.7          # 0 = dry voice, 1 = fully ring-modulated
CRUSH_LEVELS = 24       # fewer = grittier (quantization steps per side)
BLOCK = 512             # samples per audio block; small = low latency (~11 ms)

# --- Noise rejection ---
HP_CUTOFF_HZ = 150.0    # cuts rumble/wind/handling noise below this; 0 disables
GATE_HYSTERESIS_DB = 5.0  # gate closes this far below NOISE_FLOOR_DB (stops chatter)
GATE_HOLD_MS = 250      # stay open this long after the voice drops (no clipped words)
GATE_RAMP_MS = 10       # fade in/out time (avoids clicks)

raw_db = -100.0  # latest measured level, written by the audio thread
phase = 0.0      # ring modulator oscillator phase, carried across blocks
hp_alpha = np.exp(-2 * np.pi * HP_CUTOFF_HZ / rate)
hp_x1 = hp_y1 = 0.0   # high-pass filter state
gate_open = False
gate_gain = 0.0
hold_left = 0         # samples of hold remaining


def highpass(x):
    """One-pole high-pass, state carried across blocks."""
    global hp_x1, hp_y1
    y = np.empty_like(x)
    x1, y1, a = hp_x1, hp_y1, hp_alpha
    for i, xi in enumerate(x):
        y1 = a * (y1 + xi - x1)
        x1 = xi
        y[i] = y1
    hp_x1, hp_y1 = x1, y1
    return y


def apply_gate(x, db):
    """Mute x unless db is above the noise floor (with hysteresis + hold)."""
    global gate_open, gate_gain, hold_left
    open_db = NOISE_FLOOR_DB
    close_db = NOISE_FLOOR_DB - GATE_HYSTERESIS_DB
    if db >= open_db:
        gate_open = True
        hold_left = int(GATE_HOLD_MS / 1000 * rate)
    elif gate_open and db < close_db:
        hold_left -= len(x)
        if hold_left <= 0:
            gate_open = False
    target = 1.0 if gate_open else 0.0
    # linear ramp toward target, at most GATE_RAMP_MS worth per block
    step = len(x) / max(1, GATE_RAMP_MS / 1000 * rate)
    end = gate_gain + np.clip(target - gate_gain, -step, step)
    ramp = np.linspace(gate_gain, end, len(x), dtype=np.float32)
    gate_gain = float(end)
    return x * ramp


def robotize(x):
    """x: float32 mono block in -1..1. Ring-mod + bit-crush + soft clip."""
    global phase
    n = len(x)
    t = phase + 2 * np.pi * RING_FREQ_HZ / rate * np.arange(n)
    phase = (phase + 2 * np.pi * RING_FREQ_HZ / rate * n) % (2 * np.pi)
    ring = x * np.sin(t)
    y = (1 - RING_MIX) * x + RING_MIX * ring
    y = np.round(y * CRUSH_LEVELS) / CRUSH_LEVELS
    return np.tanh(2.0 * y)


def audio_callback(indata, outdata, frames, time_info, status):
    global raw_db
    mono = highpass(indata[:, 0]) if HP_CUTOFF_HZ > 0 else indata[:, 0]
    # level for the bar comes from the filtered dry mic signal, not the effect
    rms = np.sqrt(np.mean(mono ** 2))
    raw_db = 20 * np.log10(max(rms, 1e-6))
    mono = apply_gate(mono, raw_db + read_sensitivity_db())
    mono = mono * INPUT_GAIN  # after level measurement, so the bar/gate don't change
    out = robotize(mono) if EFFECT_ON else mono
    out = np.clip(out * OUTPUT_GAIN, -1.0, 1.0)  # hard limit so it can't wrap/glitch
    outdata[:] = out[:, None]  # same signal to every output channel


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
with sd.Stream(device=device, channels=(1, out_channels), samplerate=rate,
               blocksize=BLOCK, latency="low", callback=audio_callback):
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

#!/usr/bin/python3
"""
voice_bar.py - the main program for the robot costume!

What it does, in plain English:
  1. Listens to the microphone.
  2. Makes the voice sound like a robot and plays it out of the speaker.
  3. Shows how loud the voice is as a glowing bar on the LED panel.
     The bar grows out from the middle, and it goes green -> yellow -> red
     as you get louder.

How to run it:
    python voice_bar.py            # use the computer's default mic and speaker
    python voice_bar.py 2          # use audio device number 2 for both
                                   # (mic_test.py shows you the numbers)

Press Ctrl-C to stop it.
"""

# ---------------------------------------------------------------------------
# Imports: borrowing code that other people already wrote
# ---------------------------------------------------------------------------
import sys   # lets us read what was typed after the script name (like the "2" above)
import time  # lets us wait a little between pictures

import numpy as np          # fast math on big lists of numbers (our sound is a list of numbers!)
import sounddevice as sd    # talks to the microphone and the speaker

# The code that drives the LED panel. "as piomatter" just gives it a shorter name.
import adafruit_blinka_raspberry_pi5_piomatter as piomatter

# ---------------------------------------------------------------------------
# Settings for the LED panel
# Change these to change how the bar looks.
# ---------------------------------------------------------------------------
WIDTH = 32              # the panel is 32 dots (pixels) wide...
HEIGHT = 16             # ...and 16 dots tall
BAR_HEIGHT = 12         # how many rows tall the bar is (it's centered up and down)
SEG_W = 2               # each lit chunk ("segment") is 2 pixels wide
SEG_GAP = 1             # with 1 dark pixel between chunks
HALF = WIDTH // 2       # the middle column of the panel (// means divide and round down)

# How many segments fit on ONE side of the middle?
N_SEG = (HALF + SEG_GAP) // (SEG_W + SEG_GAP)

# The color of each segment, starting at the middle and going to the edge.
# Colors are (red, green, blue), each from 0 (off) to 255 (full power).
# Louder voice = more segments light up = the colors change from green to red.
SEG_COLORS = [
    (0, 255, 0),     # green
    (0, 255, 0),     # green
    (255, 255, 0),   # yellow (red + green mixed)
    (255, 110, 0),   # orange
    (255, 0, 0),     # red
]
# A safety check: stop right away if the list of colors is the wrong length.
assert len(SEG_COLORS) == N_SEG, f"need {N_SEG} colors"

# A dim green dot in the middle when it's quiet, so you can tell it's turned on.
IDLE_COLOR = (0, 60, 0)

# ---------------------------------------------------------------------------
# Settings for how the bar reacts to sound
#
# Loudness is measured in "dB" (decibels). Here, 0 dB is the loudest the mic
# can possibly hear, and quieter sounds are NEGATIVE numbers (like -35 or -50).
# Use mic_test.py to find the right numbers for your mic.
# ---------------------------------------------------------------------------
NOISE_FLOOR_DB = -35.0  # quieter than this = ignored (no segments light up)
CEILING_DB = 0.0        # this loud or louder = ALL segments light up
SENSITIVITY_DB = 0.0    # extra boost added to the mic level (negative = less sensitive)
ATTACK = 0.7            # how fast the bar jumps UP (0 to 1, bigger = faster)
RELEASE = 0.15          # how fast the bar falls DOWN (smaller = smoother, slower)
FPS = 30                # how many times per second we redraw the panel


def read_sensitivity_db():
    """Return the extra sensitivity boost, in dB.

    Right now it's just the number above. Later, if we wire up a knob
    (a potentiometer), this is the one function to change so the knob
    controls the sensitivity.
    """
    return SENSITIVITY_DB


# ---------------------------------------------------------------------------
# Pick which microphone and speaker to use
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    # Someone typed a number after the script name: use that device for both.
    in_dev = out_dev = int(sys.argv[1])
else:
    # Otherwise use whatever the computer thinks is the default mic and speaker.
    in_dev, out_dev = sd.default.device
device = (in_dev, out_dev)

# Ask the sound card how many sound measurements ("samples") it takes per second.
rate = int(sd.query_devices(in_dev, "input")["default_samplerate"])
# Use up to 2 speaker channels (left and right).
out_channels = min(2, sd.query_devices(out_dev, "output")["max_output_channels"])

# ---------------------------------------------------------------------------
# Settings for the robot voice
# ---------------------------------------------------------------------------
EFFECT_ON = True        # set to False to hear your normal voice
OUTPUT_GAIN = 1.0       # speaker volume. Turn it up slowly! Too loud = squealing feedback
RING_FREQ_HZ = 150.0    # the buzz speed: lower = gruff and growly, higher = metallic
RING_MIX = 1            # 0 = normal voice, 1 = all robot buzz
CRUSH_LEVELS = 24       # fewer = more crunchy and "video game" sounding
BLOCK = 512             # we handle sound in chunks this big (small chunk = less delay)
PITCH_SEMITONES = -5.0  # change the voice's pitch: negative = deeper, 0 = off. -12 = one octave down
PITCH_WINDOW_MS = 40    # shifter memory size: smaller = less delay but more warble

# ---------------------------------------------------------------------------
# Settings for ignoring background noise
# ---------------------------------------------------------------------------
HP_CUTOFF_HZ = 150.0    # cuts deep rumbles (wind, bumps). 0 turns this filter off
GATE_HYSTERESIS_DB = 5.0  # the gate closes a bit below where it opened, so it doesn't flutter
GATE_HOLD_MS = 250      # after you stop talking, wait this many milliseconds before closing
GATE_RAMP_MS = 10       # fade the sound in/out over this time so it doesn't click

# ---------------------------------------------------------------------------
# Variables the program remembers between chunks of sound
# ("global" memory that the sound code updates)
# ---------------------------------------------------------------------------
raw_db = -100.0         # the latest loudness measured by the mic (starts very quiet)
phase = 0.0             # where the robot-buzz wave is in its up-and-down cycle
hp_alpha = np.exp(-2 * np.pi * HP_CUTOFF_HZ / rate)  # a number the rumble filter needs
hp_x1 = hp_y1 = 0.0     # the rumble filter's memory of the last sound it saw
gate_open = False       # is the noise gate open (sound allowed through)?
gate_gain = 0.0         # how open the gate is right now: 0 = closed, 1 = fully open
hold_left = 0           # how much "keep the gate open" time is left
PS_WIN = int(rate * PITCH_WINDOW_MS / 1000)   # pitch shifter memory size, in samples
PS_HIST = PS_WIN + 2                          # how much past sound we keep
ps_hist = np.zeros(PS_HIST, dtype=np.float32)  # the pitch shifter's memory of recent sound
ps_phase = 0.0                                 # how far the shifter's "readers" have drifted


def highpass(x):
    """Remove low rumbling sounds (wind, bumps) and keep the voice.

    x is a chunk of sound: a list of numbers. We go through them one at a
    time and mix each with the previous one in a way that cancels slow,
    deep wiggles but lets fast wiggles (voices) through.
    """
    global hp_x1, hp_y1
    y = np.empty_like(x)                 # an empty list the same size, for the answer
    x1, y1, a = hp_x1, hp_y1, hp_alpha   # start from what we remembered last time
    for i, xi in enumerate(x):
        y1 = a * (y1 + xi - x1)          # the filter math
        x1 = xi                          # remember this sample for next time
        y[i] = y1
    hp_x1, hp_y1 = x1, y1                # save our memory for the next chunk
    return y


def apply_gate(x, db):
    """Noise gate: only let sound through when someone is actually talking.

    Think of a door. When the sound is loud enough the door opens. It stays
    open a little while after you stop, so the ends of words aren't chopped
    off, and it opens/closes slowly (not instantly) so it doesn't click.
    """
    global gate_open, gate_gain, hold_left
    open_db = NOISE_FLOOR_DB                       # open when louder than this
    close_db = NOISE_FLOOR_DB - GATE_HYSTERESIS_DB  # only close when quieter than THIS
    if db >= open_db:
        gate_open = True
        hold_left = int(GATE_HOLD_MS / 1000 * rate)  # restart the "stay open" timer
    elif gate_open and db < close_db:
        hold_left -= len(x)                          # count down the timer
        if hold_left <= 0:
            gate_open = False                        # time's up: close the door
    target = 1.0 if gate_open else 0.0               # fully open or fully closed
    # Slide the volume toward the target a little bit at a time.
    step = len(x) / max(1, GATE_RAMP_MS / 1000 * rate)
    end = gate_gain + np.clip(target - gate_gain, -step, step)
    ramp = np.linspace(gate_gain, end, len(x), dtype=np.float32)  # smooth slope of volumes
    gate_gain = float(end)
    return x * ramp                                  # turn the volume up or down


def pitch_shift(x):
    """Make the voice deeper (or higher) without changing how fast it talks.

    Idea: keep a short memory of recent sound, and play it back at a different
    speed, like a tape player running slow. Playing back slower makes a lower
    pitch, but the player would slowly fall behind (or run ahead of) the live
    sound. To fix that, there are TWO readers, half a window apart. Each reader
    fades out just as it jumps back to catch up, while the other fades in, so
    you never hear the jump.
    """
    global ps_hist, ps_phase
    n = len(x)
    speed = 2 ** (PITCH_SEMITONES / 12)        # 12 semitones = double the speed/pitch
    sound = np.concatenate([ps_hist, x])        # recent past + the new chunk
    j = np.arange(n)
    out = np.zeros(n, dtype=np.float32)
    for offset in (0, PS_WIN / 2):              # the two readers
        # How far behind the live sound this reader is. It drifts, then wraps around.
        delay = (ps_phase + offset + j * (1 - speed)) % PS_WIN
        pos = PS_HIST + j - delay - 1           # where in the memory to read from
        i0 = np.floor(pos).astype(int)
        frac = pos - i0
        # Read between two neighbouring samples for smoother sound.
        s = sound[i0] * (1 - frac) + sound[i0 + 1] * frac
        # Fade the reader out as it nears the point where it jumps back.
        out += s * np.sin(np.pi * delay / PS_WIN) ** 2
    ps_phase = (ps_phase + n * (1 - speed)) % PS_WIN
    ps_hist = sound[-PS_HIST:]                  # remember the latest sound for next time
    return out


def robotize(x):
    """Make a voice sound like a robot.

    x is a chunk of sound with values from -1 to 1. Three tricks:
      1. Ring modulation: multiply the voice by a fast-wobbling wave. This
         gives that classic buzzy robot sound.
      2. Bit-crush: round every value to the nearest of a few steps, which
         makes the sound crunchy, like an old video game.
      3. Soft clip (tanh): gently squash very loud peaks so they don't
         crackle harshly.
    """
    global phase
    n = len(x)
    # Build the wobbling wave (a sine wave), continuing where the last chunk ended.
    t = phase + 2 * np.pi * RING_FREQ_HZ / rate * np.arange(n)
    phase = (phase + 2 * np.pi * RING_FREQ_HZ / rate * n) % (2 * np.pi)
    ring = x * np.sin(t)                                  # trick 1: multiply by the wave
    y = (1 - RING_MIX) * x + RING_MIX * ring              # blend normal voice and robot buzz
    y = np.round(y * CRUSH_LEVELS) / CRUSH_LEVELS         # trick 2: round to fewer steps
    return np.tanh(2.0 * y)                               # trick 3: squash the peaks


def audio_callback(indata, outdata, frames, time_info, status):
    """Runs automatically every time a new chunk of sound arrives.

    indata  = sound coming IN from the microphone
    outdata = sound we fill in to go OUT to the speaker
    """
    global raw_db
    # Take the mic's sound (first channel) and remove the deep rumble if enabled.
    mono = highpass(indata[:, 0]) if HP_CUTOFF_HZ > 0 else indata[:, 0]
    # Measure loudness. RMS is a kind of average strength of the sound wave.
    # The bar uses this measurement of your plain voice, not the robot version.
    rms = np.sqrt(np.mean(mono ** 2))
    raw_db = 20 * np.log10(max(rms, 1e-6))   # turn it into dB (max() avoids log of zero)
    mono = apply_gate(mono, raw_db + read_sensitivity_db())  # mute it if it's just background noise
    if PITCH_SEMITONES != 0:
        mono = pitch_shift(mono)                              # make the voice deeper
    out = robotize(mono) if EFFECT_ON else mono               # make it sound like a robot
    outdata[:] = (out * OUTPUT_GAIN)[:, None]  # send to the speaker (same sound on every channel)


# ---------------------------------------------------------------------------
# Set up the LED panel
# ---------------------------------------------------------------------------
# Tell the library how our panel is built.
geometry = piomatter.Geometry(width=WIDTH, height=HEIGHT, n_addr_lines=3,
                              rotation=piomatter.Orientation.Normal)
# The "framebuffer" is the picture. It's a grid of HEIGHT x WIDTH pixels,
# with 3 numbers (red, green, blue) in each. We change it, then show it.
framebuffer = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
matrix = piomatter.PioMatter(colorspace=piomatter.Colorspace.RGB888Packed,
                             pinout=piomatter.Pinout.AdafruitMatrixBonnet,
                             framebuffer=framebuffer,
                             geometry=geometry)


def draw_bars(smoothed):
    """Draw the bar on the panel.

    smoothed is the loudness from 0 (silent) to 1 (as loud as it gets).
    It lights up that fraction of the segments on each side of the middle.
    """
    framebuffer[:] = 0                          # erase the old picture (all black)
    top = (HEIGHT - BAR_HEIGHT) // 2            # first row of the bar, so it's centered up/down
    rows = slice(top, top + BAR_HEIGHT)         # the rows the bar covers
    lit = smoothed * N_SEG                      # how many segments should be lit (can be 2.5, etc.)
    for i in range(N_SEG):
        # How lit is segment number i? 0 = off, 1 = full. A part-lit segment
        # glows dimly, which makes the bar move smoothly instead of jumping.
        brightness = float(np.clip(lit - i, 0, 1))
        if i == 0 and brightness == 0:
            color = IDLE_COLOR                  # nothing lit: show the dim "I'm on" dot
        else:
            color = tuple(int(c * brightness) for c in SEG_COLORS[i])  # dim the color
        offset = i * (SEG_W + SEG_GAP)          # how far this segment is from the middle
        # Draw the same segment on the right side and the left side (a mirror).
        framebuffer[rows, HALF + offset:HALF + offset + SEG_W] = color              # right
        framebuffer[rows, HALF - offset - SEG_W:HALF - offset] = color              # left
    matrix.show()                               # send the picture to the panel


# ---------------------------------------------------------------------------
# Main program: start the sound, then keep redrawing the bar
# ---------------------------------------------------------------------------
smoothed = 0.0   # the bar's current height (0 to 1); it moves toward the real loudness
# Start the sound stream. From now on audio_callback runs by itself, many times a second.
with sd.Stream(device=device, channels=(1, out_channels), samplerate=rate,
               blocksize=BLOCK, latency="low", callback=audio_callback):
    print("Running. Ctrl-C to quit.")
    try:
        while True:   # repeat forever (until Ctrl-C)
            # Loudness plus the sensitivity boost.
            db = raw_db + read_sensitivity_db()
            # Turn dB into a number from 0 to 1: 0 at the noise floor, 1 at the ceiling.
            level = float(np.clip((db - NOISE_FLOOR_DB) / (CEILING_DB - NOISE_FLOOR_DB), 0, 1))
            # Move the bar toward that level: quickly up, slowly down, so it looks
            # punchy but doesn't flicker.
            k = ATTACK if level > smoothed else RELEASE
            smoothed += (level - smoothed) * k
            draw_bars(smoothed)
            time.sleep(1 / FPS)   # wait a moment before the next picture
    except KeyboardInterrupt:
        pass  # Ctrl-C was pressed: leave the loop and exit quietly

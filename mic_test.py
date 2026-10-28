#!/usr/bin/python3
"""
mic_test.py - check that the microphone works (no LED panel needed).

It prints a list of all the sound devices, then shows a live loudness meter.
Talk and watch the numbers and the #### bar change.

Why bother? The numbers you see here are what you use to tune voice_bar.py:
write down the loudness when it's QUIET and when you're TALKING, then use
them for NOISE_FLOOR_DB and CEILING_DB in voice_bar.py.

Run it:
    python mic_test.py            # use the default mic
    python mic_test.py 2          # use audio device number 2 from the list

Press Ctrl-C to stop.
"""

import sys

import numpy as np          # math on lists of numbers
import sounddevice as sd    # talks to the microphone

# Print every sound device the computer knows about, each with a number.
print(sd.query_devices())

# Did someone type a device number after the script name? If so use it.
# None means "use the default mic".
device = int(sys.argv[1]) if len(sys.argv) > 1 else None
info = sd.query_devices(device, "input")
rate = int(info["default_samplerate"])   # samples (sound measurements) per second
print(f"\nUsing: {info['name']} @ {rate} Hz  (Ctrl-C to quit)\n")


def callback(indata, frames, time, status):
    """Runs automatically every time a new chunk of sound arrives from the mic."""
    # RMS = a kind of average strength of the sound wave.
    rms = np.sqrt(np.mean(indata[:, 0] ** 2))
    # Convert to dB. 0 is the loudest possible; a quiet room is about -60.
    db = 20 * np.log10(max(rms, 1e-6))   # max() stops us taking the log of zero
    # Draw a row of # signs: more # = louder.
    bar = "#" * max(0, int((db + 70) / 70 * 50))
    # "\r" goes back to the start of the line so the meter updates in place.
    print(f"\r{db:6.1f} dBFS {bar:<50}", end="", flush=True)


# Start listening. The callback above runs by itself ~30 times per second.
with sd.InputStream(device=device, channels=1, samplerate=rate,
                    blocksize=rate // 30, callback=callback):
    try:
        while True:
            sd.sleep(1000)   # just wait; the callback does all the work
    except KeyboardInterrupt:
        print()              # move to a fresh line when Ctrl-C is pressed

# Leifbot

A robot costume that talks back. A microphone listens, a speaker plays your
voice back as a robot, and an LED panel on the chest shows a glowing bar that
grows when you talk loudly.

```
 microphone  -->  Raspberry Pi  -->  speaker (robot voice)
                       |
                       +---------->  LED panel (the volume bar)
```

## The parts

- **Raspberry Pi 5**: the little computer that runs everything.
- **LED matrix panel (32x16)**: the glowing display, connected through an Adafruit RGB Matrix Bonnet.
- **Lavalier microphone + USB audio interface**: picks up the voice and plays the sound out.
- **Speaker**: plugs into the same USB audio interface.
- **Batteries**: one for the Pi and a separate bank of AAs for the LED panel.

## The files

| File | What it is |
| --- | --- |
| `voice_bar.py` | The main program: robot voice + volume bar. |
| `mic_test.py` | Tests the microphone and shows how loud it hears things. Run this first. |
| `single_panel_simpletest.py` | A tiny test that draws three shapes on the panel, to check the panel works. |
| `leifbot.service` | Tells the Pi to start `voice_bar.py` by itself when it turns on. |
| `requirements.txt` | The list of Python add-ons the programs need. |

## Setting up (on the Pi)

Do this once.

```
sudo apt install libportaudio2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The `venv` is a private folder of Python add-ons just for this project.
**Every time you open a new terminal, run `source venv/bin/activate` first**,
or the programs won't find their add-ons.

## Running it

1. **Check the microphone.**

   ```
   python mic_test.py
   ```

   You'll see a list of sound devices, then a live meter. Talk and watch the
   numbers. Write down the number when it's quiet and when you're talking.
   (If the wrong mic is used, run it again with the number of the right one
   from the list, like `python mic_test.py 2`.)

2. **Run the costume program.**

   ```
   python voice_bar.py
   ```

   Press `Ctrl-C` to stop.

## Things you can change

Open `voice_bar.py`. The settings are near the top, each with a comment saying
what it does. The fun ones:

| Setting | What it changes |
| --- | --- |
| `SEG_COLORS` | The colors of the bar. Each is `(red, green, blue)`, from 0 to 255. |
| `BAR_HEIGHT` | How tall the bar is. |
| `NOISE_FLOOR_DB` | Sounds quieter than this are ignored. Raise it if the bar twitches on background noise. |
| `CEILING_DB` | How loud before the whole bar is lit. |
| `RING_FREQ_HZ` | The robot buzz. Low (like 30) is growly, high (like 200) is metallic. |
| `RING_MIX` | 0 is a normal voice, 1 is all robot. |
| `CRUSH_LEVELS` | Smaller is crunchier. |
| `OUTPUT_GAIN` | Speaker volume. Turn it up slowly! If it squeals, the speaker is too loud or too close to the mic (that's called feedback). |
| `EFFECT_ON` | `False` turns the robot voice off. |

Change one thing at a time and try it, so you know what each one does.

## How it works (the short version)

1. Sound is just a long list of numbers: how far the microphone's membrane is
   pushed at each tiny moment, thousands of times per second.
2. The program grabs that list in small chunks (`audio_callback`).
3. It measures **how loud** each chunk is (in decibels, "dB"). 0 dB is the
   loudest possible and quiet sounds are negative numbers.
4. **Cleaning up:** a filter removes deep rumbles, and a **noise gate** mutes
   the sound when nobody is talking, like a door that only opens for a voice.
5. **Robot voice** (`robotize`): the voice is multiplied by a fast-wobbling
   wave (ring modulation), rounded to fewer steps (bit-crushing), and gently
   squashed so it doesn't crackle.
6. The loudness decides how many bar segments light up (`draw_bars`). The
   panel is a grid of tiny lights, and we draw by setting each light's red,
   green, and blue amounts.

## Starting automatically when the Pi turns on

Copy and enable the service file (once):

```
sudo cp ~/leifbot/leifbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable leifbot
sudo systemctl start leifbot
```

Useful commands:

| Command | What it does |
| --- | --- |
| `sudo systemctl stop leifbot` | Stop the program (do this before running it by hand). |
| `sudo systemctl restart leifbot` | Restart it after changing the code. |
| `journalctl -u leifbot -f` | Watch what the program is printing. `Ctrl-C` to stop watching. |

## Turning the costume off

Press the power button wired to the Pi's **J2** connector and wait until the
LED panel goes dark and the green light on the Pi stops blinking. Then switch
off the batteries. Don't just pull the power, because that can damage the
Pi's memory card.

## If something's wrong

- **`No module named 'sounddevice'`**: you forgot `source venv/bin/activate`.
- **No sound or a weird mic**: run `python mic_test.py`, find the number of the
  USB audio device in the list, and give it to the program (`python voice_bar.py 2`).
- **Squealing**: lower `OUTPUT_GAIN` and move the speaker away from the mic.
- **The bar never moves or is always full**: re-tune `NOISE_FLOOR_DB` and
  `CEILING_DB` using the numbers from `mic_test.py`.
- **The program says the panel or audio is busy**: the background service may
  already be running. Run `sudo systemctl stop leifbot` first.

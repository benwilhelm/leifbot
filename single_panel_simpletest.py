#!/usr/bin/python3
# SPDX-FileCopyrightText: 2025 Tim Cocks for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
Display a simple test pattern of 3 shapes on a single 64x32 matrix panel.

Run like this:

$ python simpletest.py

"""

import numpy as np
from PIL import Image, ImageDraw

import adafruit_blinka_raspberry_pi5_piomatter as piomatter

width = 32
height = 16

geometry = piomatter.Geometry(width=width, height=height, n_addr_lines=3,
                                                     rotation=piomatter.Orientation.Normal)

canvas = Image.new('RGB', (width, height), (0, 0, 0))
draw = ImageDraw.Draw(canvas)

framebuffer = np.asarray(canvas) + 0  # Make a mutable copy
matrix = piomatter.PioMatter(colorspace=piomatter.Colorspace.RGB888Packed,
                             pinout=piomatter.Pinout.AdafruitMatrixBonnet,
                             framebuffer=framebuffer,
                             geometry=geometry)

draw.rectangle((1, 1, 5, 5), fill=0x008800)
draw.circle((9, 3), 2, fill=0x880000)
draw.polygon([(14, 1), (16, 5), (12, 5)], fill=0x000088)

framebuffer[:] = np.asarray(canvas)
matrix.show()

input("Press enter to exit")


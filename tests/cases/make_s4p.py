"""Synthetic thru channel for the tests: two uncoupled lossy lines, built with the same causal line model COM uses
for boards. Not a real channel: it exists so the engine can be run end to end.

The line model itself is product code since 0.8.0 (sicopr_assist\\example_channel.py, the THRU of the example
setup, Decision 22); this file hands the tests that one implementation under the names they have always used."""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import numpy as np  # noqa: F401 - the tests use make_s4p.np

from sicopr_assist.example_channel import tline_s, write  # noqa: F401

if __name__ == '__main__':
    import sys
    L = float(sys.argv[2]) if len(sys.argv) > 2 else 400.0
    print('points %d, loss at 53.125 GHz %.2f dB (single-ended), worst return loss %.1f dB' % write(sys.argv[1], L))

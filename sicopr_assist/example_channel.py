"""The synthetic THRU of the example setup: two uncoupled lossy lines, built with the same causal line model COM
uses for boards. It is not a measured channel: it exists so that the example runs end to end from an empty folder
, and so that the tests can run the engine with no IEEE file. The file is ours to ship.

    python -m sicopr_assist.example_channel out.s4p [length in mm]

This is the one implementation of the line model; tests\\cases\\make_s4p.py takes it from here.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import numpy as np

LENGTH_MM = 400.0                                    # the line of the example setup


def tline_s(f_hz, length_mm, zc, g0, a1, a2, tau, z0=50.0):
    f = f_hz / 1e9                                                   # GHz
    g1 = a1 * (1 + 1j)
    g2 = a2 * (1 - 1j * (2 / np.pi) * np.log(np.maximum(f, 1e-9))) + 1j * 2 * np.pi * tau
    gam = g0 + g1 * np.sqrt(f) + g2 * f                               # per mm
    gl = gam * length_mm
    D = 2 * zc * z0 * np.cosh(gl) + (zc ** 2 + z0 ** 2) * np.sinh(gl)
    s11 = (zc ** 2 - z0 ** 2) * np.sinh(gl) / D
    s21 = 2 * zc * z0 / D
    return s11, s21


def write(path, length_mm=LENGTH_MM, zc=46.25, fmax=67e9, df=10e6):
    """Write the 4-port Touchstone file of two uncoupled lines of length_mm. Returns (points, loss at 53.125 GHz in
    dB single-ended, worst return loss in dB)."""
    f = np.arange(df, fmax + df / 2, df)
    s11, s21 = tline_s(f, length_mm, zc, 0.0, 5.95e-4, 2.6e-5, 5.79e-3)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('! synthetic thru: two uncoupled %g mm lines, Zc %g ohm single-ended\n# Hz S RI R 50\n' % (length_mm, zc))
        z = 0j
        for i, fr in enumerate(f):
            S = [[s11[i], s21[i], z, z], [s21[i], s11[i], z, z], [z, z, s11[i], s21[i]], [z, z, s21[i], s11[i]]]   # ports 1-2 one line, 3-4 the other
            for r, row in enumerate(S):
                fh.write(('%.6e ' % fr if r == 0 else '  ') + ' '.join('%.9e %.9e' % (v.real, v.imag) for v in row) + '\n')
    il = -20 * np.log10(abs(s21[np.argmin(abs(f - 53.125e9))]))
    rl = -20 * np.log10(abs(s11).max())
    return len(f), il, rl


if __name__ == '__main__':
    import sys
    L = float(sys.argv[2]) if len(sys.argv) > 2 else LENGTH_MM
    print('points %d, loss at 53.125 GHz %.2f dB (single-ended), worst return loss %.1f dB' % write(sys.argv[1], L))

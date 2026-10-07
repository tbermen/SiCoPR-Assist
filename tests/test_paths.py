"""A file path in a phrase is read whichever separator it uses.

The parser read `ch\\b.s4p` as a path but split `ch/b.s4p` at the slash and kept only the file name, so
a run named that way looked for the file at the top of the project and asked for it. That broke on
Linux, where os.path.join writes `/`, and for anyone who types `/` on Windows (CI, 7 October 2026).
A path with `/` is taken only when it ends in a file extension the tool reads, so `w/`, `dB/GHz` and
`and/or` stay what they were.

    python tests/test_paths.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from check import check, finish  # noqa: E402
from sicopr_assist import parse  # noqa: E402


def files(text):
    return [f['text'] for f in parse.read(text)['files']]


def main():
    for sep in ('\\', '/'):
        got = files('Run COM on ch%sb300_thru1.s4p with data%sconfig.xlsx' % (sep, sep))
        check('a path with %r keeps its folder' % sep,
              got == ['ch%sb300_thru1.s4p' % sep, 'data%sconfig.xlsx' % sep], got)
    got = files('Re-run with ./data/public/channels/a_thru1.s4p')
    check('a relative path with ./ is one path', got == ['./data/public/channels/a_thru1.s4p'], got)
    got = files('Run C:/work/ch/a_thru1.s4p with C:\\work\\cfg.xlsx')
    check('a drive letter with either separator', got == ['C:/work/ch/a_thru1.s4p', 'C:\\work\\cfg.xlsx'], got)
    got = files('Re-run with data/mixed\\a_thru1.s4p')
    check('mixed separators are one path', got == ['data/mixed\\a_thru1.s4p'], got)
    for text in ('Re-run w/ DER_0 = 1e-4', 'Set T_dev to 2 dB/GHz', 'Re-run and/or show the summary'):
        check('no path in %r' % text, files(text) == [], files(text))
    finish()


if __name__ == '__main__':
    main()

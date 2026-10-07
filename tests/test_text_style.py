"""Gate G7.4 (Rule 11): no em dash and no emoji in any file of the repository.

Every file git tracks is read, plus any new file not yet added (git ls-files --others --exclude-standard).
A binary file is skipped: one with a NUL byte in it (the .xlsx workbooks). Every other file must decode
as UTF-8 and hold no em dash (U+2014) and no emoji. Without git (a source copy), the folder is walked
instead, leaving out what .gitignore names.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from check import check, finish  # noqa: E402

EM_DASH = chr(0x2014)
# Emoji: the pictographic planes, the dingbat and miscellaneous-symbol blocks, flags, keycap and
# variation selector 16, and the zero-width joiner that glues emoji sequences together.
EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF), (0xFE0F, 0xFE0F),
                (0x20E3, 0x20E3), (0x200D, 0x200D), (0xE0020, 0xE007F))
SKIP_DIRS = {'.git', '.sicopr', '__pycache__', 'build', 'dist', 'results'}


def repo_files():
    try:
        out = subprocess.run(['git', '-C', ROOT, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                             capture_output=True, check=True).stdout
        return 'git', sorted({p for p in out.decode('utf-8').split('\0') if p})
    except (OSError, subprocess.CalledProcessError):
        found = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.endswith('.egg-info')]
            found += [os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, '/') for f in files
                      if not f.endswith(('.pyc', '.s4p', '.mat'))]
        return 'walk', sorted(found)


def is_emoji(c):
    o = ord(c)
    return any(a <= o <= b for a, b in EMOJI_RANGES)


def scan(text):
    """[(line, column, what)] for every em dash and emoji in a text."""
    bad = []
    for n, line in enumerate(text.split('\n'), 1):
        for col, c in enumerate(line, 1):
            if c == EM_DASH:
                bad.append((n, col, 'em dash'))
            elif is_emoji(c):
                bad.append((n, col, 'emoji U+%04X' % ord(c)))
    return bad


def main():
    check('the scanner finds an em dash', scan('a ' + EM_DASH + ' b') == [(1, 3, 'em dash')])
    check('the scanner finds an emoji', [w for _, _, w in scan('ok \U0001F600')] == ['emoji U+1F600'])
    check('the scanner passes plain text, a hyphen and an en dash',
          scan('a - b, 1' + chr(0x2013) + '2, caf' + chr(0xe9)) == [])
    how, files = repo_files()
    text_files, binary, problems, undecodable = 0, [], [], []
    for rel in files:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):                       # deleted in the work tree, not yet committed
            continue
        with open(path, 'rb') as f:
            data = f.read()
        if b'\0' in data:
            binary.append(rel)
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError as e:
            undecodable.append('%s: %s' % (rel, e))
            continue
        text_files += 1
        problems += ['%s:%d:%d %s' % (rel, n, col, what) for n, col, what in scan(text)]
    print('%d files listed by %s: %d text, %d binary skipped (%s)'
          % (len(files), how, text_files, len(binary), ', '.join(os.path.basename(b) for b in binary)))
    check('every file was read (%d)' % len(files), text_files + len(binary) + len(undecodable) == len(
        [r for r in files if os.path.isfile(os.path.join(ROOT, r))]) and len(files) > 0)
    check('every text file decodes as UTF-8', not undecodable, undecodable[:10])
    check('no em dash and no emoji in any text file of the repository (%d files)' % text_files, not problems,
          problems[:20])
    finish()


if __name__ == '__main__':
    main()

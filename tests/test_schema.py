"""The schema self-check must pass; the drift check is reported and never fails this test.

The self-check exercises the two readers of sicopr_assist.schema_check on text built into it. The
drift check compares the parameter schema with the SiCoPR under test; drift is printed as a WARNING
only, because a change in SiCoPR must not turn this repository's tests red by itself.

    python tests\\test_schema.py
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


def run(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, '-m', 'sicopr_assist.schema_check'] + list(args), cwd=ROOT,
                          capture_output=True, text=True, env=env)


def main():
    got = run('--self-check')
    print(got.stdout.rstrip())
    check('schema self-check exits 0', got.returncode == 0, got.stderr.strip()[-300:] or got.stdout.strip()[-300:])
    check('schema self-check reports no FAIL', 'FAIL' not in got.stdout and 'PASS' in got.stdout)
    drift = run()
    lines = drift.stdout.rstrip().splitlines()
    for line in lines:
        print('  ' + line)
    if drift.returncode == 2:
        print('WARNING: the drift check could not find SiCoPR: %s' % (lines[-1] if lines else drift.stderr.strip()))
    elif drift.returncode != 0:
        print('WARNING: the schema has drifted from the SiCoPR under test (above). This does not fail the test; '
              'see python -m sicopr_assist.schema_check --remap-from-commit')
    else:
        print('no drift')
    finish()


if __name__ == '__main__':
    sys.exit(main())

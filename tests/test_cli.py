"""The command line and the core's outcome form.

  - core.handle returns an outcome with every key of prompt section 5
  - python -m sicopr_assist "anything" prints the outcome (a STOP in Phase 1), and so does the
    sicopr-assist script when the package is installed
  - the user settings folder follows SICOPR_ASSIST_HOME, so no test touches the real user profile

    python tests\\test_cli.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
from sicopr_assist import core, project  # noqa: E402


def main():
    d = tempfile.mkdtemp(prefix='sicopr_assist_cli_')
    home = tempfile.mkdtemp(prefix='sicopr_assist_home_')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SICOPR_ASSIST_HOME=home,
               PYTHONPATH=ROOT + os.pathsep + os.environ.get('PYTHONPATH', ''))
    try:
        o = core.handle('anything', project.Project(d))
        need = ('type', 'steps', 'changes', 'announce', 'points', 'new_runs', 'reused_runs', 'pattern', 'unplaced')
        check('the outcome carries every key of section 5', all(k in o for k in need), sorted(o))
        check('a STOP carries a reason', o['type'] != 'STOP' or bool(o.get('reason')))
        check('the outcome is plain JSON', json.loads(json.dumps(o)) == o)
        got = subprocess.run([sys.executable, '-m', 'sicopr_assist', 'anything'], cwd=d, capture_output=True,
                             text=True, env=env)
        check('python -m sicopr_assist "anything" prints the STOP', got.returncode == 0 and got.stdout.startswith('STOP: '),
              (got.returncode, got.stdout[:200], got.stderr[-300:]))
        got = subprocess.run([sys.executable, '-m', 'sicopr_assist', '--json', 'anything'], cwd=d, capture_output=True,
                             text=True, env=env)
        check('--json prints the outcome as JSON', got.returncode == 0 and json.loads(got.stdout)['type'] == 'STOP',
              got.stdout[:200])
        check('nothing is written to the project folder by a STOP', os.listdir(d) == [], os.listdir(d))
        exe = shutil.which('sicopr-assist')
        if not exe:                                    # pip may put the script in a folder that is not on PATH
            exe = shutil.which('sicopr-assist', path=sysconfig.get_path('scripts'))
        if exe:
            got = subprocess.run([exe, 'anything'], cwd=d, capture_output=True, text=True, env=env)
            check('sicopr-assist "anything" prints the STOP', got.returncode == 0 and got.stdout.startswith('STOP: '),
                  (got.returncode, got.stdout[:200], got.stderr[-300:]))
        else:
            print('SKIP: sicopr-assist is not on PATH (install the package with pip install -e . to check the script)')
        old = os.environ.get('SICOPR_ASSIST_HOME')
        os.environ['SICOPR_ASSIST_HOME'] = home
        try:
            check('the user settings file is under SICOPR_ASSIST_HOME',
                  project.user_settings_path() == os.path.join(home, '.sicopr', 'assist.ini'), project.user_settings_path())
        finally:
            if old is None:
                os.environ.pop('SICOPR_ASSIST_HOME', None)
            else:
                os.environ['SICOPR_ASSIST_HOME'] = old
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
    finish()


if __name__ == '__main__':
    sys.exit(main())

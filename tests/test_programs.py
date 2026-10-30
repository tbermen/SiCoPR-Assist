"""Programs the tool starts are started by their full path, never found in the current folder.

On Windows a bare program name is looked up in the current folder before PATH, so a file called explorer.exe or
git.exe in a project folder would be the one run. The file manager (Send feedback opens its folder) and git (the
schema tool's --remap-from-commit) are therefore started by full path, and engine.program never searches the current
folder. Rscript has the same check in tests/test_dashboard.py.

    python tests/test_programs.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
from sicopr_assist import engine, run, schema_check  # noqa: E402


class _Calls:
    """Stands in for subprocess.Popen and subprocess.run: records each argument list, starts nothing."""

    def __init__(self):
        self.argv = []

    def popen(self, argv, **kw):
        self.argv.append(list(argv))
        return None

    def run(self, argv, **kw):
        self.argv.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, b'', b'stand-in: nothing was run')


def main():
    calls = _Calls()
    real_popen, real_run = subprocess.Popen, subprocess.run
    subprocess.Popen, subprocess.run = calls.popen, calls.run
    try:
        said = run.open_folder(os.path.join(ROOT, 'README.md'))
        first = calls.argv[0][0] if calls.argv else None
        if first is None:                       # Linux with no xdg-open: reported, nothing started
            check('with no file manager, open_folder says so and starts nothing', said and 'xdg-open' in said, said)
        else:
            check('the file manager is started by its full path (%s)' % first, os.path.isabs(first), calls.argv)
        calls.argv.clear()
        got = schema_check.main(['--sicopr', engine.folder(), '--remap-from-commit', 'HEAD'])
        first = calls.argv[0][0] if calls.argv else None
        if first is None:
            check('with no git on PATH, the schema tool says so and starts nothing', got == 2, got)
        else:
            check('git is started by its full path (%s)' % first, os.path.isabs(first) and got == 2, calls.argv)
    finally:
        subprocess.Popen, subprocess.run = real_popen, real_run
    base = tempfile.mkdtemp(prefix='sicopr_assist_prog_')
    here = os.getcwd()
    try:
        for n in ('git', 'git.exe', 'git.bat'):
            p = os.path.join(base, n)
            open(p, 'w').close()
            os.chmod(p, 0o755)
        os.chdir(base)
        old = os.environ.get('PATH', '')
        for extra in ('.', '', base):
            os.environ['PATH'] = old + os.pathsep + extra
            try:
                got = engine.program('git')
            finally:
                os.environ['PATH'] = old
            check('engine.program never finds a program in the current folder (%r on PATH)' % extra,
                  got is None or os.path.dirname(got) != base, got)
    finally:
        os.chdir(here)
        shutil.rmtree(base, ignore_errors=True)
    finish()


if __name__ == '__main__':
    sys.exit(main())

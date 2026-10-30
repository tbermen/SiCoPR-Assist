"""The command line and the core's outcome form.

  - core.handle returns an outcome with every key the outcome form has
  - python -m sicopr_assist "anything" prints the outcome (a STOP), and so does the sicopr-assist script when the
    package is installed
  - --json prints one JSON document on standard output, also when a plan runs (its progress goes to standard error)
  - output that is not a terminal is UTF-8, so the multiplication sign the engine prints is not mojibake
  - --help names the gui subcommand
  - .sicopr holds a .gitignore of *, so git never picks up the project state
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


def json_run(env):
    """--json while a plan runs (the example setup with the stand-in child): standard output is one JSON document."""
    import io
    from sicopr_assist import cli
    d = tempfile.mkdtemp(prefix='sicopr_assist_json_')
    old = os.environ.get('SICOPR_ASSIST_HOME')
    os.environ['SICOPR_ASSIST_HOME'] = env['SICOPR_ASSIST_HOME']
    try:
        out, err = io.StringIO(), io.StringIO()
        child = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
        last, done = cli.handle_and_run('Run the example.', project.Project(d), as_json=True, out=out, err=err,
                                        child=child)
        try:
            doc = json.loads(out.getvalue())
        except ValueError as e:
            doc = {'error': str(e)}
        check('--json with a plan that runs: standard output is one valid JSON document',
              doc.get('type') == 'PLAN' and done is not None and done['run_ids'], out.getvalue()[-300:])
        check('--json: the document says what carrying the plan out gave (status, run ids, the result lines)',
              (doc.get('carried_out') or {}).get('run_ids') == done['run_ids']
              and doc['carried_out'].get('status') == done['status'] and doc['carried_out'].get('lines'),
              doc.get('carried_out'))
        check('--json: the plan and the progress lines go to standard error',
              'PLAN:' in err.getvalue() and 'step 1 of' in err.getvalue(), err.getvalue()[:300])
    finally:
        if old is None:
            os.environ.pop('SICOPR_ASSIST_HOME', None)
        else:
            os.environ['SICOPR_ASSIST_HOME'] = old
        shutil.rmtree(d, ignore_errors=True)


# A STOP whose reason holds the multiplication sign, printed by the real command line into a pipe.
_TIMES = """import sys
from sicopr_assist import cli, core
core.handle = lambda phrase, project: {'type': 'STOP', 'reason': '3 %s 4 cases', 'announce': []}
sys.exit(cli.main(['anything']))
""" % chr(0xd7)


def piped_utf8(env):
    d = tempfile.mkdtemp(prefix='sicopr_assist_utf8_')
    try:
        script = os.path.join(d, 'times.py')
        with open(script, 'w', encoding='utf-8') as f:
            f.write(_TIMES)
        clean = {k: v for k, v in env.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8')}
        got = subprocess.run([sys.executable, script], cwd=d, capture_output=True, env=clean)
        try:
            said = got.stdout.decode('utf-8')
        except UnicodeDecodeError as e:
            said = 'not UTF-8: %s' % e
        check('output into a pipe is UTF-8: the multiplication sign arrives as itself, not as mojibake',
              got.returncode == 0 and '3 %s 4 cases' % chr(0xd7) in said, (said[:200], got.stderr[-300:]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    d = tempfile.mkdtemp(prefix='sicopr_assist_cli_')
    home = tempfile.mkdtemp(prefix='sicopr_assist_home_')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SICOPR_ASSIST_HOME=home,
               PYTHONPATH=ROOT + os.pathsep + os.environ.get('PYTHONPATH', ''))
    try:
        o = core.handle('anything', project.Project(d))
        need = ('type', 'steps', 'changes', 'announce', 'points', 'new_runs', 'reused_runs', 'pattern', 'unplaced')
        check('the outcome carries every key of the outcome form', all(k in o for k in need), sorted(o))
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
        state = os.path.join(d, '.sicopr')
        check('a STOP writes nothing to the project folder but the history line, and the .gitignore of .sicopr',
              os.listdir(d) == ['.sicopr'] and sorted(os.listdir(state)) == ['.gitignore', 'history.jsonl'],
              (os.listdir(d), os.path.isdir(state) and os.listdir(state)))
        ignore = os.path.join(state, '.gitignore')
        check('.sicopr\\.gitignore holds *, so git never picks up the state, the cache or the runs',
              os.path.isfile(ignore) and open(ignore, encoding='utf-8').read() == '*\n')
        got = subprocess.run([sys.executable, '-m', 'sicopr_assist', '--help'], cwd=d, capture_output=True,
                             text=True, env=env)
        check('--help names the gui subcommand', got.returncode == 0 and 'sicopr-assist gui' in got.stdout,
              got.stdout[-400:])
        json_run(env)
        piped_utf8(env)
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

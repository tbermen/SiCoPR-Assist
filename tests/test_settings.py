"""The settings reader of Decision 4 (gate G5.2), with no workbook and no engine call.

Built-in defaults, then the user file (<home>\\.sicopr\\assist.ini), then the project file
(<project>\\.sicopr\\assist.ini), later wins. A bad name, a bad value or an unreadable file warns and keeps the
value in force, and never stops anything. A file with no section heading is accepted, and a setting is
accepted under either heading.

For each of the 15 settings (13, and translator and preset_overlay of Phase V2-10): the default; the user file; the project file over the user file (the user value is
listed as overridden); a bad value (warning, default kept). Once each: an unknown name, an unreadable file (bytes
that are not UTF-8, and text that cannot be parsed), a file with no heading, a setting under the other heading.
Then the same through the core: Show settings lists every value with where it came from, and a warning reaches
the announce lines of any outcome (rows SE01, SE02, SE06 to SE08).

    python tests\\test_settings.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
from sicopr_assist import project as P  # noqa: E402

# name: (default as the example file writes it, a user value, a project value, a bad value)
CASES = {
    'max_new_runs': ('30', '100', '10', 'many'),
    'tutor_until_commands': ('5', '9', '0', '-1'),
    'max_download_mb': ('500', '800', '50', '2.5'),
    'download_retries': ('1', '3', '0', 'twice'),
    'name_match_cutoff': ('0.8', '0.5', '0.9', '1.5'),
    'max_options': ('8', '4', '6', '0'),
    'trouble_misses': ('3', '2', '0', 'few'),
    'trouble_window': ('5', '7', '4', '0'),
    'feedback_notice_gap': ('20', '40', '10', '-5'),
    'min_correlation_points': ('3', '5', '4', 'three'),
    'mask_names': ('on', 'off', 'on', 'maybe'),
    'mask_numbers': ('off', 'on', 'off', 'perhaps'),
    'feedback_notice': ('on', 'off', 'on', '2'),
    'translator': ('on', 'off', 'on', 'maybe'),
    # a path: any text is taken as it is, and whether the file is there is found out when it is used (translate.py)
    'preset_overlay': ('', 'D:/work/overlay_user.csv', 'D:/work/overlay_project.csv', None),
}
TEXT = ('preset_overlay',)
HEADING = {k: ('feedback' if k.startswith(('mask_', 'feedback_notice')) and k != 'feedback_notice_gap' else
               'translator' if k in ('translator', 'preset_overlay') else 'limits') for k in CASES}


def typed(text, name=None):
    if name in TEXT:
        return text.strip()
    t = text.strip().lower()
    if t in ('on', 'off'):
        return t == 'on'
    return float(t) if '.' in t else int(t)


class Place:
    """A temporary home and project folder; the settings files are written into them."""

    def __enter__(self):
        self.home = tempfile.mkdtemp(prefix='sicopr_assist_home_')
        self.root = tempfile.mkdtemp(prefix='sicopr_assist_proj_')
        self.old = os.environ.get('SICOPR_ASSIST_HOME')
        os.environ['SICOPR_ASSIST_HOME'] = self.home
        self.project = P.Project(self.root)
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop('SICOPR_ASSIST_HOME', None)
        else:
            os.environ['SICOPR_ASSIST_HOME'] = self.old
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, which, text, raw=False):
        path = P.user_settings_path() if which == 'user' else self.project.settings_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(text if raw else text.encode('utf-8'))
        return path

    def read(self):
        return P.read_settings(self.project)


def main():
    defaults = P.setting_defaults()
    check('the shipped example names exactly the 15 settings', sorted(defaults) == sorted(CASES), sorted(defaults))
    for name, (dflt, user, proj, bad) in CASES.items():
        with Place() as pl:
            s = pl.read()
            check('%s: default %s with no file' % (name, dflt), s['values'][name] == typed(dflt, name)
                  and s['sources'][name] == 'default' and not s['warnings'], (s['values'][name], s['sources'][name]))
            up = pl.write('user', '[%s]\n%s = %s\n' % (HEADING[name], name, user))
            s = pl.read()
            check('%s: the user file sets %s' % (name, user), s['values'][name] == typed(user, name)
                  and s['sources'][name] == up and not s['warnings'], (s['values'][name], s['sources'][name]))
            pp = pl.write('project', '[%s]\n%s = %s\n' % (HEADING[name], name, proj))
            s = pl.read()
            check('%s: the project file (%s) wins over the user file (%s), which is listed as overridden'
                  % (name, proj, user), s['values'][name] == typed(proj, name) and s['sources'][name] == pp
                  and s['overridden'].get(name) == [{'value': typed(user, name), 'source': up}] and not s['warnings'],
                  (s['values'][name], s['sources'][name], s['overridden'].get(name)))
        if bad is None:
            continue
        with Place() as pl:
            pp = pl.write('project', '[%s]\n%s = %s\n' % (HEADING[name], name, bad))
            s = pl.read()
            check('%s: a bad value (%s) warns and keeps the default' % (name, bad), s['values'][name] == typed(dflt, name)
                  and s['sources'][name] == 'default' and len(s['warnings']) == 1
                  and name in s['warnings'][0] and bad in s['warnings'][0], (s['values'][name], s['warnings']))

    with Place() as pl:
        pl.write('project', '[limits]\nmax_runs = 50\n')
        s = pl.read()
        check('an unknown name warns, names the setting it is near, and changes nothing (SE06)',
              len(s['warnings']) == 1 and 'max_runs' in s['warnings'][0] and 'max_new_runs' in s['warnings'][0]
              and s['values'] == {k: v for k, (v, _) in defaults.items()}, s['warnings'])
    with Place() as pl:
        pl.write('user', '[limits]\nmax_new_runs = 7\n')
        pl.write('project', b'[limits]\nmax_new_runs = 9\nmask_names = \xff\xfe off\n', raw=True)
        s = pl.read()
        check('a file that is not UTF-8 text warns, and the values in force stay (user file 7)',
              len(s['warnings']) == 1 and 'could not be read' in s['warnings'][0] and s['values']['max_new_runs'] == 7,
              (s['warnings'], s['values']['max_new_runs']))
    with Place() as pl:
        pl.write('project', '[limits\nmax_new_runs == = 3\n[[feedback\n')
        s = pl.read()
        check('a file that cannot be parsed warns and every setting stays at its default (SE08)',
              len(s['warnings']) == 1 and 'could not be read' in s['warnings'][0]
              and s['values'] == {k: v for k, (v, _) in defaults.items()}, s['warnings'])
    with Place() as pl:
        pl.write('project', 'max_new_runs = 12\nmask_numbers = on\n')
        s = pl.read()
        check('a file with no heading is accepted', s['values']['max_new_runs'] == 12 and s['values']['mask_numbers']
              is True and not s['warnings'], (s['values'], s['warnings']))
    with Place() as pl:
        pl.write('project', '[feedback]\nmax_new_runs = 13\n[limits]\nmask_names = off\n')
        s = pl.read()
        check('a setting under the other heading is accepted', s['values']['max_new_runs'] == 13
              and s['values']['mask_names'] is False and not s['warnings'], (s['values'], s['warnings']))

    # through the core: what Show settings and any other outcome show
    from sicopr_assist import core
    with Place() as pl:
        o = core.handle('Show settings.', pl.project)
        want = ['%s = %s (default)' % (k, d) for k, (d, _, _, _) in CASES.items()]
        check('Show settings with no file: every setting, as the file writes it, reads default (SE01)',
              o['type'] == 'PLAN' and [s['op'] for s in o['steps'] if (s.get('args') or {}).get('why') not in
                                       ('new', 'trouble')] == ['show_settings']      # the tutor's own step aside
              and sorted(o['announce']) == sorted(want), o['announce'])
    with Place() as pl:
        up = pl.write('user', '[limits]\nmax_new_runs = 100\ntutor_until_commands = 0\n')
        pp = pl.write('project', '[limits]\nmax_new_runs = 10\n')
        o = core.handle('Show settings.', pl.project)
        line = next((l for l in o['announce'] if l.startswith('max_new_runs = ')), '')
        check('Show settings names the project file and the overridden user value (SE02)',
              line == 'max_new_runs = 10 (project file %s; overrides 100 from the user file %s)' % (pp, up)
              and 'tutor_until_commands = 0 (user file %s)' % up in o['announce'], o['announce'])
    with Place() as pl:
        pl.write('project', '[limits]\nmax_new_runs = many\n')
        o = core.handle('Re-run.', pl.project)
        check('a settings warning reaches the outcome before anything else (SE07), and the outcome still follows',
              o['type'] == 'QUESTION' and o['announce'][:1] and 'max_new_runs = many' in o['announce'][0],
              (o['type'], o['announce']))
    finish()


if __name__ == '__main__':
    sys.exit(main())

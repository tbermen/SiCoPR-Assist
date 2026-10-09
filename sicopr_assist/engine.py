"""The package's view of SiCoPR: load a config, the releases, which keywords the loader reads, what its R
dashboard needs (R/com_analysis.R and an Rscript to run it), and the known channel files of its benchmark.

This is one of the three modules that import sicopr or read its folder (with run_case.py and
schema_check.py). SiCoPR is found by schema_check.find_sicopr: the folder named by SICOPR_REPO, else
the folder the installed sicopr module sits in. SiCoPR is only read, never written: bytecode writing
is switched off before it is imported, and a config inside its folder is never loaded (a load can
write a .mat beside the file it reads).
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import contextlib
import csv
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
from types import SimpleNamespace

from sicopr_assist import schema_check

INSTALL_HINT = ('SiCoPR was not found. Install it from its checkout with "pip install -e <SiCoPR folder>", '
                'or set SICOPR_REPO to that folder.')

_cache = {}


class EngineMissing(RuntimeError):
    pass


def folder():
    """The SiCoPR folder, the one that holds sicopr.py."""
    if 'folder' not in _cache:
        path = schema_check.find_sicopr()
        if not path or not os.path.exists(os.path.join(path, 'sicopr.py')):
            raise EngineMissing(INSTALL_HINT)
        _cache['folder'] = os.path.abspath(path)
    return _cache['folder']


def module():
    """The sicopr module, imported from folder() with its printing captured."""
    if 'module' not in _cache:
        path = folder()
        # A .pyc written beside sicopr.py would be a write inside SiCoPR. The setting stays off for the
        # rest of the process because sicopr imports some of its own modules later, on first use.
        sys.dont_write_bytecode = True
        if sys.path[:1] != [path]:
            sys.path.insert(0, path)
        with contextlib.redirect_stdout(io.StringIO()):
            import sicopr
        if os.path.dirname(os.path.abspath(sicopr.__file__)) != path:
            raise EngineMissing('sicopr was imported from %s, not from %s' % (sicopr.__file__, path))
        _cache['module'] = sicopr
    return _cache['module']


def engine_path():
    return os.path.join(folder(), 'sicopr.py')


def engine_sha256():
    with open(engine_path(), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def version_info():
    """VERSION.json of the SiCoPR under test, read when the tool runs (Decision 12)."""
    with open(os.path.join(folder(), 'VERSION.json'), encoding='utf-8') as f:
        return json.load(f)


def supported_releases():
    return list(version_info().get('supported_matlab_versions', []))


def default_release():
    return version_info().get('default_matlab_version')


def loader_keywords():
    """{(keyword, scope): {'default', 'scale', 'lines'}} as the engine's own loader reads them."""
    if 'keywords' not in _cache:
        with open(engine_path(), encoding='utf-8') as f:
            _cache['keywords'] = schema_check.loader_keywords(f.read())
    return _cache['keywords']


def reads_keyword(name, scope=None):
    """Does the loader read this keyword? Case and surrounding spaces are ignored, as the loader does."""
    k = name.strip().lower()
    return any(kw.strip().lower() == k and (scope is None or sc == scope) for kw, sc in loader_keywords())


def keyword_names(scope):
    """The keywords the loader reads in one scope ('main' or 'package block'), spelled as the loader spells
    them."""
    return sorted(kw for kw, sc in loader_keywords() if sc == scope)


def required_keywords():
    """Main-area keywords the loader reads with no default: a config without one of them does not load."""
    return sorted(kw for (kw, sc), rec in loader_keywords().items() if sc == 'main' and rec['default'] is None)


def shipped_workbooks():
    """The workbooks SiCoPR ships (benchmark and examples), for checks that need one and not one of the four
    starting workbooks."""
    out = glob.glob(os.path.join(folder(), 'benchmark', '*', 'configs', '*.xlsx'))
    out += glob.glob(os.path.join(folder(), 'examples', '**', '*.xlsx'), recursive=True)
    return sorted(p for p in out if not os.path.basename(p).startswith('~$'))


def bootstrap_op():
    """The OP that sicopr._run_com hands to read_ParamConfigFile, lifted from the driver's source so it
    cannot drift (the same way SiCoPR's tests/test_csv_inputs.py does)."""
    with open(engine_path(), encoding='utf-8') as f:
        src = f.read().splitlines()
    a = next(i for i, line in enumerate(src) if line.strip() == 'OP = SimpleNamespace()')
    b = next(i for i, line in enumerate(src) if 'param, OP = read_ParamConfigFile' in line)
    ns = {'SimpleNamespace': SimpleNamespace}
    exec('\n'.join(line[4:] for line in src[a:b]), ns)   # SiCoPR's own lines, not text from a user
    return ns['OP']


def _inside_sicopr(path):
    a = os.path.normcase(os.path.abspath(path))
    b = os.path.normcase(folder()) + os.sep
    return a.startswith(b)


def load_config(path):
    """(param, OP) as the engine loads the config at path (.xlsx, .csv or .mat). Raises what the loader
    raises. A config inside the SiCoPR folder is refused: copy it to a temporary folder first."""
    if _inside_sicopr(path):
        raise ValueError('refusing to load a config from inside SiCoPR (%s): copy it to a temporary folder' % path)
    S = module()
    with contextlib.redirect_stdout(io.StringIO()):
        return S.read_ParamConfigFile(path, bootstrap_op())


def flatten(param, OP):
    """param and OP as {field: value}, with nested namespaces and dicts opened out."""
    out = {}

    def walk(ns, prefix):
        for k, v in vars(ns).items():
            if isinstance(v, SimpleNamespace):
                walk(v, prefix + k + '.')
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, SimpleNamespace):
                        walk(vv, prefix + k + '.' + str(kk) + '.')
                    else:
                        out[prefix + k + '.' + str(kk)] = vv
            else:
                out[prefix + k] = v

    walk(param, 'param.')
    walk(OP, 'OP.')
    return out


def known_channels():
    """The rows of the channels.csv in SiCoPR's benchmark folder: {'contribution', 'ieee_url', 'role' (THRU, FEXT
    or NEXT), 'file', 'sha256'} for the 164 channel files of six IEEE contributions, so a download can be checked
    against them. [] when this SiCoPR has no such file."""
    hits = sorted(glob.glob(os.path.join(folder(), 'benchmark', '*', 'channels.csv')))
    if not hits:
        return []
    p = hits[0]
    with open(p, newline='', encoding='utf-8') as f:
        return [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(f)]


def com_analysis_script():
    """SiCoPR's R report, R/com_analysis.R, which turns a run's .mat export into the dashboard page; None when this
    SiCoPR has none."""
    p = os.path.join(folder(), 'R', 'com_analysis.R')
    return p if os.path.isfile(p) else None


PANEL_GROUP = 'sicopr.gui_panels'       # the entry-point group SiCoPR's GUI loads panels from (its gui/README.md)


def gui_app():
    """(path of SiCoPR's gui/app.py, whether that GUI has the panel slot). A GUI without the slot never loads the
    entry-point group, so the Assist panel cannot appear in it."""
    p = os.path.join(folder(), 'gui', 'app.py')
    try:
        with open(p, encoding='utf-8') as f:
            return p, PANEL_GROUP in f.read()
    except OSError:
        return p, False


def r_version(path):
    """The version of the R install that holds an Rscript, from its folder name (R-4.10.0 -> (4, 10, 0)), compared as
    numbers so that R-4.10 is newer than R-4.9; () when the name holds none."""
    for part in reversed(os.path.normpath(path).split(os.sep)):
        m = re.match(r'R-(\d+(?:\.\d+)*)$', part)
        if m:
            return tuple(int(x) for x in m.group(1).split('.'))
    return ()


def find_rscript():
    """Rscript, found as SiCoPR's gui/app.py (_rscript) finds it: on PATH first, else in a default Windows install,
    <Program Files>\\R\\R-*\\bin (or bin\\x64), where the newest version wins by number, not by text. Program Files
    is the folder named by the ProgramFiles environment variable (C:\\Program Files on Windows when it is not set).
    None when there is no Rscript."""
    for name in ('Rscript', 'Rscript.exe'):
        p = shutil.which(name)
        if p:
            return p
    root = os.environ.get('ProgramFiles') or (r'C:\Program Files' if os.name == 'nt' else None)
    if not root:
        return None
    hits = []
    for sub in (('bin',), ('bin', 'x64')):
        for p in glob.glob(os.path.join(root, 'R', 'R-*', *sub, 'Rscript.exe')):
            hits.append((r_version(p), len(sub) == 1, p))
    return max(hits)[2] if hits else None


def load_fields(path):
    """(fields, None) when the config loads, else (None, '<ErrorType>: <message>')."""
    if _inside_sicopr(path):
        raise ValueError('refusing to load a config from inside SiCoPR (%s): copy it to a temporary folder' % path)
    try:
        param, OP = load_config(path)
    except Exception as e:                                   # the loader's own error, reported as it is
        return None, '%s: %s' % (type(e).__name__, e)
    return flatten(param, OP), None

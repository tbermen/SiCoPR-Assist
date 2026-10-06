"""The package's view of SiCoPR: load a config, the releases, which keywords the loader reads.

This is one of the three modules that import sicopr or read its folder (with run_case.py and
schema_check.py). SiCoPR is found by schema_check.find_sicopr: the folder named by SICOPR_REPO, else
the folder the installed sicopr module sits in. SiCoPR is only read, never written: bytecode writing
is switched off before it is imported, and a config inside its folder is never loaded (a load can
write a .mat beside the file it reads).
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import contextlib
import glob
import hashlib
import io
import json
import os
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


def shipped_workbooks():
    """The workbooks SiCoPR ships, for checks that need one and not one of the four starting workbooks."""
    return sorted(glob.glob(os.path.join(folder(), 'benchmark', '*', 'configs', '*.xlsx')))


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


def load_fields(path):
    """(fields, None) when the config loads, else (None, '<ErrorType>: <message>')."""
    if _inside_sicopr(path):
        raise ValueError('refusing to load a config from inside SiCoPR (%s): copy it to a temporary folder' % path)
    try:
        param, OP = load_config(path)
    except Exception as e:                                   # the loader's own error, reported as it is
        return None, '%s: %s' % (type(e).__name__, e)
    return flatten(param, OP), None

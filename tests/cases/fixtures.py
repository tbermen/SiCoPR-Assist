"""Test fixtures: the starting workbooks, the synthetic THRU, the variants V01 to V12, project folders.

    with Fixtures() as fx:
        fx.configs              {'Case1': path, ..., 'V01': path, ...}
        fx.thru                 the synthetic 400 mm THRU (make_s4p.py)
        fx.project('Case1')     a new project folder: data\\config.xlsx and data\\thru.s4p
        fx.home                 the user settings folder; SICOPR_ASSIST_HOME points here

Everything is made in two temporary folders (one for the projects, one standing in for the user
profile), and both are removed on exit. The four starting workbooks are found by SHA-256, first in
tests\\configs, then in the folder named by SICOPR_ASSIST_CONFIGS; file names prove nothing (finding
F08). SICOPR_ASSIST_HIDE_CONFIGS=1 makes them absent.

The oracle (gen_use_cases.py) is test-side only. It is used here to build the variants, to import a
workbook into a working config for seeding prior states, and to load and diff configs for scoring.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import contextlib
import copy
import csv
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
sys.dont_write_bytecode = True
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sicopr_assist import engine  # noqa: E402

STARTING = os.path.join(HERE, 'sicopr_starting_configs.csv')
CASES = ('Case1', 'Case2', 'Case3', 'Case4')
VARIANTS = tuple('V%02d' % i for i in range(1, 13))
WC_KEYS = ('schema', 'source', 'main', 'packages', 'links')


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def starting_rows():
    return list(csv.DictReader(open(STARTING, newline='', encoding='utf-8')))


def hidden():
    return os.environ.get('SICOPR_ASSIST_HIDE_CONFIGS', '') == '1'


def find_starting_configs():
    """{label: path} for Case1 to Case4, found by SHA-256; {} when hidden or absent."""
    if hidden():
        return {}
    want = {r['sha256']: r['starting_config'] for r in starting_rows() if r['starting_config'] in CASES}
    found = {}
    for d in (os.path.join(TESTS, 'configs'), os.environ.get('SICOPR_ASSIST_CONFIGS') or ''):
        if not d or not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if name.lower().endswith('.xlsx') and os.path.isfile(p):
                label = want.get(_sha(p))
                if label and label not in found:
                    found[label] = p
    return found if len(found) == len(CASES) else {}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


_oracle = None


def oracle():
    """gen_use_cases.py as a module, with its keyword tables filled from the engine under test."""
    global _oracle
    if _oracle is None:
        _oracle = load_module('gen_use_cases', os.path.join(HERE, 'gen_use_cases.py'))
        _oracle.KW = _oracle.known_keywords(engine.engine_path())
        _oracle.KW_MAIN.update(_oracle.KW[0])
    return _oracle


def make_s4p():
    return load_module('make_s4p', os.path.join(HERE, 'make_s4p.py'))


def link_or_copy(src, dst):
    """A hard link where the file system allows one (the fixtures are large and many), else a copy.
    A prior state that changes a file removes the link and writes a new file, never in place."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def working_config(cfg):
    """An oracle import cut down to the working config of Decision 1."""
    out = {k: copy.deepcopy(cfg[k]) for k in WC_KEYS}
    out['main'] = dict(out['main'])
    out['packages'] = {b: dict(p) for b, p in out['packages'].items()}
    return out


class Fixtures:
    def __init__(self, variants=True):
        self.want_variants = variants
        self.configs = {}
        self.base = None
        self.home = None
        self._wc = {}
        self._fields = {}
        self._n = 0
        self._old_home = None

    # ---- set up and tear down
    def __enter__(self):
        self.base = tempfile.mkdtemp(prefix='sicopr_assist_fx_')
        self.home = tempfile.mkdtemp(prefix='sicopr_assist_home_')
        self._old_home = os.environ.get('SICOPR_ASSIST_HOME')
        os.environ['SICOPR_ASSIST_HOME'] = self.home
        self.configs = dict(find_starting_configs())
        self.thru = os.path.join(self.base, 'thru.s4p')
        with contextlib.redirect_stdout(io.StringIO()):
            make_s4p().write(self.thru)
        if self.configs and self.want_variants:
            self.configs.update(self.build_variants())
        return self

    def __exit__(self, *exc):
        if self._old_home is None:
            os.environ.pop('SICOPR_ASSIST_HOME', None)
        else:
            os.environ['SICOPR_ASSIST_HOME'] = self._old_home
        shutil.rmtree(self.base, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)
        return False

    @property
    def available(self):
        return bool(self.configs)

    def thru_of(self, length_mm):
        """A synthetic THRU of another length (make_s4p.py), made once and kept with the fixtures."""
        path = os.path.join(self.base, 'thru_%gmm.s4p' % length_mm)
        if not os.path.exists(path):
            with contextlib.redirect_stdout(io.StringIO()):
                make_s4p().write(path, length_mm)
        return path

    # ---- variants
    def build_variants(self, outdir=None):
        """V01 to V12 from Case1, with gen_use_cases.py --variants run as its own process."""
        outdir = outdir or os.path.join(self.base, 'variants')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        got = subprocess.run([sys.executable, os.path.join(HERE, 'gen_use_cases.py'), '--variants',
                              self.configs['Case1'], outdir], capture_output=True, text=True, env=env)
        if got.returncode != 0:
            raise RuntimeError('gen_use_cases.py --variants failed: %s' % got.stderr.strip()[-500:])
        out = {}
        for name in sorted(os.listdir(outdir)):
            if name[:3] in VARIANTS and name.endswith('.xlsx'):
                out[name[:3]] = os.path.join(outdir, name)
        return out

    # ---- imports and loads (cached; the files never change during a run)
    def working_config(self, label):
        """The working config of a starting workbook or variant, as the oracle imports it."""
        if label not in self._wc:
            O = oracle()
            with contextlib.redirect_stdout(io.StringIO()):
                cfg = O.discover(self.configs[label], O.KW, label)
            self._wc[label] = (working_config(cfg), list(cfg['issues']))
        return copy.deepcopy(self._wc[label][0])

    def import_issues(self, label):
        self.working_config(label)
        return list(self._wc[label][1])

    def load_csv_bytes(self, data):
        """Loaded fields of a run CSV given as bytes, cached by its SHA-256: (fields, error)."""
        key = hashlib.sha256(data).hexdigest()
        if key not in self._fields:
            d = tempfile.mkdtemp(prefix='l3_', dir=self.base)
            p = os.path.join(d, 'run.csv')
            with open(p, 'wb') as f:
                f.write(data)
            try:
                self._fields[key] = engine.load_fields(p)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return self._fields[key]

    def load_working_config(self, wc):
        """(fields, error) of a working config written as the run CSV of Decision 2 (the oracle's to_csv)."""
        d = tempfile.mkdtemp(prefix='csv_', dir=self.base)
        p = os.path.join(d, 'run.csv')
        try:
            oracle().to_csv(wc, p)
            with open(p, 'rb') as f:
                data = f.read()
        finally:
            shutil.rmtree(d, ignore_errors=True)
        return self.load_csv_bytes(data)

    def load_file(self, path):
        """(fields, error) of a config file, loaded from a temporary copy."""
        d = tempfile.mkdtemp(prefix='file_', dir=self.base)
        p = os.path.join(d, os.path.basename(path))
        shutil.copyfile(path, p)
        try:
            return engine.load_fields(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ---- project folders
    def project(self, label, config_name='config.xlsx'):
        """A new, empty project folder holding data\\config.xlsx (the workbook of label) and
        data\\thru.s4p, and nothing else."""
        self._n += 1
        root = os.path.join(self.base, 'p%05d' % self._n)
        os.makedirs(os.path.join(root, 'data'))
        if label in self.configs:
            link_or_copy(self.configs[label], os.path.join(root, 'data', config_name))
        link_or_copy(self.thru, os.path.join(root, 'data', 'thru.s4p'))
        return root

    def remove_project(self, root):
        shutil.rmtree(root, ignore_errors=True)

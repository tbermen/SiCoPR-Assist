"""SiCoPR older than 1.1.4 is refused.

Before 1.1.4 SiCoPR read some config cells with Python's eval, so a workbook from someone else could run
code when SiCoPR-Assist loaded it (security review, 29 October 2026). 1.1.4 reads every cell with
xls_eval, a MATLAB-subset evaluator. engine.folder() checks for it and stops with a named error.

    python tests/test_engine_minimum.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from check import check, finish  # noqa: E402
from sicopr_assist import engine  # noqa: E402


def refused(source):
    """engine.folder() on a fake SiCoPR folder holding this sicopr.py: the error text, or None."""
    tmp = tempfile.mkdtemp(prefix='assist_min_')
    saved = os.environ.get('SICOPR_REPO')
    try:
        with open(os.path.join(tmp, 'sicopr.py'), 'w', encoding='utf-8') as f:
            f.write(source)
        os.environ['SICOPR_REPO'] = tmp
        engine._cache.clear()
        try:
            engine.folder()
            return None
        except engine.EngineMissing as e:
            return str(e)
    finally:
        engine._cache.clear()
        if saved is None:
            os.environ.pop('SICOPR_REPO', None)
        else:
            os.environ['SICOPR_REPO'] = saved
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    old = refused('def xls_parameter(p):\n    return eval(p)\n')
    check('a SiCoPR without xls_eval is refused', old is not None, 'engine.folder() accepted it')
    check('the refusal names 1.1.4 and the reason', old and '1.1.4' in old and 'Python' in old, repr(old))
    check('a SiCoPR with xls_eval is accepted',
          refused('def xls_eval(text, as_matrix=False):\n    pass\n') is None, 'engine.folder() refused it')
    real = engine.folder()
    check('the SiCoPR under test has the safe reader', real and engine.safe_reader(
        open(os.path.join(real, 'sicopr.py'), encoding='utf-8').read()), real)
    finish()


if __name__ == '__main__':
    main()

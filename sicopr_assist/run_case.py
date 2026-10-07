"""The child process: one case through the engine, every result field to result.json.

    python -u run_case.py CONFIG.csv RESULT.json --thru T [--fext F ...] [--next N ...]
                          [--fingerprint HEX] [--note TEXT ...]

Written after the model of SiCoPR's tools/_sicopr_case.py: it calls sicopr._run_com on the run CSV
(Decision 2) as the command line does, so the engine's own report is written unchanged to the RESULT_DIR
the CSV names, and it writes every attribute of each package case's result at full precision to RESULT.json
(JSON floats round-trip; not-a-number is kept as NaN). The release is the COM Version keyword when the
config has one, otherwise SiCoPR's default (rule VR02); the engine reports it in each result.

The parent (run.py) starts this from an argument list, with no shell and unbuffered output, one run at a time.
A failure is written to RESULT.json too, with status failed and the engine's message, and the exit code is 1.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import hashlib
import json
import os
import sys
import traceback

if __package__ in (None, ''):                    # started as a script: the package is one folder up
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.dont_write_bytecode = True                   # nothing may be written inside SiCoPR (Rule 1)

from sicopr_assist import engine  # noqa: E402
from sicopr_assist.project import result_record  # noqa: E402


def jsonable(v):
    """A result attribute as JSON: numbers as numbers, numeric arrays as lists, anything else as text."""
    import numpy as np
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v)
    if isinstance(v, (np.complexfloating, complex)):
        return [float(v.real), float(v.imag)]
    if isinstance(v, np.ndarray):
        if v.dtype.kind in 'fiub':
            return [jsonable(x) for x in v.ravel().tolist()]
        if v.dtype.kind == 'c':
            return [[float(x.real), float(x.imag)] for x in v.ravel()]
        return str(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, str) or v is None:
        return v
    return str(v)


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(prog='run_case.py')
    ap.add_argument('config')
    ap.add_argument('result')
    ap.add_argument('--thru', required=True)
    ap.add_argument('--fext', nargs='*', default=[])
    ap.add_argument('--next', nargs='*', default=[])
    ap.add_argument('--fingerprint')
    ap.add_argument('--note', action='append', default=[])
    a = ap.parse_args(argv)
    files = [a.thru] + a.fext + a.next
    channels = [{'path': p, 'sha256': _sha(p), 'role': r}
                for p, r in [(a.thru, 'thru')] + [(f, 'fext') for f in a.fext] + [(n, 'next') for n in a.next]]
    rid = os.path.basename(os.path.dirname(os.path.abspath(a.result)))
    common = dict(run_id=rid, sicopr_sha256=engine.engine_sha256(), config_csv=a.config, channels=channels,
                  fingerprint=a.fingerprint)
    try:
        S = engine.module()
        results = S._run_com(a.config, len(a.fext), len(a.next), files, export_mat=False)
        if results is None:
            raise RuntimeError('COM returned no result')
        if not isinstance(results, list):
            results = [results]
        cases = [{k: jsonable(v) for k, v in sorted(vars(r).items())} for r in results if r is not None]
        release = next((c.get('code_revision') for c in cases if c.get('code_revision')), None) or \
            getattr(S, 'COM_MATLAB_VERSION', None)
        rec = result_record(status='complete', release=release, cases=cases, message='\n'.join(a.note) or None,
                            **common)
        code = 0
    except Exception as e:                       # the engine's own error, reported as it is
        traceback.print_exc()
        rec = result_record(status='failed', release=None, message='%s: %s' % (type(e).__name__, e), **common)
        code = 1
    tmp = a.result + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rec, f, indent=1)
        f.write('\n')
    os.replace(tmp, a.result)
    for i, c in enumerate(rec['cases'], 1):
        print('--- case %d: channel_operating_margin_dB = %r' % (i, c.get('channel_operating_margin_dB')))
    return code


if __name__ == '__main__':
    sys.exit(main())

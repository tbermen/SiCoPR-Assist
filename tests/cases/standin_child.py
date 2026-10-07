"""A stand-in for sicopr_assist/run_case.py: takes the same arguments and writes a seeded result.json, so the
reuse and run-folder checks (gate G6.3) run no COM.

    python standin_child.py CONFIG.csv RESULT.json --thru T [--fext F ...] [--next N ...]
                            [--fingerprint HEX] [--note TEXT ...]

The numbers are made up but fixed by the run CSV (without its RESULT_DIR row), so the same config gives the
same numbers. The release is the one the config loads to (param.matlab_version), as the engine reports it.
SICOPR_ASSIST_STANDIN_NAN=1 makes COM not a number.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from sicopr_assist import engine  # noqa: E402
from sicopr_assist.project import result_record  # noqa: E402

PROGRESS = ('stand-in: reading the run CSV', 'stand-in: CTLE 1/3  best_FOM=-inf dB', 'stand-in: CTLE 3/3  done')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('config')
    ap.add_argument('result')
    ap.add_argument('--thru', required=True)
    ap.add_argument('--fext', nargs='*', default=[])
    ap.add_argument('--next', nargs='*', default=[])
    ap.add_argument('--fingerprint')
    ap.add_argument('--note', action='append', default=[])
    a = ap.parse_args(argv)
    for line in PROGRESS:                        # progress lines, as the engine prints while it runs (Decision 17)
        print(line, flush=True)
    with open(a.config, encoding='utf-8') as f:
        text = ''.join(line for line in f if not line.lower().startswith('result_dir,'))
    k = int(hashlib.sha256(text.encode('utf-8')).hexdigest()[:8], 16)
    fields, err = engine.load_fields(a.config)
    com = float('nan') if os.environ.get('SICOPR_ASSIST_STANDIN_NAN') == '1' else 3.0 + (k % 1000) / 250.0
    case = {'channel_operating_margin_dB': com, 'FOM': 14.0 + (k % 97) / 100.0, 'ERL': 12.5, 'VEC_dB': 9.1,
            'VEO_mV': 8.4, 'DER_thresh': 2e-4, 'code_revision': fields['param.matlab_version']}
    chans = []
    for p, r in [(a.thru, 'thru')] + [(x, 'fext') for x in a.fext] + [(x, 'next') for x in a.next]:
        with open(p, 'rb') as f:
            chans.append({'path': p, 'sha256': hashlib.sha256(f.read()).hexdigest(), 'role': r})
    rec = result_record(run_id=os.path.basename(os.path.dirname(os.path.abspath(a.result))), status='complete',
                        release=fields['param.matlab_version'], sicopr_sha256=engine.engine_sha256(),
                        config_csv=a.config, channels=chans, fingerprint=a.fingerprint, cases=[case],
                        message='\n'.join(a.note) or None)
    with open(a.result, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rec, f, indent=1)
    print('--- case 1: channel_operating_margin_dB = %r (stand-in)' % com)
    return 0


if __name__ == '__main__':
    sys.exit(main())

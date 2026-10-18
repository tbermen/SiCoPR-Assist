"""A stand-in for sicopr_assist/run_case.py: takes the same arguments and writes a seeded result.json, so the
reuse and run-folder checks (gate G6.3) run no COM.

    python standin_child.py CONFIG.csv RESULT.json --thru T [--fext F ...] [--next N ...]
                            [--fingerprint HEX] [--note TEXT ...] [--export-mat] [--eye-under-mlse]

The numbers are made up but fixed by the run CSV (without its RESULT_DIR row), so the same config gives the
same numbers. The release is the one the config loads to (param.matlab_version), as the engine reports it.
SICOPR_ASSIST_STANDIN_NAN=1 makes COM not a number. SICOPR_ASSIST_STANDIN_ARGV=<file> appends the arguments, as
one JSON list per run, to that file. --export-mat writes a small stand-in <run>_case01.mat beside RESULT.json, where
the engine writes its .mat export (<RESULT_DIR>/<config file name>_caseNN.mat), and says so in the result. Like the
engine, it writes case_01\\results.csv in RESULT_DIR, so SiCoPR's GUI lists the run folder.
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
    ap.add_argument('--export-mat', action='store_true')
    ap.add_argument('--eye-under-mlse', action='store_true')    # recorded in the result, as run_case.py records it
    a = ap.parse_args(argv)
    keep = os.environ.get('SICOPR_ASSIST_STANDIN_ARGV')
    if keep:                                     # a test reads back the arguments the runner gave (gate N3)
        with open(keep, 'a', encoding='utf-8') as f:
            f.write(json.dumps(sys.argv[1:] if argv is None else list(argv)) + '\n')
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
                        message='\n'.join(a.note) or None, export_mat=a.export_mat,
                        eye_under_mlse=a.eye_under_mlse)
    if a.export_mat:
        stem = os.path.splitext(os.path.basename(a.config))[0]
        mat = os.path.join(os.path.dirname(os.path.abspath(a.result)), '%s_case01.mat' % stem)
        with open(mat, 'wb') as f:
            f.write(b'MATLAB 5.0 MAT-file, stand-in')
        print('    [export-mat] 1 variables -> %s' % mat)
    with open(a.result, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rec, f, indent=1)
    # the engine's own report in RESULT_DIR, case_01\results.csv, by which SiCoPR's GUI finds a run folder
    case_dir = os.path.join(os.path.dirname(os.path.abspath(a.result)), 'case_01')
    os.makedirs(case_dir, exist_ok=True)
    with open(os.path.join(case_dir, 'results.csv'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('COM_dB,FOM\n%r,%r\n' % (com, case['FOM']))
    print('--- case 1: channel_operating_margin_dB = %r (stand-in)' % com)
    return 0


if __name__ == '__main__':
    sys.exit(main())

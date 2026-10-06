"""The use-case harness (prompt section 7): scores the core against every applicable row and config pair.

    python tests\\test_use_cases.py                 score, write score_use_cases.csv, print one line per group
    python tests\\test_use_cases.py --gate G1.3     also check gate G1.3 (the Phase 1 STOP stub)
    $env:SICOPR_ASSIST_FULL = "1"                   L3 on every pair (default: Case1 and the variants)

It fails on a defect of the harness itself: a prior state with no builder, a builder that does not
run, or an applicable pair left unscored. How many rows pass is reported; the gates of each phase
say how many must. The score file goes to the folder named by SICOPR_ASSIST_INPUTS, else to a
temporary folder; --out names another place.

With the four starting workbooks absent (or hidden by SICOPR_ASSIST_HIDE_CONFIGS=1) it prints SKIP
and exits 0.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--gate', choices=['G1.3'], help='check a gate condition as well')
    ap.add_argument('--out', help='where to write score_use_cases.csv')
    ap.add_argument('--only', help='comma-separated row ids, for a quick look')
    ap.add_argument('--no-paraphrases', action='store_true')
    args = ap.parse_args(argv)
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are '
              'absent or hidden; the use-case harness needs them')
        return 0

    import l4
    import prior_states
    import scoring
    from sicopr_assist import core

    rows = l4.load_table()
    if args.only:
        keep = set(args.only.split(','))
        rows = [r for r in rows if r['id'] in keep]
    full = os.environ.get('SICOPR_ASSIST_FULL', '') == '1'
    t0 = time.time()
    results, harness_errors = [], []
    with fixtures.Fixtures() as fx:
        sc = scoring.Scorer(fx, l4.load_table(), core.handle, full_l3=full)
        for row, label in scoring.pairs(rows):
            if row['prior_state'] not in prior_states.BUILDERS:
                harness_errors.append('%s: no builder for %r' % (row['id'], row['prior_state']))
                continue
            try:
                results.append(sc.score(row, label, paraphrases=not args.no_paraphrases))
            except Exception as e:                                       # a defect of the harness or the core
                traceback.print_exc()
                harness_errors.append('%s %s: %s: %s' % (row['id'], label, type(e).__name__, e))
    out = args.out or os.path.join(os.environ.get('SICOPR_ASSIST_INPUTS') or tempfile.gettempdir(),
                                   'score_use_cases.csv')
    scoring.write_scores(results, out)
    applicable = [r for r in results if r['applies'] == 'yes']
    print('scored %d pairs (%d applicable, %d not) in %.0f s, L3 %s; written to %s'
          % (len(results), len(applicable), len(results) - len(applicable), time.time() - t0,
             'on every pair' if full else 'on Case1 and the variants', out))
    for line in scoring.summarise(results):
        print(line)

    expected_pairs = sum(len(scoring.labels_of(r)) for r in rows)
    check('every row and config pair was scored (%d)' % expected_pairs,
          len(results) == expected_pairs and not harness_errors, '; '.join(harness_errors[:5]))
    check('every applicable pair has an L1 score', all(r['L1'] in ('PASS', 'FAIL') for r in applicable))

    if args.gate == 'G1.3':
        stop = [r for r in applicable if _type(rows, r) == 'STOP']
        other = [r for r in applicable if _type(rows, r) != 'STOP']
        check('G1.3: every STOP row passes L1 (%d pairs)' % len(stop), all(r['L1'] == 'PASS' for r in stop),
              [r['id'] for r in stop if r['L1'] != 'PASS'][:10])
        check('G1.3: no PLAN or QUESTION row passes L1 (%d pairs)' % len(other), all(r['L1'] == 'FAIL' for r in other),
              [r['id'] for r in other if r['L1'] != 'FAIL'][:10])
    finish()


_types = {}


def _type(rows, res):
    if not _types:
        for r in rows:
            for label in (['Case1'] if r['starting_config'] == 'any' else r['starting_config'].split('; ')):
                _types[(r['id'], label)] = r['expected_type']
    return _types[(res['id'], res['config'])]


if __name__ == '__main__':
    sys.exit(main())

"""The use-case harness (prompt section 7): scores the core against every applicable row and config pair.

    python tests\\test_use_cases.py                 score, write score_use_cases.csv, print one line per group
    python tests\\test_use_cases.py --gate G1.3     also check gate G1.3 (the Phase 1 STOP stub)
    python tests\\test_use_cases.py --gate G7 --gate M1 --gate M2     several gates on one scoring run
    python tests\\test_use_cases.py --gate N1 --gate N2                the gates of the second session
    python tests\\test_use_cases.py --gate V1.1                         version 2, Phase V2-1: tutor and feedback
    python tests\\test_use_cases.py --gate V2.1                         version 2, Phase V2-2: the dashboard
    python tests\\test_use_cases.py --gate V3.1                         version 2, Phase V2-3: channel download
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
    ap.add_argument('--gate', choices=['G1.3', 'G4', 'G6', 'G7', 'M1', 'M2', 'N1', 'N2', 'V1.1', 'V2.1', 'V3.1'],
                    action='append',
                    default=[],
                    help='check a gate condition as well (may be given more than once)')
    ap.add_argument('--review', help='with --gate G4: write the rows of the Phase 4 groups that L4 cannot check by '
                                     'machine, with the outcome given, to this CSV')
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
    failed = ['%s %s' % (r['id'], r['config']) for r in applicable if (r.get('_outcome') or {}).get('tutor_error')]
    check('the tutor never failed (it never stops a command, so a failure would otherwise pass unseen)', not failed,
          failed[:10])

    if 'G4' in args.gate:
        gate_g4(rows, results, full, args.review)
    if 'G6' in args.gate:
        gate_g6(rows, results)
    if 'G7' in args.gate:
        gate_g7(rows, results, full)
    if 'M1' in args.gate:
        gate_m1(rows, results, full)
    if 'M2' in args.gate:
        gate_m2(results)
    if 'N1' in args.gate:
        gate_n1(rows, results, full)
    if 'N2' in args.gate:
        gate_m2(results)
        gate_n2(rows)
    if 'V1.1' in args.gate:
        gate_v11(rows, results, full)
    if 'V2.1' in args.gate:
        gate_v21(rows, results, full)
    if 'V3.1' in args.gate:
        gate_v31(rows, results, full)
    if 'G1.3' in args.gate:
        stop = [r for r in applicable if _type(rows, r) == 'STOP']
        other = [r for r in applicable if _type(rows, r) != 'STOP']
        check('G1.3: every STOP row passes L1 (%d pairs)' % len(stop), all(r['L1'] == 'PASS' for r in stop),
              [r['id'] for r in stop if r['L1'] != 'PASS'][:10])
        check('G1.3: no PLAN or QUESTION row passes L1 (%d pairs)' % len(other), all(r['L1'] == 'FAIL' for r in other),
              [r['id'] for r in other if r['L1'] != 'FAIL'][:10])
    finish()


PHASE4_GROUPS = ('param', 'enum', 'resolve', 'phrasing', 'invalid', 'combo', 'change', 'structure', 'schema', 'scope',
                 'config', 'sweep')


def open_disputes():
    """{row id: why} for the disputes in the build state that are not resolved. The build state lives outside the
    repository (in SICOPR_ASSIST_INPUTS); without it no row is excused."""
    import json
    path = os.path.join(os.environ.get('SICOPR_ASSIST_INPUTS') or '', 'build_state.json')
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        state = json.load(f)
    return {d['row']: d.get('why', '') for d in state.get('disputes', []) if d.get('status') != 'resolved'}


def gate_g4(rows, results, full, review_path):
    """Gates G4.1 to G4.5 (prompt section 8, Phase 4). A disputed row is excused and named."""
    import csv
    import scoring
    by_key = {(r['id'], label): r for r in rows for label in scoring.labels_of(r)}
    disputed = open_disputes()
    if disputed:
        print('excused by dispute: %s' % ', '.join(sorted(disputed)))
    mine = [r for r in results if r['applies'] == 'yes' and r['group'] in PHASE4_GROUPS]
    must = [r for r in mine if r['priority'] == 'must' and r['id'] not in disputed]

    def listed(bad):
        return ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad]
    bad = [r for r in must if r['L1'] != 'PASS']
    check('G4.1: every must row of the Phase 4 groups passes L1 (%d pairs)' % len(must), not bad, listed(bad)[:40])
    bad = [r for r in must if r['L2'] == 'FAIL' or r['L3'] == 'FAIL']
    check('G4.2: the same rows pass L2 and L3 where they apply (L3 %s)' % ('on every pair' if full else
                                                                          'on Case1 and the variants only'),
          not bad, listed(bad)[:40])
    if not full:
        print('NOTE: G4.2 needs L3 on every pair: run with SICOPR_ASSIST_FULL=1')
    frozen = {}
    for r in mine:
        if r['L4'] in ('PASS', 'FAIL') and r['id'] not in disputed:
            frozen.setdefault(r['id'] + '|' + by_key[(r['id'], r['config'])]['starting_config'], []).append(r)
    passed = [k for k, v in frozen.items() if all(x['L4'] == 'PASS' for x in v)]
    missed = sorted(k for k in frozen if k not in passed)
    share = len(passed) / float(len(frozen) or 1)
    print('G4.3: L4 on %d of %d frozen rows of the Phase 4 groups, disputed rows left out (%.1f %%); %d pairs of %d'
          % (len(passed), len(frozen), 100 * share, sum(1 for v in frozen.values() for x in v if x['L4'] == 'PASS'),
             sum(len(v) for v in frozen.values())))
    for k in missed:
        x = next(x for x in frozen[k] if x['L4'] == 'FAIL')
        print('  L4 miss %s (%s): %s' % (k.split('|')[0], ', '.join(y['config'] for y in frozen[k] if y['L4'] == 'FAIL'),
                                         x['note'][-220:]))
    check('G4.3: L4 passes on at least 95 percent of the frozen rows of the Phase 4 groups', share >= 0.95,
          '%.1f %%' % (100 * share))
    wrong = [r for r in results if r['applies'] == 'yes' and str(r['paraphrases_wrong']) not in ('', '0')
             and r['id'] not in disputed]
    check('G4.4: no paraphrase in the whole table produces a wrong PLAN', not wrong,
          ['%s %s: %s wrong' % (r['id'], r['config'], r['paraphrases_wrong']) for r in wrong][:40])
    sweeps = [r for r in must if r['group'] == 'sweep' and scoring.stated_counts(by_key[(r['id'], r['config'])])]
    bad = [(r, scoring.counts_match(by_key[(r['id'], r['config'])], r)) for r in sweeps]
    bad = [(r, n) for r, (ok, n) in bad if not ok]
    check('G4.5: points, new runs and reused runs as stated, on %d must sweep pairs that state them' % len(sweeps),
          not bad, ['%s %s: %s' % (r['id'], r['config'], n) for r, n in bad][:40])
    if review_path:
        with open(review_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, lineterminator='\n')
            w.writerow(['id', 'config', 'group', 'priority', 'expected_type', 'expected_detail', 'outcome_type',
                        'outcome_detail', 'question_text'])
            for r in mine:
                if r['L4'] != 'review':
                    continue
                row = by_key[(r['id'], r['config'])]
                o = r.get('_outcome') or {}
                w.writerow([r['id'], r['config'], r['group'], r['priority'], row['expected_type'],
                            row['expected_detail'], o.get('type'), o.get('detail'), o.get('text')])
        print('review list written to %s' % review_path)


PHASE6_GROUPS = ('run', 'summary', 'combo')


def gate_g6(rows, results):
    """Gate G6.1: every must row of the groups run, summary and combo passes L1, and L4 where it is in the frozen
    list, on seeded results. A disputed row is excused and named."""
    disputed = open_disputes()
    if disputed:
        print('excused by dispute: %s' % ', '.join(sorted(disputed)))
    must = [r for r in results if r['applies'] == 'yes' and r['group'] in PHASE6_GROUPS and r['priority'] == 'must'
            and r['id'] not in disputed]
    bad = [r for r in must if r['L1'] != 'PASS']
    check('G6.1: every must row of run, summary and combo passes L1 (%d pairs)' % len(must), not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad][:40])
    frozen = [r for r in must if r['L4'] in ('PASS', 'FAIL')]
    bad = [r for r in frozen if r['L4'] != 'PASS']
    check('G6.1: and L4 where the row is in the frozen list (%d pairs)' % len(frozen), not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][-160:]) for r in bad][:40])


def board(results, title):
    """Print one line per group: pairs, and passes per level out of the pairs the level applies to."""
    print('-- %s' % title)
    groups = {}
    for r in results:
        g = groups.setdefault(r['group'], {'n': 0, 'L1': [0, 0], 'L2': [0, 0], 'L3': [0, 0], 'L4': [0, 0]})
        g['n'] += 1
        for lv in ('L1', 'L2', 'L3', 'L4'):
            if r[lv] in ('PASS', 'FAIL'):
                g[lv][1] += 1
                g[lv][0] += r[lv] == 'PASS'
    total = {'n': 0, 'L1': [0, 0], 'L2': [0, 0], 'L3': [0, 0], 'L4': [0, 0]}
    for name in sorted(groups) + ['all']:
        v = groups.get(name, total)
        if name != 'all':
            total['n'] += v['n']
            for lv in ('L1', 'L2', 'L3', 'L4'):
                total[lv] = [total[lv][0] + v[lv][0], total[lv][1] + v[lv][1]]
        print('%-10s pairs %4d  L1 %4d/%-4d  L2 %4d/%-4d  L3 %4d/%-4d  L4 %4d/%-4d'
              % (name, v['n'], v['L1'][0], v['L1'][1], v['L2'][0], v['L2'][1], v['L3'][0], v['L3'][1],
                 v['L4'][0], v['L4'][1]))


def gate_g7(rows, results, full):
    """Gates G7.1 to G7.3 (prompt section 8, Phase 7): the final scoreboard. A disputed row is excused and named."""
    import scoring
    by_key = {(r['id'], label): r for r in rows for label in scoring.labels_of(r)}
    disputed = open_disputes()
    if disputed:
        print('excused by dispute: %s' % ', '.join(sorted(disputed)))
    applicable = [r for r in results if r['applies'] == 'yes']
    gated = [r for r in applicable if r['group'] not in scoring.DEFERRED]
    must = [r for r in gated if r['priority'] == 'must' and r['id'] not in disputed]
    board(must, 'must rows outside the deferred groups')
    board([r for r in gated if r['priority'] != 'must'], 'stretch rows outside the deferred groups (not gated)')
    board([r for r in applicable if r['group'] in scoring.DEFERRED], 'deferred to version 2, all priorities '
                                                                     '(not gated)')

    def listed(bad):
        return ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad]
    for lv in ('L1', 'L2', 'L3'):
        bad = [r for r in must if r[lv] == 'FAIL' or (lv == 'L1' and r[lv] != 'PASS')]
        check('G7.1: every must pair outside the deferred groups passes %s where it applies (%d pairs)'
              % (lv, len(must)), not bad, listed(bad)[:40])
    if not full:
        print('NOTE: G7.1 needs L3 on every pair: run with SICOPR_ASSIST_FULL=1')
    frozen = {}
    for r in must:
        if r['L4'] in ('PASS', 'FAIL'):
            frozen.setdefault(r['id'] + '|' + by_key[(r['id'], r['config'])]['starting_config'], []).append(r)
    passed = [k for k, v in frozen.items() if all(x['L4'] == 'PASS' for x in v)]
    missed = sorted(k for k in frozen if k not in passed)
    share = len(passed) / float(len(frozen) or 1)
    print('G7.2: L4 on %d of %d frozen must rows outside the deferred groups (%.1f %%); %d pairs of %d'
          % (len(passed), len(frozen), 100 * share, sum(1 for v in frozen.values() for x in v if x['L4'] == 'PASS'),
             sum(len(v) for v in frozen.values())))
    for k in missed:
        x = next(x for x in frozen[k] if x['L4'] == 'FAIL')
        print('  L4 miss %s (%s): %s' % (k.split('|')[0], ', '.join(y['config'] for y in frozen[k] if y['L4'] == 'FAIL'),
                                         x['note'][-220:]))
    check('G7.2: L4 passes on at least 95 percent of the frozen must rows outside the deferred groups', share >= 0.95,
          '%.1f %%' % (100 * share))
    stretch_l4 = sorted({r['id'] for r in gated if r['priority'] != 'must' and r['L4'] == 'FAIL'})
    print('stretch L4 misses (not gated): %s' % (', '.join(stretch_l4) or 'none'))
    for lv in ('L1', 'L2', 'L3'):
        ids = sorted({r['id'] for r in gated if r['priority'] != 'must' and r[lv] == 'FAIL'})
        print('stretch %s misses (not gated): %s' % (lv, ', '.join(ids) or 'none'))
    for lv in ('L1', 'L2', 'L3', 'L4'):
        ids = sorted({r['id'] for r in applicable if r['group'] in scoring.DEFERRED and r[lv] == 'FAIL'})
        print('deferred %s misses (not gated): %s' % (lv, ', '.join(ids) or 'none'))
    n = [sum(int(r[k] or 0) for r in applicable) for k in ('paraphrases_ok', 'paraphrases_asked', 'paraphrases_wrong')]
    print('paraphrases over the whole table: %d, %d understood, %d asked, %d wrong' % (sum(n), n[0], n[1], n[2]))
    check('G7.3: stretch rows and the deferred groups were scored (%d and %d pairs)'
          % (len([r for r in gated if r['priority'] != 'must']),
             len([r for r in applicable if r['group'] in scoring.DEFERRED])),
          all(r['L1'] in ('PASS', 'FAIL') for r in applicable if r['priority'] != 'must'
              or r['group'] in scoring.DEFERRED))


def gate_m1(rows, results, full):
    """Gate M1 (after first use, 6 October): every must CH row passes L1, L2, L3 (full mode) and L4 where it is in
    the frozen list, and no row is excused. The earlier gates are checked by --gate G4, G6 and G7 on the same run."""
    import scoring
    want = sum(len(scoring.labels_of(r)) for r in rows if r['id'].startswith('CH') and r['priority'] == 'must')
    ch = [r for r in results if r['applies'] == 'yes' and r['id'].startswith('CH') and r['priority'] == 'must']
    check('M1: the must CH rows were scored (%d pairs)' % want, want > 0 and len(ch) == want, len(ch))
    check('M1: L3 ran in full mode (SICOPR_ASSIST_FULL=1)', full)
    bad = [r for r in ch if r['L1'] != 'PASS' or 'FAIL' in (r['L2'], r['L3'], r['L4'])]
    check('M1: every must CH pair passes L1, and L2, L3 and L4 where they apply', not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad])
    print('M1: %d must CH pairs; L4 on %d of them (the others are STOP rows on the review list)'
          % (len(ch), sum(1 for r in ch if r['L4'] in ('PASS', 'FAIL'))))
    check('M1: no row is excused by an open dispute', not open_disputes(), sorted(open_disputes()))


def gate_m2(results):
    """Gate M2: no paraphrase in the whole table produces a wrong PLAN."""
    wrong = [r for r in results if r['applies'] == 'yes' and str(r['paraphrases_wrong']) not in ('', '0')]
    n = sum(int(r['paraphrases_ok'] or 0) + int(r['paraphrases_asked'] or 0) + int(r['paraphrases_wrong'] or 0)
            for r in results if r['applies'] == 'yes')
    check('M2: no paraphrase in the whole table produces a wrong PLAN (%d paraphrase pairs)' % n, n and not wrong,
          ['%s %s: %s wrong' % (r['id'], r['config'], r['paraphrases_wrong']) for r in wrong][:40])


NEW_ROWS_N = ('XT01', 'XT02', 'XT03', 'XT04', 'XT05', 'XT06', 'SM16')


def gate_n1(rows, results, full):
    """Gate N1 (second session, 7 October): every must XT row and SM16 pass L1, L2, L3 (full mode) and L4 where
    they are in the frozen list; no row is excused; only the new rows entered the frozen list (639 rows after
    first use, 645 now: XT01, XT02, XT03, XT05, XT06 and SM16; XT04 is a STOP row on the review list)."""
    import csv
    import scoring
    want = sum(len(scoring.labels_of(r)) for r in rows if r['id'] in NEW_ROWS_N and r['priority'] == 'must')
    got = [r for r in results if r['applies'] == 'yes' and r['id'] in NEW_ROWS_N and r['priority'] == 'must']
    check('N1: the must XT rows and SM16 were scored (%d pairs)' % want, want > 0 and len(got) == want, len(got))
    check('N1: L3 ran in full mode (SICOPR_ASSIST_FULL=1)', full)
    bad = [r for r in got if r['L1'] != 'PASS' or 'FAIL' in (r['L2'], r['L3'], r['L4'])]
    check('N1: every must XT and SM16 pair passes L1, and L2, L3 and L4 where they apply', not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad])
    print('N1: %d pairs; L4 on %d of them' % (len(got), sum(1 for r in got if r['L4'] in ('PASS', 'FAIL'))))
    check('N1: no row is excused by an open dispute', not open_disputes(), sorted(open_disputes()))
    frozen = [r['id'] for r in csv.DictReader(open(scoring.FROZEN, newline='', encoding='utf-8'))]
    check('N1: the frozen list has 645 rows and its new ones are exactly XT01, XT02, XT03, XT05, XT06 and SM16',
          len(frozen) == 645 and sorted(i for i in frozen if i in NEW_ROWS_N) ==
          ['SM16', 'XT01', 'XT02', 'XT03', 'XT05', 'XT06'] and frozen[-6:] ==
          ['XT01', 'XT02', 'XT03', 'XT05', 'XT06', 'SM16'], (len(frozen), frozen[-8:]))


V1_GROUPS = ('tutor', 'feedback')


def gate_v11(rows, results, full):
    """Gate V1.1 (version 2, Phase V2-1): every must row in the groups tutor and feedback passes L1, and L2, L3 and
    L4 where they apply (L4: the rows in the frozen list); no row is excused. The tutor text that L4 does not read
    is checked by tests/test_tutor.py, and the feedback file by tests/test_feedback.py."""
    import scoring
    want = sum(len(scoring.labels_of(r)) for r in rows if r['group'] in V1_GROUPS and r['priority'] == 'must')
    got = [r for r in results if r['applies'] == 'yes' and r['group'] in V1_GROUPS and r['priority'] == 'must']
    check('V1.1: the must rows of tutor and feedback were scored (%d pairs)' % want, want > 0 and len(got) == want,
          len(got))
    check('V1.1: L3 ran in full mode (SICOPR_ASSIST_FULL=1)', full)
    board(got, 'V1.1: must rows of tutor and feedback')
    bad = [r for r in got if r['L1'] != 'PASS' or 'FAIL' in (r['L2'], r['L3'], r['L4'])]
    check('V1.1: every must pair of tutor and feedback passes L1, and L2, L3 and L4 where they apply', not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad])
    print('V1.1: %d pairs; L4 on %d of them (the others are on the review list)'
          % (len(got), sum(1 for r in got if r['L4'] in ('PASS', 'FAIL'))))
    check('V1.1: no row is excused by an open dispute', not open_disputes(), sorted(open_disputes()))


V2_ROWS = ('CB17', 'C2')                         # restored to their dashboard chains in Phase V2-2


def gate_v21(rows, results, full):
    """Gate V2.1 (version 2, Phase V2-2): every must row in the group report, and CB17 and C2, pass all levels that
    apply (L1, and L2, L3 and L4 where they apply; L4: the rows in the frozen list); no row is excused. CB17 and C2
    are frozen with their dashboard chains."""
    import csv
    import scoring

    def mine(r):
        return r['priority'] == 'must' and (r['group'] == 'report' or r['id'] in V2_ROWS)
    want = sum(len(scoring.labels_of(r)) for r in rows if mine(r))
    got = [r for r in results if r['applies'] == 'yes' and mine(r)]
    check('V2.1: the must rows of report, CB17 and C2 were scored (%d pairs)' % want, want > 0 and len(got) == want,
          len(got))
    check('V2.1: L3 ran in full mode (SICOPR_ASSIST_FULL=1)', full)
    board(got, 'V2.1: must rows of report, CB17 and C2')
    bad = [r for r in got if r['L1'] != 'PASS' or 'FAIL' in (r['L2'], r['L3'], r['L4'])]
    check('V2.1: every must pair of report, CB17 and C2 passes L1, and L2, L3 and L4 where they apply', not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad])
    print('V2.1: %d pairs; L4 on %d of them (the others are on the review list)'
          % (len(got), sum(1 for r in got if r['L4'] in ('PASS', 'FAIL'))))
    check('V2.1: no row is excused by an open dispute', not open_disputes(), sorted(open_disputes()))
    frozen = {r['id']: r['expected'] for r in csv.DictReader(open(scoring.FROZEN, newline='', encoding='utf-8'))}
    tail = 'run_com > summarize > export_mat > render_dashboard > open_report'
    check('V2.1: CB17 and C2 are frozen with their dashboard chains',
          all(frozen.get(i, '').endswith(tail) for i in V2_ROWS), {i: frozen.get(i) for i in V2_ROWS})


def gate_v31(rows, results, full):
    """Gate V3.1 (version 2, Phase V2-3): every must row in the group fetch passes all levels that apply, against the
    local stand-in of the IEEE tools page (tests/cases/standin_ieee.py); no row is excused. The stretch row F8 is
    scored and reported."""
    import scoring

    def mine(r):
        return r['priority'] == 'must' and r['group'] == 'fetch'
    want = sum(len(scoring.labels_of(r)) for r in rows if mine(r))
    got = [r for r in results if r['applies'] == 'yes' and mine(r)]
    check('V3.1: the must rows of fetch were scored (%d pairs)' % want, want > 0 and len(got) == want, len(got))
    check('V3.1: L3 ran in full mode (SICOPR_ASSIST_FULL=1)', full)
    board(got, 'V3.1: must rows of fetch')
    bad = [r for r in got if r['L1'] != 'PASS' or 'FAIL' in (r['L2'], r['L3'], r['L4'])]
    check('V3.1: every must pair of fetch passes L1, and L2, L3 and L4 where they apply', not bad,
          ['%s %s: %s' % (r['id'], r['config'], r['note'][:160]) for r in bad])
    print('V3.1: %d pairs; L4 on %d of them (the others are on the review list)'
          % (len(got), sum(1 for r in got if r['L4'] in ('PASS', 'FAIL'))))
    for r in [r for r in results if r['applies'] == 'yes' and r['group'] == 'fetch']:
        o = r.get('_outcome') or {}
        print('  %-4s %-7s %-8s L1 %-4s L4 %-6s %s' % (r['id'], r['priority'], o.get('type'), r['L1'], r['L4'],
                                                      (o.get('detail') or '')[:150]))
    check('V3.1: no row is excused by an open dispute', not open_disputes(), sorted(open_disputes()))


MAINTAINER_XT = ('Re-run last config, but include the matching xtalk files in the simulation.',
                 'Add xtalk files and re-run.')


def gate_n2(rows):
    """Gate N2: the maintainer's two crosstalk phrases (paraphrases of XT01) give XT01's plan, step for step with
    the same arguments, on every config XT01 names."""
    import scoring
    import prior_states
    from sicopr_assist import core
    xt01 = next(r for r in rows if r['id'] == 'XT01')
    check('N2: the maintainer\'s two phrases are paraphrases of XT01',
          all(p in [x.strip() for x in xt01['paraphrases'].split(' | ')] for p in MAINTAINER_XT))
    with fixtures.Fixtures() as fx:
        for label in scoring.labels_of(xt01):
            plans = []
            for phrase in (xt01['phrase'],) + MAINTAINER_XT:
                ctx = prior_states.Ctx(fx, label)
                prior_states.build(xt01['prior_state'], ctx)
                o = core.handle(phrase, ctx.project)
                plans.append((o['type'], o['steps']))
            check('N2 %s: both phrases give the PLAN of XT01 (%s)' % (label, ' > '.join(s['op'] for s in plans[0][1])),
                  plans[0][0] == 'PLAN' and plans[1] == plans[0] and plans[2] == plans[0],
                  [(t, [s['op'] for s in st]) for t, st in plans])


_types = {}


def _type(rows, res):
    if not _types:
        for r in rows:
            for label in (['Case1'] if r['starting_config'] == 'any' else r['starting_config'].split('; ')):
                _types[(r['id'], label)] = r['expected_type']
    return _types[(res['id'], res['config'])]


if __name__ == '__main__':
    sys.exit(main())

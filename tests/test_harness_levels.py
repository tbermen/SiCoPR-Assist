"""Gate G1.5: a stub that returns a wrong outcome for one row is caught at L1, at L2, at L3 and at L4.

An answer key is built from the row's own columns (the right type, the change and its linked
changes, the frozen step chain). It must pass all four levels; then one thing is made wrong at a
time, and the level that guards it must fail. Four separate demonstrations, on two rows:

    L1  the right outcome with the wrong type
    L2  DER_0 set to 1e-5 where the row asks for 1e-4
    L3  f_b set to 26.5625 where the row asks for 53.125 (the loaded fields then differ)
    L4  the right outcome with two steps of the chain swapped

    python tests\\test_harness_levels.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402


def value(text):
    try:
        return float(text)
    except ValueError:
        return text


def answer_key(row, prior_wc, frozen):
    """The outcome the row asks for, built from its columns."""
    import l4
    import prior_states
    import scoring
    from sicopr_assist import core
    jp = row['json_path']
    before = scoring.strip_linked(row['value_before'])
    changes = [{'json_path': jp, 'before': None if before == '(absent)' else value(before),
                'after': value(row['value_after']), 'kind': 'set', 'applied': True}]
    for name, after in (scoring.parse_linked(row['linked_changes'], prior_wc) if row['linked_changes'] else []):
        key = name if name in prior_wc['main'] else next('packages.%s.%s' % (b, name) for b, p in prior_wc['packages'].items()
                                                         if name in p)
        changes.append({'json_path': prior_states.json_path_of(key), 'before': None, 'after': value(after),
                        'kind': 'linked', 'applied': True})
    kind, steps = frozen[l4.row_key(row)]
    assert kind == 'chain'
    return core.outcome('PLAN', steps=[{'op': s, 'args': {}} for s in steps], changes=changes, pattern='answer key')


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent')
        return 0
    import l4
    import scoring
    rows = l4.load_table()
    frozen = scoring.read_frozen()

    def pick(target, linked):
        return next(r for r in rows if r['group'] == 'param' and r['target_param'] == target and r['expected_type'] == 'PLAN'
                    and 'Case1' in r['starting_config'].split('; ') and bool(r['linked_changes']) == linked
                    and 'loader' in r['verified'] and l4.row_key(r) in frozen)

    der0, fb = pick('DER_0', False), pick('f_b', True)
    with fixtures.Fixtures(variants=False) as fx:

        def score(row, outcome):
            sc = scoring.Scorer(fx, rows, lambda phrase, project: copy.deepcopy(outcome), frozen=frozen)
            return sc.score(row, 'Case1', paraphrases=False)

        for row in (der0, fb):
            wc = fx.working_config('Case1')
            key = answer_key(row, wc, frozen)
            r = score(row, key)
            check('%s: the answer key passes L1, L2, L3 and L4' % row['id'],
                  (r['L1'], r['L2'], r['L3'], r['L4']) == ('PASS',) * 4, r)
            if row is der0:
                wrong = copy.deepcopy(key)
                wrong['type'] = 'QUESTION'
                wrong['question'] = {'text': 'which?', 'options': ['DER_0', 'cancel']}
                r = score(row, wrong)
                check('L1 catches a wrong type on %s' % row['id'], r['L1'] == 'FAIL', r)
                wrong = copy.deepcopy(key)
                wrong['changes'][0]['after'] = 1e-5
                r = score(row, wrong)
                check('L2 catches DER_0 = 1e-5 for 1e-4 on %s' % row['id'], r['L1'] == 'PASS' and r['L2'] == 'FAIL', r)
            else:
                wrong = copy.deepcopy(key)
                wrong['changes'][0]['after'] = 26.5625
                r = score(row, wrong)
                check('L3 catches f_b = 26.5625 for 53.125 on %s' % row['id'], r['L3'] == 'FAIL', r)
                wrong = copy.deepcopy(key)
                s = wrong['steps']
                s[0], s[1] = s[1], s[0]
                r = score(row, wrong)
                check('L4 catches two steps swapped on %s' % row['id'],
                      (r['L1'], r['L2'], r['L3'], r['L4']) == ('PASS', 'PASS', 'PASS', 'FAIL'), r)
    finish()


if __name__ == '__main__':
    sys.exit(main())

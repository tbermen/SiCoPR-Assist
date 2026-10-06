"""Gate G1.1: every prior_state string of the table has a builder, and each builder runs.

For each of the strings in sicopr_prior_states.csv, the builder seeds a project folder for the first
row and config that use it, and everything it wrote is read back through sicopr_assist.project.

    python tests\\test_prior_states.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402
import l4  # noqa: E402
import prior_states  # noqa: E402


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent')
        return 0
    rows = l4.load_table()
    by_id = {}
    for r in rows:
        by_id.setdefault(r['id'], []).append(r)
    states = prior_states.strings()
    check('the prior-state file lists 91 strings', len(states) == 91 and len(set(states)) == 91, len(states))
    in_table = {r['prior_state'] for r in rows}
    check('every prior_state in the table is in the prior-state file', in_table <= set(states),
          sorted(in_table - set(states))[:5])
    missing = [s for s in states if s not in prior_states.BUILDERS]
    check('every prior-state string has a builder', not missing, missing[:5])
    extra = [s for s in prior_states.BUILDERS if s not in states]
    check('every builder belongs to a prior-state string', not extra, extra[:5])
    ran = 0
    with fixtures.Fixtures() as fx:
        for s in states:
            row = next(r for r in rows if r['prior_state'] == s)
            label = row['starting_config'].split('; ')[0]
            label = 'Case1' if label == 'any' else label
            try:
                ctx = prior_states.Ctx(fx, label, row, by_id)
                prior_states.build(s, ctx)
                n = prior_states.check_built(ctx)
                ran += 1
            except Exception as e:                                # report the builder and carry on
                traceback.print_exc()
                check('builder runs: %s' % s, False, '%s: %s' % (type(e).__name__, e))
                continue
            print('  built %-4s %-5s %d history records: %s' % (row['id'], label, n, s[:80]))
    check('%d of %d prior-state builders run' % (ran, len(states)), ran == len(states))
    finish()


if __name__ == '__main__':
    sys.exit(main())

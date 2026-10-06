"""The step vocabulary and the frozen L4 list.

  - the step names the chains of the table use are exactly sicopr_assist.core.STEPS
  - the normaliser, run on the table again, reproduces tests\\cases\\l4_rows.csv exactly, so the frozen
    list cannot drift from the code that made it
  - the copy of l4_rows.csv in the inputs folder (when SICOPR_ASSIST_INPUTS is set) is the same file
  - a few readings by hand: a chain with prose before it, a one-step chain, options with remarks

    python tests\\test_l4_normaliser.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import filecmp
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.path.insert(0, os.path.dirname(HERE))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import l4  # noqa: E402
import scoring  # noqa: E402
from sicopr_assist import core  # noqa: E402


def main():
    rows = l4.load_table()
    vocab = l4.extract_vocabulary(rows)
    check('the table uses exactly the %d step names of core.STEPS' % len(core.STEPS), vocab == set(core.STEPS),
          'only in the table: %s; only in STEPS: %s' % (sorted(vocab - set(core.STEPS)), sorted(set(core.STEPS) - vocab)))
    d = tempfile.mkdtemp()
    try:
        a, b = os.path.join(d, 'l4_rows.csv'), os.path.join(d, 'l4_review.csv')
        out, rev = scoring.write_frozen(rows, a, b)
        check('the normaliser reproduces the frozen l4_rows.csv', filecmp.cmp(a, scoring.FROZEN, shallow=False))
        check('the normaliser reproduces l4_review.csv', filecmp.cmp(b, scoring.REVIEW, shallow=False))
        check('every row is in the frozen list or the review list', len(out) + len(rev) == len(rows), (len(out), len(rev)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    inputs = os.environ.get('SICOPR_ASSIST_INPUTS')
    if inputs and os.path.exists(os.path.join(inputs, 'l4_rows.csv')):
        check('the inputs folder holds the same frozen list',
              filecmp.cmp(os.path.join(inputs, 'l4_rows.csv'), scoring.FROZEN, shallow=False))
    # readings by hand
    v = set(core.STEPS)
    check('a label before the chain', l4.chain_of('relative change: set_param(SNR_TX: 33.5 -> 32.5) > validate_config > '
                                                  'run_com > summarize', v)[0]
          == ['set_param', 'validate_config', 'run_com', 'summarize'])
    check('an annotation and validate each', l4.chain_of('build_matrix(C_b = 1e-5, 3e-5) > 2 working configs > validate each'
                                                         ' > run_batch > batch_summary with one row per value', v)[0]
          == ['build_matrix', 'validate_config', 'run_batch', 'batch_summary'])
    check('three set_param steps', l4.chain_of('three set_param steps (N_b, b_max(2..N_b)) > validate_config', v)[0]
          == ['set_param'] * 3 + ['validate_config'])
    check('an element with no step name is reported', l4.chain_of('drop_override(SNR_TX) > working config rebuilt > '
                                                                  'run_com', v)[1] == ['working config rebuilt'])
    check('options with remarks and keyword parentheses',
          l4.options_of('options: z_p select first (the only one that takes a case index), then z_p (TX), z_p (RX)')[0]
          == ['z_p select', 'z_p (tx)', 'z_p (rx)'])
    check('options from the keyword descriptions', l4.options_of(
        'options from the keyword descriptions, each shown with its description: f_b, f_v, none of these; after')[0]
          == ['f_b', 'f_v', 'none of these'])
    check('options described, not named, go to review', l4.options_of('options the eight orders on the sheet')[0] is None)
    finish()


if __name__ == '__main__':
    sys.exit(main())

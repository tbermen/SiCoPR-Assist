"""Gate G1.2: V01 to V12 rebuild from Case1, and each matches sicopr_starting_configs.csv on main
parameter count, link count and whether it loads. The four starting workbooks are checked the same way.

    python tests\\test_variants.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent')
        return 0
    want = {r['starting_config']: r for r in fixtures.starting_rows()}
    with fixtures.Fixtures() as fx:
        check('V01 to V12 were rebuilt', sorted(k for k in fx.configs if k.startswith('V')) == list(fixtures.VARIANTS),
              sorted(fx.configs))
        matched = 0
        for label in fixtures.CASES + fixtures.VARIANTS:
            if label not in fx.configs:
                continue
            w = want[label]
            wc = fx.working_config(label)
            fields, err = fx.load_file(fx.configs[label])
            loads = 'yes' if err is None else 'no: ' + err
            ok = (check('%s main parameters %s' % (label, w['main_params']), len(wc['main']) == int(w['main_params']),
                        len(wc['main']))
                  & check('%s links %s' % (label, w['links']), len(wc['links']) == int(w['links']), len(wc['links']))
                  & check('%s loads: %s' % (label, w['loads_in_sicopr']), loads == w['loads_in_sicopr'], loads))
            matched += ok
        check('%d of 16 configs match the table (12 variants, 4 starting workbooks)' % matched, matched == 16)
    finish()


if __name__ == '__main__':
    sys.exit(main())

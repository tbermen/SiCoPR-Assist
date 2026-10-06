"""check, xcheck and finish for the standalone test scripts (after SiCoPR's tests/audit_check.py).

    from check import check, xcheck, finish
    check('name', cond, 'reason shown on FAIL')
    xcheck('known_gap', cond, 'why it is still expected to fail')
    finish()      # prints a summary and exits 1 on any unexpected outcome

check: the condition must hold. xcheck: a known, recorded gap; it is expected to fail, and a pass
means the record is stale, so the run fails to say so. Nothing is written to disk.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import sys

_results = []
_xresults = []


def check(name, cond, reason=''):
    cond = bool(cond)
    print('PASS %s' % name if cond else 'FAIL %s: %s' % (name, reason))
    _results.append(cond)
    return cond


def xcheck(name, cond, reason=''):
    cond = bool(cond)
    if cond:
        print('XPASS %s: the known gap is gone; update the record and make this a check' % name)
    else:
        print('XFAIL %s (known gap): %s' % (name, reason))
    _xresults.append(cond)
    return cond


def finish():
    n_fail = _results.count(False)
    n_stale = _xresults.count(True)
    print('%d checks, %d failed; %d known gaps, %d resolved' % (len(_results), n_fail, len(_xresults), n_stale))
    sys.exit(1 if (n_fail or n_stale) else 0)

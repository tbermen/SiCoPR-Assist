"""A stand-in for Rscript running SiCoPR's R/com_analysis.R, so the dashboard steps run with no R (CI has none).

    python standin_rscript.py <path of com_analysis.R> <run>_caseNN.mat

As the real script does, it writes <run>_caseNN_report.html beside the .mat and a lib folder beside the page, and
prints a few lines. SICOPR_ASSIST_STANDIN_R_ARGV=<file> appends {"argv", "cwd"} as one JSON line per call to that
file; SICOPR_ASSIST_STANDIN_R_FAIL=1 makes it stop with exit code 1 and write nothing.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import sys

LINES = ('stand-in R: reading the .mat export', 'stand-in R: stage 1 to 7 plots')


def main(argv):
    keep = os.environ.get('SICOPR_ASSIST_STANDIN_R_ARGV')
    if keep:
        with open(keep, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'argv': list(argv), 'cwd': os.getcwd()}) + '\n')
    if len(argv) < 2 or not argv[1].lower().endswith('.mat') or not os.path.isfile(argv[1]):
        print('Usage: Rscript R/com_analysis.R <run>_caseNN.mat [out_report.html]')
        return 1
    for line in LINES:
        print(line, flush=True)
    if os.environ.get('SICOPR_ASSIST_STANDIN_R_FAIL') == '1':
        print('Error in library(plotly) : there is no package called plotly')
        return 1
    page = argv[1][:-len('.mat')] + '_report.html'
    lib = os.path.join(os.path.dirname(os.path.abspath(page)), 'lib')
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, 'plotly.min.js'), 'w', encoding='utf-8') as f:
        f.write('// stand-in\n')
    with open(page, 'w', encoding='utf-8', newline='\n') as f:
        f.write('<!doctype html><title>stand-in dashboard</title><p>%s</p>\n' % os.path.basename(argv[1]))
    print('Wrote %s' % page)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

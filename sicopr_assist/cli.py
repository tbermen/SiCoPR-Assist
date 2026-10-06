"""The command line: one phrase per call, or an interactive prompt when no phrase is given (Decision 13).

    sicopr-assist "Re-run with DER_0 = 1e-4"
    python -m sicopr_assist "Re-run with DER_0 = 1e-4"
    sicopr-assist                       (prompts until "quit" or end of input)

The project is the folder the tool is run from. --json prints the outcome as JSON.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import json
import os
import sys

from sicopr_assist import __version__, core
from sicopr_assist.project import Project


def show(outcome, as_json=False, out=None):
    out = out or sys.stdout
    if as_json:
        out.write(json.dumps(outcome, indent=1) + '\n')
        return
    for line in outcome.get('announce') or []:
        out.write(line + '\n')
    t = outcome['type']
    if t == 'STOP':
        out.write('STOP: %s\n' % outcome.get('reason', ''))
    elif t == 'QUESTION':
        q = outcome.get('question') or {}
        out.write('QUESTION: %s\n' % q.get('text', ''))
        for i, opt in enumerate(q.get('options') or [], 1):
            out.write('  %d. %s\n' % (i, opt))
    else:
        out.write('PLAN:\n')
        for i, step in enumerate(outcome.get('steps') or [], 1):
            out.write('  %d. %s\n' % (i, step.get('op')))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='sicopr-assist', description='Turn a phrase into a SiCoPR run.')
    ap.add_argument('phrase', nargs='*', help='the phrase; with none, an interactive prompt starts')
    ap.add_argument('--json', action='store_true', help='print the outcome as JSON')
    ap.add_argument('--version', action='version', version='SiCoPR-Assist %s' % __version__)
    args = ap.parse_args(argv)
    project = Project(os.getcwd())
    if args.phrase:
        show(core.handle(' '.join(args.phrase), project), args.json)
        return 0
    while True:
        try:
            phrase = input('sicopr-assist> ')
        except EOFError:
            print()
            return 0
        if phrase.strip().lower() in ('quit', 'exit'):
            return 0
        if phrase.strip():
            show(core.handle(phrase, project), args.json)


if __name__ == '__main__':
    sys.exit(main())

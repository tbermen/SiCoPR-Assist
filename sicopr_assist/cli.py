"""The command line: one phrase per call, or an interactive prompt when no phrase is given (Decision 13).

    sicopr-assist "Re-run with DER_0 = 1e-4"
    python -m sicopr_assist "Re-run with DER_0 = 1e-4"
    sicopr-assist                       (prompts until "quit" or end of input)

The project is the folder the tool is run from. --json prints the outcome as JSON. A PLAN is shown, then
carried out (run.carry_out), and what it gives is printed; cli.py only formats and prints what the core and
run.py return. While a plan is carried out, every line the runner hands over is printed as it comes: a status
line as each step starts, the engine's own lines indented, and each run's elapsed time and headline result
(Decision 17). --quiet leaves out the engine's lines and keeps the status lines; run.log keeps them all.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import json
import os
import sys

from sicopr_assist import __version__, core, run
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
    if t != 'PLAN':                              # what the tutor adds (Decision 11); after a PLAN, run.py hands
        for line in (outcome.get('tutor') or {}).get('lines') or []:      # its lines over once the plan is done
            out.write(line + '\n')


def handle_and_run(phrase, project, as_json=False, out=None, quiet=False, child=None):
    """One phrase: the outcome is shown; a PLAN is then carried out, its progress printed as it comes, then its
    lines. child replaces the command that runs one case (a test gives a stand-in)."""
    out = out or sys.stdout
    outcome = core.handle(phrase, project)
    show(outcome, as_json, out)
    if outcome['type'] != 'PLAN':
        return outcome, None

    def progress(kind, text):
        if quiet and kind == 'engine':
            return
        out.write(run.line_text(kind, text) + '\n')
        out.flush()
    done = run.carry_out(project, outcome, child=child, progress=progress)
    for line in done['lines']:
        out.write(line + '\n')
    return outcome, done


def main(argv=None):
    ap = argparse.ArgumentParser(prog='sicopr-assist', description='Turn a phrase into a SiCoPR run.')
    ap.add_argument('phrase', nargs='*', help='the phrase; with none, an interactive prompt starts')
    ap.add_argument('--json', action='store_true', help='print the outcome as JSON')
    ap.add_argument('--quiet', action='store_true',
                    help="while COM runs, show the status lines but not the engine's own lines")
    ap.add_argument('--version', action='version', version='SiCoPR-Assist %s' % __version__)
    args = ap.parse_args(argv)
    project = Project(os.getcwd())
    if args.phrase:
        handle_and_run(' '.join(args.phrase), project, args.json, quiet=args.quiet)
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
            handle_and_run(phrase, project, args.json, quiet=args.quiet)


if __name__ == '__main__':
    sys.exit(main())

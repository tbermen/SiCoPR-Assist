"""The command line: one phrase per call, or an interactive prompt when no phrase is given.

    sicopr-assist "Re-run with DER_0 = 1e-4"
    python -m sicopr_assist "Re-run with DER_0 = 1e-4"
    sicopr-assist                       (prompts until "quit" or end of input)
    sicopr-assist gui [folder]          SiCoPR's GUI with the Assist panel (docs/GUI_DESIGN.md)

The project is the folder the tool is run from. A PLAN is shown, then carried out (run.carry_out), and what it
gives is printed; cli.py only formats and prints what the core and run.py return. While a plan is carried out,
every line the runner hands over is printed as it comes: a status line as each step starts, the engine's own lines
indented, and each run's elapsed time and headline result. --quiet leaves out the engine's lines and keeps the
status lines; run.log keeps them all.

--json prints one JSON document on standard output, and nothing else: the last outcome, with what carrying it out
gave under "carried_out" when it is a PLAN. Everything a person reads (the plan, the progress lines, the results)
goes to standard error instead. Output that is not a terminal is written as UTF-8, so the engine's lines (which hold
characters such as the multiplication sign) arrive intact through a pipe or a file.
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
    if t != 'PLAN':                              # what the tutor adds; after a PLAN, run.py hands
        for line in (outcome.get('tutor') or {}).get('lines') or []:      # its lines over once the plan is done
            out.write(line + '\n')


def handle_and_run(phrase, project, as_json=False, out=None, quiet=False, child=None, err=None, **stand_ins):
    """One phrase: the outcome is shown; a PLAN is then carried out, its progress printed as it comes, then its
    lines. A channel download is carried out in two parts: the zip, then the outcome the core plans from it, which
    is shown and, if it is a PLAN, carried out; that last outcome is returned. child replaces the command that runs
    one case, and stand_ins the other outside pieces run.carry_out takes (rscript, open_page, open_folder); a test
    gives stand-ins. With as_json, out gets one JSON document, written last, and the text goes to err (standard
    error by default)."""
    out = out or sys.stdout
    text = (err or sys.stderr) if as_json else out
    outcome = core.handle(phrase, project)
    show(outcome, False, text)
    if outcome['type'] != 'PLAN':
        if as_json:
            show(outcome, True, out)
        return outcome, None

    def progress(kind, line):
        if quiet and kind == 'engine':
            return
        text.write(run.line_text(kind, line) + '\n')
        text.flush()

    def lines(ls):
        for line in ls:
            text.write(line + '\n')
    last, done = run.follow(project, outcome, show=lambda o: show(o, False, text), lines=lines, child=child,
                            progress=progress, **stand_ins)
    if as_json:
        doc = dict(last)
        if last['type'] == 'PLAN' and done is not None:
            doc['carried_out'] = {k: done.get(k) for k in ('status', 'run_ids', 'lines')}
        show(doc, True, out)
    return last, done


def _utf8_when_piped():
    """Write standard output and standard error as UTF-8 when they are not a terminal and PYTHONIOENCODING does not
    say otherwise. On Windows a pipe or a file would otherwise get the ANSI code page, and a reader expecting UTF-8
    would see mojibake for characters such as the multiplication sign the engine prints."""
    if os.environ.get('PYTHONIOENCODING'):
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty() and hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass


def gui(argv):
    """sicopr-assist gui [folder] [--port N] [--no-browser]: SiCoPR's GUI with the Assist panel, on the project
    folder (GUI_DESIGN.md section 5). SiCoPR's gui/app.py is started from an argument list, no shell, with the
    folder opened (--dir) and made the run directory (--run-dir); the panel finds the project through
    SICOPR_ASSIST_PROJECT. Returns the GUI's exit code."""
    from sicopr_assist import engine
    ap = argparse.ArgumentParser(prog='sicopr-assist gui', description="SiCoPR's GUI with the SiCoPR-Assist panel.")
    ap.add_argument('folder', nargs='?', default=os.getcwd(), help='the project folder (default: this folder)')
    ap.add_argument('--port', type=int, default=None, help="the port (default: SiCoPR's, 8765)")
    ap.add_argument('--no-browser', action='store_true', help='do not open a browser')
    args = ap.parse_args(argv)
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print('not a folder: %s' % folder)
        return 2
    try:
        app, has_slot = engine.gui_app()
    except engine.EngineMissing as e:
        print(e)
        return 2
    if not has_slot:
        print("The SiCoPR at %s has no panel slot in its GUI (gui/app.py does not load sicopr.gui_panels), so the "
              "Assist panel cannot be shown there. Use a SiCoPR with the slot, or the command line." % engine.folder())
        return 2
    print('SiCoPR-Assist %s: project %s' % (__version__, folder))
    return run.start_gui(app, folder, args.port, args.no_browser)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _utf8_when_piped()
    if argv[:1] == ['gui']:
        return gui(argv[1:])
    ap = argparse.ArgumentParser(
        prog='sicopr-assist', description='Turn a phrase into a SiCoPR run. The project is the current folder.',
        epilog="sicopr-assist gui [folder] starts SiCoPR's GUI with the Assist panel on the folder "
               "(sicopr-assist gui --help).")
    ap.add_argument('phrase', nargs='*', help='the phrase; with none, an interactive prompt starts')
    ap.add_argument('--json', action='store_true',
                    help='print one JSON document on standard output (the outcome, and what carrying it out gave); '
                         'the text goes to standard error')
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

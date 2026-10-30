"""The tutor and trouble detection (rows TU01 to TU19; check V1.3).

V1.3: every phrase the tutor offers, for each of the four starting configs and the twelve variants, works in the
state it is offered in: it resolves through the core to a PLAN, never a QUESTION or a STOP and never with a word
left unplaced (row TU04). The phrases are the ones the outcome itself lists (outcome["tutor"]["phrases"]), and each
is checked to be printed. Three states per config: no run yet (the one phrase offered is the run itself), after a
run, and after a run that set DER_0 = 1e-4 (that change is not offered again). Two more states on the first
starting config: an empty folder, where the one phrase is Run the example., and a plan that makes no run in a
folder with no run (Show settings.), after which no re-run is offered. The nearest forms of five missed phrases are
taken on the four starting configs; a nearest form corrects the user's own phrase, so it may resolve to a QUESTION.
A phrase holding <value> is checked with half the current value, twice it, or the value itself, and passes when one
of them resolves.

Then the behaviour of rows TU01 to TU19 that L4 does not look at: whether the tutor text is shown, the nearest
form of a missed phrase, the feedback line and its gap, and what the history records as shown.

The dashboard example (TU01) is taught only where it works, so it needs an Rscript: the whole test runs with the
stand-in Rscript of fixtures.r_env found, and one check hides it and sees the example left out (row D3).

    python tests\\test_tutor.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

# phrases a user gets wrong, whose nearest form the tutor prints (rows TU02, PH22, C3, PH08)
MISSES = ('halve the baud rate and rerun', 'Re-run with DER_0 = 1e-4 pronto.', 'Re-run with zp select 2',
          'rerun with fb = 53.125', 'rn it agian with DER_0 1e-4')
KINDS = 7                 # the six examples of row TU01 (the dashboard among them) and the package of TU07
STATES = ('no run', 'after a run', 'after DER_0 = 1e-4')


def fills(phrase, wc):
    """The phrase with <value> filled in: half the current value, twice it, the value itself."""
    m = re.search(r'with (.+?) = <value>', phrase)
    if not m:
        return [phrase]
    from sicopr_assist import core
    v = core._current(wc, m.group(1))
    try:
        x = float(v)
        return [phrase.replace('<value>', '%g' % t) for t in (x / 2, x * 2, x)]
    except (TypeError, ValueError):
        return [phrase.replace('<value>', core.show(v))]


def state(fx, label, ran):
    """A project in one of STATES (ran is its index): no run yet, a run, or a run and then DER_0 = 1e-4."""
    import prior_states
    ctx = prior_states.Ctx(fx, label)
    if ran:
        prior_states.seed_run(ctx)
    if ran == 2:
        prior_states.seed_override_run(ctx, {'DER_0': 1e-4})
    return ctx


def resolves(fx, label, ran, phrase, plan_only):
    """(ok, what) for one printed phrase, handled on a fresh copy of the state it was printed in."""
    from sicopr_assist import core
    got = []
    ctx = state(fx, label, ran)
    wc = ctx.prior_wc
    fx.remove_project(ctx.root)
    for text in fills(phrase, wc):
        ctx = state(fx, label, ran)
        try:
            o = core.handle(text, ctx.project)
        finally:
            fx.remove_project(ctx.root)
        good = o['type'] in (('PLAN',) if plan_only else ('PLAN', 'QUESTION')) and not o.get('unplaced')
        got.append('%s -> %s%s' % (text, o['type'], ' unplaced %s' % o['unplaced'] if o.get('unplaced') else ''))
        if good:
            return True, got[-1]
    return False, '; '.join(got)


def printed(o):
    t = o.get('tutor') or {}
    text = '\n'.join(t.get('lines') or [])
    return list(t.get('phrases') or []), all(p in text for p in t.get('phrases') or [])


def gate_v13(fx):
    from sicopr_assist import core
    labels = [lb for lb in fixtures.CASES + fixtures.VARIANTS if lb in fx.configs]
    n_phrases = 0
    bad = []
    for label in labels:
        for ran in range(len(STATES)):
            ctx = state(fx, label, ran)
            try:
                o = core.handle('What can I say?', ctx.project)
            finally:
                fx.remove_project(ctx.root)
            phrases, shown = printed(o)
            where = '%s %s' % (label, STATES[ran])
            if not shown:
                bad.append('%s: a phrase is not in the printed lines' % where)
            text = '\n'.join((o.get('tutor') or {}).get('lines') or [])
            # with no run the one phrase offered is the run itself, or the example setup when this folder's own
            # config does not run (a variant the loader refuses), and never a re-run
            if not ran and (len(phrases) != 1 or not (phrases[0].startswith('Run COM on ') or
                                                      phrases[0] == 'Run the example.') or 'Re-run' in text
                            or (label in fixtures.CASES and phrases[0] == 'Run the example.')):
                bad.append('%s: with no run the one phrase offered is the run itself, and no re-run: %s'
                           % (where, phrases))
            if ran == 2 and any(re.match(r'Re-run with DER_0 = 1e-4$', p) for p in phrases):
                bad.append('%s: a change already in effect is offered: %s' % (where, phrases))
            if label in fixtures.CASES and ran == 1 and len(phrases) != KINDS:
                bad.append('%s: %d example phrases, expected %d: %s' % (where, len(phrases), KINDS, phrases))
            forms = []
            if label in fixtures.CASES:
                for miss in MISSES:
                    c2 = state(fx, label, ran)
                    try:
                        o2 = core.handle(miss, c2.project)
                    finally:
                        fx.remove_project(c2.root)
                    ph2, shown2 = printed(o2)
                    if not shown2:
                        bad.append('%s: a nearest form of %r is not printed' % (where, miss))
                    forms += ph2
            for p in phrases:
                ok, what = resolves(fx, label, ran, p, plan_only=True)      # TU04: every phrase offered is a PLAN
                n_phrases += 1
                if not ok:
                    bad.append('%s: %s' % (where, what))
            for p in dict.fromkeys(forms):
                ok, what = resolves(fx, label, ran, p, plan_only=False)
                n_phrases += 1
                if not ok:
                    bad.append('%s nearest form: %s' % (where, what))
    n_phrases += no_run_states(fx, bad)
    check('V1.3: every phrase the tutor offers resolves to a PLAN with no unplaced word in the state it is offered in, '
          'on %d configs in %d states, an empty folder and a plan with no run (%d phrases)'
          % (len(labels), len(STATES), n_phrases), not bad and n_phrases > 0, bad[:20])
    return n_phrases


def no_run_states(fx, bad):
    """An empty folder, and a plan that makes no run in a folder with no run yet: only what runs now is offered."""
    import shutil
    import tempfile
    from sicopr_assist import core
    from sicopr_assist.project import Project
    n = 0
    empty = tempfile.mkdtemp(prefix='sicopr_assist_tu_')
    try:
        o = core.handle('What can I say?', Project(empty))
        phrases, shown = printed(o)
        text = '\n'.join((o.get('tutor') or {}).get('lines') or [])
        if phrases != ['Run the example.'] or not shown or 'Re-run' in text:
            bad.append('empty folder: the one phrase offered is Run the example.: %s %r' % (phrases, text[:200]))
        for p in phrases:
            n += 1
            got = core.handle(p, Project(tempfile.mkdtemp(dir=empty)))
            if got['type'] != 'PLAN' or got.get('unplaced'):
                bad.append('empty folder: %s -> %s' % (p, got['type']))
    finally:
        shutil.rmtree(empty, ignore_errors=True)
    ctx = state(fx, fixtures.CASES[0], 0)
    try:
        o = core.handle('Show settings.', ctx.project)
    finally:
        fx.remove_project(ctx.root)
    phrases, shown = printed(o)
    text = '\n'.join((o.get('tutor') or {}).get('lines') or [])
    if not phrases or 'Re-run' in text or any(not p.startswith('Run COM on ') for p in phrases):
        bad.append('a plan that makes no run, with no run yet: only the run itself is offered: %s %r'
                   % (phrases, text[:200]))
    for p in phrases:
        n += 1
        ok, what = resolves(fx, fixtures.CASES[0], 0, p, plan_only=True)
        if not ok:
            bad.append('a plan with no run: %s' % what)
    return n


def row_checks(fx):
    """The tutor text of the TU rows, which L4 does not read."""
    import l4
    import prior_states
    from sicopr_assist import core, run
    rows = l4.load_table()
    by = {}
    for r in rows:
        by.setdefault(r['id'], []).append(r)

    def handle(rid, phrase=None, label='Case1'):
        row = by[rid][0]
        ctx = prior_states.Ctx(fx, label, row, by)
        prior_states.build(row['prior_state'], ctx)
        o = core.handle(phrase or row['phrase'], ctx.project)
        hist = ctx.project.read_history()
        return o, ctx, hist

    def lines(o):
        return '\n'.join((o.get('tutor') or {}).get('lines') or [])

    for rid in ('TU01', 'TU09', 'TU11', 'TU13'):
        o, ctx, hist = handle(rid)
        steps = [s['op'] for s in o['steps']]
        check('%s: the run plan ends with show_tutor and the examples are printed' % rid,
              steps[-1:] == ['show_tutor'] and 'Re-run with DER_0 = 1e-4' in lines(o) and hist[-1]['shown'] == ['tutor'],
              (steps, lines(o)[:200], hist[-1]['shown']))
        fx.remove_project(ctx.root)
    for rid in ('TU05', 'TU10', 'TU12'):
        o, ctx, hist = handle(rid)
        check('%s: no tutor text' % rid, not o.get('tutor') and 'show_tutor' not in [s['op'] for s in o['steps']]
              and hist[-1]['shown'] == [], o.get('tutor'))
        fx.remove_project(ctx.root)
    o, ctx, _ = handle('TU12', 'What can I say?')
    check('TU12: What can I say? still works with tutor_until_commands = 0 (no run yet: it offers the run)',
          o['type'] == 'PLAN' and (o.get('tutor') or {}).get('phrases') == [r'Run COM on data\thru.s4p with '
                                                                            r'data\config.xlsx'], lines(o)[:200])
    import io
    from sicopr_assist import cli
    buf = io.StringIO()
    o2, done = cli.handle_and_run('What can I say?', ctx.project, out=buf)
    check('Decision 13: the core returns the tutor lines as data, run.py hands them over and cli.py prints them '
          'after the plan', buf.getvalue().endswith(lines(o2) + '\n') and 'PLAN:' in buf.getvalue() and
          done['lines'] == o2['tutor']['lines'], buf.getvalue()[-300:])
    buf = io.StringIO()
    c1 = prior_states.Ctx(fx, 'Case1', by['TU01'][0], by)
    prior_states.build(by['TU01'][0]['prior_state'], c1)
    standin = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
    o1, done1 = cli.handle_and_run(by['TU01'][0]['phrase'], c1.project, out=buf, child=standin)
    printed1 = buf.getvalue().splitlines()
    check('TU01 carried out: the run, its summary, then a status line for show_tutor and the tutor lines last',
          done1['run_ids'] and done1['lines'][-len(o1['tutor']['lines']):] == o1['tutor']['lines'] and
          printed1[-len(o1['tutor']['lines']):] == o1['tutor']['lines'] and
          any(x.startswith('step 5 of 5: show_tutor') for x in printed1), printed1[-12:])
    fx.remove_project(c1.root)
    buf = io.StringIO()
    c2 = prior_states.Ctx(fx, 'Case1', by['TU02'][0], by)
    prior_states.build(by['TU02'][0]['prior_state'], c2)
    o3, _ = cli.handle_and_run('halve the baud rate and rerun', c2.project, out=buf)
    check('Decision 13: after a question, cli.py prints the tutor lines after the options',
          buf.getvalue().endswith(lines(o3) + '\n') and 'QUESTION:' in buf.getvalue(), buf.getvalue()[-300:])
    fx.remove_project(c2.root)
    fx.remove_project(ctx.root)
    o, ctx, _ = handle('TU02')
    check('TU02: the question offers f_b and the tutor adds Re-run with f_b = <value>',
          o['type'] == 'QUESTION' and 'Re-run with f_b = <value>' in lines(o) and
          (o.get('tutor') or {}).get('phrases') == ['Re-run with f_b = <value>'], (o['type'], lines(o)))
    fx.remove_project(ctx.root)
    o, ctx, _ = handle('TU01')                       # the run of TU01, then What can I say? on its config
    prior_states.seed_run(ctx)
    o = core.handle('What can I say?', ctx.project)
    from sicopr_assist import tutor
    kinds = [k for k, _ in tutor.examples(core.Context(ctx.project))]
    check('TU01: the six kinds of example, the dashboard among them, and the package example of TU07',
          kinds == ['re-run with one change', 're-run with another package', 'sweep a range', 'sweep a choice',
                    'show the dashboard', 'what did you change', 'go back to the original']
          and '  %s' % core.DASHBOARD_PHRASE in lines(o).splitlines(), (kinds, lines(o)))
    old = {k: os.environ.get(k) for k in ('PATH', 'ProgramFiles')}
    os.environ.update(fx.r_env(found=False))
    try:
        o2 = core.handle('What can I say?', ctx.project)
        hidden = [k for k, _ in tutor.examples(core.Context(ctx.project))]
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check('TU01 with Rscript hidden: the dashboard example is left out (it would be a STOP, row D3) and the rest stay',
          hidden == [k for k in kinds if k != 'show the dashboard'] and core.DASHBOARD_PHRASE not in lines(o2),
          (hidden, lines(o2)))
    fx.remove_project(ctx.root)
    row = by['TU07'][0]
    ctx = prior_states.Ctx(fx, 'V07', row, by)
    prior_states.build(row['prior_state'], ctx)
    prior_states.seed_run(ctx)                       # examples are offered once there is a run
    o = core.handle(row['phrase'], ctx.project)
    check('TU07: the package example uses this sheet\'s names (Re-run with package PkgB)',
          'Re-run with package PkgB' in lines(o) and 'PKG_HiR_CLASSB' not in lines(o), lines(o))
    fx.remove_project(ctx.root)
    feedback_line = 'Export feedback writes the command history to a text file, names masked, that can be emailed ' \
                    'to %s' % core.FEEDBACK_ADDRESS
    expect = {'TU14': (True, True), 'TU15': (False, False), 'TU16': (False, False), 'TU17': (True, False),
              'TU18': (True, False), 'TU19': (False, False)}
    for rid, (tut, fb) in expect.items():
        o, ctx, hist = handle(rid)
        text = lines(o)
        got_t = 'Re-run with DER_0 = 1e-4 pronto.  ->  Re-run with DER_0 = 1e-4' in text
        got_f = feedback_line in text
        opts = (o.get('question') or {}).get('options') or []
        check('%s: PH22\'s options; tutor %s, feedback line %s' % (rid, 'shown' if tut else 'not shown',
                                                                   'shown' if fb else 'not shown'),
              o['type'] == 'QUESTION' and opts[-1:] == ['cancel'] and opts[0].startswith('run the change that was '
                                                                                         'understood')
              and got_t == tut and got_f == fb and
              hist[-1]['shown'] == (['tutor'] + (['feedback_notice'] if fb else []) if tut else []),
              (opts, text, hist[-1]['shown']))
        fx.remove_project(ctx.root)
    # TU17's note: the misses counted towards one showing are not counted again
    o, ctx, hist = handle('TU14')
    o2 = core.handle('Re-run with DER_0 = 1e-4 pronto.', ctx.project)
    check('TU17 note: right after a showing, the next miss does not bring the tutor up again', not o2.get('tutor'),
          lines(o2))
    fx.remove_project(ctx.root)
    # TU06 (stretch): Tutor off writes the line, Tutor on removes it
    o, ctx, _ = handle('TU06')
    done = run.carry_out(ctx.project, o)
    with open(ctx.project.settings_path, encoding='utf-8') as f:
        off = f.read()
    o2 = core.handle('Tutor on.', ctx.project)
    run.carry_out(ctx.project, o2)
    with open(ctx.project.settings_path, encoding='utf-8') as f:
        on = f.read()
    check('TU06: Tutor off writes tutor_until_commands = 0 to the project file, Tutor on removes it',
          [s['op'] for s in o['steps']] == ['set_setting'] and 'tutor_until_commands = 0' in off and
          'tutor_until_commands' not in on, (done['lines'], off, on))
    fx.remove_project(ctx.root)


def unit_checks():
    """Decision 11's counting, on history records alone."""
    from sicopr_assist import tutor

    def rec(kind, shown=()):
        return {'ok': {'status': 'ok', 'outcome': 'PLAN'},
                'miss': {'status': 'stopped', 'outcome': 'STOP', 'unplaced': ['xyzzy']},
                'cancelled': {'status': 'cancelled', 'outcome': 'STOP'},
                'nothing': {'status': 'stopped', 'outcome': 'STOP', 'reason': 'Not a supported request. ...'},
                'answered': {'status': 'ok', 'outcome': 'PLAN', 'options': ['a', 'b'], 'chosen': 'a'},
                'plan_with_word': {'status': 'ok', 'outcome': 'PLAN', 'unplaced': ['settings']}}[kind] | \
            {'shown': list(shown)}
    st = {'trouble_misses': 3, 'trouble_window': 5, 'feedback_notice': True, 'feedback_notice_gap': 20}
    check('a miss: an unplaced word, a cancelled question, a phrase that matched nothing',
          all(tutor.is_miss(rec(k)) for k in ('miss', 'cancelled', 'nothing')) and
          not any(tutor.is_miss(rec(k)) for k in ('ok', 'answered', 'plan_with_word')))
    cur = rec('miss')
    check('3 misses in the last 5 commands bring the tutor up',
          len(tutor.trouble([rec('ok')] * 10 + [rec('miss'), rec('ok'), rec('miss'), rec('ok')], cur, st)) == 3)
    check('2 misses in the last 5 do not',
          not tutor.trouble([rec('ok')] * 10 + [rec('ok'), rec('ok'), rec('miss'), rec('ok')], cur, st))
    check('a miss before the last 5 commands is not counted',
          not tutor.trouble([rec('miss')] * 3 + [rec('ok')] * 4, cur, st))
    check('misses before a showing of the tutor are not counted again',
          not tutor.trouble([rec('miss'), rec('miss', ['tutor']), rec('ok'), rec('ok')], cur, st))
    check('trouble_misses = 0 never brings the tutor up', not tutor.trouble([rec('miss')] * 5, cur,
                                                                           dict(st, trouble_misses=0)))
    check('the feedback line: due with none shown, not within 20 commands of the last, due after 20',
          tutor.feedback_notice_due([rec('ok')] * 5, st) and
          not tutor.feedback_notice_due([rec('ok', ['tutor', 'feedback_notice'])] + [rec('ok')] * 18, st) and
          tutor.feedback_notice_due([rec('ok', ['tutor', 'feedback_notice'])] + [rec('ok')] * 19, st) and
          not tutor.feedback_notice_due([rec('ok')] * 5, dict(st, feedback_notice=False)))
    check('successful commands are the ones with status ok',
          tutor.successes([rec('ok'), rec('answered'), rec('miss'), rec('cancelled')]) == 2)
    # an edit or a workbook opened in the GUI's Config view is not a typed command (GUI_DESIGN.md section 10)
    view = [dict(rec('ok'), kind='edit', origin='gui'), dict(rec('ok'), kind='open', origin='gui'),
            dict(rec('miss'), kind='edit', origin='gui')]
    check('Config-view records are not commands: not successes, and not in the window that counts misses',
          tutor.successes([rec('ok')] + view * 3) == 1
          and not tutor.trouble([rec('miss'), rec('ok'), rec('ok')] + view * 2, cur, st)
          and len(tutor.trouble([rec('miss'), rec('miss')] + view * 3 + [rec('ok')], cur, st)) == 3
          and not tutor.feedback_notice_due([rec('ok', ['tutor', 'feedback_notice'])] + [rec('ok')] * 5 + view * 10,
                                            st))


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; the tutor checks need them')
        return 0
    parts = sys.argv[1:] or ['unit', 'rows', 'v13']      # a part alone: python tests\test_tutor.py rows
    if 'unit' in parts:
        unit_checks()
    with fixtures.Fixtures() as fx:
        os.environ.update(fx.r_env())               # Rscript found (the stand-in) on every machine
        if 'rows' in parts:
            row_checks(fx)
        if 'v13' in parts:
            gate_v13(fx)
    finish()


if __name__ == '__main__':
    sys.exit(main())

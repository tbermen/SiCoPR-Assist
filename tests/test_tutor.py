"""The tutor and trouble detection (Decision 11; rows TU01 to TU19; gate V1.3).

V1.3: every phrase the tutor can print, for each of the four starting configs and the twelve variants, resolves
through the core to a PLAN or a QUESTION, never a STOP and never with a word left unplaced. The phrases are the
ones the outcome itself lists (outcome["tutor"]["phrases"]), and each is checked to be printed. Two states per
config: no run yet, and after a run. The nearest forms of five missed phrases are taken on the four starting
configs. After a run every example resolves to a PLAN (row TU04); with no run yet
the first example is the run itself, and it resolves to a PLAN. A phrase holding <value> is checked with half
the current value, twice it, or the value itself, and passes when one of them resolves.

Then the behaviour of rows TU01 to TU19 that L4 does not look at: whether the tutor text is shown, the nearest
form of a missed phrase, the feedback line and its gap, and what the history records as shown.

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
KINDS = 6                 # the examples of row TU01 (the dashboard waits for Phase V2-2) and the package of TU07


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
    import prior_states
    ctx = prior_states.Ctx(fx, label)
    if ran:
        prior_states.seed_run(ctx)
    return ctx


def resolves(fx, label, ran, phrase, plan_only):
    """(ok, what) for one printed phrase, handled on a fresh copy of the state it was printed in."""
    from sicopr_assist import core
    wc = fx.working_config(label)
    got = []
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
        for ran in (False, True):
            ctx = state(fx, label, ran)
            try:
                o = core.handle('What can I say?', ctx.project)
            finally:
                fx.remove_project(ctx.root)
            phrases, shown = printed(o)
            where = '%s %s' % (label, 'after a run' if ran else 'no run')
            if not shown:
                bad.append('%s: a phrase is not in the printed lines' % where)
            if label in fixtures.CASES:
                want = KINDS + (0 if ran else 1)
                if len(phrases) != want:
                    bad.append('%s: %d example phrases, expected %d: %s' % (where, len(phrases), want, phrases))
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
                # TU04: after a run every example is a PLAN; with no run yet the run itself is
                ok, what = resolves(fx, label, ran, p, plan_only=ran or p.startswith('Run COM on '))
                n_phrases += 1
                if not ok:
                    bad.append('%s: %s' % (where, what))
            for p in dict.fromkeys(forms):
                ok, what = resolves(fx, label, ran, p, plan_only=False)
                n_phrases += 1
                if not ok:
                    bad.append('%s nearest form: %s' % (where, what))
    check('V1.3: every phrase the tutor prints resolves to a PLAN or a QUESTION with no unplaced word, on %d configs in '
          'two states (%d phrases)' % (len(labels), n_phrases), not bad and n_phrases > 0, bad[:20])
    return n_phrases


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
    check('TU12: What can I say? still works with tutor_until_commands = 0', o['type'] == 'PLAN' and
          'Re-run with DER_0 = 1e-4' in lines(o), lines(o)[:200])
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
    o, ctx, _ = handle('TU07', label='V07')
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


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; the tutor checks need them')
        return 0
    parts = sys.argv[1:] or ['unit', 'rows', 'v13']      # a part alone: python tests\test_tutor.py rows
    if 'unit' in parts:
        unit_checks()
    with fixtures.Fixtures() as fx:
        if 'rows' in parts:
            row_checks(fx)
        if 'v13' in parts:
            gate_v13(fx)
    finish()


if __name__ == '__main__':
    sys.exit(main())

"""Decisions 7 and 16 as the maintainer ruled on 6 October 2026, through the real core and its pending question.

Decision 7: a sweep with points that a rule asks about asks once for the batch, with exactly the options
run all points anyway, run only the points that pass, cancel. Each answer leads to its plan: every point; only
the points no rule asks about; nothing. A point a rule stops is never run, whatever the answer.

Decision 16: a phrase that asks for a version 1 action and a version 2 feature runs the version 1 part and
announces that the rest is not in this version (CB17, and C2 after a dashboard). A phrase that asks only for a
version 2 feature is a STOP.

Also row RS28: the question about two package blocks carries the change asked for, and each option leads to it.

    python tests\\test_decisions.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

OPTIONS = ['run all points anyway', 'run only the points that pass', 'cancel']

# row: (values a rule asks about, values that pass), on Case1 after the starting run
SWEEPS = {
    'SW038': (['0'], ['1']),
    'SV038': (['0'], ['1']),
    'SW058': (['0.01', '0.02', '0.03', '0.04'], ['0']),
    'SW076': (['1.02'], ['0.68', '0.765', '0.85', '0.935']),
    'SW084': (['0.01', '0.02', '0.03', '0.04'], ['0']),
    'SW102': (['1.045', '1.14'], ['0.76', '0.855', '0.95']),
}


class Rows:
    def __init__(self, fx):
        import l4
        self.fx = fx
        self.rows = l4.load_table()
        self.by_id = {}
        for r in self.rows:
            self.by_id.setdefault(r['id'], []).append(r)

    def talk(self, rid, phrases, label='Case1'):
        """Every outcome of a conversation in one fresh project, on the row's prior state."""
        import prior_states
        from sicopr_assist import core
        from sicopr_assist.project import Project
        row = self.by_id[rid][0]
        ctx = prior_states.Ctx(self.fx, label, row, self.by_id)
        prior_states.build(row['prior_state'], ctx)
        old = {k: os.environ.get(k) for k in ctx.env}
        os.environ.update(ctx.env)
        try:
            return [core.handle(p if p is not None else row['phrase'], Project(ctx.root)) for p in phrases]
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            self.fx.remove_project(ctx.root)


def labels(o):
    from sicopr_assist import validate
    return [', '.join(validate.show(v) for v in p['values'].values()) for p in o['points']]


def steps(o):
    """The steps of a plan, without the show_tutor step that the tutor adds on its own at the end (Decision 11):
    these rows are outside the tutor group, and the harness reads them the same way (scoring.without_own_tutor)."""
    out = list(o['steps'])
    if out and out[-1]['op'] == 'show_tutor' and (out[-1].get('args') or {}).get('why') in ('new', 'trouble'):
        out = out[:-1]
    return [s['op'] for s in out]


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; these checks need them')
        return 0
    from sicopr_assist import core
    with fixtures.Fixtures() as fx:
        t = Rows(fx)
        for rid, (asked, good) in sorted(SWEEPS.items()):
            q, = t.talk(rid, [None])
            check('%s: one question for the batch, with exactly the three options' % rid,
                  q['type'] == 'QUESTION' and q['question']['options'] == OPTIONS, (q['type'], q.get('question')))
            check('%s: the question names every point a rule asks about (%s)' % (rid, ', '.join(asked)),
                  all(a in q['question']['text'] for a in asked), q.get('question', {}).get('text'))
            check('%s: the question carries every point, with the counts' % rid,
                  labels(q) == asked + good or sorted(labels(q)) == sorted(asked + good), labels(q))
            _, a = t.talk(rid, [None, OPTIONS[0]])
            check('%s: run all points anyway plans every point' % rid,
                  a['type'] == 'PLAN' and sorted(labels(a)) == sorted(asked + good) and 'batch_summary' in steps(a),
                  (a['type'], labels(a), a.get('reason')))
            check('%s: and announces the points run although a rule asks about them' % rid,
                  any(l.startswith('run anyway as you chose') and all(x in l for x in asked) for l in a['announce']),
                  a['announce'])
            _, b = t.talk(rid, [None, OPTIONS[1]])
            check('%s: run only the points that pass plans exactly %s' % (rid, ', '.join(good)),
                  b['type'] == 'PLAN' and labels(b) == good and 'batch_summary' in steps(b),
                  (b['type'], labels(b), b.get('reason')))
            check('%s: and announces the points left out' % rid,
                  any(l.startswith('left out as you chose') and all(x in l for x in asked) for l in b['announce'])
                  and not any(x in b['announce'][0] for x in asked if x not in good), b['announce'])
            _, c = t.talk(rid, [None, OPTIONS[2]])
            check('%s: cancel runs nothing' % rid, c['type'] == 'STOP' and not c['points'] and not c['steps'],
                  (c['type'], labels(c)))
        _, b = t.talk('SV038', [None, OPTIONS[1]])
        check('SV038: the summary of differences follows the answer', steps(b)[-1:] == ['diff_results'], steps(b))

        # a point a rule stops (DER_0 = 0, rule Q13) is never run, whatever the answer
        ph = 'Sweep b_max(1) from 0.85 to 1.02 in 2 steps and run DER_0 at 0 and 1e-4.'
        q, a = t.talk('SW076', [ph, OPTIONS[0]])
        stopped = [p for p in q['points'] if p['skipped']]
        check('a sweep with a stopped point and an asked point asks the batch question',
              q['type'] == 'QUESTION' and q['question']['options'] == OPTIONS and len(stopped) == 2,
              (q['type'], q.get('question'), labels(q)))
        ran = [p for p in a['points'] if p['new'] or p['reused_from']]
        check('run all points anyway never runs a point a rule stops',
              a['type'] == 'PLAN' and len(ran) == 2 and all(not p['skipped'] for p in ran)
              and all(p['skipped'] and not p['new'] for p in a['points'] if p not in ran)
              and all(p['values'].get('/main/DER_0') != 0 for p in ran), [(labels({'points': [p]}), p['new'],
                                                                           p['skipped']) for p in a['points']])
        _, b = t.talk('SW076', [ph, OPTIONS[1]])
        check('run only the points that pass leaves out both the asked and the stopped points',
              b['type'] == 'PLAN' and labels(b) == ['0.85, 1e-4'], (b['type'], labels(b)))

        # Decision 16
        for label in ('Case1', 'Case3'):
            o, = t.talk('CB17', [None], label)
            check('CB17 %s: the version 1 part is planned' % label,
                  o['type'] == 'PLAN' and steps(o) == ['set_param', 'validate_config', 'run_com', 'summarize']
                  and [c['json_path'] for c in o['changes']] == ['/main/DER_0'], (o['type'], steps(o), o.get('reason')))
            check('CB17 %s: and the dashboard is announced as not in this version' % label,
                  any(l == core.NOT_IN_V1_PART['dashboard'] for l in o['announce']), o['announce'])
        o, = t.talk('C2', [None])
        check('C2: a re-run after a dashboard plans the run and announces that the dashboard is not in this version',
              o['type'] == 'PLAN' and steps(o) == ['set_param', 'validate_config', 'run_com', 'summarize']
              and core.NOT_IN_V1_PART['dashboard'] in o['announce'], (o['type'], steps(o), o['announce']))
        o, = t.talk('CB17', ['Re-run with DER_0 = 1e-4.'])
        check('the same change without the dashboard announces nothing about it',
              o['type'] == 'PLAN' and core.NOT_IN_V1_PART['dashboard'] not in o['announce'], o['announce'])
        for rid, ph in (('D1', None), ('CB17', 'Show the dashboard.'), ('CB17', 'Download the channels.')):
            o, = t.talk(rid, [ph])
            check('%s: a phrase that asks only for a version 2 feature is a STOP that says so' % (ph or rid),
                  o['type'] == 'STOP' and 'not in this version' in o['reason'], (o['type'], o.get('reason')))

        # CB12 and its paraphrase: four package blocks, each run with every z_p select case
        for ph in (None, 'sweep all packages and all z_p select cases'):
            o, = t.talk('CB12', [ph])
            writes = [p['writes'] for p in o['points']]
            check('CB12 (%s): 4 runs, each block on both sides with z_p select = [ 1 2 3 4 ]' % (ph or 'phrase'),
                  o['type'] == 'PLAN' and o['new_runs'] == 4 and len(writes) == 4
                  and all(w.get('/main/z_p select') == '[ 1 2 3 4 ]' and len(set(w['/main/PKG_NAME'].split())) == 1
                          for w in writes) and len({w['/main/PKG_NAME'] for w in writes}) == 4, writes)
            check('CB12 (%s): announces the case list at every point and 16 results' % (ph or 'phrase'),
                  any('z_p select = [ 1 2 3 4 ] at every point' in l and '16 in all' in l for l in o['announce']),
                  o['announce'])

        # RS28: the question carries the change asked for; each option leads to its block
        q, a = t.talk('RS28', [None, '1'])
        check('RS28: the question carries the change asked for, not applied',
              q['type'] == 'QUESTION' and [(c['json_path'], c['after'], c['applied']) for c in q['changes']]
              == [('/packages/PKG_LowR_CLASSA/C_p', '[0.3e-4 0.3e-4]', False)], q['changes'])
        check('RS28: the TX option plans the change in the TX block', a['type'] == 'PLAN'
              and [c['json_path'] for c in a['changes']] == ['/packages/PKG_LowR_CLASSA/C_p'], (a['type'], a['changes']))
        _, a = t.talk('RS28', [None, '2'])
        check('RS28: the RX option plans the change in the RX block', a['type'] == 'PLAN'
              and [c['json_path'] for c in a['changes']] == ['/packages/PKG_Module/C_p'], (a['type'], a['changes']))
    finish()


if __name__ == '__main__':
    sys.exit(main())

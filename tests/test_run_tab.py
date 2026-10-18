"""After the maintainer's second GUI session (17 October): the Run tab and Assist as one (Decision 23).

    python tests\\test_run_tab.py

read      the forms of "run the command" (the command, what is in the Run tab, the Run tab; run it), the dynamic
          results (the dashboard), "I'd like", the last config and channel files, and a run named by its id; and
          nothing near them (Rule 4)
core      the Run tab's state is data handed to core.handle with the selection: its files and its two options; the
          options are part of the run and of what decides reuse; "Run it." keeps its meaning on the command line; no
          Run tab asks, and its option re-runs the last run; the last config and channels are the setup of the last
          run; the dashboard of a run named by its id
run       with a stand-in child that records its arguments: Output dynamic results is --export-mat and
          --eye-under-mlse is passed to the child, which sets the engine's EYE_PLOT_UNDER_MLSE; the command the Run tab
          shows is the command that runs; a run with another --eye-under-mlse is not reused
panel     POST handle gives the Run tab's setup with a PLAN (sicopr:set-run), POST runtab its command after a change
          in the Run tab, the selection line names the options that are on, and a result says whether it has the .mat
          export and which phrase shows its dynamic results

With the four starting workbooks absent it prints SKIP and exits 0.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
BASE = r'run complete with the starting config and data\thru.s4p'
TAB_DYN = BASE + '; the Run tab holds the same files with Output dynamic results ticked'
TAB_SAME = BASE + '; the Run tab holds the same files and options as that run'
TAB_EYE = BASE + '; the Run tab holds the same files with --eye-under-mlse ticked'
NOTAB = BASE + '; there is no Run tab (the command line)'
R3 = 'none; project folder holds exactly one config and one THRU file'
RUN_TAB_FORMS = ['Run the command.', 'Run the command in the Run tab', 'Run what is in the Run tab',
                 "Run what's in the Run tab", 'Run the Run tab', 'run my command']
NOT_RUN_TAB = ['Run the tab', 'Run the commands', 'Run it in the tabs', 'Run tab', 'Run the command line']
DYNAMIC = ['Show the dynamic results of the last run', 'Results dynamic for the last run', 'Give me dynamic results',
           "I'd like results, dynamic for the last run.", 'I would like the dynamic results']


class Host:
    def __init__(self, roots):
        self._roots = list(roots)

    def roots(self):
        return list(self._roots)

    def run_dir(self):
        return self._roots[0]

    def com_running(self):
        return False


def call(panel, method, path, body=None, host=None):
    got = panel.handle(method, path, {}, body, host)
    if isinstance(got, tuple):
        return got[0], json.loads(got[2])
    return 200, got


def wait(panel, timeout=120):
    t0 = time.time()
    while panel.job is not None and panel.job.finished is None and time.time() - t0 < timeout:
        time.sleep(0.1)
    return panel.job.status(0) if panel.job is not None else {}


class Argv:
    """The stand-in child's arguments, one list per run (SICOPR_ASSIST_STANDIN_ARGV)."""

    def __init__(self):
        fd, self.path = tempfile.mkstemp(suffix='.jsonl')
        os.close(fd)
        os.environ['SICOPR_ASSIST_STANDIN_ARGV'] = self.path

    def runs(self):
        with open(self.path, encoding='utf-8') as f:
            return [json.loads(x) for x in f if x.strip()]

    def close(self):
        os.environ.pop('SICOPR_ASSIST_STANDIN_ARGV', None)
        os.remove(self.path)


def ops(o):
    return [s['op'] for s in o.get('steps') or [] if s['op'] != 'show_tutor']


def step(o, op):
    return next((s['args'] for s in o.get('steps') or [] if s['op'] == op), None)


def main():
    from sicopr_assist import parse
    # ---------------------------------------------------------------- read
    bad = [p for p in RUN_TAB_FORMS if 'run_tab' not in parse.read(p)['flags'] or parse.read(p)['unplaced']]
    check('the forms of "run the command" are read as the Run tab, with no word left unplaced', not bad, bad)
    near = [p for p in NOT_RUN_TAB if not parse.read(p)['unplaced']]
    check('near the forms and not one of them, a word stays unplaced and is asked about', not near,
          [(p, parse.read(p)['flags'], parse.read(p)['unplaced']) for p in near])
    it = parse.read('Run it.')
    check('"Run it." alone is run_it (the core decides), and "Run it again" is not',
          'run_it' in it['flags'] and not it['unplaced'] and 'run_it' not in parse.read('Run it again')['flags']
          and 'run_it' not in parse.read('Run it with DER_0 = 1e-4')['flags'], it['flags'])
    dyn = [p for p in DYNAMIC if 'dashboard' not in parse.read(p)['actions'] or parse.read(p)['unplaced']]
    check('the dynamic results are the dashboard, and "I\'d like" is placed', not dyn,
          [(p, parse.read(p)['unplaced']) for p in dyn])
    alone = parse.read('Show the dynamic stuff')
    check('"dynamic" alone is not the dashboard, and "like" alone is not placed',
          'dashboard' not in alone['actions'] and 'like' in parse.read('Run like this')['unplaced'], alone['actions'])
    last = ['Re-run last config and channel.', 'Re-run the last config and channels', 'Run the same config and channel '
            'again', 'Re-run the previous config and the last channel files']
    lc = [p for p in last if not {'last_config', 'last_channels'} <= set(parse.read(p)['flags'])
          or parse.read(p)['unplaced']]
    check('the last config and channel files are read as such', not lc, lc)
    check('a channel alone after the last config is not placed', 'and' in ' '.join(parse.read(
        'Re-run the last config and widget')['unplaced']) or 'widget' in parse.read(
        'Re-run the last config and widget')['unplaced'])
    named = parse.read('Show the dynamic results of run_0004.')
    other = parse.read('Re-run with run_0004.')
    check('a run id is taken for the dashboard, and anywhere else it is unplaced',
          named['runs'] == ['run_0004'] and not named['unplaced'] and other['runs'] == []
          and 'run_0004' in other['unplaced'], (named['runs'], named['unplaced'], other['unplaced']))

    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent or '
              'hidden; the core, run and panel checks need them')
        return finish()
    import prior_states
    from sicopr_assist import core, run
    from sicopr_assist.panel import api
    from sicopr_assist.project import Project

    with fixtures.Fixtures(variants=False) as fx:
        def state(name, label='Case1'):
            ctx = prior_states.Ctx(fx, label)
            prior_states.build(name, ctx)
            os.environ.update(ctx.env)
            return ctx

        def handle(ctx, phrase, selection='ctx'):
            return core.handle(phrase, ctx.project, selection=ctx.selection if selection == 'ctx' else selection)

        # ------------------------------------------------------------ core
        sel = core.selection_of({'thru': 'x.s4p', 'options': {'export_mat': True, 'eye_under_mlse': 'yes'}}, ROOT)
        check('the selection carries the two options, each on only when it is true',
              sel['options'] == {'export_mat': True, 'eye_under_mlse': False}
              and core.selection_of({'thru': 'x.s4p'}, ROOT)['options'] == {'export_mat': False,
                                                                           'eye_under_mlse': False}
              and core.selection_of(None, ROOT) is None, sel)

        ctx = state(TAB_DYN)
        o = handle(ctx, 'Run the command.')
        check('RT01: the Run tab with Output dynamic results ticked is a run with the .mat export',
              o['type'] == 'PLAN' and ops(o) == ['validate_inputs', 'validate_config', 'run_com', 'summarize']
              and step(o, 'run_com').get('export_mat') is True and 'eye_under_mlse' not in step(o, 'run_com')
              and any('Results, dynamic' in a for a in o['announce']), (o['type'], ops(o), step(o, 'run_com')))
        rec = ctx.project.read_history()[-1]
        check('the record of "Run the command." keeps the Run tab as it was, with its options',
              (rec.get('detail') or {}).get('selection', {}).get('options') == {'export_mat': True,
                                                                               'eye_under_mlse': False}, rec.get('detail'))
        fx.remove_project(ctx.root)

        ctx = state(TAB_EYE)
        o = handle(ctx, 'Run it.')
        check('RT04: --eye-under-mlse goes to run_com, and "Run it." in the GUI is the Run tab',
              o['type'] == 'PLAN' and step(o, 'run_com').get('eye_under_mlse') is True
              and 'run tab' in o['pattern'].split('; ') and any('no reported value' in a for a in o['announce']),
              (o['type'], o['pattern'], step(o, 'run_com')))
        fx.remove_project(ctx.root)

        ctx = state(TAB_SAME)
        o = handle(ctx, 'Run the command.')
        check('RT02: the Run tab holding the setup of the last run is a STOP, nothing changed',
              o['type'] == 'STOP' and 'nothing changed' in o['reason'], o.get('reason'))
        # Output dynamic results unticked after a run that had the export: the export run serves, so nothing changed
        seeded = ctx.project.read_result('run_0001')
        seeded['export_mat'] = True
        ctx.project.write_result('run_0001', seeded)
        o = handle(ctx, 'Run the command.')
        check('after a run with the .mat export, the Run tab without it changes nothing (an export run serves one '
              'without)', o['type'] == 'STOP', o['type'])
        sel2 = dict(ctx.selection, thru=ctx.data('thru2.s4p'))
        prior_states.second_thru(ctx)
        o = handle(ctx, 'Run the command.', sel2)
        check('another THRU picked in the Run tab is a set_channel to it, the config kept',
              o['type'] == 'PLAN' and ops(o)[0] == 'set_channel' and step(o, 'set_channel')['after'].endswith(
                  'thru2.s4p'), (o['type'], ops(o)))
        fx.remove_project(ctx.root)

        ctx = state(NOTAB)
        o = handle(ctx, 'Run the command.')
        check('RT03: with no Run tab it asks: re-run the last run, cancel',
              o['type'] == 'QUESTION' and o['question']['options'] == [core.RERUN_LAST, core.CANCEL], o.get('question'))
        o = handle(ctx, core.RERUN_LAST)
        check('RT03: its option re-runs the last run, as Re-run. does',
              o['type'] == 'PLAN' and ops(o) == ['import_config', 'validate_inputs', 'run_com', 'summarize']
              and o['pattern'].startswith('answer: %s' % core.RERUN_LAST), (o['type'], ops(o), o['pattern']))
        fx.remove_project(ctx.root)

        for st, want in ((R3, 'import_config'), (NOTAB, 'import_config')):
            ctx = state(st)
            o = handle(ctx, 'Run it.')
            check('on the command line "Run it." keeps its meaning (%s)' % st[:40],
                  o['type'] == 'PLAN' and ops(o)[0] == want and 'run tab' not in o['pattern'], (o['type'], ops(o)))
            fx.remove_project(ctx.root)

        ctx = state(TAB_DYN)
        core.edit(ctx.project, [('/main/DER_0', 1e-4)])           # an edit in the Config view since the last run
        o = handle(ctx, 'Run the command.')
        check('after an edit in the Config view, the Run tab runs the working config as it is',
              o['type'] == 'PLAN' and 'set_param' not in ops(o) and any('config view' in a for a in o['announce']),
              (o['type'], ops(o), o['announce'][:1]))
        fx.remove_project(ctx.root)

        ctx = state(BASE)
        o = handle(ctx, 'Re-run last config and channel.', None)
        check('RT06: the last config and channel files are the last run: a STOP, nothing changed',
              o['type'] == 'STOP' and 'nothing changed' in o['reason'], o.get('reason'))
        core.edit(ctx.project, [('/main/DER_0', 1e-4)])
        o = handle(ctx, 'Re-run the last config and channels', None)
        check('after an edit, the last config and channel files run with the working config as it is',
              o['type'] == 'PLAN' and ops(o) == ['validate_inputs', 'validate_config', 'run_com', 'summarize'],
              (o['type'], ops(o)))
        fx.remove_project(ctx.root)
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.build('project folder with no history', ctx)
        o = handle(ctx, 'Re-run last config and channel.', None)
        check('with no run yet the last config and channels ask, as a re-run does', o['type'] == 'QUESTION',
              o['type'])
        fx.remove_project(ctx.root)

        # ------------------------------------------------------------ reuse: the options in the fingerprint
        f = {'param.x': 1.0}
        plain, mat = core._fingerprint(f, ['a'], 's'), core._fingerprint(f, ['a'], 's', True)
        eye, both = core._fingerprint(f, ['a'], 's', False, True), core._fingerprint(f, ['a'], 's', True, True)
        check('--eye-under-mlse is part of what decides reuse: only the same setting serves; the export still serves a '
              'run without it',
              core._same_fingerprint(mat, plain) and not core._same_fingerprint(plain, mat)
              and not core._same_fingerprint(eye, plain) and not core._same_fingerprint(plain, eye)
              and core._same_fingerprint(both, eye) and core._same_fingerprint(eye, eye)
              and run.fingerprint_hash(plain) != run.fingerprint_hash(eye)
              and run.fingerprint_hash(plain) == run.fingerprint_hash(core._fingerprint(f, ['a'], 's', False, False)))

        # ------------------------------------------------------------ run, with the stand-in child
        argv = Argv()
        try:
            ctx = state(TAB_DYN)
            o = handle(ctx, 'Run the command.')
            tab = run.run_tab_setup(ctx.project, o)
            done = run.carry_out(ctx.project, o, child=STANDIN)
            got = argv.runs()
            res = ctx.project.read_result('run_0002')
            check('Output dynamic results is --export-mat for the child, and the result says so',
                  done['status'] == 'ok' and got and '--export-mat' in got[-1] and '--eye-under-mlse' not in got[-1]
                  and res['export_mat'] is True and not res['eye_under_mlse'], (done['status'], got[-1:]))
            shown = tab['command'].split(' ')[3:]
            ran = [os.path.relpath(a, ctx.root) if os.path.isabs(a) and core.inside_folder(a, ctx.root) else a
                   for a in got[-1]]
            ran = [a for i, a in enumerate(ran) if a not in ('--fingerprint', '--note')
                   and (i == 0 or ran[i - 1] not in ('--fingerprint', '--note'))]
            check('the command the Run tab shows is the command that ran (without its bookkeeping arguments)',
                  tab['run_id'] == 'run_0002' and shown == ran and tab['options']['export_mat'] is True
                  and 'not the workbook' in tab['note'] and tab['thru'].endswith('thru.s4p'),
                  (tab['command'], ran))
            o = handle(ctx, 'Run the command.')
            check('the same Run tab again after that run: nothing changed', o['type'] == 'STOP', o['type'])
            fx.remove_project(ctx.root)

            ctx = state(TAB_EYE)
            o = handle(ctx, 'Run the command.')
            run.carry_out(ctx.project, o, child=STANDIN)
            got = argv.runs()
            res = ctx.project.read_result('run_0002')
            check('--eye-under-mlse is passed to the child, and the result says so',
                  '--eye-under-mlse' in got[-1] and res['eye_under_mlse'] is True, got[-1:])
            o = handle(ctx, 'Run the command.', dict(ctx.selection, options={}))
            n = len(argv.runs())
            done = run.carry_out(ctx.project, o, child=STANDIN)
            check('the run without --eye-under-mlse after one with it reuses the earlier run without it, never the eye '
                  'run', o['type'] == 'PLAN' and len(argv.runs()) == n and done['run_ids'] == ['run_0001'],
                  (o['type'], done.get('run_ids')))
            fx.remove_project(ctx.root)
        finally:
            argv.close()

        # the run child sets the engine's EYE_PLOT_UNDER_MLSE, as sicopr.py --eye-under-mlse does
        from sicopr_assist import engine, run_case
        seen = {}

        class Fake:
            EYE_PLOT_UNDER_MLSE = False
            COM_MATLAB_VERSION = '4p17p0'

            @staticmethod
            def _run_com(cfg, nf, nn, files, export_mat=False):
                seen['eye'], seen['mat'] = Fake.EYE_PLOT_UNDER_MLSE, export_mat
                return None

        d = tempfile.mkdtemp()
        thru = os.path.join(d, 't.s4p')
        with open(thru, 'w') as fh:
            fh.write('! t\n')
        real = engine.module
        engine.module = lambda: Fake
        try:
            with open(os.devnull, 'w') as null:
                old = sys.stderr
                sys.stderr = null
                try:
                    run_case.main([os.path.join(d, 'c.csv'), os.path.join(d, 'r.json'), '--thru', thru,
                                   '--eye-under-mlse'])
                finally:
                    sys.stderr = old
            rec = json.load(io.open(os.path.join(d, 'r.json'), encoding='utf-8'))
        finally:
            engine.module = real
        check('run_case.py --eye-under-mlse sets the engine\'s EYE_PLOT_UNDER_MLSE before COM runs, and records it',
              seen.get('eye') is True and rec['eye_under_mlse'] is True, (seen, rec.get('eye_under_mlse')))

        # the dashboard of a run named by its id
        argv = Argv()
        try:
            ctx = state(BASE)
            prior_states.second_thru(ctx)
            o = handle(ctx, 'Re-run with data\\thru2.s4p.', None)
            run.carry_out(ctx.project, o, child=STANDIN)
            o = handle(ctx, 'Show the dynamic results of run_0001.', None)
            check('the dynamic results of an earlier run named by its id are its dashboard',
                  o['type'] == 'PLAN' and ops(o) == ['export_mat', 'render_dashboard', 'open_report']
                  and step(o, 'export_mat')['run'] == 'run_0001', (o['type'], ops(o)))
            done = run.carry_out(ctx.project, o, child=STANDIN, rscript=fixtures.STANDIN_RSCRIPT,
                                 open_page=lambda p: None)
            got = argv.runs()
            check('that dashboard re-runs run_0001 on its own THRU with the export',
                  got and '--export-mat' in got[-1] and got[-1][got[-1].index('--thru') + 1].endswith('thru.s4p'),
                  got[-1:])
            o = handle(ctx, 'Show the dynamic results of run_0009.', None)
            o2 = handle(ctx, 'Show the dynamic results of run_0001 and run_0002.', None)
            check('a run id that is not a run stops, and two ask', o['type'] == 'STOP' and o2['type'] == 'QUESTION',
                  (o['type'], o2['type']))
            last = core.Context(ctx.project).last_run_id()
            check('the phrase of a run\'s dynamic results names the last run as such, and another by its id',
                  core.dynamic_phrase(ctx.project, last) == 'Show the dynamic results of the last run.'
                  and core.dynamic_phrase(ctx.project, 'run_0001') == 'Show the dynamic results of run_0001.')
            fx.remove_project(ctx.root)
        finally:
            argv.close()

        # ------------------------------------------------------------ the panel API
        ctx = state(TAB_DYN)
        p, host = api.Panel(root=ctx.root, child=STANDIN), Host([ctx.root])
        code, r = call(p, 'POST', 'handle', {'phrase': 'Run the command.', 'selection': ctx.selection}, host)
        tab = r.get('run_tab') or {}
        check('POST handle gives the Run tab\'s setup with a PLAN that runs COM (sicopr:set-run)',
              r['outcome']['type'] == 'PLAN' and tab.get('run_id') == 'run_0002' and '--export-mat' in tab['command']
              and tab['options'] == {'export_mat': True, 'eye_under_mlse': False}
              and set(tab) >= {'config', 'thru', 'fext', 'next', 'options', 'command', 'note'}, tab)
        st = wait(p)
        rid = ((st.get('done') or {}).get('run_ids') or [None])[-1]
        res = api.result(Project(ctx.root), rid)
        check('the export run from the panel has the .mat export, and its result says so',
              rid == 'run_0002' and res['export_mat'] is True
              and res['dynamic_phrase'] == 'Show the dynamic results of the last run.', (rid, res.get('export_mat')))
        check('a run without the export says so', api.result(Project(ctx.root), 'run_0001')['export_mat'] is False)
        code, prev = call(p, 'POST', 'runtab', {'selection': dict(ctx.selection, options={'eye_under_mlse': True})},
                          host)
        code, none = call(p, 'POST', 'runtab', {'selection': dict(ctx.selection, thru=None)}, host)
        check('POST runtab gives the command for the files and options in the Run tab now',
              '--eye-under-mlse' in prev['command'] and '--export-mat' not in prev['command']
              and prev['run_id'] == 'run_0003' and none == {'command': None}, (prev.get('command'), none))
        code, s1 = call(p, 'POST', 'selection', {'selection': ctx.selection}, host)
        code, s2 = call(p, 'POST', 'selection', {'selection': dict(ctx.selection, options={
            'export_mat': True, 'eye_under_mlse': True})}, host)
        code, s3 = call(p, 'POST', 'selection', {'selection': dict(ctx.selection, options={'export_mat': 'true'})},
                        host)
        check('the selection line names the options that are on, and only a true one is on',
              s1['line'].endswith('; Output dynamic results')
              and s2['line'].endswith('; Output dynamic results, --eye-under-mlse')
              and 'Output' not in s3['line'] and s3['selection']['options']['export_mat'] is False, (s1['line'],
                                                                                                    s2['line']))
        code, r = call(p, 'POST', 'handle', {'phrase': 'What can I change?', 'selection': ctx.selection}, host)
        check('an outcome that runs nothing gives no Run tab setup', not r.get('run_tab'), r.get('run_tab'))
        fx.remove_project(ctx.root)
    finish()


if __name__ == '__main__':
    main()

"""The dashboard (version 2, Phase V2-2; rows D1 to D3, CB17, C2; gates V2.2 and V2.3).

    python tests\\test_dashboard.py
    $env:SICOPR_ASSIST_E2E = "1"; python tests\\test_dashboard.py      also gate V2.3: real COM runs and real Rscript

Finding Rscript: on PATH, else the newest R under Program Files, newest by number (R-4.10 beats R-4.9). These checks
build a stand-in Program Files folder, so they run on any machine, R or not.

V2.2: with a stand-in child (tests/cases/standin_child.py) and a stand-in Rscript (tests/cases/standin_rscript.py),
a dashboard plan carries out in order: export_mat re-runs the last working config with --export-mat (or reuses a
run that had it, and only such a run), Rscript runs SiCoPR's R/com_analysis.R on the .mat with the run folder as its
working folder, the page and its lib folder land beside the .mat, the page path is announced and handed to the
opener. With Rscript hidden (from PATH and from Program Files), D3's STOP, and nothing runs.

V2.3 (SICOPR_ASSIST_E2E=1): the synthetic THRU run, then the dashboard phrase, through the real engine and the real
Rscript, writes the dashboard. No browser is opened.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
DASH = ('export_mat', 'render_dashboard', 'open_report')


class Env:
    """os.environ with some variables set, and put back on exit."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.values}
        os.environ.update(self.values)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def ops(o, tutor=False):
    return [s['op'] for s in o['steps'] if tutor or s['op'] != 'show_tutor']


# ----------------------------------------------------------------------------- finding Rscript
def finder():
    from sicopr_assist import engine
    check('R versions compare as numbers: R-4.10.0 is newer than R-4.9.3, which text order gets wrong',
          engine.r_version(os.path.join('R', 'R-4.10.0', 'bin', 'Rscript.exe')) == (4, 10, 0)
          and engine.r_version(os.path.join('R', 'R-4.10.0', 'bin')) > engine.r_version(os.path.join('R', 'R-4.9.3'))
          and sorted(['R-4.10.0', 'R-4.9.3'])[-1] == 'R-4.9.3' and engine.r_version('Rscript') == ())
    base = tempfile.mkdtemp(prefix='sicopr_assist_r_')
    try:
        pf = os.path.join(base, 'Program Files')
        for v, sub in (('4.4.1', ('bin',)), ('4.9.3', ('bin',)), ('4.10.0', ('bin',)), ('4.10.0', ('bin', 'x64')),
                       ('4.2.0', ('bin', 'x64'))):
            d = os.path.join(pf, 'R', 'R-' + v, *sub)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, 'Rscript.exe'), 'w').close()
        on_path = os.path.join(base, 'on_path')
        os.makedirs(on_path)
        for n in ('Rscript', 'Rscript.exe'):
            open(os.path.join(on_path, n), 'w').close()
            os.chmod(os.path.join(on_path, n), 0o755)
        empty = os.path.join(base, 'empty')
        os.makedirs(empty)
        keep = os.pathsep.join(d for d in os.environ.get('PATH', '').split(os.pathsep)
                               if d and not any(os.path.exists(os.path.join(d, n)) for n in ('Rscript', 'Rscript.exe')))
        newest = os.path.join(pf, 'R', 'R-4.10.0', 'bin', 'Rscript.exe')
        with Env(PATH=keep, ProgramFiles=pf):
            got = engine.find_rscript()
        check('not on PATH: the newest R under Program Files by number, its bin before bin\\x64 (R-4.10.0)',
              got == newest, got)
        with Env(PATH=on_path + os.pathsep + keep, ProgramFiles=pf):
            got = engine.find_rscript()
        check('an Rscript on PATH is taken first, as SiCoPR\'s gui/app.py does',
              got is not None and os.path.dirname(got) == on_path, got)
        with Env(PATH=keep, ProgramFiles=empty):
            got = engine.find_rscript()
        check('hidden from PATH and from Program Files: no Rscript', got is None, got)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    script = engine.com_analysis_script()
    check('SiCoPR\'s R/com_analysis.R is found through engine.py', script is not None and os.path.isfile(script)
          and os.path.dirname(os.path.dirname(script)) == engine.folder(), script)


# ----------------------------------------------------------------------------- the core
def core_checks(fx):
    import prior_states
    from sicopr_assist import core, engine
    from sicopr_assist.project import Project
    with Env(**fx.r_env()):
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.r1_complete(ctx)
        o = core.handle(core.DASHBOARD_PHRASE, Project(ctx.root))
        check('D1: export_mat > render_dashboard > open_report, announced as a re-run with the .mat export on',
              o['type'] == 'PLAN' and ops(o) == list(DASH) and any(
                  l.startswith('export_mat re-runs the working config of the last run (run_0001)') and 'full COM run'
                  in l for l in o['announce']) and any('com_analysis.R' in l for l in o['announce']), o['announce'])
        fx.remove_project(ctx.root)
    with Env(**fx.r_env(found=False)):
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.r1_complete(ctx)
        rid = 'run_0001'
        case = os.path.join(Project(ctx.root).run_dir(rid), 'case_01')
        os.makedirs(case)
        open(os.path.join(case, 'results.csv'), 'w').close()
        o = core.handle(core.DASHBOARD_PHRASE, Project(ctx.root))
        want = os.path.join('.sicopr', 'runs', rid, 'case_01', 'results.csv')
        check('D3: with Rscript hidden from PATH and from Program Files, a STOP that says R is missing and names the '
              'CSV summary', engine.find_rscript() is None and o['type'] == 'STOP' and 'Rscript was not found'
              in o['reason'] and want in o['reason'] and not o['steps'], o.get('reason'))
        o = core.handle('Re-run with DER_0 = 1e-4 and show the dashboard.', Project(ctx.root))
        check('CB17 with Rscript hidden: D3\'s STOP, with the change asked for and not applied', o['type'] == 'STOP'
              and 'Rscript was not found' in o['reason'] and [(c['json_path'], c['applied']) for c in o['changes']]
              == [('/main/DER_0', False)], (o['type'], o.get('reason'), o['changes']))
        fx.remove_project(ctx.root)
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.build('R1 then D1 complete', ctx)
        o = core.handle('Re-run with z_p select = 2', Project(ctx.root))
        check('C2 with Rscript hidden: the re-run is planned without the dashboard, and says why',
              o['type'] == 'PLAN' and ops(o) == ['set_param', 'validate_config', 'run_com', 'summarize']
              and any('not built again' in l and 'Rscript was not found' in l for l in o['announce']), o['announce'])
        fx.remove_project(ctx.root)
    with Env(**fx.r_env()):
        ctx = prior_states.Ctx(fx, 'Case1')
        o = core.handle('Give me the results in a dynamic dashboard.', Project(ctx.root))
        q = o.get('question') or {}
        check('D2: no run yet asks, with the two options of the row', o['type'] == 'QUESTION' and q.get('options') ==
              ['run the example setup then build the dashboard', 'point to an existing results file'], q)
        a = core.handle('1', Project(ctx.root))
        check('D2: the first option names a phrase, and that phrase plans the example run and then the dashboard',
              a['type'] == 'STOP' and 'Run SiCoPR on the example setup and show the dashboard.' in a['reason'], a)
        b = core.handle('Run SiCoPR on the example setup and show the dashboard.', Project(ctx.root))
        check('  ... import_config > validate_inputs > run_com (with the .mat export) > summarize > the dashboard',
              b['type'] == 'PLAN' and ops(b) == ['import_config', 'validate_inputs', 'run_com', 'summarize'] + list(DASH)
              and [s['args'].get('export_mat') for s in b['steps'] if s['op'] == 'run_com'] == [True],
              (b['type'], ops(b), b.get('reason') or b.get('question')))
        fx.remove_project(ctx.root)
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.build('run complete with the starting config and data\\thru.s4p', ctx)
        o = core.handle('Re-run with DER_0 = 1e-4 and show the dashboard.', Project(ctx.root))
        run_com = [s['args'] for s in o['steps'] if s['op'] == 'run_com']
        check('CB17: run_com runs with the .mat export on, and export_mat takes that run (COM does not run twice)',
              o['type'] == 'PLAN' and run_com and run_com[0].get('export_mat') is True and any(
                  'COM does not run twice' in l for l in o['announce']), (run_com, o['announce']))
        for ph in ('open the report', 'plot the results', 'show me a dashboard'):
            o = core.handle(ph, Project(ctx.root))
            check('the paraphrase %r plans the dashboard' % ph, o['type'] == 'PLAN' and ops(o) == list(DASH),
                  (o['type'], ops(o), o.get('reason') or o.get('question')))
        o = core.handle('Show the dashboard of COM in purple.', Project(ctx.root))
        check('strict mode: a word the dashboard request cannot place asks, and nothing runs',
              o['type'] == 'QUESTION' and 'purple' in o['unplaced'], (o['type'], o['unplaced']))
        fx.remove_project(ctx.root)


# ----------------------------------------------------------------------------- V2.2: carried out with stand-ins
def standin_runs(fx):
    import standin_rscript
    from sicopr_assist import cli, core, engine
    from sicopr_assist.project import Project
    argv_child = os.path.join(fx.base, 'child_argv.jsonl')
    argv_r = os.path.join(fx.base, 'r_argv.jsonl')
    opened = []

    def opener(path):
        opened.append(path)
        return None

    def child_calls():
        if not os.path.exists(argv_child):
            return []
        with open(argv_child, encoding='utf-8') as f:
            return [json.loads(x) for x in f]

    def r_calls():
        if not os.path.exists(argv_r):
            return []
        with open(argv_r, encoding='utf-8') as f:
            return [json.loads(x) for x in f]

    def say(p, phrase):
        buf = io.StringIO()
        o, done = cli.handle_and_run(phrase, p, out=buf, child=STANDIN, rscript=fixtures.STANDIN_RSCRIPT,
                                     open_page=opener)
        return o, done, buf.getvalue().splitlines()

    with Env(SICOPR_ASSIST_STANDIN_ARGV=argv_child, SICOPR_ASSIST_STANDIN_R_ARGV=argv_r, **fx.r_env()):
        p = Project(fx.project('Case1'))
        say(p, r'Run COM on data\thru.s4p with data\config.xlsx')
        n_child = len(child_calls())
        o, done, printed = say(p, core.DASHBOARD_PHRASE)
        steps = ops(o, tutor=True)
        at = [next((i for i, x in enumerate(printed) if x.startswith('step %d of %d: %s' % (k + 1, len(steps), op))),
                   None) for k, op in enumerate(steps)]
        check('V2.2: a status line for each step, in the order of the plan (%s)' % ' > '.join(steps),
              steps[:3] == list(DASH) and None not in at and at == sorted(at), printed)
        calls = child_calls()[n_child:]
        check('V2.2: export_mat is a new run (run_0002) of the last working config with --export-mat, and a run '
              'without the .mat is not reused for it', done['run_ids'] == ['run_0002'] and len(calls) == 1
              and '--export-mat' in calls[0] and p.read_result('run_0002').get('export_mat') is True,
              (done['run_ids'], calls))
        a = p.read_working_config('run_0001')
        b = p.read_working_config('run_0002')
        key = next(k for k in a['main'] if k.strip().lower() == 'result_dir')
        check('V2.2: the export run keeps the working config of the last run (only RESULT_DIR differs)',
              dict(a['main'], **{key: None}) == dict(b['main'], **{key: None}) and a['packages'] == b['packages'])
        folder = p.run_dir('run_0002')
        mat = os.path.join(folder, 'run_0002_case01.mat')
        page = os.path.join(folder, 'run_0002_case01_report.html')
        rc = r_calls()
        check('V2.2: Rscript ran SiCoPR\'s R/com_analysis.R on the .mat, with the run folder as its working folder '
              '(never SiCoPR\'s)', len(rc) == 1 and rc[0]['argv'] == [engine.com_analysis_script(), os.path.basename(mat)]
              and os.path.normcase(rc[0]['cwd']) == os.path.normcase(folder)
              and not os.path.normcase(rc[0]['cwd']).startswith(os.path.normcase(engine.folder())), rc)
        check('V2.2: the page and its lib folder are beside the .mat, in the run\'s own folder',
              os.path.isfile(mat) and os.path.isfile(page) and os.path.isdir(os.path.join(folder, 'lib')),
              os.listdir(folder))
        shown = 'dashboard: %s' % p.relative(page)
        check('V2.2: the page path is announced, printed and handed to the opener',
              any(x.startswith(shown) for x in done['lines']) and any(x.startswith(shown) for x in printed)
              and opened == [page], (done['lines'], opened))
        r_lines = [x for x in printed if x.strip() in standin_rscript.LINES]
        check('Decision 17: the R step has its status lines, and Rscript\'s own lines are passed on indented',
              any(re.match(r'step 2 of \d+: render_dashboard: Rscript com_analysis.R run_0002_case01.mat', x)
                  for x in printed)
              and any(re.match(r'step 2 of \d+: render_dashboard: written in \d+ s: ', x) for x in printed)
              and len(r_lines) == len(standin_rscript.LINES) and all(x.startswith('    ') for x in r_lines), printed)
        with open(os.path.join(folder, 'run.log'), encoding='utf-8') as f:
            log = f.read()
        check('Decision 17: run.log of the export run holds the R step lines too',
              'render_dashboard: written in' in log and standin_rscript.LINES[0] in log, log[-400:])
        rec = p.read_history()[-1]
        check('the history record names the export run and its working config',
              rec['run_ids'] == ['run_0002'] and rec['working_config'].endswith('run_0002.json')
              and rec['status'] == 'ok', (rec['run_ids'], rec['working_config'], rec['status']))

        # again: the run with the .mat is reused, the page is built again
        n_child, opened[:] = len(child_calls()), []
        o, done, printed = say(p, core.DASHBOARD_PHRASE)
        check('the dashboard asked for again reuses the run that has the .mat: no new run, announced as such',
              len(child_calls()) == n_child and done['run_ids'] == ['run_0002'] and p.run_numbers() == [1, 2]
              and any('run_0002 was run with the .mat export on' in l for l in o['announce'])
              and opened == [page], (done['run_ids'], o['announce'][:1]))
        # the export flag in the fingerprint: a run with the .mat serves a plain run (its results are the same), and
        # a run without it never serves an export
        have = p.read_result('run_0002')
        fp = core._fingerprint({'param.x': 1.0}, ['a'], have.get('sicopr_sha256'))
        fp_mat = core._fingerprint({'param.x': 1.0}, ['a'], have.get('sicopr_sha256'), True)
        check('reuse: a run with the .mat export serves a run without it, never the other way round',
              core._same_fingerprint(fp_mat, fp) and core._same_fingerprint(fp_mat, fp_mat)
              and not core._same_fingerprint(fp, fp_mat) and core._same_fingerprint(fp, fp))

        # CB17: one run, with the .mat export, and the dashboard of that run
        n_child, opened[:] = len(child_calls()), []
        o, done, printed = say(p, 'Re-run with DER_0 = 1e-4 and show the dashboard.')
        calls = child_calls()[n_child:]
        check('CB17 carried out: COM runs once, with --export-mat, and export_mat reuses that run',
              o['type'] == 'PLAN' and len(calls) == 1 and '--export-mat' in calls[0] and done['run_ids'] == ['run_0003']
              and any(re.match(r'step 5 of \d+: export_mat: the inputs equal those of run_0003, which has the .mat '
                               r'export', x) for x in printed), (calls, done['run_ids'], printed))
        check('CB17 carried out: the dashboard of run_0003 is written and opened',
              opened == [os.path.join(p.run_dir('run_0003'), 'run_0003_case01_report.html')], opened)
        o = core.handle('Run it again.', p)
        check('a replay of that plan holds its dashboard steps once, and no others', o['type'] == 'PLAN'
              and ops(o) == ['set_param', 'validate_config', 'run_com', 'summarize'] + list(DASH), ops(o))
        # C2: a re-run right after a dashboard builds it again
        n_child, opened[:] = len(child_calls()), []
        o, done, printed = say(p, 'Re-run with DER_0 = 5e-5')
        check('C2 carried out: a re-run right after a dashboard runs once and builds the dashboard again',
              ops(o)[-3:] == list(DASH) and len(child_calls()) == n_child + 1 and len(opened) == 1, (ops(o), opened))

        # Rscript fails: no page, said, and nothing opened
        n_child, opened[:] = len(child_calls()), []
        with Env(SICOPR_ASSIST_STANDIN_R_FAIL='1'):
            o, done, printed = say(p, 'Re-run with DER_0 = 2e-5 and show the dashboard.')
        check('an Rscript that fails: the dashboard is said not to be built, the command fails, nothing is opened',
              done['status'] == 'failed' and any(x.startswith('the dashboard was not built: Rscript stopped with exit '
                                                              'code 1') for x in done['lines'])
              and not opened and p.read_history()[-1]['status'] == 'failed', (done['status'], done['lines'][-3:]))

    # D3 through the command line: Rscript hidden, a STOP, nothing runs
    with Env(SICOPR_ASSIST_STANDIN_ARGV=argv_child, **fx.r_env(found=False)):
        n_child, opened[:] = len(child_calls()), []
        runs = p.run_numbers()
        o, done, printed = say(p, core.DASHBOARD_PHRASE)
        check('V2.2: with Rscript hidden, D3\'s STOP, it names the CSV summary or the run folder, and nothing runs',
              o['type'] == 'STOP' and done is None and printed and printed[-1].startswith('STOP: The dashboard cannot '
                                                                                          'be built: Rscript was not found')
              and re.search(r'\.sicopr.runs.run_\d{4}', o['reason']) and p.run_numbers() == runs
              and len(child_calls()) == n_child and not opened, printed[-1:])


# ----------------------------------------------------------------------------- V2.3: end to end
def e2e(fx):
    if os.environ.get('SICOPR_ASSIST_E2E', '') != '1':
        print('SKIP: V2.3 end to end runs only with SICOPR_ASSIST_E2E=1 (two real COM runs and Rscript, about 10 '
              'minutes)')
        return
    from sicopr_assist import cli, core, engine
    from sicopr_assist.project import Project
    import test_run
    if engine.find_rscript() is None:
        print('SKIP: V2.3 needs Rscript (with R.matlab, plotly and htmltools); none was found')
        return
    p = Project(fx.project('Case1'))
    opened = []
    buf = io.StringIO()
    t0 = time.time()
    o1, d1 = cli.handle_and_run(test_run.G64_PHRASE, p, out=buf, quiet=True)
    took1 = time.time() - t0
    rid1 = d1['run_ids'][0] if d1 and d1['run_ids'] else None
    com1 = (p.read_result(rid1).get('cases') or [{}])[0].get('channel_operating_margin_dB') if rid1 else None
    check('V2.3: the synthetic THRU run completes (%s, COM %r dB, %.0f s)' % (rid1, com1, took1),
          isinstance(com1, float), d1 and d1['lines'][-3:])
    buf = io.StringIO()
    t0 = time.time()
    o2, d2 = cli.handle_and_run(core.DASHBOARD_PHRASE, p, out=buf, open_page=lambda path: opened.append(path))
    took2 = time.time() - t0
    printed = buf.getvalue().splitlines()
    rid2 = d2['run_ids'][0] if d2 and d2['run_ids'] else None
    res2 = p.read_result(rid2) if rid2 else {}
    com2 = (res2.get('cases') or [{}])[0].get('channel_operating_margin_dB')
    folder = p.run_dir(rid2) if rid2 else ''
    mats = sorted(n for n in os.listdir(folder) if n.endswith('.mat')) if rid2 else []
    page = os.path.join(folder, '%s_case01_report.html' % rid2) if rid2 else ''
    check('V2.3: the dashboard phrase re-runs the config with the .mat export (%s, COM %r dB, the same as %s) and '
          'writes the .mat in the run folder (%s)' % (rid2, com2, rid1, ', '.join(mats)),
          o2['type'] == 'PLAN' and rid2 and rid2 != rid1 and res2.get('export_mat') is True and com2 == com1
          and mats == ['%s_case01.mat' % rid2], (o2.get('reason'), d2 and d2['lines']))
    ok = os.path.isfile(page)
    text = open(page, encoding='utf-8', errors='replace').read() if ok else ''
    check('V2.3: the dashboard page is written beside the .mat with its lib folder, and opened (%s, %.1f MB, %.0f s)'
          % (p.relative(page) if rid2 else '-', os.path.getsize(page) / 1e6 if ok else 0, took2),
          ok and os.path.isdir(os.path.join(folder, 'lib')) and opened == [page], printed[-12:])
    widgets = len(re.findall(r'class="plotly html-widget', text))
    check('V2.3: the page holds the stage plots (%d plotly widgets) and the COM of the run (%.4f)' % (widgets, com2 or 0),
          widgets >= 10 and ('%.4f' % com2) in text if com2 else False, widgets)
    print('V2.3 RESULT: COM %r dB; dashboard %s (%d bytes); first run %.0f s, dashboard command %.0f s'
          % (com2, page, os.path.getsize(page) if ok else 0, took1, took2))
    print('V2.3 what the command line printed for the dashboard phrase (%d lines):' % len(printed))
    for line in printed:
        if not line.startswith('    ') or 'export-mat' in line:
            print('| ' + line)


def main():
    finder()
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks are absent or hidden; the dashboard plan checks need them')
        finish()
    with fixtures.Fixtures(variants=False) as fx:
        core_checks(fx)
        standin_runs(fx)
        e2e(fx)
    finish()


if __name__ == '__main__':
    main()

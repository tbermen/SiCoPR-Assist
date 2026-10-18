"""After the maintainer's third GUI session (18 October): GUI first (Decision 24), the panel's part on the server.

    python tests\\test_gui_first.py

A run carried out by the panel streams its lines to the Run tab's Output (the page sends them as sicopr:output; that
part is checked in tests\\test_gui_static.py and on the real page in the walk-through of gate V8.4). What the page is
given for it is checked here, through the panel's API with the stand-in child, so no COM runs:

running   while a plan runs, the job's status names the run under way in the one line the panel shows
          (run_0002 running: output in the Run tab), and for a batch its point; it says whether the plan runs
          anything (only then does its output go to the Run tab)
result    after a run, the headline result: COM of each case, pass or fail against COM Pass threshold
batch     a batch streams every point's lines in order, each headed with its point; its reply is a short table, one
          row per point, with the run and COM
history   the run record at the end holds the status lines of Decision 17 (the engine's own are in each run.log)

With the four starting workbooks absent it prints SKIP and exits 0.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
BASE = r'run complete with the starting config and data\thru.s4p'
THRU_ONLY = (r'run complete thru-only with the starting config and data\ch\b300_thru1.s4p; data\ch holds two THRUs, '
             r'b300_thru1.s4p and b500_thru1.s4p, each with three FEXT (b300_xtalk1_Fext.s4p to b300_xtalk3_Fext.s4p) '
             r'and four NEXT files (b300_xtalk4_Next.s4p to b300_xtalk7_Next.s4p) named after it')


class Host:
    def __init__(self, roots):
        self._roots = list(roots)

    def roots(self):
        return list(self._roots)

    def run_dir(self):
        return self._roots[0]

    def com_running(self):
        return False


def wait(panel, timeout=180):
    t0 = time.time()
    while panel.job is not None and panel.job.finished is None and time.time() - t0 < timeout:
        time.sleep(0.05)
    return panel.job.status(0) if panel.job is not None else {}


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent or '
              'hidden; the panel checks need them')
        return finish()
    import prior_states
    from sicopr_assist import summary
    from sicopr_assist.panel import api
    from sicopr_assist.project import Project

    with fixtures.Fixtures(variants=False) as fx:
        # ---- one run: the running line, the headline, the run record
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.build(BASE, ctx)
        os.environ.update(ctx.env)
        p, host, proj = api.Panel(root=ctx.root, child=STANDIN), Host([ctx.root]), Project(ctx.root)
        got = p.handle('POST', 'handle', {}, {'phrase': 'Re-run with DER_0 = 1e-4.'}, host)
        st = wait(p)
        check('running: the plan runs COM, so its output goes to the Run tab (runs)', got.get('job') and st.get('runs'),
              st.get('runs'))
        check('running: the one line names the run under way: run_0002 running: output in the Run tab',
              st.get('running_line') == 'run_0002 running: output in the Run tab', st.get('running_line'))
        res = p.handle('GET', 'result', {'run': 'run_0002'}, None, host)
        com = proj.read_result('run_0002')['cases'][0][summary.COM_FIELD]
        thr = res.get('threshold')
        want = 'run_0002: COM %s dB, %s (COM Pass threshold %s dB)' % (summary.fmt(com), 'pass' if com >= thr else
                                                                       'fail', summary.fmt(thr))
        check('result: the headline is COM, pass or fail against COM Pass threshold (%s)' % want,
              thr is not None and res.get('headline') == want, res.get('headline'))
        res2 = dict(res, threshold=com + 1.0)
        check('result: a COM under the threshold is a fail', api.headline(res2).endswith(
            ', fail (COM Pass threshold %s dB)' % summary.fmt(com + 1.0)), api.headline(res2))
        end = [r for r in proj.read_history(log=True) if r.get('kind') == 'run'][-1]
        statuses = [t for k, t in st.get('lines') or [] if k == 'status']
        check('history: the run record at the end holds the status lines (Decision 17), not the engine lines',
              (end.get('detail') or {}).get('event') == 'end' and end['detail'].get('lines') == statuses
              and any(t.endswith('run_0002 started') for t in statuses)
              and not any(t.startswith('stand-in:') for t in end['detail']['lines']), end.get('detail'))
        no_run = api.Panel(root=ctx.root, child=STANDIN)
        no_run.handle('POST', 'handle', {}, {'phrase': 'Tutor off.'}, host)
        st0 = wait(no_run)
        check('running: a plan that runs nothing does not send output to the Run tab (runs is false)',
              st0 and st0.get('runs') is False, st0.get('runs'))
        fx.remove_project(ctx.root)

        # ---- a batch: the thru-only case reused, the crosstalk case new, each point's lines headed with it
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.build(THRU_ONLY, ctx)
        os.environ.update(ctx.env)
        p, host = api.Panel(root=ctx.root, child=STANDIN), Host([ctx.root])
        got = p.handle('POST', 'handle', {}, {'phrase': 'Run thru-only and with xtalk and compare results.'}, host)
        st = wait(p)
        lines = [t for _, t in st.get('lines') or []]
        heads = [i for i, t in enumerate(lines) if re.search(r'run_batch: point \d of 2 \(', t)]
        first = [i for i, t in enumerate(lines) if 'point 1 of 2 (channel = b300_thru1.s4p, mode = thru_only)' in t]
        second = [i for i, t in enumerate(lines) if 'point 2 of 2 (channel = b300_thru1.s4p, mode = xtalk)' in t]
        engine = [i for i, t in enumerate(lines) if t.strip().startswith('stand-in:')]
        check('batch: every point streams in order, each headed with its point (1 of 2 thru-only, then 2 of 2 xtalk)',
              got.get('job') and first and second and max(first) < min(second) and heads == first + second, lines)
        check('batch: the new point\'s engine lines come after its head and its run starting',
              engine and second and min(engine) > min(second)
              and any(t.endswith('point 2 of 2 (channel = b300_thru1.s4p, mode = xtalk): run_0002 started')
                      for t in lines), lines)
        check('batch: the running line names the run under way and its point (the last to start: point 2 of 2)',
              st.get('running_line') == 'run_0002 (point 2 of 2) running: output in the Run tab', st.get('running_line'))
        b = p.handle('GET', 'batch', {'seq': st['seq']}, None, host)
        rows = b.get('rows') or []
        check('batch: the reply is a short table, one row per point: point, values, status, run, COM',
              [(r['point'], r['status'], r['run_id']) for r in rows] == [(1, 'reused', 'run_0001'), (2, 'new', 'run_0002')]
              and all(r['com'] and r['values'].startswith('channel = b300_thru1.s4p; mode = ') for r in rows), rows)
        done = st.get('done') or {}
        check('batch: the results are compared against the thru-only case',
              any(ln.startswith('differences in COM against the thru-only case (run_0001') for ln in done.get('lines') or []),
              done.get('lines'))
        fx.remove_project(ctx.root)
    finish()


if __name__ == '__main__':
    sys.exit(main())

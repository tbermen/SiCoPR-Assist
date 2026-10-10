"""The Assist panel's API (GUI_DESIGN.md section 11; gates V5.2, V5.3, V5.4).

    python tests\\test_gui_api.py
    python tests\\test_gui_api.py --skip-l4      leave out the frozen L4 list (minutes); for quick reruns only

Drives sicopr_assist.panel.api.Panel as SiCoPR's GUI does (handle(method, path, query, body, host)), with a stand-in
host and the stand-in child (tests\\cases\\standin_child.py), so no COM runs:

  the same answers   for the frozen L4 list, POST handle returns what core.handle returns, key for key (V5.3); and
                     a plan carried out by the panel gives the progress lines cli.handle_and_run prints
  the round trip     on the four starting configs: a Config-view edit is one history record and the next run's CSV
                     loads to it; f_b moves its links and the overlay tags them linked; an edit of f_z removes its
                     link; a [TX RX] half keeps the other half and the shape; a refused edit never reaches the
                     working config; the latest record wins and says which it replaced; an edit is validated as the
                     same value typed in a phrase is; the source workbook's SHA-256 never changes
  overlay keys       every key the overlay sends is a key of SiCoPR's own gui.app.config_payload (read only)
  runs and results   busy both ways; Stop leaves the record failed and no result; every run folder is in SiCoPR's
                     /api/results once the project folder is opened
  paths              anything outside the project folder and the opened roots is refused
  the history (7a)   each kind of interaction writes one record of its kind with origin gui; errors are recorded,
                     a repeated one once a minute; the feedback export masks the new fields (V5.4)
  following          another workbook opened in the Config view is followed (V5.4)

The checks that need SiCoPR's GUI with the panel slot (the real server routing to the panel) print SKIP when the
SiCoPR in use has no slot, as CI's SICOPR_REF does not yet; the rest need only SiCoPR's gui.app as it is.
With the four starting workbooks absent it prints SKIP and exits 0.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

RUN_COMPLETE = r'run complete with the starting config and data\thru.s4p'
STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
CASES = ('Case1', 'Case2', 'Case3', 'Case4')


class Host:
    """A stand-in for the host object SiCoPR's GUI hands a panel."""

    def __init__(self, roots, busy=False):
        self._roots = list(roots)
        self.busy = busy

    def roots(self):
        return list(self._roots)

    def run_dir(self):
        return self._roots[0] if self._roots else ''

    def com_running(self):
        return self.busy


def call(panel, method, path, body=None, host=None, query=None):
    got = panel.handle(method, path, query or {}, body, host)
    if isinstance(got, tuple):
        return got[0], json.loads(got[2])
    return 200, got


def wait(panel, timeout=180):
    t0 = time.time()
    while panel.job is not None and panel.job.finished is None and time.time() - t0 < timeout:
        time.sleep(0.1)
    if panel.job is None:                        # nothing was carried out: an empty status, so the checks fail
        return {'seq': None, 'running': False, 'lines': [], 'done': None, 'outcomes': [], 'pages': []}
    return panel.job.status(0)


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def kinds(project):
    return [(r.get('origin'), r.get('kind')) for r in project.read_history(log=True)]


def no_rd(fields):
    return {k: v for k, v in (fields or {}).items() if not k.endswith('RESULT_DIR')}


def same_fields(fx, a, b):
    return not fixtures.oracle().diff(no_rd(a), no_rd(b))


def normalise(obj, roots):
    """The outcome with every project folder written as <root>, so two copies of one prior state compare."""
    if isinstance(obj, dict):
        return {k: normalise(v, roots) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalise(v, roots) for v in obj]
    if isinstance(obj, str):
        for r in roots:
            for form in (r, r.replace('\\', '/'), r.replace('/', '\\')):
                obj = obj.replace(form, '<root>')
        # each prior state serves the stand-in tools page under its own path (tests\cases\standin_ieee.py)
        return re.sub(r'(http://127\.0\.0\.1:\d+/)s\d+/', r'\1s<n>/', obj)
    return obj


@contextlib.contextmanager
def env(values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; the panel checks need them')
        return finish()
    import prior_states
    from sicopr_assist import cli, config_model, core, engine, feedback, run
    from sicopr_assist.panel import api
    from sicopr_assist.project import Project

    slow_dir = tempfile.mkdtemp(prefix='sicopr_assist_slow_')
    slow = os.path.join(slow_dir, 'slow_child.py')
    with open(slow, 'w', encoding='utf-8') as f:     # a child that runs until it is stopped
        f.write('import sys, time\nprint("slow stand-in: started", flush=True)\ntime.sleep(60)\n')
    SLOW_CHILD = [sys.executable, slow]

    with fixtures.Fixtures() as fx:
        books = {lab: sha(fx.configs[lab]) for lab in CASES}

        def seeded(label):
            ctx = prior_states.Ctx(fx, label)
            prior_states.build(RUN_COMPLETE, ctx)
            return ctx

        def panel_on(ctx, child=STANDIN, **kw):
            return api.Panel(root=ctx.root, child=child, **kw), Host([ctx.root])

        # ------------------------------------------------------------ the same answers (V5.3)
        import l4
        import scoring
        rows = l4.load_table()
        frozen = scoring.read_frozen()
        by_key = {'%s|%s' % (r['id'], r['starting_config']): r for r in rows}
        sc = scoring.Scorer(fx, rows, core.handle)

        class NoRun(api.Panel):                  # the outcome is what is compared; carrying it out is checked below
            def start(self, p, seq, out):
                return None
        differ, compared, t0 = [], 0, time.time()
        skip_l4 = '--skip-l4' in sys.argv           # a quick run for Rule 7 mutations of the other checks; the
        for key in ([] if skip_l4 else frozen):      # default, and every gate, compares the whole frozen list
            row = by_key.get(key)
            if row is None or not scoring.applies(row):
                continue
            label = scoring.labels_of(row)[0]
            phrase = sc.phrase_of(row)
            a, b = sc.context(row, label), sc.context(row, label)
            # a row whose prior state holds a selection in the GUI's tabs (rows SL01 to SL05): the page posts it with
            # the phrase, and the panel hands it to the core as data (Decision 20)
            with env(a.env):
                want = core.handle(phrase, Project(a.root),
                                   **({'selection': a.selection} if a.selection is not None else {}))
            body = dict({'phrase': phrase}, **({'selection': b.selection} if b.selection is not None else {}))
            with env(b.env):
                code, got = call(NoRun(root=b.root), 'POST', 'handle', body, Host([b.root]))
            compared += 1
            if code != 200 or 'outcome' not in got or \
                    normalise(want, [a.root]) != normalise(got['outcome'], [b.root]):
                differ.append(row['id'])
                wa, wb = normalise(want, [a.root]), normalise(got.get('outcome') or {}, [b.root])
                print('V5.3 %s: keys that differ: %s' % (row['id'], {k: (str(wa.get(k))[:300], str(wb.get(k))[:300])
                                                                    for k in set(wa) | set(wb) if wa.get(k) != wb.get(k)}))
            fx.remove_project(a.root)
            fx.remove_project(b.root)
        print('compared %d frozen L4 rows through the panel in %.0f s' % (compared, time.time() - t0))
        if skip_l4:
            print('SKIP: V5.3 (the frozen L4 list through the panel) left out by --skip-l4')
        else:
            check('V5.3: for the frozen L4 list, POST handle returns what core.handle returns, key for key',
                  compared >= 600 and not differ, '%d compared, these differ: %s' % (compared, differ[:20]))

        # the progress lines of a plan carried out by the panel are the lines the command line prints
        a, b = seeded('Case1'), seeded('Case1')
        phrase = 'Re-run with DER_0 = 1e-4.'
        buf = io.StringIO()
        with env(a.env):
            out, done = cli.handle_and_run(phrase, Project(a.root), out=buf, child=STANDIN)
            shown = io.StringIO()
            cli.show(out, out=shown)
        printed = buf.getvalue().splitlines()
        progress = printed[len(shown.getvalue().splitlines()):len(printed) - len(done['lines'])]
        with env(b.env):
            p, host = panel_on(b)
            code, got = call(p, 'POST', 'handle', {'phrase': phrase}, host)
            st = wait(p)
        lines = [t for _, t in st['lines']]
        tame = lambda ls: [re.sub(r'\d+ (?:min \d+ )?s\b', '<t>', x) for x in ls]   # noqa: E731 - elapsed times
        check('the panel shows the progress lines cli.handle_and_run prints for the same plan, in order',
              got.get('job') and tame(lines) == tame(progress) and len(lines) >= 6,
              'panel %r\ncli %r' % (lines, progress))
        check('the panel carries out the plan the core recorded, and the run lands in the history',
              st['done'] and st['done']['status'] == 'ok' and Project(b.root).last_record(with_runs=True)['run_ids'],
              'job %r' % st.get('done'))

        # ------------------------------------------------------------ the round trip, on the four configs
        same_typed = {}
        for label in CASES:
            ctx = seeded(label)
            p, host = panel_on(ctx)
            proj = Project(ctx.root)
            n0 = len(proj.read_history(log=True))
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'DER_0', 'value': 0.0001}]}, host)
            hist = proj.read_history(log=True)
            rec = hist[-1]
            check('%s: a Config-view edit is one history record, kind edit, origin gui, with a working config' % label,
                  r['outcome']['type'] == 'PLAN' and len(hist) == n0 + 1 and rec['kind'] == 'edit'
                  and rec['origin'] == 'gui' and rec['working_config'] and r['clear'] == ['DER_0']
                  and rec['phrase'] == 'Set DER_0 = 0.0001.',
                  'outcome %s, %d new records, last %r' % (r['outcome']['type'], len(hist) - n0,
                                                           {k: rec.get(k) for k in ('kind', 'origin', 'phrase')}))
            check('%s: the edit record holds the keyword, the values before and after, and accepted' % label,
                  (rec['detail'] or {}).get('edits', [{}])[0].get('keyword') == 'DER_0'
                  and rec['detail']['edits'][0].get('before') == 0.0002
                  and rec['detail']['edits'][0].get('after') == 0.0001 and rec['detail']['edits'][0].get('accepted'),
                  'detail %r' % rec.get('detail'))
            # Re-run after the edit runs the edited config (GUI_DESIGN.md section 10), checked with the loader
            code, r = call(p, 'POST', 'handle', {'phrase': 'Re-run.'}, host)
            st = wait(p)
            rid = ((st['done'] or {}).get('run_ids') or [None])[-1]
            want = fx.load_working_config(prior_states.with_values(fx.working_config(label), {'DER_0': 0.0001}))
            have = fx.load_file(proj.run_csv_path(rid)) if rid else (None, 'no run')
            check('%s: Re-run. after the edit runs the edited config (the run CSV loads to DER_0 = 1e-4)' % label,
                  rid and not have[1] and not want[1] and same_fields(fx, have[0], want[0])
                  and any('config view since' in x for x in r['outcome']['announce']),
                  'run %s, load error %s, announce %r' % (rid, have[1], r['outcome'].get('announce')))
            # the latest record wins, and says which one it replaced
            code, r = call(p, 'POST', 'handle', {'phrase': 'Re-run with DER_0 = 5e-5.'}, host)
            wait(p)
            check('%s: a command that changes a keyword last edited in the view says so' % label,
                  any(x.startswith('DER_0:') and 'edited in the config view, #%s' % rec['seq'] in x
                      for x in r['outcome']['announce']), r['outcome']['announce'])
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'DER_0', 'value': 0.0003}]}, host)
            cmd = proj.last_record(with_runs=True)
            check('%s: an edit of a keyword a command set says which command it replaces, and wins' % label,
                  any('set by command #%s' % cmd['seq'] in x for x in r['outcome']['announce'])
                  and core.Context(proj).wc['main']['DER_0'] == 0.0003, r['outcome']['announce'])
            # f_b moves its links; the overlay tags them linked
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'f_b', 'value': 53.125}]}, host)
            moved = sorted(c['json_path'] for c in r['outcome']['changes'] if c['kind'] == 'linked')
            ov = api.overlay(proj, ['f_b', 'f_z', 'f_p1', 'f_p2', 'DER_0'])
            check('%s: an edit of f_b recomputes the linked keys, and the overlay tags them linked' % label,
                  '/main/f_z' in moved and '/main/f_p1' in moved and ov['cells'].get('f_z', {}).get('tag') == 'linked'
                  and ov['cells'].get('f_b', {}).get('tag', '').startswith('edited here #'),
                  'linked %s, overlay %r' % (moved, {k: v.get('tag') for k, v in ov['cells'].items()}))
            # f_z edited directly: its link is removed, and the overlay says so
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'f_z', 'value': 20}]}, host)
            wc = core.Context(proj).wc
            ov = api.overlay(proj, ['f_z'])
            check('%s: an edit of f_z removes its link, and the overlay names the link removed' % label,
                  r['outcome']['type'] == 'PLAN' and 'f_z' not in wc['links'] and wc['main']['f_z'] == 20
                  and 'link' in ov['cells'].get('f_z', {}).get('note', '') and 'removed' in ov['cells']['f_z']['note'],
                  'links %s, overlay %r' % (sorted(wc['links']), ov['cells'].get('f_z')))
            # a [TX RX] half keeps the other half and the shape
            pair_key = next((k for k in ('C_b', 'L_s', 'C_d') if api.split_tx_rx(wc['main'].get(k, '')) is not None
                             and k in wc['main']), None)
            before = wc['main'].get(pair_key)
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': '%s#tx' % pair_key, 'value': 2e-5}]}, host)
            after = core.Context(proj).wc['main'].get(pair_key)
            bp, ap = api.split_tx_rx(before), api.split_tx_rx(after) if after is not None else None
            check('%s: a #tx half of %s keeps the RX half and the shape of the value' % (label, pair_key),
                  r['outcome']['type'] == 'PLAN' and ap is not None and ap[1] == bp[1]
                  and float(ap[0]) == 2e-5 and str(after).strip().startswith('[') == str(before).strip().startswith('[')
                  and str(after).count(';') == str(before).count(';'),
                  '%s: %r -> %r (%s)' % (pair_key, before, after, r['outcome'].get('reason')))
            # a refused edit never reaches the working config
            last_wc = core.Context(proj).wc
            n0 = len(proj.read_history(log=True))
            edits_before = sorted(os.listdir(proj.configs_dir))
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'f_b', 'value': -5}]}, host)
            rec = proj.read_history(log=True)[-1]
            check('%s: a refused edit (f_b = -5) is a STOP that never reaches the working config' % label,
                  r['outcome']['type'] == 'STOP' and r['clear'] == [] and core.Context(proj).wc == last_wc
                  and sorted(os.listdir(proj.configs_dir)) == edits_before and rec['kind'] == 'edit'
                  and rec['status'] == 'stopped' and not rec['working_config']
                  and len(proj.read_history(log=True)) == n0 + 1
                  and rec['detail']['edits'][0]['accepted'] is False,
                  'outcome %s, record %r' % (r['outcome']['type'], {k: rec.get(k) for k in ('kind', 'status')}))
            # an edit is validated as the same value typed in a phrase is
            for name, value in (('DER_0', 1e-4), ('N_b', 0), ('f_b', -5), ('f_b', 'fast'), ('DER_0', 2)):
                x, y = seeded(label), seeded(label)
                typed = core.handle('Re-run with %s = %s.' % (name, value), Project(x.root))['type']
                viewed = core.edit(Project(y.root), [('/main/' + name, value)])['type']
                same_typed[(label, name, str(value))] = (typed, viewed)
                fx.remove_project(x.root)
                fx.remove_project(y.root)
            fx.remove_project(ctx.root)
        bad = {k: v for k, v in same_typed.items() if v[0] != v[1]}
        kinds_seen = {v[0] for v in same_typed.values()}
        check('an edit gives the outcome the same value typed in a phrase gives (ok, ask and stop, four configs)',
              not bad and kinds_seen == {'PLAN', 'QUESTION', 'STOP'}, 'differ: %r; types %r' % (bad, kinds_seen))

        # an edit that asks: the question is pending, and the button's answer finishes the edit
        ctx = seeded('Case1')
        p, host = panel_on(ctx)
        proj = Project(ctx.root)
        code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'N_b', 'value': 0}]}, host)
        q = r['outcome']
        pend = proj.read_pending()
        ov = api.overlay(proj, ['N_b', 'MLSE'])
        check('an edit that a rule asks about is a pending QUESTION, and the overlay shows the value as proposed',
              q['type'] == 'QUESTION' and pend and pend['outcome']['resume'].get('edit')
              and ov['cells'].get('N_b', {}).get('tag') == 'proposed', '%s, overlay %r' % (q['type'], ov['cells']))
        opt = next(o for o in q['question']['options'] if 'MLSE' in o)
        n0 = len(proj.read_history(log=True))
        code, r = call(p, 'POST', 'handle', {'phrase': opt}, host)
        rec = proj.read_history()[-1]
        wait(p)
        wc = core.Context(proj).wc
        ov = api.overlay(proj, ['N_b', 'MLSE'])
        check('an edit finished by an answer is tagged as an edit made here, not as a command',
              ov['cells'].get('N_b', {}).get('tag', '').startswith('edited here #')
              and ov['cells'].get('MLSE', {}).get('tag', '').startswith('edited here #'), ov['cells'])
        check('the answer by button finishes the edit: one answer record, the working config holds both values',
              r['outcome']['type'] == 'PLAN' and rec['kind'] == 'answer' and rec['answers'] == pend['seq']
              and rec['chosen'] == opt and rec['working_config'] and wc['main']['N_b'] == 0
              and wc['main']['MLSE'] == 0 and len(proj.read_history(log=True)) - n0 == 1
              and proj.read_pending() is None,
              'outcome %s, record %r, N_b %r MLSE %r' % (r['outcome']['type'], {k: rec.get(k) for k in
                                                         ('kind', 'answers', 'chosen')}, wc['main'].get('N_b'),
                                                         wc['main'].get('MLSE')))
        fx.remove_project(ctx.root)

        # ------------------------------------------------------------ overlay keys against SiCoPR's own payload
        sic = engine.folder()
        sys.path.insert(0, sic)
        sys.dont_write_bytecode = True
        with contextlib.redirect_stdout(io.StringIO()):
            from gui import app as sapp
        ctx = seeded('Case1')
        p, host = panel_on(ctx)
        proj = Project(ctx.root)
        src = os.path.join(ctx.root, 'data', 'config.xlsx')
        sapp.add_root(ctx.root)
        payload = sapp.config_payload(src)
        page_keys = [c['key'] for b in payload['blocks'] for c in b['cells']]
        pair_key = 'C_b' if 'C_b#rx' in page_keys else next(k[:-3] for k in page_keys if k.endswith('#tx'))
        for e in ({'key': 'DER_0', 'value': 0.0001}, {'key': pair_key + '#rx', 'value': 2.5e-5},
                  {'key': 'f_b', 'value': 53.125}):
            call(p, 'POST', 'edit', {'edits': [e]}, host)
        call(p, 'POST', 'handle', {'phrase': 'Re-run with COM Version = 4p16p0.'}, host)
        wait(p)
        ov = api.overlay(proj, page_keys)
        cells = ov['cells']
        stray = [k for k in cells if k not in page_keys and '/' not in k and 'not in the workbook' not in
                 cells[k]['tag']]
        check('every overlay key is a key of SiCoPR\'s config_payload (a [TX RX] value as its halves), or is marked '
              'not in the workbook', cells and not stray and pair_key + '#rx' in cells and 'DER_0' in cells
              and any('not in the workbook' in v['tag'] for v in cells.values()),
              'stray %s; cells %s' % (stray, sorted(cells)))
        check('the overlay keeps the workbook value in the note and SiCoPR keys for the linked values',
              cells['DER_0']['note'] == 'workbook 2e-4' and 'f_z' in cells and 'f_z' in page_keys,
              cells.get('DER_0'))

        # ------------------------------------------------------------ runs and results
        made = [rid for rec in proj.read_history() if rec.get('origin') == 'gui' for rid in rec.get('run_ids') or []]
        listed = [os.path.normcase(r['path']) for r in sapp.list_results()]
        check('every run folder the panel made is listed by SiCoPR\'s /api/results once the project folder is opened',
              made and all(os.path.normcase(proj.run_dir(rid)) in listed for rid in made), (made, listed[:6]))
        rid0 = made[0]
        res = proj.read_result(rid0)
        res['cases'][0]['ERL'] = float('inf')         # as a real run gives when ERL is not computed
        res['cases'][0]['FOM'] = float('nan')
        proj.write_result(rid0, res)
        code, r = call(p, 'GET', 'result', None, host, {'run': rid0})
        try:
            json.dumps(r, allow_nan=False)
            strict_ok = True
        except ValueError:
            strict_ok = False
        check('a result with inf and nan is answered as strict JSON, which a browser can read',
              code == 200 and strict_ok and r['cases'][0]['ERL'] == 'inf' and r['lines'], r.get('cases', [{}])[0].get('ERL'))
        code, r = call(p, 'POST', 'handle', {'phrase': 'Re-run with DER_0 = 7e-5.'}, Host([ctx.root], busy=True))
        rec = proj.last_record()
        check('a plan with runs is refused while the Run tab runs COM, and its record ends failed',
              r.get('refused') and not r['job'] and rec['status'] == 'failed' and 'Run tab' in (rec['reason'] or ''),
              r)
        p2, host2 = panel_on(ctx, child=SLOW_CHILD)
        code, r = call(p2, 'POST', 'handle', {'phrase': 'Re-run with DER_0 = 6e-5.'}, host2)
        time.sleep(1.5)
        busy = p2.busy()
        code, ov = call(p2, 'POST', 'overlay', {'keys': page_keys}, host2)
        check('while a plan runs, the overlay already shows its change, tagged with its command, before the run ends',
              ov['cells'].get('DER_0', {}).get('value') == 6e-05
              and ov['cells']['DER_0'].get('tag') == 'Assist #%s' % r['seq'], ov['cells'].get('DER_0'))
        code, r2 = call(p2, 'POST', 'handle', {'phrase': 'Re-run.'}, host2)
        check('while a plan with runs is carried out, the panel is busy (SiCoPR refuses a Run-tab run) and takes no '
              'new command', busy == api.BUSY and 'error' in r2, '%r %r' % (busy, r2))
        code, s = call(p2, 'POST', 'stop', {}, host2)
        st = wait(p2, 30)
        rec = next(x for x in proj.read_history() if x['seq'] == st['seq'])
        rid = rec['run_ids'][-1] if rec['run_ids'] else None
        res = proj.read_result(rid) if rid else {}
        logs = [x for x in proj.read_history(log=True) if x.get('kind') in ('stop', 'run')]
        check('Stop terminates the run: the record ends failed, the result is failed, and a stop record says what '
              'was running', s['stopped'] and not st['running'] and rec['status'] == 'failed'
              and run.STOPPED in (rec['reason'] or '') and res.get('status') == 'failed'
              and any(x['kind'] == 'stop' and x['detail']['command'] == st['seq'] for x in logs)
              and p2.busy() is None,
              'record %r, result %r' % ({k: rec.get(k) for k in ('status', 'reason', 'run_ids')}, res.get('status')))
        check('a stopped run is never reused: the same command runs again', not any(
            rid2 == rid for rid2, _ in core.Context(proj).runs), core.Context(proj).runs)

        # ------------------------------------------------------------ the selection in the tabs (Decision 20)
        def selected(c, thru=None, fext=(), nxt=(), config='config.xlsx'):
            full = lambda n: os.path.join(c.root, 'data', n).replace(os.sep, '/')   # noqa: E731 - as the page holds them
            return {'config': full(config) if config else None, 'thru': full(thru) if thru else None,
                    'fext': [full(n) for n in fext], 'next': [full(n) for n in nxt]}
        sctx = prior_states.Ctx(fx, 'Case1')
        prior_states.xtalk_folder(sctx)
        sp, shost = api.Panel(root=sctx.root, child=STANDIN), Host([sctx.root])
        xt = [os.path.join('ch', n) for n in prior_states.XT_FEXT], [os.path.join('ch', n) for n in prior_states.XT_NEXT]
        shown = []
        for sel in (selected(sctx), selected(sctx, 'thru.s4p'),
                    selected(sctx, os.path.join('ch', 'b300_thru1.s4p'), xt[0], xt[1]), selected(sctx, config=None)):
            code, r = call(sp, 'POST', 'selection', {'selection': sel}, shost)
            shown.append(r.get('line'))
        check('the selection line follows the config and the channel files: Selected: <config>; THRU <file>; 3 FEXT, '
              '4 NEXT', shown == ['Selected: config.xlsx; ' + api.NO_CHANNEL, 'Selected: config.xlsx; THRU thru.s4p',
                                  'Selected: config.xlsx; THRU b300_thru1.s4p; 3 FEXT, 4 NEXT',
                                  'Selected: no config; ' + api.NO_CHANNEL] and r.get('phrase') == core.RUN_SELECTION,
              shown)
        sel = selected(sctx, os.path.join('ch', 'b300_thru1.s4p'), xt[0], xt[1])
        other = prior_states.Ctx(fx, 'Case1')
        prior_states.xtalk_folder(other)
        with env(sctx.env):
            want = core.handle(api.RUN_SELECTION, Project(other.root), selection=selected(
                other, os.path.join('ch', 'b300_thru1.s4p'), xt[0], xt[1]))

            class Held(api.Panel):
                def start(self, p, seq, out):
                    return None
            code, got = call(Held(root=sctx.root), 'POST', 'handle', {'phrase': api.RUN_SELECTION, 'selection': sel}, shost)
        run_step = next((s['args'] for s in (got.get('outcome') or {}).get('steps') or [] if s['op'] == 'run_com'), {})
        check('the phrase of the Run selection button, posted with the selection, gives the plan with those files: the '
              'THRU, 3 FEXT and 4 NEXT, as the core plans them', got.get('outcome', {}).get('type') == 'PLAN'
              and normalise(got['outcome'], [sctx.root]) == normalise(want, [other.root])
              and run_step.get('roles') == ['thru'] + ['fext'] * 3 + ['next'] * 4
              and [os.path.basename(c) for c in run_step.get('channels') or []]
              == ['b300_thru1.s4p'] + prior_states.XT_FEXT + prior_states.XT_NEXT,
              (got.get('outcome', {}).get('type'), run_step))
        plans = []
        for phrase in ('Run the selected config and channel.', 'Run on the config and channels specified in the tabs.',
                       'Run the config and channel specified.'):
            c2 = prior_states.Ctx(fx, 'Case3')
            with env(c2.env):
                code, g = call(Held(root=c2.root), 'POST', 'handle',
                               {'phrase': phrase, 'selection': selected(c2, 'thru.s4p')}, Host([c2.root]))
            o = g.get('outcome') or {}
            plans.append((o.get('type'), [(s['op'], json.dumps(s.get('args'), sort_keys=True)) for s in
                                          o.get('steps') or [] if s['op'] != 'show_tutor']))
        check('through the panel, the maintainer\'s two phrases give the plan of row SL01 on the selected files',
              plans[0][0] == 'PLAN' and [op for op, _ in plans[0][1]] == ['import_config', 'validate_inputs', 'run_com',
                                                                         'summarize']
              and plans[1] == plans[0] and plans[2] == plans[0], [(t, [op for op, _ in st]) for t, st in plans])
        # with no selection posted the core is handed none, as on the command line (row SL04)
        c3 = prior_states.Ctx(fx, 'Case1')
        with env(c3.env):
            code, g = call(Held(root=c3.root), 'POST', 'handle', {'phrase': api.RUN_SELECTION}, Host([c3.root]))
        check('a phrase posted without a selection is handed none: the question of row SL04',
              (g.get('outcome') or {}).get('type') == 'QUESTION'
              and g['outcome']['question']['options'] == [core.PROVIDE_FILES, core.CANCEL], g.get('outcome'))
        # a path from outside the opened directories never reaches the core
        away = tempfile.mkdtemp(prefix='sicopr_assist_away_')
        stray = os.path.join(away, 'thru.s4p')
        shutil.copyfile(fx.thru, stray)
        c4 = prior_states.Ctx(fx, 'Case1')
        bad_sel = dict(selected(c4), thru=stray, fext=[stray, os.path.join(c4.root, os.path.relpath(stray, c4.root))])
        code, r = call(api.Panel(root=c4.root), 'POST', 'selection', {'selection': bad_sel}, Host([c4.root]))
        with env(c4.env):
            code, g = call(Held(root=c4.root), 'POST', 'handle', {'phrase': api.RUN_SELECTION, 'selection': bad_sel},
                           Host([c4.root]))
        code, r2 = call(api.Panel(root=c4.root), 'POST', 'selection', {'selection': bad_sel}, Host([c4.root, away]))
        check('a selected file outside the project folder and the opened directories is left out and never reaches the '
              'core (the question of row SL03), and is taken once its directory is opened',
              r.get('selection') == {'config': os.path.abspath(selected(c4)['config']), 'thru': None, 'fext': [],
                                     'next': []}
              and (g.get('outcome') or {}).get('type') == 'QUESTION'
              and g['outcome']['question']['options'][0] == core.SELECT_IN_RUN_TAB
              and r2.get('selection', {}).get('thru') == os.path.abspath(stray) and len(r2['selection']['fext']) == 2,
              (r.get('selection'), (g.get('outcome') or {}).get('type'), r2.get('selection')))
        shutil.rmtree(away, ignore_errors=True)

        # the state the maintainer was in: a run, then something done in the Config view; his phrase runs the working
        # config as it is now on the channel selected in the Run tab
        mctx = seeded('Case1')
        prior_states.second_thru(mctx)
        with env(mctx.env):
            mp, mhost = panel_on(mctx)
            call(mp, 'POST', 'edit', {'edits': [{'key': 'DER_0', 'value': '5e-5'}]}, mhost)
            code, g = call(mp, 'POST', 'handle', {'phrase': 'Run on the config and channels specified in the tabs.',
                                                  'selection': selected(mctx, 'thru2.s4p')}, mhost)
            st = wait(mp)
        mproj = Project(mctx.root)
        mrec = mproj.last_record(with_runs=True)
        mrid = (mrec.get('run_ids') or [None])[-1]
        mf, _ = fx.load_csv_bytes(open(mproj.run_csv_path(mrid), 'rb').read()) if mrid else ({}, None)
        check('after an edit in the Config view, the maintainer\'s phrase runs the edited working config on the channel '
              'selected in the Run tab', (g.get('outcome') or {}).get('type') == 'PLAN' and g.get('job')
              and [s['op'] for s in g['outcome']['steps'] if s['op'] != 'show_tutor']
              == ['set_channel', 'validate_inputs', 'validate_config', 'run_com', 'summarize']
              and (st.get('done') or {}).get('status') == 'ok' and mrid != 'run_0001'
              and [os.path.basename(c['path']) for c in mrec.get('channels') or []] == ['thru2.s4p']
              and mproj.read_working_config(mrid)['main'].get('DER_0') == 5e-5 and bool(mf),
              ((g.get('outcome') or {}).get('type'), g.get('outcome', {}).get('question'), st.get('done'),
               mrec.get('channels')))

        # ------------------------------------------------------------ the examples under the command box (Decision 21)
        ectx = prior_states.Ctx(fx, 'Case1')
        with env(ectx.env):
            code, e0 = call(api.Panel(root=ectx.root), 'POST', 'examples', {'selection': selected(ectx)}, Host([ectx.root]))
        first_run = 'Run COM on %s with %s' % (os.path.join('data', 'thru.s4p'), os.path.join('data', 'config.xlsx'))
        check('with no run yet the examples start with what runs now: the files of the folder, and the example setup',
              (e0.get('phrases') or [])[:2] == [first_run, 'Run the example.']
              and len(e0['phrases']) <= api.MAX_EXAMPLES and not any('Re-run' in ph for ph in e0['phrases']), e0)
        ectx = seeded('Case1')
        with env(ectx.env):
            code, e1 = call(api.Panel(root=ectx.root), 'POST', 'examples', {'selection': selected(ectx)}, Host([ectx.root]))
            outs = []
            for ph in e1.get('phrases') or []:
                fresh = seeded('Case1')
                outs.append(core.handle(ph, Project(fresh.root))['type'])
        names = fx.working_config('Case1')['main']
        check('after a run there are four examples, written with names of the config in view, and each one sent to the '
              'core gives a PLAN (row TU04)', len(e1.get('phrases') or []) == api.MAX_EXAMPLES
              and outs == ['PLAN'] * api.MAX_EXAMPLES and any(k in ph for ph in e1['phrases'] for k in names)
              and 'Run the example.' not in e1['phrases'], (e1, outs))

        # ------------------------------------------------------------ paths
        outside = tempfile.mkdtemp(prefix='sicopr_assist_outside_')
        bait = os.path.join(outside, 'config.xlsx')
        shutil.copyfile(src, bait)
        refused = []
        for body in ({'path': outside}, {'path': os.path.join('..', '..')}, {'path': '..\\..'},
                     {'path': os.path.join(ctx.root, '..', os.path.basename(outside))}):
            code, r = call(p, 'POST', 'project', body, host)
            if 'error' not in r:
                refused.append(('project', body))
        for body in ({'path': bait}, {'path': os.path.relpath(bait, ctx.root)}):
            code, r = call(p, 'POST', 'open', body, host)
            if 'error' not in r:
                refused.append(('open', body))
        code, r = call(p, 'GET', 'result', None, host, {'run': '..\\run_0001'})
        if code == 200 and 'error' not in r:
            refused.append(('result', '..'))
        check('paths outside the project folder and the opened roots are refused (absolute, ..\\ and ../, a real '
              'folder and a real workbook outside)', not refused and os.path.isdir(outside), refused)
        check('the panel stays on its project after the refusals', p.root == ctx.root, p.root)
        code, r = call(p, 'POST', 'project', {'path': outside}, Host([ctx.root, outside]))
        check('a folder under an opened root is accepted as the project', r.get('project') == outside, r)
        p.root = ctx.root
        shutil.rmtree(outside, ignore_errors=True)

        # ------------------------------------------------------------ the history (section 7a)
        n = {k: sum(1 for x in kinds(proj) if x == ('gui', k)) for k in api_kinds()}
        call(p, 'POST', 'log', {'kind': 'view', 'what': 'run in Results, static', 'run': 'run_0002'}, host)
        call(p, 'POST', 'log', {'kind': 'error', 'where': 'script', 'message': 'TypeError: x is null',
                                'trace': 'panel.js:12'}, host)
        call(p, 'POST', 'log', {'kind': 'error', 'where': 'script', 'message': 'TypeError: x is null',
                                'trace': 'panel.js:12'}, host)
        code, r = call(p, 'GET', 'result', None, host, {'run': 'run_9999'})
        m = {k: sum(1 for x in kinds(proj) if x == ('gui', k)) for k in api_kinds()}
        errs = [x for x in proj.read_history(log=True) if x.get('kind') == 'error']
        check('a view record for a run shown, and one error record for a page script error repeated within a minute',
              m['view'] - n['view'] == 1 and sum(1 for e in errs if e['detail']['message'] == 'TypeError: x is null')
              == 1, '%r -> %r' % (n, m))
        check('a failing endpoint answers a JSON error and leaves an error record with the endpoint and the trace',
              code == 500 and 'error' in r and any(e['detail']['where'] == 'api GET result'
                                                  and 'Traceback' in e['detail']['trace'] for e in errs),
              '%s %r' % (code, r))
        every = proj.read_history(log=True)
        seen = {x.get('kind') for x in every if x.get('origin') == 'gui'}
        check('every kind of GUI record is in the history, each with origin gui',
              seen >= {'phrase', 'edit', 'run', 'stop', 'view', 'error'}, sorted(seen))
        runs = [x for x in every if x.get('kind') == 'run']
        check('a run record at the start and at the end of each plan carried out, the end with run ids, status and '
              'elapsed time', runs and all(x['detail']['event'] in ('start', 'end') for x in runs)
              and sum(1 for x in runs if x['detail']['event'] == 'start')
              == sum(1 for x in runs if x['detail']['event'] == 'end')
              and all('elapsed' in x['detail'] and 'status' in x['detail'] for x in runs
                      if x['detail']['event'] == 'end'), runs[-2:])
        check('the CLI and the core never see the log records: Context.history and history_lines leave them out',
              not any(x.get('kind') in ('run', 'stop', 'view', 'error') for x in core.Context(proj).history)
              and proj.read_history()[-1]['kind'] not in ('run', 'stop', 'view', 'error'), '')
        code, h = call(p, 'GET', 'history', None, host, {'limit': '1000'})
        check('GET history gives every kind, so the session can be shown again after a reload',
              {x.get('kind') for x in h['records']} >= seen and h['phrases'][0] == 'Re-run with DER_0 = 6e-5.',
              h['phrases'][:3])
        # the feedback export masks the new fields
        secret_path = os.path.join(ctx.root, 'MySecretFolder', 'secret_board.xlsx')
        api.log(proj, 'error', {'where': 'page', 'message': 'cannot read %s for BoardX9 at 7.25 GHz' % secret_path,
                                'trace': 'File "C:\\Users\\someone\\proj\\panel.py", line 42'})
        with open(proj.settings_path, 'a', encoding='utf-8') as f:
            f.write('\n[feedback]\nmask_names = on\nmask_numbers = on\n')
        text = '\n'.join(feedback.export_lines(proj))
        leaks = [w for w in ('MySecretFolder', 'secret_board', 'BoardX9', '7.25', 'someone', 'panel.py',
                             '0.0001', '6e-05') if w in text]
        check('the feedback export lists every record, view edits marked config view, and masks the new fields',
              not leaks and '(config view)' in text and 'GUI records' in text and '<file' in text,
              'in clear: %s' % leaks)
        fx.remove_project(ctx.root)

        # ------------------------------------------------------------ following another workbook (V5.4)
        for first, second in (('Case1', 'Case2'), ('Case3', 'Case4'), ('Case2', 'Case3'), ('Case4', 'Case1')):
            ctx = seeded(first)
            p, host = panel_on(ctx)
            proj = Project(ctx.root)
            other = os.path.join(ctx.root, 'data', 'other.xlsx')
            fixtures.link_or_copy(fx.configs[second], other)
            chans = proj.last_record(with_runs=True)['channels']
            n0 = len(proj.read_history(log=True))
            code, r = call(p, 'POST', 'open', {'path': other}, host)
            rec = proj.read_history(log=True)[-1]
            src, _ = api.source_of(proj)
            check('%s -> %s: opening another workbook in the Config view imports it, keeps the channel files, and '
                  'is one open record with both sources and their SHA-256' % (first, second),
                  r['outcome']['type'] == 'PLAN' and rec['kind'] == 'open' and rec['origin'] == 'gui'
                  and len(proj.read_history(log=True)) == n0 + 1 and rec['channels'] == chans
                  and rec['detail']['source_now']['sha256'] == books[second] and rec['detail']['source_was']['sha256']
                  and os.path.normcase(src) == os.path.normcase(other),
                  'outcome %s, record %r' % (r['outcome']['type'], {k: rec.get(k) for k in ('kind', 'detail')}))
            code, r = call(p, 'POST', 'handle', {'phrase': 'Re-run.'}, host)
            st = wait(p)
            rid = ((st['done'] or {}).get('run_ids') or [None])[-1]
            have = fx.load_file(proj.run_csv_path(rid)) if rid else (None, 'no run')
            want = fx.load_working_config(fx.working_config(second))
            check('%s -> %s: the next run\'s CSV loads to the fields of the workbook followed' % (first, second),
                  rid and not have[1] and same_fields(fx, have[0], want[0]), 'run %s: %s' % (rid, have[1]))
            fx.remove_project(ctx.root)

        # with overrides: asked once; both answers give the right working config
        for answer in ('keep', 'start'):
            ctx = seeded('Case1')
            p, host = panel_on(ctx)
            proj = Project(ctx.root)
            other = os.path.join(ctx.root, 'data', 'other.xlsx')
            fixtures.link_or_copy(fx.configs['Case2'], other)
            call(p, 'POST', 'handle', {'phrase': 'Re-run with DER_0 = 1e-4.'}, host)
            wait(p)
            # two overrides that need each other: N_b = 0 is valid only with MLSE = 0 beside it
            code, r = call(p, 'POST', 'edit', {'edits': [{'key': 'N_b', 'value': 0}]}, host)
            both = next((o for o in (r['outcome'].get('question') or {}).get('options') or [] if 'MLSE' in o), None)
            call(p, 'POST', 'handle', {'phrase': both or 'cancel'}, host)
            wait(p)
            code, r = call(p, 'POST', 'open', {'path': other}, host)
            q = r['outcome']
            options = (q.get('question') or {}).get('options') or []
            opt = next((o for o in options if o.startswith(answer)), 'no such option')
            code, r = call(p, 'POST', 'handle', {'phrase': opt}, host)
            wc = core.Context(proj).wc
            want = fx.working_config('Case2')
            if answer == 'keep':
                want = prior_states.with_values(want, {'DER_0': 0.0001, 'N_b': 0, 'MLSE': 0})
            got_f, want_f = fx.load_working_config(wc), fx.load_working_config(want)
            check('with overrides, opening another workbook asks once, and "%s" gives the right working config (two '
                  'overrides that need each other are kept together)' % answer,
                  q['type'] == 'QUESTION' and len(options) == 2 and r['outcome']['type'] ==
                  'PLAN' and same_fields(fx, got_f[0], want_f[0]) and os.path.normcase(api.source_of(proj)[0]) ==
                  os.path.normcase(other), '%s then %s: %s' % (q['type'], r['outcome']['type'],
                                                             r['outcome'].get('announce')))
            fx.remove_project(ctx.root)

        # a workbook that does not import leaves Assist on the previous source
        ctx = seeded('Case1')
        p, host = panel_on(ctx)
        proj = Project(ctx.root)
        broken = os.path.join(ctx.root, 'data', 'broken.xlsx')
        with open(broken, 'wb') as f:
            f.write(b'this is not a workbook')
        before = api.source_of(proj)[0]
        wc0 = core.Context(proj).wc
        code, r = call(p, 'POST', 'open', {'path': broken}, host)
        check('a workbook that does not import gives a STOP or a QUESTION, and Assist stays on the previous source',
              r['outcome']['type'] in ('STOP', 'QUESTION') and api.source_of(proj)[0] == before
              and core.Context(proj).wc == wc0 and any('stays on' in x for x in r['outcome']['announce']),
              r['outcome'])
        fx.remove_project(ctx.root)

        check('the four source workbooks are unchanged after every check (Decision 2)',
              all(sha(fx.configs[lab]) == books[lab] for lab in CASES),
              {lab: sha(fx.configs[lab]) == books[lab] for lab in CASES})

        # ------------------------------------------------------------ the real SiCoPR server, when it has the slot
        if not hasattr(sapp, 'load_panels'):
            print('SKIP: the SiCoPR at %s has no panel slot (gui/app.py has no load_panels), so the checks of the real '
                  'server routing to the panel do not run; they need SiCoPR with the gui-panel-slot change' % sic)
        else:
            from http.server import ThreadingHTTPServer
            from sicopr_assist import panel as assist_panel
            ctx = seeded('Case1')
            api.PANEL.root, api.PANEL.child = ctx.root, SLOW_CHILD
            sapp.add_root(ctx.root)
            with contextlib.redirect_stdout(io.StringIO()):
                sapp.load_panels([('assist', lambda: assist_panel)])
            srv = ThreadingHTTPServer(('127.0.0.1', 0), sapp.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = 'http://127.0.0.1:%d' % srv.server_address[1]

            def post(path, body):
                req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method='POST',
                                             headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        return json.loads(resp.read())
                except urllib.error.HTTPError as e:
                    return json.loads(e.read())
            try:
                with urllib.request.urlopen(base + '/api/panels', timeout=20) as resp:
                    listed = json.loads(resp.read())
                with urllib.request.urlopen(base + '/panel/assist/api/state', timeout=20) as resp:
                    stt = json.loads(resp.read())
                check('SiCoPR\'s server lists the Assist panel and routes its state', listed['panels'][0]['name'] ==
                      'assist' and os.path.normcase(stt['project'] or '') == os.path.normcase(ctx.root), (listed, stt))
                got = post('/panel/assist/api/handle', {'phrase': 'Re-run with DER_0 = 6e-5.'})
                time.sleep(1.5)
                refused = post('/api/exec/start', {'config': '', 'thru': ''})
                check('while the panel runs a plan, SiCoPR\'s Run tab is refused with the panel\'s text',
                      got.get('job') and refused.get('error') == api.BUSY, refused)
                post('/panel/assist/api/stop', {})
                wait(api.PANEL, 30)
            finally:
                srv.shutdown()
                with contextlib.redirect_stdout(io.StringIO()):
                    sapp.load_panels([])
                api.PANEL.root, api.PANEL.child = None, None
                fx.remove_project(ctx.root)
    shutil.rmtree(slow_dir, ignore_errors=True)
    finish()


def api_kinds():
    return ('phrase', 'answer', 'edit', 'open', 'run', 'stop', 'view', 'error')


if __name__ == '__main__':
    main()

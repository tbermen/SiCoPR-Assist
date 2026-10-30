"""Phase 6: running, batches and summaries.

    python tests\\test_run.py
    $env:SICOPR_ASSIST_E2E = "1"; python tests\\test_run.py      also gate G6.4: one real COM run (1 to 4 minutes)

G6.2   statistics and the Pearson coefficient against independent values (statistics module), three seeded sets
G6.3   reuse by fingerprint, with a stand-in child (tests\\cases\\standin_child.py) that runs no COM
G6.4   end to end through the real engine, only when SICOPR_ASSIST_E2E=1 (otherwise SKIP)
M3     what the command line shows while a plan runs, and run.log (Decision 17), with the stand-in child
D18    a re-run with another channel file keeps the config and is a new run; the same file again is reused
M4     end to end: Case1 on the 400 mm THRU, then a re-run on a 300 mm THRU, only when SICOPR_ASSIST_E2E=1
and the checks of Phase 6: what a run leaves behind (rows CP01, CP09, CP10), validate_inputs (rows R7, R8,
rule EN09), the run summary (row D4, rule VR02), not-a-number results (finding F10), Decision 13 (the command
line prints what functions return), and the LLM rule (only a plan the core made and recorded is carried out;
only run.py writes the run CSV or starts a process).

final  a plan says what its run will use: a config JSON named in the phrase is the config that runs (row CP14),
       in a new folder and after other runs; an override the plan sets again, or a config imported again, is not
       announced as kept; a value already in effect is no step and no change line; a note the import made on the
       config as it was (MLSE = 1 turns COM_CONTRIBUTION off) is dropped when the plan's own change makes it untrue
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import ast
import contextlib
import hashlib
import io
import json
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402
from sicopr_assist import cli, config_model, core, engine, run, summary  # noqa: E402
from sicopr_assist.project import Project  # noqa: E402

PKG = os.path.join(fixtures.ROOT, 'sicopr_assist')
STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
SWEEP = 'Re-run the setup, but sweep C_b from 0.1e-4 to 0.5e-4 in 3 steps.'


def rel_close(a, b, tol=1e-12):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol * max(abs(b), 1e-300)


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def do(p, phrase, child=STANDIN):
    """The phrase through the core; a PLAN is then carried out with the stand-in child."""
    out = core.handle(phrase, p)
    done = run.carry_out(p, out, child=child) if out['type'] == 'PLAN' else \
        {'status': out['type'], 'run_ids': [], 'points': [], 'lines': []}
    return out, done


def replace_bytes(path, data):
    """New bytes at path without writing through a hard link (the fixtures link the shared files)."""
    os.remove(path)
    with open(path, 'wb') as f:
        f.write(data)


# ----------------------------------------------------------------------------- G6.2
SETS = {
    'nine': ([1e-05, 1.5e-05, 2e-05, 2.5e-05, 3e-05, 3.5e-05, 4e-05, 4.5e-05, 5e-05],
             [4.2113, 4.4871, 4.9032, 5.1187, 5.6420, 5.8135, 6.2509, 6.6074, 6.9998]),
    'with NaN': ([1, 2, 3, 4, 5, 6], [3.25, float('nan'), 3.75, 4.5, 4.125, 5.0625]),
    'two points': ([1e-05, 5e-05], [3.87, 4.24]),
}


def independent(xs, ys):
    """Expected values from the statistics module, with not-a-number pairs left out."""
    keep = [(x, y) for x, y in zip(xs, ys) if y == y]
    yv = [y for _, y in keep]
    xv = [x for x, _ in keep]
    out = {'count': len(yv), 'left_out': len(ys) - len(yv), 'minimum': min(yv), 'maximum': max(yv),
           'mean': statistics.mean(yv), 'median': statistics.median(yv), 'stdev': statistics.stdev(yv)}
    out['r'] = statistics.correlation(xv, yv)
    out['slope'] = statistics.linear_regression(xv, yv).slope
    return out


def g62_pure():
    ok = True
    for name, (xs, ys) in SETS.items():
        exp = independent(xs, ys)
        got = summary.describe(ys)
        for k in ('count', 'left_out'):
            ok &= check('G6.2 %s: %s %s = %s' % (name, k, got[k], exp[k]), got[k] == exp[k])
        for k in ('minimum', 'maximum', 'mean', 'median', 'stdev'):
            ok &= check('G6.2 %s: %s %r against %r (1e-12 relative)' % (name, k, got[k], exp[k]),
                        rel_close(got[k], exp[k]))
        keep = [(x, y) for x, y in zip(xs, ys) if y == y]
        r, slope = summary.pearson([float(x) for x, _ in keep], [y for _, y in keep])
        ok &= check('G6.2 %s: Pearson %r against %r' % (name, r, exp['r']), rel_close(r, exp['r']))
        ok &= check('G6.2 %s: slope %r against %r' % (name, slope, exp['slope']), rel_close(slope, exp['slope']))
    one = summary.describe([4.5])
    check('G6.2: one value has no standard deviation', one['count'] == 1 and one['stdev'] is None)
    return ok


def seed_set(fx, name):
    """A project whose last set of runs holds the numbers of SETS[name], C_b at the x values (seeded files)."""
    import prior_states
    xs, ys = SETS[name]
    ctx = prior_states.Ctx(fx, 'Case1')
    nums = iter(ys)
    base = ctx.numbers

    def numbers():
        n = base()
        n['channel_operating_margin_dB'] = next(nums)
        return n
    ctx.numbers = numbers
    prior_states.seed_batch(ctx, 'Sweep C_b at %s.' % ', '.join(str(x) for x in xs),
                            [{'C_b': '[%s %s]' % (x, x)} for x in xs])
    return Project(ctx.root)


def g62_seeded(fx):
    """The same sets through the product's own reading of the runs on disk: last_set, result_stats, relation."""
    for name, (xs, ys) in SETS.items():
        p = seed_set(fx, name)
        exp = independent(xs, ys)
        s = summary.last_set(p)
        st = summary.result_stats(s, summary.COM_FIELD)
        check('G6.2 seeded %s: %d results read from disk' % (name, len(s['results'])), len(s['results']) == len(xs))
        check('G6.2 seeded %s: statistics' % name,
              all(rel_close(st[k], exp[k]) for k in ('minimum', 'maximum', 'mean', 'median', 'stdev'))
              and st['count'] == exp['count'], st)
        rel = summary.relation(s, 'C_b', summary.COM_FIELD, True, 3)
        if exp['count'] >= 3:
            check('G6.2 seeded %s: Pearson %r and slope %r' % (name, rel.get('coefficient'), rel.get('slope')),
                  rel['kind'] == 'pearson' and rel_close(rel['coefficient'], exp['r'])
                  and rel_close(rel['slope'], exp['slope']), rel['lines'])
        else:
            check('G6.2 seeded %s: fewer than three points give the pairs and the difference, no coefficient' % name,
                  rel['kind'] == 'few' and 'coefficient' not in rel and rel_close(rel['difference'], ys[-1] - ys[0]),
                  rel['lines'])
        if exp['left_out']:
            text = '\n'.join(st['lines'])
            check('F10: the not-a-number result is shown as it is and its exclusion is stated',
                  'NaN' in text and '1 result is not a number and is left out of the statistics' in text, text)


# ----------------------------------------------------------------------------- G6.3 and the run checks
def runs_on_disk(p):
    return p.run_numbers()


def g63(fx):
    p = Project(fx.project('Case1'))
    out, done = do(p, r'Run COM on data\thru.s4p with data\config.xlsx')
    check('G6.3 setup: the first run is carried out (run_0001)', done and done['run_ids'] == ['run_0001'],
          (out.get('reason'), done))
    out1, done1 = do(p, SWEEP)
    n_pts = len(out1['points'])
    made = [x for x in done1['points'] if x['new']]
    check('G6.3: the batch makes the new runs its plan announced (%d of %d points)' % (out1['new_runs'], n_pts),
          len(made) == out1['new_runs'] and len(runs_on_disk(p)) == 1 + out1['new_runs'], (out1['new_runs'], done1))
    before = runs_on_disk(p)
    out2, done2 = do(p, SWEEP)
    check('G6.3: carried out twice, the second plan has zero new runs and reuses every point',
          out2['type'] == 'PLAN' and out2['new_runs'] == 0 and out2['reused_runs'] == n_pts, out2.get('reason'))
    check('G6.3: and the second time no run is made', runs_on_disk(p) == before
          and all(x['reused_from'] and not x['new'] for x in done2['points']), done2)
    bfile = os.path.join(p.runs_dir, summary.BATCH_FILE)
    rows = open(bfile, encoding='utf-8').read().splitlines() if os.path.exists(bfile) else []
    check('batch_summary.csv: a header and one row per point of each batch (%d)' % (2 * n_pts),
          len(rows) == 1 + 2 * n_pts and rows[0].startswith('command,point,values'), rows[:3])
    # the THRU file's bytes
    thru = os.path.join(p.root, 'data', 'thru.s4p')
    replace_bytes(thru, open(thru, 'rb').read() + b'! one more comment line\n')
    out3, done3 = do(p, SWEEP)
    check('G6.3: other THRU bytes make every point new again', out3['new_runs'] == n_pts
          and len(runs_on_disk(p)) == len(before) + n_pts, out3['new_runs'])
    # one loaded parameter
    n = len(runs_on_disk(p))
    out4, done4 = do(p, 'Re-run with DER_0 = 1e-4.')
    check('G6.3: one loaded parameter changed makes the run new', done4['run_ids'] and
          len(runs_on_disk(p)) == n + 1, done4)
    out5, _ = do(p, SWEEP)
    check('G6.3: and the sweep on that config is new at every point but the one that equals that run',
          out5['new_runs'] == out1['new_runs'] and [x['reused_from'] for x in out5['points'] if not x['new']]
          == done4['run_ids'], (out5['new_runs'], [x['reused_from'] for x in out5['points']]))
    # the engine's SHA-256
    real = engine.engine_sha256
    engine.engine_sha256 = lambda: '0' * 64
    try:
        n = len(runs_on_disk(p))
        out6, done6 = do(p, SWEEP)
        check('G6.3: another engine SHA-256 makes every point new again', out6['new_runs'] == n_pts
              and len(runs_on_disk(p)) == n + n_pts, out6['new_runs'])
    finally:
        engine.engine_sha256 = real
    n = len(runs_on_disk(p))
    out7, done7 = do(p, "What's my COM summary statistics for the last set of runs?")
    check('Decision 8: statistics are carried out without a run', out7['type'] == 'PLAN' and done7['run_ids'] == []
          and len(runs_on_disk(p)) == n, done7)
    return p


def what_a_run_leaves(fx):
    """Rows CP01, CP09, CP10."""
    p = Project(fx.project('Case1'))
    src = os.path.join(p.root, 'data', 'config.xlsx')
    h0 = sha(src)
    do(p, r'Run COM on data\thru.s4p with data\config.xlsx')
    out, done = do(p, 'Re-run with DER_0 = 1e-4.')
    rid = done['run_ids'][0]
    rec = p.read_history()[-1]
    check('CP01: the source config has the same SHA-256 after the runs', sha(src) == h0)
    check('CP01: the working config is .sicopr\\configs\\%s.json and holds the change' % rid,
          rec['working_config'] == os.path.join('.sicopr', 'configs', rid + '.json')
          and p.read_working_config(rid)['main']['DER_0'] == 1e-4, rec['working_config'])
    check('CP01: the history record holds source path and hash, the overrides and the working config',
          rec['source'] == {'path': os.path.join('data', 'config.xlsx'), 'sha256': h0}
          and [o['json_path'] for o in rec['overrides']] == ['/main/DER_0'] and rec['run_ids'] == [rid]
          and rec['channels'][0]['path'] == os.path.join('data', 'thru.s4p') and rec['sicopr']['sha256'], rec)
    check('CP01: no spreadsheet was written', not [f for f in os.listdir(os.path.join(p.root, 'data'))
                                                   if f.endswith('.xlsx') and f != 'config.xlsx'])
    dirs = [p.read_working_config(r)['main']['RESULT_DIR'] for r in ('run_0001', rid)]
    check('CP09: each run has its own RESULT_DIR, its run folder', dirs[0] != dirs[1] and all(
        os.path.normcase(d.rstrip('\\/')) == os.path.normcase(p.run_dir(r)) for d, r in zip(dirs, ('run_0001', rid))), dirs)
    check('CP09: the results of the earlier run are still on disk',
          os.path.exists(p.result_path('run_0001')) and os.path.exists(p.result_path(rid)))
    check('Decision 2: configs\\%s.csv is what the engine read, written from the working config' % rid,
          open(p.run_csv_path(rid), encoding='utf-8', newline='').read()
          == config_model.run_csv_text(p.read_working_config(rid)))
    # CP10: the source edited and saved since then
    import prior_states
    prior_states.edit_workbook(fx.configs['Case1'], src, edits={'SNR_TX': 34})
    out, done = do(p, 'Re-run with SNR_TX = 33.')
    check('CP10: a changed source is noticed and announced', any('changed since the last run' in a
                                                                  for a in out['announce']), out['announce'])
    wc = p.read_working_config(done['run_ids'][0])
    check('CP10: the source is imported again (SNR_TX 34 -> 33) and the stored override is reapplied (DER_0)',
          out['changes'][0]['before'] == 34 and wc['main']['SNR_TX'] == 33 and wc['main']['DER_0'] == 1e-4,
          (out['changes'], wc['main']['DER_0']))
    out, done = do(p, 'Re-run with DER_0 = 2e-4.')
    wc = p.read_working_config(done['run_ids'][0])
    rec = p.read_history()[-1]
    check('CP10: the run imports the source again and reapplies the stored overrides',
          wc['main']['DER_0'] == 2e-4 and wc['main']['SNR_TX'] == 33, (wc['main']['DER_0'], wc['main']['SNR_TX']))
    check('CP10: the history records the new source hash', rec['source']['sha256'] == sha(src))


def plan_from_final_config(fx):
    """A plan's announcement and its run follow the config the run will use (see final above)."""
    import prior_states
    ctx = prior_states.Ctx(fx, 'Case1')
    p = ctx.project
    try:
        wc = fx.working_config('Case1')
        mlse = next(k for k in wc['main'] if k.strip() == 'MLSE')
        contrib = next(k for k in wc['main'] if k.strip() == 'COM_CONTRIBUTION')
        der = next(k for k in wc['main'] if k.strip() == 'DER_0')
        wc['main'][mlse], wc['main'][contrib], wc['main'][der] = 1, 1, 3.3e-5
        with open(ctx.data('config.json'), 'w', encoding='utf-8') as f:
            json.dump(wc, f, indent=1)
        out, done = do(p, r'Run data\thru.s4p with data\config.json.')
        rid = (done['run_ids'] or [None])[0]
        check('CP14 carried out in a new folder: the config JSON named is the config that runs',
              out['type'] == 'PLAN' and done['status'] == 'ok' and rid
              and p.read_working_config(rid)['main'][der] == 3.3e-5
              and p.read_history()[-1]['source']['path'] == os.path.join('data', 'config.json'),
              (out['type'], done['status'], done.get('lines')))
        do(p, r'Run COM on data\thru.s4p with data\config.xlsx')
        out, done = do(p, 'Re-run with DER_0 = 1e-4 and SNR_TX = 31.')
        out, _ = do(p, 'Re-run with DER_0 = 2e-4 and SNR_TX = 31 and C_b = 2e-5.')
        said = '\n'.join(out['announce'])
        check('an override the plan sets again is not announced as kept (DER_0), one it leaves is (SNR_TX)',
              out['type'] == 'PLAN' and 'kept from earlier runs: DER_0' not in said
              and 'kept from earlier runs: SNR_TX = 31' in said, out['announce'])
        ops = [(s['op'], validate_name(s)) for s in out['steps']]
        check('a value already in effect (SNR_TX = 31) is no step and no change line, and is named once',
              ('set_param', 'SNR_TX') not in ops and 'SNR_TX: 31 -> 31' not in said
              and any(a.startswith('already in effect') and 'SNR_TX = 31' in a for a in out['announce']),
              (ops, out['announce']))
        out, done = do(p, r'Run COM on data\thru.s4p with data\config.json and MLSE = 0.')
        said = '\n'.join(out['announce'])
        rid = (done['run_ids'] or [None])[0]
        check('a config imported again: the overrides of the last run are not announced as kept, and the run does '
              'not keep them', out['type'] == 'PLAN' and 'kept from earlier runs' not in said and rid
              and p.read_working_config(rid)['main'][der] == 3.3e-5 and p.read_working_config(rid)['main'][mlse] == 0,
              (out['announce'], done.get('lines')))
        check('the note MLSE = 1 turns COM_CONTRIBUTION off is dropped when the plan sets MLSE = 0',
              'turns COM_CONTRIBUTION off' not in said, out['announce'])
        out, _ = do(p, r'Run COM on data\thru.s4p with data\config.json and DER_0 = 5e-5.')
        check('the note stays when the plan leaves MLSE = 1', 'turns COM_CONTRIBUTION off' in '\n'.join(out['announce']),
              out['announce'])
    finally:
        fx.remove_project(ctx.root)


def validate_name(step):
    from sicopr_assist import validate
    jp = (step.get('args') or {}).get('json_path')
    return validate.name_of(jp) if jp else None


def inputs(fx):
    """validate_inputs: rows R7 and R8, rule EN09."""
    import prior_states
    import make_s4p
    ctx = prior_states.Ctx(fx, 'Case1')
    prior_states.truncated_s4p(ctx)
    prior_states.low_frequency_thru(ctx)
    p = ctx.project
    out = core.handle(r'Run COM on data\bad.s4p with data\config.xlsx', p)
    check('R7: a truncated Touchstone file stops, naming the line', out['type'] == 'STOP'
          and 'not a valid Touchstone file' in out['reason'] and 'line' in out['reason'], out.get('reason'))
    out, done = do(p, r'Run COM on data\lowf.s4p with data\config.xlsx')
    warn = [a for a in out['announce'] if a.startswith('warning: in lowf.s4p the maximum frequency provided, 20 GHz')]
    check('R8: a THRU below the signaling rate runs, with a warning in the plan', out['type'] == 'PLAN' and warn,
          out['announce'])
    lines = summary.run_summary(p, done['run_ids'][0])['lines']
    check('R8: and the warning is shown in the run summary', any(w in lines for w in warn), lines)
    check('VR02: the run summary names the release emulated (%s)' % engine.default_release(),
          'emulating COM release %s' % engine.default_release() in lines[0], lines[0])
    out, done = do(p, 'Re-run with COM Version = 4p16p0.')
    lines = summary.run_summary(p, done['run_ids'][0])['lines'] if done and done['run_ids'] else [str(out)]
    check('VR02: a run with COM Version = 4p16p0 says so in its summary', 'emulating COM release 4p16p0' in lines[0],
          lines[:2])
    # EN09: a 2-port THRU
    s2p = ctx.data('thru.s2p')
    f = make_s4p.np.arange(10e6, 67e9 + 5e6, 10e6)
    s11, s21 = make_s4p.tline_s(f, 400.0, 46.25, 0.0, 5.95e-4, 2.6e-5, 5.79e-3)
    with open(s2p, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Hz S RI R 50\n')
        for i, fr in enumerate(f):
            fh.write('%.6e %.9e %.9e %.9e %.9e %.9e %.9e %.9e %.9e\n' % (
                fr, s11[i].real, s11[i].imag, s21[i].real, s21[i].imag, s21[i].real, s21[i].imag, s11[i].real,
                s11[i].imag))
    out = core.handle(r'Run COM on data\thru.s2p with data\config.xlsx and TDR_W_TXPKG = 1', p)
    check('EN09: TDR_W_TXPKG = 1 with a 2-port THRU stops before any run, with the engine message',
          out['type'] == 'STOP' and out['reason'].startswith('EN09') and 'IndexError' in out['reason'], out.get('reason'))
    out = core.handle(r'Run COM on data\thru.s2p with data\config.xlsx', p)
    check('EN09: the same 2-port THRU with TDR_W_TXPKG = 0 is planned', out['type'] == 'PLAN', out.get('reason'))
    # ERL = 2 is asked about by rule Q17 before it gets this far, so the engine's own stop is checked directly
    wc = config_model.apply_changes(fx.working_config('Case1'), {'/main/TDR_W_TXPKG': 1, '/main/ERL': 2})['config']
    stops, _ = core.input_check(wc, [(ctx.data('thru.s4p'), 'thru')], with_notes=False)
    check('EN09: TDR_W_TXPKG = 1 with ERL = 2 stops with the engine message, whatever the file',
          stops and 'ERL==2 not supported with TDR_W_TXPKG=1' in stops[0], stops)
    do(p, r'Run COM on data\thru.s2p with data\config.xlsx')
    out = core.handle('Re-run with TDR_W_TXPKG = 1.', p)
    check('EN09: a re-run that sets TDR_W_TXPKG = 1 on the 2-port THRU of the last run stops',
          out['type'] == 'STOP' and out['reason'].startswith('EN09'), out.get('reason'))


def llm_rule(fx):
    """Only a plan the core made and recorded is carried out; only run.py writes a run CSV or starts a process."""
    p = Project(fx.project('Case1'))
    fake = core.outcome('PLAN', steps=[{'op': 'run_com', 'args': {}}, {'op': 'summarize', 'args': {}}])
    try:
        run.carry_out(p, fake, child=STANDIN)
        refused = False
    except Exception as e:                      # anything but the refusal is a defect too
        refused = isinstance(e, run.NotRecorded)
    check('LLM rule: a PLAN the core did not make is not carried out', refused and not p.run_numbers())
    out = core.handle(r'Run COM on data\thru.s4p with data\config.xlsx', p)
    edited = json.loads(json.dumps(out))
    edited['steps'].insert(1, {'op': 'set_param', 'args': {'json_path': '/main/DER_0', 'after': -5}})
    try:
        run.carry_out(p, edited, child=STANDIN)
        refused = False
    except Exception as e:                      # anything but the refusal is a defect too
        refused = isinstance(e, run.NotRecorded)
    check('LLM rule: a recorded PLAN changed after the core made it is not carried out', refused and not p.run_numbers())
    done = run.carry_out(p, out, child=STANDIN)
    check('the recorded PLAN itself is carried out', done['run_ids'] == ['run_0001'])
    writers, spawners = set(), set()
    for name in os.listdir(PKG):
        if not name.endswith('.py'):
            continue
        tree = ast.parse(open(os.path.join(PKG, name), encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'write_run_csv':
                writers.add(name)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                if any(m and m.split('.')[0] in ('subprocess', 'multiprocessing') for m in mods):
                    spawners.add(name)
            if isinstance(node, ast.Attribute) and node.attr in ('system', 'popen', 'startfile', 'spawnv', 'execv'):
                spawners.add(name)
    check('LLM rule: only run.py writes a run CSV (found in %s)' % sorted(writers), writers == {'run.py'})
    check('LLM rule: only run.py starts a process, apart from the git calls of the drift check in schema_check.py '
          '(found in %s)' % sorted(spawners), spawners == {'run.py', 'schema_check.py'})
    sc = ast.parse(open(os.path.join(PKG, 'schema_check.py'), encoding='utf-8').read())
    calls = [n for n in ast.walk(sc) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ('run', 'Popen', 'call', 'check_output')]
    # git is started by its full path: the name git, bound once to engine.program('git')
    bound = [n for n in ast.walk(sc) if isinstance(n, ast.Assign) and [getattr(t, 'id', None) for t in n.targets]
             == ['git']]
    git_found = len(bound) == 1 and ast.unparse(bound[0].value) == "engine.program('git')"
    check('LLM rule: schema_check.py starts git and nothing else', calls and git_found and all(
        isinstance(c.args[0], ast.List) and isinstance(c.args[0].elts[0], ast.Name)
        and c.args[0].elts[0].id == 'git' for c in calls), len(calls))
    core_src = open(os.path.join(PKG, 'core.py'), encoding='utf-8').read()
    check('the core does not import run.py, so it never runs COM', not any(
        isinstance(n, ast.ImportFrom) and any(a.name == 'run' for a in n.names) or
        isinstance(n, ast.Import) and any(a.name.endswith('.run') for a in n.names) for n in ast.walk(ast.parse(core_src))))


def decision13(fx):
    """The command line prints what the functions return, and nothing it computes itself."""
    p = seed_set(fx, 'nine')
    phrase = "What's my COM summary statistics for the last set of runs?"
    expect = summary.result_stats(summary.last_set(p), summary.COM_FIELD)['lines']
    buf = io.StringIO()
    outcome, done = cli.handle_and_run(phrase, p, out=buf)
    printed = buf.getvalue().splitlines()
    check('Decision 13: every line of the statistics comes from summary.result_stats and is printed',
          all(line in printed for line in expect) and all(a in printed for a in outcome['announce']), printed[:5])
    check('Decision 13: a summary runs nothing', done is not None and done['run_ids'] == [] and len(p.run_numbers()) == 9)
    d4 = core.handle('Show me the summary again.', p)
    check('D4: the summary of the last run, with its release, and no run',
          d4['type'] == 'PLAN' and [s['op'] for s in d4['steps'] if (s.get('args') or {}).get('why') not in
                                    ('new', 'trouble')] == ['summarize']
          and d4['announce'] == summary.run_summary(p, core.Context(p).last_run_id())['lines'], d4['announce'][:2])


# ----------------------------------------------------------------------------- G6.4
G64_PHRASE = (r'Run COM on data\thru.s4p with data\config.xlsx with c(-1) = [-0.12:0.06:0], c(-2) = [0:0.04:0.04], '
              r'c(1) = [-0.05:0.05:0], g_DC = [-12:4:0], g_DC_HP = [-3:3:0], sample_adjustment = [-4 4], '
              r'num_ui_RXFF_noise = 1024 and N_bg = 0.')
G64_EXPECTED = 7.1408


def g64(fx):
    if os.environ.get('SICOPR_ASSIST_E2E', '') != '1':
        print('SKIP: G6.4 end to end runs only with SICOPR_ASSIST_E2E=1 (one real COM run, 1 to 4 minutes)')
        return
    p = Project(fx.project('Case1'))
    out = core.handle(G64_PHRASE, p)
    check('G6.4: the phrase gives a PLAN with the eight changes', out['type'] == 'PLAN' and len(
        [c for c in out['changes'] if c['kind'] == 'set']) == 8, out.get('reason') or out.get('question'))
    t0 = time.time()
    lines = []
    done = run.carry_out(p, out, progress=lambda kind, text: lines.append(text))
    took = time.time() - t0
    rid = done['run_ids'][0] if done['run_ids'] else None
    res = p.read_result(rid) if rid else {}
    com = (res.get('cases') or [{}])[0].get(summary.COM_FIELD)
    check('G6.4: the run completes from the run CSV and writes result.json (%s, %.0f s)' % (rid, took),
          res.get('status') == 'complete' and res.get('config_csv') == p.run_csv_path(rid), res.get('message'))
    check('G6.4: result.json holds the fields at full precision, COM %r' % com, isinstance(com, float), com)
    with open(p.result_path(rid), encoding='utf-8') as f:
        raw = json.load(f)
    check('G6.4: the engine report is in the run folder (RESULT_DIR)', any(
        n.lower().startswith('case') or n.endswith('.csv') for n in os.listdir(p.run_dir(rid))), os.listdir(p.run_dir(rid)))
    print('G6.4 RESULT: COM %r dB under %s in %.0f s (%d fields in case 1); 6 October gave %s; difference %.4f dB%s'
          % (com, raw.get('release'), took, len(raw['cases'][0]), G64_EXPECTED, com - G64_EXPECTED,
             ' (above 0.01 dB: reported, not failed)' if abs(com - G64_EXPECTED) > 0.01 else ''))
    for line in summary.run_summary(p, rid)['lines']:
        print('  ' + line)


# ----------------------------------------------------------------------------- after first use (6 October)
THRU2_MM = 300.0                                 # the second synthetic THRU: another length than the 400 mm one


def progress_part(printed, outcome, done):
    """The lines cli.py printed while the plan was carried out: after the PLAN listing, before the plan's lines."""
    k0 = printed.index('PLAN:') + 1 + len(outcome['steps'])
    k1 = len(printed) - len(done['lines'])
    return printed[k0:k1], printed[k1:]


def decision17(fx):
    """Gate M3: with the stand-in child printing progress lines, cli.py shows a status line for each step, every
    child line in order and before the result, and the elapsed time; --quiet drops the child lines only; run.log
    holds the same lines."""
    import re
    import standin_child
    p = Project(fx.project('Case1'))
    buf = io.StringIO()
    outcome, done = cli.handle_and_run(r'Run COM on data\thru.s4p with data\config.xlsx', p, out=buf, child=STANDIN)
    printed = buf.getvalue().splitlines()
    shown, after = progress_part(printed, outcome, done)
    ops = [s['op'] for s in outcome['steps']]
    at = [next((i for i, line in enumerate(shown) if line.startswith('step %d of %d: %s' % (k + 1, len(ops), op))), None)
          for k, op in enumerate(ops)]
    check('M3: a status line for each step, in the order of the plan (%s)' % ' > '.join(ops),
          None not in at and at == sorted(at), shown[:8])
    check('M3: the status line of run_com names the run id', any(re.match(r'step \d+ of \d+: run_com: run_0001 started$', x)
                                                                 for x in shown), shown[:8])
    child = [x[len(run.ENGINE_INDENT):] for x in shown if x.startswith(run.ENGINE_INDENT)]
    check('M3: every child line is shown, indented and unchanged, in order',
          child[:len(standin_child.PROGRESS)] == list(standin_child.PROGRESS) and len(child) == len(standin_child.PROGRESS) + 1
          and child[-1].startswith('--- case 1: channel_operating_margin_dB'), child)
    end = [i for i, x in enumerate(shown) if re.match(r'run_0001 finished in \d+ s: COM -?[\d.]+ dB$', x)]
    last_child = max((i for i, x in enumerate(shown) if x.startswith(run.ENGINE_INDENT)), default=-1)
    check('M3: the run ends with its elapsed time and the headline result, after every child line',
          len(end) == 1 and end[0] > last_child, shown)
    check('M3: the child lines come before the result: the summary follows the progress lines',
          after == done['lines'] and done['lines'] and last_child >= 0
          and printed.index(done['lines'][0]) > printed.index(shown[last_child]), after[:4])
    with open(os.path.join(p.run_dir('run_0001'), 'run.log'), encoding='utf-8') as f:
        log = f.read().splitlines()
    check('M3: run.log holds the same lines as were shown, in the same form', log == shown,
          '%d logged, %d shown' % (len(log), len(shown)))
    buf = io.StringIO()
    outcome, done = cli.handle_and_run('Re-run with DER_0 = 1e-4.', p, out=buf, quiet=True, child=STANDIN)
    printed = buf.getvalue().splitlines()
    shown, _ = progress_part(printed, outcome, done)
    with open(os.path.join(p.run_dir('run_0002'), 'run.log'), encoding='utf-8') as f:
        log = f.read().splitlines()
    check('M3: --quiet drops the child lines, and only them',
          not any(x.startswith(run.ENGINE_INDENT) for x in shown) and shown == [x for x in log if not x.startswith(
              run.ENGINE_INDENT)] and any(x.startswith('step ') for x in shown)
          and any(re.match(r'run_0002 finished in \d+ s: COM', x) for x in shown), shown)
    check('M3: with --quiet, run.log still holds the child lines',
          [x[len(run.ENGINE_INDENT):] for x in log if x.startswith(run.ENGINE_INDENT)][:3] == list(standin_child.PROGRESS),
          log[:8])
    got = []
    out = core.handle('Re-run with DER_0 = 2e-5.', p)
    run.carry_out(p, out, child=STANDIN, progress=lambda kind, text: got.append((kind, text)))
    check('M3: the runner hands each line to a callback as (kind, text), for a GUI as for cli.py',
          {k for k, _ in got} == {'status', 'engine'} and [t for k, t in got if k == 'engine'][:3]
          == list(standin_child.PROGRESS), got[:4])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SICOPR_ASSIST_HOME=fx.home,
               PYTHONPATH=fixtures.ROOT + os.pathsep + os.environ.get('PYTHONPATH', ''))
    import subprocess
    r = subprocess.run([sys.executable, '-m', 'sicopr_assist', '--quiet', 'anything'], cwd=fx.project('Case1'),
                       capture_output=True, text=True, env=env)
    check('M3: the command line takes --quiet', r.returncode == 0 and r.stdout.startswith('STOP: '), r.stderr[-300:])


def decision18_runs(fx):
    """Decision 18 in the runner: a re-run with another THRU keeps the config and overrides of the last run and
    is a new run (the channel's SHA-256 is in the fingerprint); the same THRU again is reused."""
    p = Project(fx.project('Case1'))
    fixtures.link_or_copy(fx.thru_of(THRU2_MM), os.path.join(p.root, 'data', 'thru2.s4p'))
    do(p, r'Run COM on data\thru.s4p with data\config.xlsx')
    do(p, 'Re-run with DER_0 = 1e-4.')
    out, done = do(p, r'Re-run with data\thru2.s4p.')
    check('D18: the re-run with data\\thru2.s4p is a PLAN that starts with set_channel and imports nothing',
          out['type'] == 'PLAN' and out['steps'][0]['op'] == 'set_channel'
          and 'import_config' not in [s['op'] for s in out['steps']], out.get('reason') or out.get('question'))
    check('D18: a new THRU makes a new run', done['run_ids'] == ['run_0003'] and p.run_numbers() == [1, 2, 3],
          (done['run_ids'], p.run_numbers()))
    a = p.read_working_config('run_0002')
    b = p.read_working_config('run_0003') if os.path.exists(p.working_config_path('run_0003')) else \
        {'main': {}, 'packages': None}
    key = next(k for k in a['main'] if k.strip().lower() == 'result_dir')
    check('D18: the run keeps the working config of the last run, its override included (only RESULT_DIR differs)',
          dict(a['main'], **{key: None}) == dict(b['main'], **{key: None}) and a['packages'] == b['packages']
          and b['main'].get('DER_0') == 1e-4, b['main'].get('DER_0'))
    rec = p.read_history()[-1]
    res = p.read_result('run_0003') if os.path.exists(p.result_path('run_0003')) else {}
    want = sha(os.path.join(p.root, 'data', 'thru2.s4p'))
    check('D18: the history and the result name the new THRU with its SHA-256, and keep the override',
          [c['sha256'] for c in rec['channels']] == [want] and [c['sha256'] for c in res.get('channels') or []] == [want]
          and [o['json_path'] for o in rec['overrides']] == ['/main/DER_0'], (rec['channels'], rec['overrides']))
    out, done = do(p, r'Re-run with data\thru.s4p.')
    check('D18: back to data\\thru.s4p with the same config is reused from run_0002, not run again',
          out['type'] == 'PLAN' and done['run_ids'] == ['run_0002'] and p.run_numbers() == [1, 2, 3],
          (out.get('reason'), done['run_ids'], p.run_numbers()))
    out = core.handle(r'Re-run with data\thru.s4p.', p)
    check('D18 (CH07): the THRU already in use is a STOP, and nothing runs', out['type'] == 'STOP', out.get('steps'))
    fixtures.link_or_copy(fx.thru, os.path.join(p.root, 'data', 'fext1.s4p'))
    out, done = do(p, r'Re-run with FEXT data\fext1.s4p.')
    res = p.read_result(done['run_ids'][0]) if done['run_ids'] else {}
    check('D18 (CH08): a FEXT file is added to the run as a FEXT aggressor',
          [c['role'] for c in res.get('channels') or []] == ['thru', 'fext'], res.get('channels'))
    # the maintainer's phrase 5: a channel named by its file name alone, in the folder of the last THRU
    q = Project(fx.project('Case1'))
    ch = os.path.join(q.root, 'ch', 'set1')
    fixtures.link_or_copy(fx.thru, os.path.join(ch, 'a_thru1.s4p'))
    fixtures.link_or_copy(fx.thru_of(THRU2_MM), os.path.join(ch, 'b_thru1.s4p'))
    do(q, r'Run COM on ch\set1\a_thru1.s4p with data\config.xlsx')
    out = core.handle('Re-run with b_thru1.s4p', q)
    sw = [s['args'] for s in out['steps'] if s['op'] == 'set_channel']
    check('D18: a bare file name is found by that exact name beside the THRU of the last run',
          out['type'] == 'PLAN' and len(sw) == 1 and sw[0]['after'] == os.path.join('ch', 'set1', 'b_thru1.s4p'), sw)
    out = core.handle('Re-run with c_thru1.s4p', q)
    check('D18: a bare file name that is nowhere there stops and keeps the last setup', out['type'] == 'STOP'
          and 'does not exist' in out['reason'], out.get('reason'))


def m4(fx):
    """Gate M4: end to end, Case1 on the synthetic 400 mm THRU, then Re-run with a second synthetic THRU of another
    length: the second run keeps the config, makes a new run, and its COM differs from the first."""
    if os.environ.get('SICOPR_ASSIST_E2E', '') != '1':
        print('SKIP: M4 end to end runs only with SICOPR_ASSIST_E2E=1 (two real COM runs, about 4 minutes each)')
        return
    p = Project(fx.project('Case1'))
    fixtures.link_or_copy(fx.thru_of(THRU2_MM), os.path.join(p.root, 'data', 'thru2.s4p'))
    buf = io.StringIO()
    t0 = time.time()
    o1, d1 = cli.handle_and_run(r'Run COM on data\thru.s4p with data\config.xlsx', p, out=buf)
    took1 = time.time() - t0
    buf = io.StringIO()
    t0 = time.time()
    o2, d2 = cli.handle_and_run(r'Re-run with data\thru2.s4p.', p, out=buf)
    took2 = time.time() - t0
    printed = buf.getvalue().splitlines()
    com = []
    for d in (d1, d2):
        rid = (d or {}).get('run_ids', [None])[0] if d and d.get('run_ids') else None
        com.append(((p.read_result(rid).get('cases') or [{}])[0].get(summary.COM_FIELD)) if rid else None)
    check('M4: the first run completes (run_0001, COM %r dB, %.0f s)' % (com[0], took1),
          d1 and d1['run_ids'] == ['run_0001'] and isinstance(com[0], float))
    check('M4: Re-run with data\\thru2.s4p is a PLAN that keeps the config: set_channel, no import_config',
          o2['type'] == 'PLAN' and [s['op'] for s in o2['steps']][:1] == ['set_channel']
          and 'import_config' not in [s['op'] for s in o2['steps']], o2.get('reason') or o2.get('question'))
    a, b = p.read_working_config('run_0001'), p.read_working_config('run_0002') if d2 and d2['run_ids'] else None
    key = next(k for k in a['main'] if k.strip().lower() == 'result_dir')
    check('M4: the second run is new (run_0002) and keeps the config (only RESULT_DIR differs)',
          d2 and d2['run_ids'] == ['run_0002'] and b is not None
          and dict(a['main'], **{key: None}) == dict(b['main'], **{key: None}) and a['packages'] == b['packages'])
    check('M4: its COM differs from the first (%r against %r dB, %.0f s)' % (com[1], com[0], took2),
          isinstance(com[1], float) and com[1] != com[0])
    print('M4 RESULT: COM %r dB on the 400 mm THRU, %r dB on the %g mm THRU' % (com[0], com[1], THRU2_MM))
    print('M4 what the command line printed for the re-run (%d lines; the first 16 and the last 12):' % len(printed))
    for line in printed[:16] + ['    ...'] + printed[-12:]:
        print('| ' + line)


def main():
    g62_pure()
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks are absent or hidden; the run checks need them')
        finish()
    with fixtures.Fixtures(variants=False) as fx:
        g62_seeded(fx)
        g63(fx)
        what_a_run_leaves(fx)
        plan_from_final_config(fx)
        inputs(fx)
        llm_rule(fx)
        decision13(fx)
        decision17(fx)
        decision18_runs(fx)
        g64(fx)
        m4(fx)
    finish()


if __name__ == '__main__':
    main()

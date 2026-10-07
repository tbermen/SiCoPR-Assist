"""Carries out a plan: child process, run folders, reuse, batches.

carry_out(project, outcome) takes a PLAN that core.handle has just returned and recorded, and does what its
steps say. It refuses any other outcome: a plan reaches the engine only through the core, which validated it
(an upstream layer, such as a language model, never gets a way to write the run CSV or run the engine past the
core). Each config is validated again before its run CSV is written.

A run is one child process (run_case.py) started from an argument list, with no shell and unbuffered output,
one at a time. Each run gets the next run id and writes, under the project's .sicopr folder (Decision 3):

    configs\\run_NNNN.json    the working config, with RESULT_DIR set to the run's own folder (row CP09)
    configs\\run_NNNN.csv     what the engine read (Decision 2)
    runs\\run_NNNN\\          RESULT_DIR: the engine's own report, run.log, result.json

A point whose loaded parameters, channel files and engine equal an earlier run's is reused, not run again
(Decision 6). A point that fails validation is skipped and reported, and a batch goes on (Decision 7).
Everything returned is data: the lines to show are in the result's "lines" (Decision 13).

While a plan is carried out (Decision 17), each line is handed to the progress callback as (kind, text) as it
happens: a "status" line as each step starts (the step, the run id, and for a batch the point n of N), every
"engine" line the child prints, as it arrives and unchanged, and a "status" line that ends each run with its
elapsed time and headline result. line_text gives the form shown: an engine line is indented. run.log in the run
folder holds the same lines in that form, whatever the caller shows.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import hashlib
import json
import os
import subprocess
import sys
import time

from sicopr_assist import config_model, core, engine, summary, validate, xlsx_io
from sicopr_assist.project import result_record

RUN_CASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_case.py')
ENGINE_INDENT = '    '


def line_text(kind, text):
    """A progress line as it is shown and as run.log holds it: a status line as it is, an engine line indented."""
    return ENGINE_INDENT + text if kind == 'engine' else text


def elapsed_text(seconds):
    s = int(round(seconds))
    return '%d s' % s if s < 60 else '%d min %d s' % (s // 60, s % 60)


class NotRecorded(ValueError):
    """The outcome handed to carry_out is not the plan the core last recorded."""


def child_command():
    """The child that runs one case: this Python, unbuffered, on run_case.py."""
    return [sys.executable, '-u', RUN_CASE]


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _native(path):
    """A path as typed in a phrase (data\\thru.s4p) with this system's separators; an absolute path as it is."""
    if os.path.isabs(path):
        return path
    return os.path.join(*[x for x in path.replace('\\', '/').split('/') if x])


def _canon(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def _record_of(project, out):
    """The history record that holds this plan: the last one, written by core.handle."""
    hist = project.read_history()
    rec = hist[-1] if hist else None
    if rec is None or rec.get('outcome') != 'PLAN' or _canon(rec.get('plan')) != _canon(out):
        raise NotRecorded('only the plan the core has just made and recorded can be carried out')
    return rec


def fingerprint_hash(fp):
    """A short text form of a run's fingerprint (loaded fields without RESULT_DIR, channel files, engine), kept in
    result.json for the record. Reuse compares the fingerprints themselves (core._same_fingerprint)."""
    fields, chans, sic = fp
    h = hashlib.sha256()
    for k in sorted(fields):
        v = fields[k]
        h.update(k.encode('utf-8'))
        h.update(repr(v.tolist() if hasattr(v, 'tolist') else v).encode('utf-8'))
    h.update(repr((chans, sic)).encode('utf-8'))
    return h.hexdigest()


def _with_result_dir(wc, folder):
    new = copy.deepcopy(wc)
    key = next((k for k in new['main'] if k.strip().lower() == 'result_dir'), 'RESULT_DIR')
    new['main'][key] = folder + os.sep
    new['links'].pop(key, None)
    return new


class _Runner:
    def __init__(self, project, child, progress):
        self.project = project
        self.child = list(child or child_command())
        self.progress = progress
        self.ctx = core.Context(project)
        self.known = list(self.ctx.runs)            # [(run id, fingerprint)] of complete runs, oldest first
        self.sic = engine.engine_sha256()
        self.log = None                             # run.log of the run under way
        self.last_log = None                        # run.log of the last run, for the lines after it
        self.held = []                              # lines said while no run.log is open

    def say(self, kind, text):
        """One progress line (Decision 17): to the callback, and to run.log in the form shown."""
        if self.progress:
            self.progress(kind, text)
        line = line_text(kind, text)
        if self.log is not None:
            self.log.write(line + '\n')
            self.log.flush()
        else:
            self.held.append(line)

    def close(self):
        """The lines said after the last run (the summary steps) go to the end of its run.log."""
        if self.held and self.last_log:
            with open(self.last_log, 'a', encoding='utf-8', newline='\n') as f:
                f.write(''.join(line + '\n' for line in self.held))
        self.held = []

    def fingerprint(self, wc, channels):
        fields, err = config_model.loaded_fields(wc)
        if err:
            return None, err
        shas = [_sha(self.ctx.path(p)) for p, _ in channels]
        return core._fingerprint(fields, shas, self.sic), None

    def run_point(self, wc, channels, head, notes=()):
        """One point: reuse an equal earlier run, or run it. head starts its status line (the step, and for a batch
        the point n of N). Returns {'run_id', 'new', 'reused_from', 'skipped', 'status', 'message'}."""
        res = validate.validate_config(wc)
        if res['status'] == 'stop':
            self.say('status', '%s: skipped, validate_config fails: %s' % (head, res['text']))
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_config fails: %s' % res['text'], 'message': res['text']}
        stops, more = core.input_check(wc, [(self.ctx.path(p), r) for p, r in channels])
        if stops:
            self.say('status', '%s: skipped, validate_inputs fails: %s' % (head, stops[0]))
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_inputs fails: %s' % stops[0], 'message': stops[0]}
        fp, err = self.fingerprint(wc, channels)
        if fp is None:
            self.say('status', '%s: skipped, validate_config fails: %s' % (head, err))
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_config fails: %s' % err, 'message': err}
        same = next((rid for rid, f in self.known if core._same_fingerprint(f, fp)), None)
        if same is not None:
            self.say('status', '%s: the inputs equal those of %s, so its results are reused and nothing runs'
                     % (head, same))
            return {'run_id': same, 'new': False, 'reused_from': same, 'skipped': None, 'status': 'reused',
                    'message': None}
        rid = self.project.next_run_id()
        folder = self.project.run_dir(rid)
        os.makedirs(folder, exist_ok=True)
        run_wc = _with_result_dir(wc, folder)
        self.project.write_working_config(rid, run_wc)
        csv_path = config_model.write_run_csv(run_wc, self.project.run_csv_path(rid))
        status, message = self._child(rid, csv_path, channels, fingerprint_hash(fp), list(notes) + list(more), head)
        if status == 'complete':
            self.known.append((rid, fp))
        return {'run_id': rid, 'new': True, 'reused_from': None, 'skipped': None, 'status': status,
                'message': message}

    def _child(self, rid, csv_path, channels, fp_hash, notes, head):
        p = self.project
        result = p.result_path(rid)
        paths = [(os.path.abspath(self.ctx.path(c)), r) for c, r in channels]
        cmd = self.child + [csv_path, result, '--thru', paths[0][0]]
        for role in ('fext', 'next'):
            files = [c for c, r in paths[1:] if r == role]
            if files:
                cmd += ['--' + role] + files
        cmd += ['--fingerprint', fp_hash]
        for n in notes:
            cmd += ['--note', n]
        # the child writes UTF-8, so the engine's lines reach run.log and the screen unchanged
        env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        log = os.path.join(p.run_dir(rid), 'run.log')
        said = []
        t0 = time.time()
        with open(log, 'w', encoding='utf-8', newline='\n') as f:
            f.write(''.join(line + '\n' for line in self.held))
            self.held = []
            self.log = f
            try:
                self.say('status', '%s: %s started' % (head, rid))
                proc = subprocess.Popen(cmd, cwd=p.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                                        bufsize=1)
                for line in proc.stdout:
                    said.append(line.rstrip('\n'))
                    self.say('engine', said[-1])
                code = proc.wait()
                took = elapsed_text(time.time() - t0)
                try:
                    rec = p.read_result(rid)
                except (OSError, ValueError):
                    rec = None
                if rec is None:
                    msg = 'the run stopped with exit code %s and wrote no result: %s' % (code, ' / '.join(said[-3:]))
                    p.write_result(rid, result_record(run_id=rid, status='failed', message=msg, sicopr_sha256=self.sic,
                                                      config_csv=csv_path, fingerprint=fp_hash))
                    rec = {'status': 'failed', 'message': msg}
                if rec['status'] == 'complete':
                    self.say('status', '%s finished in %s: %s' % (rid, took, _headline(rec)))
                else:
                    self.say('status', '%s failed after %s: %s' % (rid, took, rec.get('message')))
            finally:
                self.log = None
        self.last_log = log
        return rec['status'], rec.get('message')


def _headline(rec):
    """The headline result of a finished run: COM of each package case."""
    coms = [c.get(summary.COM_FIELD) for c in rec.get('cases') or []]
    if not coms:
        return 'no COM value in the result'
    return 'COM %s dB%s' % (', '.join(summary.fmt(v) for v in coms),
                            ' (%d package cases)' % len(coms) if len(coms) > 1 else '')


def _step_detail(op, a):
    """What a status line says about a step besides its name."""
    if op == 'import_config':
        return a.get('path') or ''
    if op in ('set_param', 'add_param'):
        return '%s: %s -> %s' % (validate.name_of(a['json_path']), validate.show(a.get('before')),
                                 validate.show(a.get('after')))
    if op == 'recompute_linked':
        return ', '.join(validate.name_of(c['json_path']) for c in a.get('changes') or [])
    if op == 'set_channel' and a.get('role') == 'crosstalk':
        return 'FEXT: %s -> %d files; NEXT: %s -> %d files' % (
            'none' if not a.get('before') else 'replaced', len(a.get('fext') or []),
            'none' if not a.get('before') else 'replaced', len(a.get('next') or []))
    if op == 'set_channel':
        return '%s: %s -> %s' % ((a.get('role') or 'thru').upper(), a.get('before') or 'none', a['after'])
    if op == 'clear_overrides':
        return 'every override is dropped'
    if op == 'build_matrix':
        return '%s points' % a.get('points', '')
    if op == 'export_xlsx':
        return a.get('path') or ''
    return ''


def _apply_channel(channels, a):
    """[(path, role)] after one set_channel step (Decision 18): the THRU is replaced; an aggressor replaces the
    one it names, or is added. Applying the same step twice changes nothing, so a replayed plan is safe."""
    if a.get('role') == 'crosstalk':             # Decision 19: the THRU is kept and the aggressors are replaced
        thru = [(p, r) for p, r in channels if r == 'thru'][:1]
        return thru + [(p, 'fext') for p in a.get('fext') or []] + [(p, 'next') for p in a.get('next') or []]
    role, after, before = a.get('role') or 'thru', a['after'], a.get('before')
    out = list(channels)
    if (after, role) in out:
        return out
    if role == 'thru':
        k = next((i for i, (_, r) in enumerate(out) if r == 'thru'), None)
    else:
        k = next((i for i, (p, r) in enumerate(out) if r == role and p == before), None) if before else None
    if k is not None:
        out[k] = (after, role)
    elif role == 'thru':
        out.insert(0, (after, role))
    else:
        out.append((after, role))
    return out


def carry_out(project, out, child=None, progress=None):
    """Carry out a PLAN that core.handle returned and recorded. child replaces the command that runs one case
    (a test gives a stand-in that writes a seeded result.json). progress, when given, is called with (kind, text)
    for every line said while the plan is carried out (Decision 17; see line_text for the form shown).
    Returns {'status', 'run_ids', 'points', 'lines'} and fills in the history record."""
    if out.get('type') != 'PLAN':
        raise ValueError('only a PLAN is carried out')
    rec = _record_of(project, out)
    steps = [(s['op'], s.get('args') or {}) for s in out['steps']]
    ops = [op for op, _ in steps]
    R = _Runner(project, child, progress)
    ctx = R.ctx
    lines = []
    if not out.get('points') and not any(op in ops for op in ('run_com', 'run_batch', 'build_matrix', 'export_xlsx')):
        return {'status': 'ok', 'run_ids': [], 'points': [], 'lines': lines}      # shown already (Decision 8)
    said = set()

    def say_step(k, more=''):
        op, a = steps[k]
        detail = _step_detail(op, a)
        R.say('status', 'step %d of %d: %s%s%s' % (k + 1, len(steps), op, ': ' + detail if detail else '', more))
        said.add(k)
    first_run = next((k for k, op in enumerate(ops) if op in ('run_com', 'run_batch')), len(ops))

    last = ctx.last or {}
    source = dict(last.get('source') or {}) or None
    overrides = [dict(o) for o in last.get('overrides') or []]
    channels = [(c['path'], c.get('role') or 'thru') for c in last.get('channels') or []]
    base_run = ctx.last_run_id()
    imported = next((a for op, a in steps if op == 'import_config'), None)
    for k, op in enumerate(ops[:first_run]):
        if op in ('import_config', 'clear_overrides'):
            say_step(k)
    if imported is not None or 'clear_overrides' in ops:
        path = ctx.path(imported['path']) if imported else ctx.path((source or {}).get('path') or '')
        wc, issues = config_model.import_config(path)
        if wc is None or config_model.stops(issues):
            return _failed(project, rec, 'the config %s cannot be imported: %s' % (
                path, '; '.join(i['text'] for i in config_model.stops(issues)) or 'no config'))
        source = {'path': _native(imported['path'] if imported else source['path']), 'sha256': _sha(path)}
        overrides = []
        named = next((a.get('channels') for op, a in steps if op in ('validate_inputs', 'run_com') and a.get('channels')),
                     None)
        if named:
            channels = core.channel_roles(named)
    else:
        wc = ctx.wc
        if wc is None:
            return _failed(project, rec, ctx.base[1])
        if ctx.source_changed():
            source = dict(source, sha256=_sha(ctx.path(source['path'])))
    # the changes of the plan, from its steps (a replayed plan holds them there too)
    sets = [(a['json_path'], a['after']) for op, a in steps if op in ('set_param', 'add_param')]
    if sets:
        applied = config_model.apply_changes(wc, sets)
        wc = applied['config']
        for c in applied['changes']:
            if c['kind'] == 'linked':
                continue
            overrides = [o for o in overrides if o['json_path'] != c['json_path']]
            overrides.append({'json_path': c['json_path'], 'before': c['before'], 'after': c['after'],
                              'kind': c['kind']})
    # another channel file, with the config of the last run (Decision 18)
    for op, a in steps:
        if op == 'set_channel':
            channels = _apply_channel(channels, a)
    run_com = next((a for op, a in steps if op == 'run_com'), None)
    if run_com and run_com.get('thru_only'):
        channels = channels[:1]
    if not channels and any(op in ops for op in ('run_com', 'run_batch')):
        return _failed(project, rec, 'no channel file is known for this run')
    chan_recs = [{'path': _native(p), 'sha256': _sha(ctx.path(p)), 'role': r} for p, r in channels]
    fields = dict(source=source, channels=chan_recs, overrides=overrides)
    run_ids, points, status = [], [], 'ok'
    for k in range(first_run):                  # the steps before the run, as the run starts
        if k not in said:
            say_step(k)
    head = 'step %d of %d: %s' % (first_run + 1, len(steps), ops[first_run]) if first_run < len(ops) else 'run'
    said.add(first_run)

    if 'build_matrix' in ops or 'run_batch' in ops or out.get('points'):
        pts = out.get('points') or []
        for i, pt in enumerate(pts, 1):
            rec_pt = {'values': pt.get('values'), 'run_id': None, 'new': False, 'reused_from': None,
                      'skipped': pt.get('skipped')}
            where = '%s: point %d of %d (%s)' % (head, i, len(pts), ', '.join(
                '%s = %s' % (validate.name_of(k) if str(k).startswith('/') else k, validate.show(v))
                for k, v in (pt.get('values') or {}).items()))
            if pt.get('skipped'):
                R.say('status', '%s: skipped, %s' % (where, pt['skipped']))
            else:
                point_wc = config_model.apply_changes(wc, list((pt.get('writes') or pt.get('values') or {}).items()))
                got = R.run_point(point_wc['config'], channels, where)
                rec_pt.update(run_id=got['run_id'], new=got['new'], reused_from=got['reused_from'],
                              skipped=got['skipped'])
                if got['status'] == 'failed':
                    rec_pt['skipped'] = 'the run failed: %s' % got['message']
                if got['run_id']:
                    run_ids.append(got['run_id'])
            points.append(rec_pt)
        fields.update(working_config=None, run_ids=run_ids, points=points)
    elif run_com is not None:
        got = R.run_point(wc, channels, head)
        if got['run_id']:
            run_ids.append(got['run_id'])
            fields.update(working_config=project.relative(project.working_config_path(got['run_id'])),
                          run_ids=run_ids)
        if got['status'] in ('failed', 'skipped'):
            status = 'failed'
            fields.update(status='failed', reason=got['message'])
    release = None
    for rid in run_ids:
        try:
            release = project.read_result(rid).get('release') or release
        except (OSError, ValueError):
            pass
    fields['sicopr'] = {'sha256': R.sic, 'release': release or validate.emulated_release(wc)}
    project.update_history(rec['seq'], **fields)

    # what is shown once the plan is carried out
    for k, (op, a) in enumerate(steps):
        if k not in said and op in ('summarize', 'batch_summary', 'diff_results', 'export_xlsx'):
            say_step(k)
        if op == 'summarize' and run_com is not None:
            for rid in run_ids:
                lines += summary.run_summary(project, rid)['lines']
            if not run_ids:
                lines.append('the run did not happen: %s' % fields.get('reason'))
        elif op == 'batch_summary':
            path, rows = summary.write_batch_summary(project, rec['seq'], points)
            lines += summary.batch_lines(rows) + ['one row per point added to %s' % project.relative(path)]
        elif op == 'diff_results':
            lines += _diff_lines(project, base_run, points)
        elif op == 'export_xlsx':
            src = ctx.source_path
            if not src:
                lines.append('no source workbook to copy, so nothing was saved')
            else:
                got = xlsx_io.export_workbook(wc, src, ctx.path(a['path']))
                lines.append('saved %s (%d cells rewritten, %d keywords added)' % (
                    a['path'], len(got['written']), len(got['added'])))
                lines += got['warnings']
    R.close()
    return {'status': status, 'run_ids': run_ids, 'points': points, 'lines': lines}


def _failed(project, rec, message):
    project.update_history(rec['seq'], status='failed', reason=message)
    return {'status': 'failed', 'run_ids': [], 'points': [], 'lines': ['nothing ran: %s' % message]}


def _diff_lines(project, base_run, points):
    """COM of each point against the run the batch started from."""
    def com(rid):
        try:
            cases = project.read_result(rid).get('cases') or []
        except (OSError, ValueError):
            return None
        return cases[0].get(summary.COM_FIELD) if cases else None
    ref = com(base_run) if base_run else None
    if ref is None:
        return ['no earlier run to compare with']
    out = ['differences in COM against the last run before the batch (%s, COM %s dB):' % (base_run, summary.fmt(ref))]
    for i, p in enumerate(points, 1):
        v = com(p['run_id']) if p.get('run_id') else None
        out.append('%d. %s: %s' % (i, ', '.join('%s = %s' % (validate.name_of(k) if str(k).startswith('/') else k,
                                                              summary.fmt(x)) for k, x in (p.get('values') or {}).items()),
                                   'skipped' if v is None else '%s dB' % summary.fmt(v - ref)))
    return out

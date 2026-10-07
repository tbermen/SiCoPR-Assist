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
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import hashlib
import json
import os
import subprocess
import sys

from sicopr_assist import config_model, core, engine, summary, validate, xlsx_io
from sicopr_assist.project import result_record

RUN_CASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_case.py')


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
    def __init__(self, project, child, echo):
        self.project = project
        self.child = list(child or child_command())
        self.echo = echo
        self.ctx = core.Context(project)
        self.known = list(self.ctx.runs)            # [(run id, fingerprint)] of complete runs, oldest first
        self.sic = engine.engine_sha256()

    def fingerprint(self, wc, channels):
        fields, err = config_model.loaded_fields(wc)
        if err:
            return None, err
        shas = [_sha(self.ctx.path(p)) for p, _ in channels]
        return core._fingerprint(fields, shas, self.sic), None

    def run_point(self, wc, channels, notes=()):
        """One point: reuse an equal earlier run, or run it. Returns {'run_id', 'new', 'reused_from', 'skipped',
        'status', 'message'}."""
        res = validate.validate_config(wc)
        if res['status'] == 'stop':
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_config fails: %s' % res['text'], 'message': res['text']}
        stops, more = core.input_check(wc, [(self.ctx.path(p), r) for p, r in channels])
        if stops:
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_inputs fails: %s' % stops[0], 'message': stops[0]}
        fp, err = self.fingerprint(wc, channels)
        if fp is None:
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_config fails: %s' % err, 'message': err}
        same = next((rid for rid, f in self.known if core._same_fingerprint(f, fp)), None)
        if same is not None:
            return {'run_id': same, 'new': False, 'reused_from': same, 'skipped': None, 'status': 'reused',
                    'message': None}
        rid = self.project.next_run_id()
        folder = self.project.run_dir(rid)
        os.makedirs(folder, exist_ok=True)
        run_wc = _with_result_dir(wc, folder)
        self.project.write_working_config(rid, run_wc)
        csv_path = config_model.write_run_csv(run_wc, self.project.run_csv_path(rid))
        status, message = self._child(rid, csv_path, channels, fingerprint_hash(fp), list(notes) + list(more))
        if status == 'complete':
            self.known.append((rid, fp))
        return {'run_id': rid, 'new': True, 'reused_from': None, 'skipped': None, 'status': status,
                'message': message}

    def _child(self, rid, csv_path, channels, fp_hash, notes):
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
        env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
        log = os.path.join(p.run_dir(rid), 'run.log')
        with open(log, 'w', encoding='utf-8', newline='\n') as f:
            proc = subprocess.Popen(cmd, cwd=p.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1)
            for line in proc.stdout:
                f.write(line)
                if self.echo:
                    self.echo(line.rstrip('\n'))
            code = proc.wait()
        try:
            rec = p.read_result(rid)
        except (OSError, ValueError):
            rec = None
        if rec is None:
            tail = open(log, encoding='utf-8', errors='replace').read().strip().splitlines()[-3:]
            msg = 'the run stopped with exit code %s and wrote no result: %s' % (code, ' / '.join(tail))
            p.write_result(rid, result_record(run_id=rid, status='failed', message=msg, sicopr_sha256=self.sic,
                                              config_csv=csv_path, fingerprint=fp_hash))
            return 'failed', msg
        return rec['status'], rec.get('message')


def carry_out(project, out, child=None, echo=None):
    """Carry out a PLAN that core.handle returned and recorded. child replaces the command that runs one case
    (a test gives a stand-in that writes a seeded result.json); echo, when given, receives each line the child
    prints. Returns {'status', 'run_ids', 'points', 'lines'} and fills in the history record."""
    if out.get('type') != 'PLAN':
        raise ValueError('only a PLAN is carried out')
    rec = _record_of(project, out)
    steps = [(s['op'], s.get('args') or {}) for s in out['steps']]
    ops = [op for op, _ in steps]
    R = _Runner(project, child, echo)
    ctx = R.ctx
    lines = []
    if not out.get('points') and not any(op in ops for op in ('run_com', 'run_batch', 'build_matrix', 'export_xlsx')):
        return {'status': 'ok', 'run_ids': [], 'points': [], 'lines': lines}      # shown already (Decision 8)

    last = ctx.last or {}
    source = dict(last.get('source') or {}) or None
    overrides = [dict(o) for o in last.get('overrides') or []]
    channels = [(c['path'], c.get('role') or 'thru') for c in last.get('channels') or []]
    base_run = ctx.last_run_id()
    imported = next((a for op, a in steps if op == 'import_config'), None)
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
    run_com = next((a for op, a in steps if op == 'run_com'), None)
    if run_com and run_com.get('thru_only'):
        channels = channels[:1]
    if not channels and any(op in ops for op in ('run_com', 'run_batch')):
        return _failed(project, rec, 'no channel file is known for this run')
    chan_recs = [{'path': _native(p), 'sha256': _sha(ctx.path(p)), 'role': r} for p, r in channels]
    fields = dict(source=source, channels=chan_recs, overrides=overrides)
    run_ids, points, status = [], [], 'ok'

    if 'build_matrix' in ops or 'run_batch' in ops or out.get('points'):
        for i, pt in enumerate(out.get('points') or [], 1):
            rec_pt = {'values': pt.get('values'), 'run_id': None, 'new': False, 'reused_from': None,
                      'skipped': pt.get('skipped')}
            if not pt.get('skipped'):
                point_wc = config_model.apply_changes(wc, list((pt.get('writes') or pt.get('values') or {}).items()))
                got = R.run_point(point_wc['config'], channels)
                rec_pt.update(run_id=got['run_id'], new=got['new'], reused_from=got['reused_from'],
                              skipped=got['skipped'])
                if got['status'] == 'failed':
                    rec_pt['skipped'] = 'the run failed: %s' % got['message']
                if got['run_id']:
                    run_ids.append(got['run_id'])
            points.append(rec_pt)
        fields.update(working_config=None, run_ids=run_ids, points=points)
    elif run_com is not None:
        got = R.run_point(wc, channels)
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
    for op, a in steps:
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

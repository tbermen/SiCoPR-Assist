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

A channel download (rows F1 to F12) is carried out in two parts. First the zip: downloaded with fetch.py into
.sicopr\\cache\\<interface>\\ (unless it is there), unpacked with every path checked, and its inventory written; the
core then plans the run matrix from the cache (core.fetch_followup), and that outcome is handed back under "next".
Then that plan, a batch whose points each name their own channel files.
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
import glob
import hashlib
import json
import os
import subprocess
import sys
import threading
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
    fields, chans, sic, mat = fp
    h = hashlib.sha256()
    for k in sorted(fields):
        v = fields[k]
        h.update(k.encode('utf-8'))
        h.update(repr(v.tolist() if hasattr(v, 'tolist') else v).encode('utf-8'))
    h.update(repr((chans, sic) + ((True,) if mat else ())).encode('utf-8'))
    return h.hexdigest()


def _with_result_dir(wc, folder):
    new = copy.deepcopy(wc)
    key = next((k for k in new['main'] if k.strip().lower() == 'result_dir'), 'RESULT_DIR')
    new['main'][key] = folder + os.sep
    new['links'].pop(key, None)
    return new


STOPPED = 'stopped by the user'


class _Runner:
    def __init__(self, project, child, progress, cancel=None):
        self.project = project
        self.cancel = cancel                        # a threading.Event: Stop in the GUI (GUI_DESIGN.md section 10)
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

    def fingerprint(self, wc, channels, export=False):
        fields, err = config_model.loaded_fields(wc)
        if err:
            return None, err
        keys = core.channel_keys((r, _sha(self.ctx.path(p))) for p, r in channels)
        return core._fingerprint(fields, keys, self.sic, export), None

    def run_point(self, wc, channels, head, notes=(), export=False):
        """One point: reuse an equal earlier run, or run it. head starts its status line (the step, and for a batch
        the point n of N). export: the engine's .mat export is on (the dashboard needs it), and only a run that had it
        is reused. Returns {'run_id', 'new', 'reused_from', 'skipped', 'status', 'message'}."""
        if self.cancel is not None and self.cancel.is_set():
            self.say('status', '%s: skipped, %s' % (head, STOPPED))
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped', 'skipped': STOPPED,
                    'message': STOPPED}
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
        fp, err = self.fingerprint(wc, channels, export)
        if fp is None:
            self.say('status', '%s: skipped, validate_config fails: %s' % (head, err))
            return {'run_id': None, 'new': False, 'reused_from': None, 'status': 'skipped',
                    'skipped': 'validate_config fails: %s' % err, 'message': err}
        same = next((rid for rid, f in self.known if core._same_fingerprint(f, fp)), None)
        if same is not None:
            self.say('status', '%s: the inputs equal those of %s%s, so its results are reused and nothing runs'
                     % (head, same, ', which has the .mat export' if export else ''))
            return {'run_id': same, 'new': False, 'reused_from': same, 'skipped': None, 'status': 'reused',
                    'message': None}
        rid = self.project.next_run_id()
        folder = self.project.run_dir(rid)
        os.makedirs(folder, exist_ok=True)
        run_wc = _with_result_dir(wc, folder)
        self.project.write_working_config(rid, run_wc)
        csv_path = config_model.write_run_csv(run_wc, self.project.run_csv_path(rid))
        status, message = self._child(rid, csv_path, channels, fingerprint_hash(fp), list(notes) + list(more), head,
                                      export)
        if status == 'complete':
            self.known.append((rid, fp))
        return {'run_id': rid, 'new': True, 'reused_from': None, 'skipped': None, 'status': status,
                'message': message}

    def _child(self, rid, csv_path, channels, fp_hash, notes, head, export=False):
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
        if export:
            cmd.append('--export-mat')
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
                if self.cancel is not None:      # Stop: the child is terminated, and its run is recorded failed
                    threading.Thread(target=_terminate_on, args=(proc, self.cancel), daemon=True).start()
                for line in proc.stdout:
                    said.append(line.rstrip('\n'))
                    self.say('engine', said[-1])
                code = proc.wait()
                took = elapsed_text(time.time() - t0)
                try:
                    rec = p.read_result(rid)
                except (OSError, ValueError):
                    rec = None
                if self.cancel is not None and self.cancel.is_set():
                    msg = '%s after %s; no result of this run is kept' % (STOPPED, took)
                    p.write_result(rid, result_record(run_id=rid, status='failed', message=msg, sicopr_sha256=self.sic,
                                                      config_csv=csv_path, fingerprint=fp_hash, export_mat=export))
                    rec = {'status': 'failed', 'message': msg}
                if rec is None:
                    msg = 'the run stopped with exit code %s and wrote no result: %s' % (code, ' / '.join(said[-3:]))
                    p.write_result(rid, result_record(run_id=rid, status='failed', message=msg, sicopr_sha256=self.sic,
                                                      config_csv=csv_path, fingerprint=fp_hash, export_mat=export))
                    rec = {'status': 'failed', 'message': msg}
                if rec['status'] == 'complete':
                    self.say('status', '%s finished in %s: %s' % (rid, took, _headline(rec)))
                else:
                    self.say('status', '%s failed after %s: %s' % (rid, took, rec.get('message')))
            finally:
                self.log = None
        self.last_log = log
        return rec['status'], rec.get('message')


def _terminate_on(proc, cancel):
    """Terminate proc once cancel is set, unless it ends first."""
    while proc.poll() is None:
        if cancel.wait(0.2):
            if proc.poll() is None:
                proc.terminate()
            return


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
    if op == 'infer_interface':
        return '%s (%s)' % (a.get('interface'), a.get('how'))
    if op == 'select_zip':
        return a.get('zip') or ''
    if op in ('download', 'extract', 'inventory'):
        what = a.get('path') or a.get('folder') or ''
        return '%s%s' % (what, ', done before this plan' if a.get('done') else '')
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


def open_folder(path):
    """Open the folder that holds path in the file manager, with the file selected where the system can (row FB06).
    Returns a line to show, or None. Started from an argument list, no shell; a failure is reported, not raised."""
    try:
        if sys.platform.startswith('win'):
            subprocess.Popen(['explorer', '/select,' + os.path.abspath(path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', os.path.abspath(path)])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(os.path.abspath(path))], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except OSError as e:
        return 'the folder could not be opened (%s); the file is %s' % (e, path)
    return None


def _export_feedback(project, a, opener):
    """Write the feedback file (Decision 10). For Send feedback, give the address and subject and open the folder.
    Nothing is sent."""
    from sicopr_assist import feedback
    path = feedback.write(project, os.path.join(project.root, _native(a['path'])))
    lines = ['feedback written to %s (%d bytes); read it before you send it' % (project.relative(path),
                                                                              os.path.getsize(path))]
    if a.get('send'):
        c = core.feedback_contact()
        lines += ['email that file to %s' % c['address'], 'subject: %s' % c['subject'],
                  'SiCoPR-Assist sends nothing itself and makes no network connection for feedback']
        said = opener(path) if opener else None
        if said:
            lines.append(said)
    return lines


def set_project_setting(project, name, value):
    """Write name = value into the project settings file, replacing any line that sets name; value None removes
    that line (rows TU06, Decision 4). Returns the file's path."""
    import re
    path = project.settings_path
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read().splitlines()
    except OSError:
        text = []
    keep = [ln for ln in text if not re.match(r'\s*%s\s*[=:]' % re.escape(name), ln, re.I)]
    if value is not None:
        if not any(ln.strip().startswith('[') for ln in keep):
            keep = ['[limits]'] + keep
        keep.append('%s = %s' % (name, value))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(keep) + ('\n' if keep else ''))
    return path


def start_gui(app, folder, port=None, no_browser=False):
    """SiCoPR's GUI (app, its gui/app.py) with the Assist panel, on the project folder: started from an argument list,
    no shell, with the folder opened (--dir) and made the run directory (--run-dir), and the project named to the
    panel by SICOPR_ASSIST_PROJECT. Bytecode writing is off, so SiCoPR's folder gets no .pyc (Rule 1). Waits for it
    and returns its exit code."""
    env = dict(os.environ, SICOPR_ASSIST_PROJECT=folder, PYTHONDONTWRITEBYTECODE='1')
    if port:
        env['SICOPR_GUI_PORT'] = str(port)
    cmd = [sys.executable, app, '--dir', folder, '--run-dir', folder] + (['--no-browser'] if no_browser else [])
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


def open_page(path):
    """Open the dashboard page in the browser (row D1). Returns a line to show when that fails, else None."""
    import pathlib
    import webbrowser
    try:
        ok = webbrowser.open(pathlib.Path(os.path.abspath(path)).as_uri())
    except Exception as e:                       # noqa: BLE001 - the page is written; say where it is
        return 'the page could not be opened (%s); it is %s' % (e, path)
    return None if ok else 'no browser could be started; the page is %s' % path


def fetch_pending(out):
    """Whether a channel-download plan still has its download, its unpacking or its inventory to do."""
    return any(s['op'] in ('download', 'extract', 'inventory') and not (s.get('args') or {}).get('done')
               for s in out.get('steps') or [])


def write_inventory(path, rows):
    """inventory.csv of an unpacked zip (core.INVENTORY_COLUMNS), which the user may correct (row F6)."""
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=core.INVENTORY_COLUMNS, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in core.INVENTORY_COLUMNS})
    return path


def _fetch_stage(project, out, rec, progress):
    """The download part of a channel-download plan (rows F1 to F12): the zip is downloaded into .sicopr\\cache
    (unless it is there), unpacked with every member path checked, and its inventory written; then the core plans
    the run matrix from the cache (core.fetch_followup), and that outcome is returned under 'next' for the caller to
    show and, if it is a PLAN, to carry out. Runs no COM. A download or unpacking that does not complete leaves
    nothing in the cache, and 'next' is the STOP that says why (row F9)."""
    import shutil
    from sicopr_assist import fetch

    def say(text, kind='status'):
        if progress:
            progress(kind, text)
    steps = [(s['op'], s.get('args') or {}) for s in out['steps']]
    sel = next(a for op, a in steps if op == 'select_zip')
    iface, name = sel['interface'], sel['zip']
    zpath = core.cached_zip(project, iface, name)
    folder = core.unpack_dir(project, iface, name)
    inv = core.inventory_path(project, iface, name)
    lines = list((out.get('tutor') or {}).get('lines') or [])

    def stopped(why):
        project.update_history(rec['seq'], status='failed', reason=why)
        say(why)
        nxt = core.fetch_followup(project, out, failure=why)
        return {'status': 'failed', 'run_ids': [], 'points': [], 'lines': lines, 'next': nxt}
    files, warnings = None, []
    for k, (op, a) in enumerate(steps):
        if op not in ('import_config', 'infer_interface', 'fetch_index', 'select_zip', 'download', 'extract',
                      'inventory'):
            break
        detail = _step_detail(op, a)
        say('step %d of %d: %s%s' % (k + 1, len(steps), op, ': ' + detail if detail else ''))
        if a.get('done'):
            continue
        if op == 'download':
            t0 = time.time()
            try:
                got = fetch.download(a['url'], zpath, core.partial_path(project, name), retries=a.get('retries', 1),
                                     say=lambda t: say(t, 'engine'))
            except fetch.FetchError as e:
                return stopped('The download of %s is incomplete: %s (download_retries = %s). Nothing was kept in the '
                               'cache, and nothing runs.' % (name, e, a.get('retries', 1)))
            say('downloaded %s (%s) in %s%s' % (name, _size_text(got['bytes']), elapsed_text(time.time() - t0),
                                                ', on try %d' % got['tries'] if got['tries'] > 1 else ''))
        elif op == 'extract':
            shutil.rmtree(folder, ignore_errors=True)
            if os.path.exists(inv):
                os.remove(inv)
            try:
                un = fetch.unpack(zpath, folder)
            except fetch.FetchError as e:
                if os.path.exists(zpath):        # a zip that cannot be unpacked safely is not kept either
                    os.remove(zpath)
                return stopped('%s. It was removed from the cache, and nothing runs.' % e)
            files, warnings = un['files'], un['warnings']
            say('unpacked %d files into %s' % (len(files), project.relative(folder)))
            for w in warnings:
                say('warning: %s' % w)
        elif op == 'inventory':
            if files is None:                    # unpacked by an earlier plan: the files as they are on disk
                files = sorted(os.path.relpath(os.path.join(d, n), folder).replace(os.sep, '/')
                               for d, _, ns in os.walk(folder) for n in ns)
            rows = core.fetch_inventory(folder, files, engine.known_channels())
            write_inventory(inv, rows)
            say('inventory written to %s: %d files' % (project.relative(inv), len(rows)))
    nxt = core.fetch_followup(project, out, announce=['warning: %s' % w for w in warnings])
    return {'status': 'ok', 'run_ids': [], 'points': [], 'lines': lines, 'next': nxt}


def follow(project, out, show=None, lines=None, **kw):
    """Carry out a PLAN, then follow a channel download (rows F1 to F12) the same way wherever it is asked for
    (Decision 13): the zip first, then the outcome the core plans from it, shown with show(outcome) and, if it is a
    PLAN, carried out. lines(list) gets the lines of each part as it ends. kw goes to carry_out. Returns the last
    outcome and what carrying it out gave."""
    done = carry_out(project, out, **kw)
    if lines:
        lines(done['lines'])
    while done.get('next') is not None:          # a channel download: what the core plans once the zip is unpacked
        out = done['next']
        if show:
            show(out)
        if out['type'] != 'PLAN':
            break
        if fetch_pending(out):                   # the zip should be in the cache now: never download in a loop
            if lines:
                lines(['the downloaded zip is not in the cache as planned, so nothing more is done'])
            break
        done = carry_out(project, out, **kw)
        if lines:
            lines(done['lines'])
    return out, done


def carry_out(project, out, child=None, progress=None, open_folder=open_folder, rscript=None, open_page=open_page,
              cancel=None):
    """Carry out a PLAN that core.handle returned and recorded. child replaces the command that runs one case
    (a test gives a stand-in that writes a seeded result.json). progress, when given, is called with (kind, text)
    for every line said while the plan is carried out (Decision 17; see line_text for the form shown).
    open_folder opens a folder for Send feedback, rscript replaces the Rscript command of the dashboard (a list;
    default: the Rscript engine.find_rscript finds), and open_page opens the dashboard page (tests give stand-ins).
    Returns {'status', 'run_ids', 'points', 'lines'} and fills in the history record. A channel-download plan whose
    zip is not yet downloaded or unpacked does only that part (_fetch_stage) and adds 'next', the outcome the core
    plans from the cache. cancel: a threading.Event that stops the plan (Stop in the GUI): no further point starts,
    the child under way is terminated, and the record ends failed."""
    if out.get('type') != 'PLAN':
        raise ValueError('only a PLAN is carried out')
    rec = _record_of(project, out)
    if fetch_pending(out):                       # a channel download: the zip first, then the core plans the runs
        return _fetch_stage(project, out, rec, progress)
    steps = [(s['op'], s.get('args') or {}) for s in out['steps']]
    ops = [op for op, _ in steps]
    R = _Runner(project, child, progress, cancel)
    ctx = R.ctx
    lines = []
    for op, a in steps:                          # steps that write a file and run nothing (Decisions 10 and 11)
        if op == 'export_feedback':
            lines += _export_feedback(project, a, open_folder)
        elif op == 'set_setting':
            path = set_project_setting(project, a['name'], a.get('value'))
            done = 'removed the %s line' % a['name'] if a.get('value') is None else \
                'wrote %s = %s' % (a['name'], a['value'])
            lines.append('%s in %s' % (done, project.relative(path)))
    tutor_lines = list((out.get('tutor') or {}).get('lines') or [])      # shown after the plan (Decision 11)
    if not out.get('points') and not any(op in ops for op in ('run_com', 'run_batch', 'build_matrix', 'export_xlsx',
                                                              'export_mat')):
        return {'status': 'ok', 'run_ids': [], 'points': [], 'lines': lines + tutor_lines}   # shown already (Decision 8)
    said = set()

    def say_step(k, more=''):
        op, a = steps[k]
        detail = _step_detail(op, a)
        R.say('status', 'step %d of %d: %s%s%s' % (k + 1, len(steps), op, ': ' + detail if detail else '', more))
        said.add(k)
    first_run = next((k for k, op in enumerate(ops) if op in ('run_com', 'run_batch', 'export_mat')), len(ops))

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
            # the roles as the plan gives them (the selection in the GUI's tabs, Decision 20), else from the names
            roles = next((a.get('roles') for op, a in steps if op == 'run_com' and a.get('roles')), None)
            channels = list(zip(named, roles)) if roles and len(roles) == len(named) else core.channel_roles(named)
        synthetic = imported.get('example_channel') if imported else None
        if synthetic and not os.path.exists(ctx.path(synthetic)):
            # the example setup in a folder with no channel file (Decision 22): its synthetic THRU is written now
            from sicopr_assist import example_channel
            os.makedirs(os.path.dirname(ctx.path(synthetic)), exist_ok=True)
            n, il, _ = example_channel.write(ctx.path(synthetic))
            R.say('status', 'wrote %s: a synthetic %g mm lossy line (%d points, %.1f dB at 53.125 GHz), not a '
                            'measured channel' % (_native(synthetic), example_channel.LENGTH_MM, n, il))
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
    point_channels = any(pt.get('channels') for pt in out.get('points') or [])     # a fetched batch names its own
    if not channels and not point_channels and any(op in ops for op in ('run_com', 'run_batch', 'export_mat')):
        return _failed(project, rec, 'no channel file is known for this run')
    chan_recs = [{'path': _native(p), 'sha256': _sha(ctx.path(p)), 'role': r} for p, r in channels]
    fields = dict(source=source, channels=chan_recs, overrides=overrides)
    run_ids, points, status = [], [], 'ok'
    for k in range(first_run):                  # the steps before the run, as the run starts
        if k not in said:
            say_step(k)
    head = 'step %d of %d: %s' % (first_run + 1, len(steps), ops[first_run]) if first_run < len(ops) else 'run'
    if first_run < len(ops) and ops[first_run] != 'export_mat':     # export_mat says its own line, below
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
                if pt.get('channels'):           # a fetched batch: each point has its own channel files, no change
                    point_wc = {'config': wc}
                    point_chans = [(p, r) for p, r in pt['channels']]
                else:
                    point_wc = config_model.apply_changes(wc, list((pt.get('writes') or pt.get('values') or {}).items()))
                    point_chans = channels
                got = R.run_point(point_wc['config'], point_chans, where)
                rec_pt.update(run_id=got['run_id'], new=got['new'], reused_from=got['reused_from'],
                              skipped=got['skipped'])
                if got['status'] == 'failed':
                    rec_pt['skipped'] = 'the run failed: %s' % got['message']
                if got['run_id']:
                    run_ids.append(got['run_id'])
            points.append(rec_pt)
        fields.update(working_config=None, run_ids=run_ids, points=points)
        if cancel is not None and cancel.is_set():
            left = sum(1 for pt in points if pt.get('skipped') == STOPPED)
            status = 'failed'
            fields.update(status='failed', reason='%s; %d point%s left' % (STOPPED, left, '' if left == 1 else 's'))
    elif run_com is not None:
        got = R.run_point(wc, channels, head, export=bool(run_com.get('export_mat')))
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

    # what is shown once the plan is carried out, and the dashboard after the run (rows D1, CB17, C2)
    mat_run, pages, no_page = None, [], None
    for k, (op, a) in enumerate(steps):
        if k not in said and op in ('summarize', 'batch_summary', 'diff_results', 'export_xlsx', 'show_tutor'):
            say_step(k)
        at = 'step %d of %d: %s' % (k + 1, len(steps), op)
        if op == 'export_mat':
            said.add(k)
            if status != 'ok':
                no_page = 'the run did not happen, so there is no .mat export'
                R.say('status', '%s: skipped, %s' % (at, no_page))
                continue
            got = R.run_point(wc, channels, at, export=True)
            if got['run_id'] and got['status'] in ('complete', 'reused'):
                mat_run = got['run_id']
                if mat_run not in run_ids:
                    run_ids.append(mat_run)
                    project.update_history(rec['seq'], run_ids=run_ids, working_config=project.relative(
                        project.working_config_path(mat_run)))
            else:
                no_page = 'the run with the .mat export did not complete: %s' % got['message']
        elif op == 'render_dashboard':
            said.add(k)
            if mat_run is None:
                R.say('status', '%s: skipped, %s' % (at, no_page))
                continue
            pages, problems = _render(R, project, mat_run, rscript, at)
            if problems:
                no_page = '; '.join(problems)
        elif op == 'open_report':
            said.add(k)
            if not pages:
                R.say('status', '%s: skipped, no page was written' % at)
                lines.append('the dashboard was not built: %s' % (no_page or 'no page was written'))
                status = 'failed'
                project.update_history(rec['seq'], status='failed', reason='the dashboard was not built: %s' % no_page)
                continue
            for page in pages:
                R.say('status', '%s: %s' % (at, project.relative(page)))
                lines.append('dashboard: %s (%s), with its lib folder beside it' % (project.relative(page),
                                                                                   _size_text(os.path.getsize(page))))
                problem = open_page(page) if open_page else None
                if problem:
                    lines.append(problem)
        if op == 'show_tutor':
            lines += tutor_lines
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


def _size_text(n):
    return '%.1f MB' % (n / 1e6) if n >= 1e5 else '%d bytes' % n


def _render(R, project, rid, rscript, head):
    """Rscript on SiCoPR's R/com_analysis.R for each .mat export in the folder of run rid (row D1), started from an
    argument list with that run folder as its working folder, never SiCoPR's (Rule 1): the page
    (<run>_caseNN_report.html) and its lib folder land beside the .mat. Every line Rscript prints is passed on as a
    child line (Decision 17). Returns ([pages written], [problems])."""
    folder = project.run_dir(rid)
    mats = sorted(glob.glob(os.path.join(folder, '*_case[0-9]*.mat')))
    if not mats:
        R.say('status', '%s: no .mat export in %s' % (head, project.relative(folder)))
        return [], ['no .mat export in %s' % project.relative(folder)]
    script = engine.com_analysis_script()
    if rscript is None:
        found = engine.find_rscript()
        rscript = [found] if found else None
    if rscript is None or script is None:
        why = 'Rscript was not found' if rscript is None else 'the SiCoPR in use has no R/com_analysis.R'
        R.say('status', '%s: %s' % (head, why))
        return [], [why]
    pages, problems = [], []
    for mat in mats:
        name = os.path.basename(mat)
        R.say('status', '%s: Rscript com_analysis.R %s, in %s' % (head, name, project.relative(folder)))
        t0 = time.time()
        try:
            proc = subprocess.Popen(list(rscript) + [script, name], cwd=folder, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                                    errors='replace', bufsize=1)
        except OSError as e:
            R.say('status', '%s: Rscript could not be started: %s' % (head, e))
            problems.append('Rscript could not be started: %s' % e)
            continue
        for line in proc.stdout:
            R.say('engine', line.rstrip(chr(10)))
        code = proc.wait()
        page = mat[:-len('.mat')] + '_report.html'
        took = elapsed_text(time.time() - t0)
        if code == 0 and os.path.isfile(page):
            R.say('status', '%s: written in %s: %s (%s)' % (head, took, project.relative(page),
                                                            _size_text(os.path.getsize(page))))
            pages.append(page)
        else:
            R.say('status', '%s: Rscript stopped after %s with exit code %s and wrote no page for %s'
                  % (head, took, code, name))
            problems.append('Rscript stopped with exit code %s on %s' % (code, name))
    return pages, problems


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

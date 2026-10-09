"""The Assist panel's endpoints (GUI_DESIGN.md section 8), as plain functions over the core and a small Panel that
routes HTTP to them for SiCoPR's GUI.

Nothing here reaches past the core: a phrase goes to core.handle, a Config-view edit to core.edit, and a PLAN is
carried out by run.follow in a worker thread, exactly as the command line carries it out (Decision 13). The functions
take a Project and return plain data, so si-gui can call them without HTTP. Every path the page gives is checked
against the project folder and the directories the user opened in SiCoPR's GUI (host.roots()).

Everything the GUI does is in the project's history (GUI_DESIGN.md section 7a): phrases, answers, edits and opens are
records the core writes; run, stop, view and error are log records written here, each with origin "gui".
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import collections
import copy
import os
import re
import threading
import time
import traceback

from sicopr_assist import __version__, config_model, core, run, summary, validate
from sicopr_assist.project import Project, history_record, is_command, read_settings

SAVE_HINT = 'Save the working config from the Assist panel: Save that config as data\\config_new.xlsx.'
RUN_NOTE = ('this runs the workbook file as saved, without the working config of SiCoPR-Assist; run from the panel to '
            'include it')
RUN_TAB_BUSY = 'a run started from the Run tab is in progress, so nothing runs; wait for it, or stop it in the Run tab'
BUSY = 'a run started from SiCoPR-Assist is in progress'
MAX_LINES = 2000                 # progress lines the panel keeps, as SiCoPR's runner caps its chunks
ERROR_GAP = 60.0                 # seconds: one error record per distinct message per minute
_RUN_OPS = ('run_com', 'run_batch', 'build_matrix', 'export_mat', 'download')


# ----------------------------------------------------------------------------- paths
def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def inside(path, roots):
    """Whether path is inside one of roots."""
    full = _norm(path)
    for r in roots:
        try:
            if os.path.commonpath([full, _norm(r)]) == _norm(r):
                return True
        except ValueError:                       # another drive
            continue
    return False


def allowed(project, path, roots):
    """The absolute path when it is inside the project folder or an opened directory, else None. A relative path is
    read against the project folder, so ..\\ that leaves it is refused like an absolute path elsewhere."""
    if not path or not isinstance(path, str):
        return None
    full = os.path.abspath(path if os.path.isabs(path) else os.path.join(project.root if project else '', path))
    keep = list(roots) + ([project.root] if project else [])
    return full if inside(full, keep) else None


# ----------------------------------------------------------------------------- [TX RX] halves
def _rows_of(value):
    """A literal split into rows of tokens. From SiCoPR's gui/config_io.py (55c3f71), as xlsx_io.py is."""
    s = str(value).strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    return [[t for t in re.split(r'[,\s]+', part.strip()) if t] for part in s.split(';')]


def split_tx_rx(value):
    """(tx_text, rx_text) of a [TX RX] value, else None (SiCoPR's gui/config_io.py split_tx_rx)."""
    rows = _rows_of(value)
    if len(rows) == 2 and all(rows):
        return ' '.join(rows[0]), ' '.join(rows[1])
    if len(rows) == 1 and len(rows[0]) == 2:
        return rows[0][0], rows[0][1]
    return None


def join_tx_rx(tx, rx, original):
    """The two halves in the shape original had (SiCoPR's gui/config_io.py join_tx_rx)."""
    orig = str(original).strip()
    body = ('%s ; %s' if len(_rows_of(original)) == 2 else '%s %s') % (str(tx).strip(), str(rx).strip())
    return '[%s]' % body if orig.startswith('[') and orig.endswith(']') else body


def _main_key(wc, name):
    k = next((x for x in wc['main'] if x.strip().lower() == str(name).strip().lower()), None)
    return k if k is not None else name


def to_changes(wc, edits):
    """[(json_path, value)] from Config-view edits [{key, value}] (GUI_DESIGN.md section 6): name is /main/name,
    BLOCK/name is /packages/BLOCK/name, and a #tx or #rx half is put back with the other half of the working value,
    in the shape that value has. Raises ValueError for a key that cannot be placed."""
    out, halves = [], {}
    for e in edits:
        key, value = str(e.get('key') or ''), e.get('value')
        if not key:
            raise ValueError('an edit without a key')
        if '#' in key:
            name, _, side = key.rpartition('#')
            if side not in ('tx', 'rx') or not name:
                raise ValueError('%s is not a half of a [TX RX] value' % key)
            halves.setdefault(name, {})[side] = value
        elif '/' in key:
            block, _, name = key.partition('/')
            out.append(('/packages/%s/%s' % (block, name), value))
        else:
            out.append(('/main/' + _main_key(wc, key), value))
    for name, sides in halves.items():
        k = _main_key(wc, name)
        whole = wc['main'].get(k)
        pair = split_tx_rx(whole) if whole is not None else None
        if pair is None:
            raise ValueError('%s holds %s, not a [TX RX] pair, so it cannot be edited one half at a time'
                             % (k, validate.show(whole)))
        tx = core._view_text(sides['tx']) if 'tx' in sides else pair[0]
        rx = core._view_text(sides['rx']) if 'rx' in sides else pair[1]
        out.append(('/main/' + k, join_tx_rx(tx, rx, whole)))
    return out


# ----------------------------------------------------------------------------- reading the project
def working_line(project):
    """The project line of the panel header: working config run_0003, 2 overrides, 1 edit from the config view."""
    hist = project.read_history()
    rec = next((r for r in reversed(hist) if r.get('working_config')), None)
    if rec is None:
        return 'no working config yet'
    name = os.path.splitext(os.path.basename(rec['working_config']))[0]
    k = next((i for i in range(len(hist) - 1, -1, -1) if hist[i].get('run_ids') and is_command(hist[i])), -1)
    edits = sum(1 for r in hist[k + 1:] if r.get('kind') == 'edit' and r.get('working_config'))
    n = len(rec.get('overrides') or [])
    return 'working config %s, %d override%s%s' % (name, n, '' if n == 1 else 's',
                                                   ', %d edit%s from the config view' % (edits, '' if edits == 1 else 's')
                                                   if edits else '')


def source_of(project):
    """(absolute path, 'workbook' | 'other') of the source of the working config, or (None, None)."""
    ctx = core.Context(project)
    rec = ctx.last
    if rec and (rec.get('source') or {}).get('path'):
        p = ctx.path(rec['source']['path'])
        return p, 'workbook' if p.lower().endswith(('.xlsx', '.xls')) else 'other'
    p = ctx.source_path
    return (p, 'workbook') if p else (None, None)


def state(project, running=False):
    """GET state: the project line, the source workbook, the pending question, whether a plan is running."""
    if project is None:
        return {'version': __version__, 'project': None, 'line': 'no project folder: use Browse to choose one',
                'source': None, 'source_kind': None, 'pending': None, 'running': False}
    try:
        pending = project.read_pending()
    except (OSError, ValueError):
        pending = None
    src, kind = source_of(project)
    q = (pending or {}).get('outcome') or None
    return {'version': __version__, 'project': project.root, 'line': working_line(project), 'source': src,
            'source_kind': kind, 'running': running,
            'pending': None if q is None else {'seq': pending.get('seq'), 'phrase': pending.get('phrase'),
                                               'question': q.get('question'), 'changes': q.get('changes') or [],
                                               'announce': q.get('announce') or []}}


_IMPORTS = {}


def _workbook(path):
    """The source workbook as imported, cached by SHA-256."""
    sha = core._sha(path)
    if sha not in _IMPORTS:
        if len(_IMPORTS) > 8:
            _IMPORTS.clear()
        _IMPORTS[sha] = config_model.import_config(path)[0]
    return _IMPORTS[sha]


def _origins(hist):
    """{json_path: (tag, seq)}: the record that last set each key. An open that keeps overrides carries them over,
    so it does not count as where they came from."""
    out = {}
    for r in hist:
        for c in ((r.get('plan') or {}).get('changes') or []):
            if not c.get('applied'):
                continue
            jp = c.get('json_path')
            pattern = r.get('pattern') or ''
            if c.get('kind') == 'linked':
                out[jp] = ('linked', r.get('seq'))
            elif r.get('kind') == 'edit' or core.VIEW_SET in pattern:     # an edit, or the answer that finished one
                out[jp] = ('edited here #%s' % r.get('seq'), r.get('seq'))
            elif r.get('kind') != 'open' and core.VIEW_OPEN not in pattern:
                out[jp] = ('Assist #%s' % r.get('seq'), r.get('seq'))
    return out


def overlay(project, keys=None, changed=(), planned=None, planned_seq=None):
    """POST overlay: the working config laid over its source workbook (GUI_DESIGN.md section 6), as sicopr:overlay
    takes it: every key whose working value differs from the workbook's, with where it came from; the changes a
    pending question would make (proposed) and the keywords it offers (option n). keys: the field keys the Config
    view shows; a [TX RX] value shown as halves is sent as halves, and a keyword the view does not show goes to its
    Other settings block. changed: json paths of the last outcome, whose keys the view should bring into sight.
    planned: the PLAN being carried out (its seq planned_seq), shown before its runs end: its working config is
    recorded only when they do, and the user watches the view while they run."""
    src, kind = source_of(project) if project else (None, None)
    steps = [(s.get('op'), s.get('args') or {}) for s in (planned or {}).get('steps') or []]
    imported = next((a.get('path') for op, a in steps if op == 'import_config' and a.get('path')), None)
    ctx = core.Context(project) if project else None
    if imported:                                 # a first run: the workbook it imports is the source
        src = ctx.path(imported)
        kind = 'workbook' if src.lower().endswith(('.xlsx', '.xls')) else 'other'
    base = {'source': src, 'source_kind': kind, 'cells': {}, 'title': '', 'save_hint': SAVE_HINT,
            'run_note': RUN_NOTE, 'focus': [], 'packages': 0}
    if project is None or kind != 'workbook' or not os.path.isfile(src):
        return base
    book = _workbook(src)
    wc = copy.deepcopy(book) if imported else ctx.wc
    if wc is None or book is None:
        return base
    keys = set(keys or [])
    hist = ctx.history
    origin = _origins(hist)
    sets = [(a['json_path'], a.get('after')) for op, a in steps if op in ('set_param', 'add_param')]
    if sets:
        applied = config_model.apply_changes(wc, sets)
        wc = applied['config']
        for c in applied['changes']:
            origin[c['json_path']] = ('linked', planned_seq) if c['kind'] == 'linked' else \
                ('Assist #%s' % planned_seq, planned_seq)
    cells, packages = {}, 0

    def put(name, value, tag, note):
        if '%s#tx' % name in keys or '%s#rx' % name in keys:
            pair = split_tx_rx(value)
            wpair = split_tx_rx(book['main'].get(name)) if name in book['main'] else None
            if pair is not None:
                for i, side in enumerate(('tx', 'rx')):
                    if '%s#%s' % (name, side) in keys:
                        cells['%s#%s' % (name, side)] = {'value': pair[i], 'tag': tag,
                                                         'note': 'workbook %s' % (wpair[i] if wpair else
                                                                                  validate.show(book['main'].get(name)))
                                                         + note}
                return [name + '#tx', name + '#rx']
        cells[name] = {'value': value, 'tag': tag + ('' if name in book['main'] or name in keys else
                                                     ', not in the workbook'),
                       'note': ('workbook %s' % validate.show(book['main'][name]) if name in book['main'] else
                                'not in the workbook') + note}
        return [name]

    jp_keys = {}
    for k, v in wc['main'].items():
        if k.strip().lower() == 'result_dir':    # each run's own folder (row CP09), set by the runner, not a change
            continue
        w = book['main'].get(k, config_model.ABSENT)
        if w is not config_model.ABSENT and config_model.same_value(v, w):
            continue
        jp = '/main/' + k
        tag = (origin.get(jp) or ('Assist', None))[0]
        note = '; link %s removed' % book['links'][k] if k in book['links'] and k not in wc['links'] else ''
        jp_keys[jp] = put(k, v, tag, note)
    for b, params in wc['packages'].items():
        for k, v in params.items():
            w = (book['packages'].get(b) or {}).get(k, config_model.ABSENT)
            if w is config_model.ABSENT or not config_model.same_value(v, w):
                packages += 1
                key = '%s/%s' % (b, k)
                cells[key] = {'value': v, 'tag': (origin.get('/packages/%s/%s' % (b, k)) or ('Assist', None))[0],
                              'note': 'package block %s' % b}
                jp_keys['/packages/%s/%s' % (b, k)] = [key]
    try:
        pending = project.read_pending()
    except (OSError, ValueError):
        pending = None
    q = (pending or {}).get('outcome') or {}
    for c in q.get('changes') or []:
        if c.get('applied') or c.get('kind') not in ('set', 'add'):
            continue
        jp = c['json_path']
        try:
            block, name = core._jp_parts(jp)
        except ValueError:
            continue
        if block is None:
            jp_keys[jp] = put(name, c['after'], 'proposed', '; working value %s' % validate.show(c.get('before')))
    for i, opt in enumerate((q.get('question') or {}).get('options') or [], 1):
        name = re.sub(r'\s*\([^()]*\)\s*$', '', str(opt)).strip()
        k = next((x for x in wc['main'] if x.strip().lower() == name.lower()), None)
        if k is not None:
            prev = cells.get(k)
            put(k, wc['main'][k], 'option %d' % i, '' if prev is None else '; %s' % prev['tag'])
    focus = []
    for jp in changed or ():
        focus += jp_keys.get(jp, [])
    n = sum(1 for k in cells if '/' not in k)
    title = 'SiCoPR-Assist: %s; %d value%s laid over %s%s' % (
        working_line(project), n, '' if n == 1 else 's', os.path.basename(src),
        ', %d in package blocks' % packages if packages else '')
    return dict(base, cells=cells, title=title, focus=focus, packages=packages)


def history(project, limit=200):
    """GET history: every record, newest last (up to limit), and the phrases typed, newest first, for recall."""
    hist = project.read_history(log=True)
    phrases = []
    for r in reversed(hist):
        if r.get('kind') in (None, 'phrase') and r.get('phrase') and r['phrase'] not in phrases:
            phrases.append(r['phrase'])
    keep = ('seq', 'time', 'origin', 'kind', 'phrase', 'outcome', 'status', 'reason', 'run_ids', 'detail', 'chosen')
    recs = []
    for r in hist[-limit:]:
        x = {k: r.get(k) for k in keep}
        plan = r.get('plan') or {}
        x['plan'] = {'type': plan.get('type'), 'announce': plan.get('announce') or [],
                     'steps': [s.get('op') for s in plan.get('steps') or []], 'question': plan.get('question'),
                     'reason': plan.get('reason'), 'tutor': plan.get('tutor')} if plan else None
        recs.append(x)
    return {'records': recs, 'phrases': phrases}


def result(project, rid):
    """GET result: one run's summary card (summary.run_summary), and its folder."""
    if not re.fullmatch(r'run_\d{4,}', str(rid or '')):
        raise ValueError('not a run id: %s' % rid)
    got = summary.run_summary(project, rid)
    return dict(got, folder=project.run_dir(rid))


def batch(project, seq):
    """GET batch: the table of a batch command (summary.batch_rows) and where batch_summary.csv is."""
    rec = next((r for r in project.read_history() if str(r.get('seq')) == str(seq)), None)
    if rec is None:
        raise ValueError('no history record %s' % seq)
    rows = summary.batch_rows(project, rec['seq'], rec.get('points') or [])
    return {'seq': rec['seq'], 'lines': summary.batch_lines(rows),
            'csv': os.path.join(project.runs_dir, 'batch_summary.csv'),
            'folders': [project.run_dir(r) for r in rec.get('run_ids') or []]}


def settings(project):
    """GET settings: the settings in force, with where each came from."""
    return {'lines': core.settings_lines(read_settings(project))}


def log(project, kind, detail, outcome_type=None):
    """Write one GUI log record (run, stop, view, error) with origin gui. Returns its seq."""
    rec = history_record(origin='gui', kind=kind, detail=detail, outcome=outcome_type)
    return project.append_history(rec)['seq']


def _has_runs(out):
    return any(s.get('op') in _RUN_OPS for s in out.get('steps') or []) or bool(out.get('points'))


# ----------------------------------------------------------------------------- the panel behind SiCoPR's GUI
class Job:
    """A PLAN carried out in a worker thread, its progress lines kept in a bounded buffer polled by since."""

    def __init__(self, seq, out):
        self.seq = seq
        self.out = out
        self.lines = collections.deque(maxlen=MAX_LINES)
        self.count = 0
        self.started = time.time()
        self.last = self.started
        self.finished = None
        self.done = None
        self.outcomes = []
        self.pages = []
        self.cancel = threading.Event()
        self.error = None
        self.runs = _has_runs(out)
        self._lock = threading.Lock()

    def add(self, kind, text):
        with self._lock:
            self.lines.append((self.count, kind, run.line_text(kind, text)))
            self.count += 1
            self.last = time.time()

    def status(self, since=0):
        with self._lock:
            first = self.count - len(self.lines)
            resync = since < first
            lines = [[k, t] for n, k, t in self.lines if n >= since]
            return {'seq': self.seq, 'running': self.finished is None, 'lines': lines, 'next': self.count,
                    'resync': resync, 'quiet': time.time() - self.last,
                    'elapsed': (self.finished or time.time()) - self.started, 'done': self.done,
                    'outcomes': list(self.outcomes), 'pages': list(self.pages), 'error': self.error}


class Panel:
    """Routes /panel/assist/api/<path> (SiCoPR gui/README.md, Panels) to the functions above."""

    def __init__(self, root=None, child=None, stand_ins=None):
        self.root = root if root is not None else (os.environ.get('SICOPR_ASSIST_PROJECT') or None)
        self.child = child                       # a test gives the stand-in child (run.carry_out)
        self.stand_ins = dict(stand_ins or {})
        self.job = None
        self.errors = {}
        self._lock = threading.Lock()

    @property
    def project(self):
        return Project(self.root) if self.root and os.path.isdir(self.root) else None

    def busy(self):
        j = self.job
        return BUSY if j is not None and j.finished is None and j.runs else None

    def running(self):
        j = self.job
        return j is not None and j.finished is None

    # ---- the route
    def handle(self, method, path, query, body, host):
        try:
            got = self._route(method, path.strip('/'), query or {}, body or {}, host)
            return got if isinstance(got, tuple) else strict(got)
        except Exception as e:                    # noqa: BLE001 - recorded, then answered as a JSON error
            self.record_error('api %s %s' % (method, path), '%s: %s' % (type(e).__name__, e), traceback.format_exc())
            return 500, 'application/json', ('{"error": %s}' % _json_text('%s: %s' % (type(e).__name__, e))).encode()

    def record_error(self, where, message, trace=''):
        """One error record per distinct message per minute, so a loop cannot fill the history."""
        p = self.project
        now = time.time()
        if p is None or now - self.errors.get((where, message), -ERROR_GAP) < ERROR_GAP:
            return None
        self.errors[(where, message)] = now
        try:
            return log(p, 'error', {'where': where, 'message': message, 'trace': trace})
        except (OSError, ValueError):
            return None

    def _route(self, method, path, q, body, host):
        roots = host.roots() if host is not None else []
        if path == 'state':
            return state(self.project, self.running())
        if path == 'project' and method == 'POST':
            full = allowed(None, body.get('path'), roots)
            if not full or not os.path.isdir(full):
                return {'error': 'not a folder inside the directories opened in this GUI: %s' % body.get('path')}
            if self.running():
                return {'error': BUSY}
            self.root = full
            return state(self.project)
        p = self.project
        if p is None:
            return {'error': 'no project folder: use Browse to choose one'}
        if path == 'handle' and method == 'POST':
            return self.phrase(p, str(body.get('phrase') or ''), host)
        if path == 'job':
            j = self.job
            return {'idle': True} if j is None else j.status(int(q.get('since') or 0))
        if path == 'stop' and method == 'POST':
            return self.stop(p)
        if path == 'overlay':
            j = self.job if self.running() else None
            return overlay(p, body.get('keys') or [], body.get('changed') or [], j.out if j else None,
                           j.seq if j else None)
        if path == 'edit' and method == 'POST':
            return self.edit(p, body, roots)
        if path == 'open' and method == 'POST':
            return self.follow(p, body.get('path'), roots)
        if path == 'history':
            return history(p, int(q.get('limit') or 200))
        if path == 'result':
            return result(p, q.get('run'))
        if path == 'batch':
            return batch(p, q.get('seq'))
        if path == 'settings':
            return settings(p)
        if path == 'log' and method == 'POST':
            return self.page_log(p, body)
        return 404, 'application/json', b'{"error": "not an endpoint of the Assist panel"}'

    # ---- commands
    def phrase(self, p, phrase, host):
        """POST handle: core.handle, then a PLAN carried out in the worker."""
        if not phrase.strip():
            return {'error': 'type a command'}
        if self.running():
            return {'error': 'a plan is being carried out; wait for it, or press Stop'}
        out = core.handle(phrase, p, origin='gui')
        seq = (p.last_record() or {}).get('seq')
        res = {'outcome': out, 'seq': seq, 'job': False}
        if out['type'] != 'PLAN':
            return res
        if _has_runs(out) and host is not None and host.com_running():
            p.update_history(seq, status='failed', reason=RUN_TAB_BUSY)
            return dict(res, refused=RUN_TAB_BUSY)
        self.start(p, seq, out)
        return dict(res, job=True)

    def start(self, p, seq, out):
        job = Job(seq, out)
        self.job = job
        if job.runs:                              # a run record for a plan that runs something (section 7a)
            log(p, 'run', {'event': 'start', 'command': seq, 'steps': [s['op'] for s in out.get('steps') or []]})

        def show(o):
            job.outcomes.append(o)

        def opener(page):                         # the dashboard goes to Results, dynamic, not to a new tab
            job.pages.append(page)
            return None
        kw = dict(self.stand_ins)
        kw.setdefault('open_page', opener)

        def work():
            try:
                _, done = run.follow(p, out, show=show, lines=None, child=self.child, progress=job.add,
                                     cancel=job.cancel, **kw)
                job.done = {'status': done.get('status'), 'run_ids': done.get('run_ids') or [],
                            'points': done.get('points') or [], 'lines': done.get('lines') or []}
            except Exception as e:                # noqa: BLE001 - the plan failed: recorded, and the panel says so
                job.error = '%s: %s' % (type(e).__name__, e)
                self.record_error('carry out #%s' % seq, job.error, traceback.format_exc())
            finally:
                job.finished = time.time()
                d = job.done or {}
                if job.runs:
                    log(p, 'run', {'event': 'end', 'command': seq, 'run_ids': d.get('run_ids') or [],
                                   'status': 'stopped' if job.cancel.is_set() else (d.get('status') or 'failed'),
                                   'elapsed': round(job.finished - job.started, 1),
                                   'reason': run.STOPPED if job.cancel.is_set() else job.error})
        threading.Thread(target=work, daemon=True).start()
        return job

    def stop(self, p):
        j = self.job
        if j is None or j.finished is not None:
            return {'stopped': False}
        j.cancel.set()
        last = next((t for n, k, t in reversed(j.lines) if k == 'status'), '')
        rec = next((r for r in p.read_history() if r.get('seq') == j.seq), {})
        log(p, 'stop', {'command': j.seq, 'phrase': rec.get('phrase'), 'running': last,
                        'left': 'the step under way and every point after it' if j.out.get('points') else
                        'the run under way and the steps after it'})
        return {'stopped': True}

    def edit(self, p, body, roots):
        """POST edit: committed Config-view edits into the working config, through core.edit."""
        if self.running():
            return {'error': 'a plan is being carried out; the edit stays unsaved in the config view'}
        edits = body.get('edits') or []
        src = body.get('source')
        wc = core.Context(p).wc
        if wc is None and src:                    # no working config yet: the workbook in the view is the source
            full = allowed(p, src, roots)
            if not full or not os.path.isfile(full):
                return {'error': 'the workbook is outside the directories opened in this GUI: %s' % src}
            book = _workbook(full)
            if book is None:
                return {'outcome': core.edit(p, [], source=full)}
            out = core.edit(p, to_changes(book, edits), source=full)
        elif wc is None:
            out = core.edit(p, [(('/main/' + str(e.get('key'))), e.get('value')) for e in edits])
        else:
            try:
                changes = to_changes(wc, edits)
            except ValueError as e:
                out = core.outcome('STOP', reason=str(e) + '.', pattern=core.VIEW_SET)
                core._record(p, 'Set %s.' % ', '.join('%s = %s' % (x.get('key'), x.get('value')) for x in edits), out,
                             None, answered=False, origin='gui', kind='edit',
                             detail={'edits': [dict(x, accepted=False, outcome='STOP') for x in edits]})
                return {'outcome': out, 'clear': []}
            out = core.edit(p, changes)
        clear = [e.get('key') for e in edits] if out['type'] == 'PLAN' else []
        return {'outcome': out, 'clear': clear, 'seq': (p.last_record() or {}).get('seq')}

    def follow(self, p, path, roots):
        """POST open: Assist follows another workbook opened in the Config view (core.edit with a source)."""
        full = allowed(p, path, roots)
        if not full or not os.path.isfile(full):
            return {'error': 'the workbook is outside the directories opened in this GUI: %s' % path}
        if self.running():
            return {'error': 'a plan is being carried out; Assist stays on its config until it ends'}
        src, _ = source_of(p)
        if src and _norm(src) == _norm(full):
            return {'same': True}
        return {'outcome': core.edit(p, [], source=full), 'seq': (p.last_record() or {}).get('seq')}

    def page_log(self, p, body):
        """POST log: what the page reports, as a history record: a view shown, or an error (a failed call or a
        script error), at most once a minute for one message."""
        kind = body.get('kind')
        if kind == 'view':
            return {'seq': log(p, 'view', {'what': str(body.get('what') or ''), 'run': body.get('run'),
                                            'path': body.get('path')})}
        if kind == 'error':
            seq = self.record_error('page %s' % (body.get('where') or ''), str(body.get('message') or ''),
                                    str(body.get('trace') or ''))
            return {'seq': seq, 'recorded': seq is not None}
        return {'error': 'log takes kind view or error'}


def strict(obj):
    """obj with every number that is not finite written as text (inf, -inf, nan): a browser reads only strict JSON,
    and a run's results hold such numbers (ERL is inf when it is not computed)."""
    if isinstance(obj, dict):
        return {k: strict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [strict(v) for v in obj]
    if isinstance(obj, float) and obj != obj:
        return 'nan'
    if isinstance(obj, float) and obj in (float('inf'), float('-inf')):
        return 'inf' if obj > 0 else '-inf'
    return obj


def _json_text(s):
    import json
    return json.dumps(s)


PANEL = Panel()

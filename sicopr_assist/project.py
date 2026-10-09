"""Project state: the .sicopr folder, the history, the working configs, the results, the pending question.

The formats are fixed here in Phase 1 (later phases add behaviour, not formats). Everything lives in
.sicopr in the folder the tool is run from (Decision 3):

    .sicopr\\history.jsonl              one history record per line (Decision 9)
    .sicopr\\configs\\run_NNNN.json      the working config of a run (Decision 1)
    .sicopr\\configs\\run_NNNN.csv       what the engine read (Decision 2)
    .sicopr\\runs\\run_NNNN\\            the run's own RESULT_DIR; result.json holds every result field
    .sicopr\\pending.json               the open question, if there is one
    .sicopr\\assist.ini                 project settings (Decision 4)

The user settings file is <home>\\.sicopr\\assist.ini, where <home> is SICOPR_ASSIST_HOME when that is
set and the user profile otherwise; user_home() is the only place that decides it.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import datetime
import json
import os

STATE_DIR = '.sicopr'
SETTINGS_FILE = 'assist.ini'

CONFIG_SCHEMA = 'sicopr-config/1'
HISTORY_FORMAT = 'sicopr-assist-history/1'
RESULT_FORMAT = 'sicopr-assist-result/1'
PENDING_FORMAT = 'sicopr-assist-pending/1'

CONFIG_KEYS = ('schema', 'source', 'main', 'packages', 'links')
SOURCE_KEYS = ('file', 'sheet', 'sha256')

# A history record. Every key is always written; a key that does not apply holds None or an empty list.
HISTORY_KEYS = (
    'format',          # HISTORY_FORMAT
    'seq',             # 1, 2, 3 ... in the order the commands were given
    'time',            # ISO 8601, local time, seconds
    'tool_version',    # sicopr_assist.__version__ that wrote the record
    'phrase',          # as typed
    'pattern',         # how the phrase was read
    'unplaced',        # words that could not be placed
    'options',         # options offered, when the outcome was a question
    'chosen',          # the option chosen, when this record answers a question
    'answers',         # seq of the record whose question this one answers, or None
    'rephrase_of',     # seq of a cancelled command this one rephrases, or None
    'outcome',         # PLAN, QUESTION or STOP
    'status',          # ok | question | cancelled | stopped | failed
    'reason',          # the STOP reason or the failure message
    'plan',            # the resolved outcome dictionary; replay uses this, not a new parse
    'source',          # {'path', 'sha256'} of the source config, or None
    'channels',        # [{'path', 'sha256', 'role'}] with role thru, fext or next
    'overrides',       # [{'json_path', 'before', 'after', 'kind'}] active in the working config
    'working_config',  # path of configs\\run_NNNN.json relative to the project folder, or None
    'run_ids',         # runs this command made or reused, in point order
    'points',          # for a batch: [{'values', 'run_id', 'new', 'reused_from', 'skipped'}]
    'sicopr',          # {'sha256', 'release'} of the engine the runs used, or None
    'shown',           # extra text shown after the outcome: 'tutor', 'feedback_notice' (version 2)
    'origin',          # 'cli' or 'gui': where the record was written (version 2, the GUI); None in older records
    'kind',            # what the record is (KINDS); None in older records, which are all phrases
    'detail',          # what a GUI record holds besides the keys above (GUI_DESIGN.md section 7a), or None
)
STATUSES = ('ok', 'question', 'cancelled', 'stopped', 'failed')

# Record kinds (GUI_DESIGN.md section 7a). A phrase typed or an option chosen is a command, as before. An edit or a
# workbook opened in the GUI's Config view is a record with a working config and no run, which the next command builds
# on. The log kinds record what else happened in the GUI, so that it can be reviewed later; they carry no plan and no
# working config, and every reader of the history but the history view and the feedback export leaves them out
# (Project.read_history).
COMMAND_KINDS = ('phrase', 'answer')
VIEW_KINDS = ('edit', 'open')
LOG_KINDS = ('run', 'stop', 'view', 'error')
KINDS = COMMAND_KINDS + VIEW_KINDS + LOG_KINDS
ORIGINS = ('cli', 'gui')


def is_command(rec):
    """Whether a history record is a typed phrase or a chosen option (records older than 0.7.0 all are)."""
    return rec.get('kind') in (None,) + COMMAND_KINDS

RESULT_KEYS = ('format', 'run_id', 'status', 'release', 'sicopr_sha256', 'config_csv', 'channels',
               'fingerprint', 'cases', 'message', 'export_mat')     # export_mat: the engine's .mat export was on
RESULT_STATUSES = ('complete', 'failed')


def now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def user_home():
    """The folder that holds the user's .sicopr folder: SICOPR_ASSIST_HOME, else the user profile."""
    home = os.environ.get('SICOPR_ASSIST_HOME')
    if home:
        return home
    return os.environ.get('USERPROFILE') or os.path.expanduser('~')


def user_settings_path():
    return os.path.join(user_home(), STATE_DIR, SETTINGS_FILE)


SETTINGS_EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sicopr_assist_settings_example.ini')
_ON_OFF = {'on': True, 'yes': True, 'true': True, '1': True, 'off': False, 'no': False, 'false': False, '0': False}


def setting_defaults():
    """{name: (default, heading)} read from the settings example shipped in data/ (Decision 4): the names, the
    defaults and the headings live in that one file."""
    import configparser
    cp = configparser.ConfigParser()
    with open(SETTINGS_EXAMPLE, encoding='utf-8') as f:
        cp.read_string(f.read())
    out = {}
    for sec in cp.sections():
        for k, raw in cp.items(sec):
            if raw.strip().lower() in ('on', 'off'):
                out[k] = (_ON_OFF[raw.strip().lower()], sec)
            elif '.' in raw:
                out[k] = (float(raw), sec)
            else:
                out[k] = (int(raw), sec)
    return out


def read_settings(project=None):
    """The settings in force: built-in defaults, then the user file, then the project file, later wins.
    A bad name, a bad value or an unreadable file warns and keeps the value in force; a file with no heading
    is accepted, and a setting is accepted under either heading. Returns {'values', 'sources', 'overridden',
    'warnings', 'files'}: sources[name] is 'default' or the file that set the value; overridden[name] lists the
    values of earlier files that a later file replaced, as {'value', 'source'}; files names the user and project
    files looked at."""
    import configparser
    import re
    defaults = setting_defaults()
    vals = {k: v for k, (v, _) in defaults.items()}
    src = {k: 'default' for k in vals}
    over = {}
    warn = []
    paths = [user_settings_path()] + ([project.settings_path] if project is not None else [])
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                text = f.read()
            if not re.search(r'^\s*\[', text, re.M):
                text = '[limits]\n' + text
            cp = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
            cp.read_string(text, source=p)
        except (OSError, UnicodeDecodeError, configparser.Error) as e:
            warn.append('%s could not be read (%s), so its settings are ignored' % (p, str(e).splitlines()[0]))
            continue
        for sec in cp.sections():
            for k, raw in cp.items(sec):
                if k not in defaults:
                    import difflib
                    near = difflib.get_close_matches(k, list(defaults), 1, 0.5)
                    warn.append('%s: %s is not a setting and was ignored%s' % (p, k, '; did you mean %s' % near[0] if near else ''))
                    continue
                d = defaults[k][0]
                raw = raw.strip()
                if isinstance(d, bool):
                    if raw.lower() not in _ON_OFF:
                        warn.append('%s: %s = %s is not on or off, so %s stays in force' % (p, k, raw, 'on' if vals[k] else 'off'))
                        continue
                    v = _ON_OFF[raw.lower()]
                else:
                    try:
                        v = type(d)(raw)
                    except ValueError:
                        v = None
                    if v is None or v < 0 or (isinstance(d, float) and v > 1) or (k in ('max_options', 'trouble_window') and v < 1):
                        warn.append('%s: %s = %s is not a usable value, so %s stays in force' % (p, k, raw, vals[k]))
                        continue
                if src[k] not in ('default', p):
                    over.setdefault(k, []).append({'value': vals[k], 'source': src[k]})
                vals[k] = v
                src[k] = p
    return {'values': vals, 'sources': src, 'overridden': over, 'warnings': warn,
            'files': {'user': paths[0], 'project': paths[1] if len(paths) > 1 else None}}


def setting_text(value):
    """A setting's value as the settings file writes it: on or off for a switch."""
    if isinstance(value, bool):
        return 'on' if value else 'off'
    return str(value)


def run_id(n):
    return 'run_%04d' % n


def check_working_config(cfg):
    """Raise ValueError unless cfg has the form of Decision 1."""
    if not isinstance(cfg, dict):
        raise ValueError('a working config is a JSON object')
    if cfg.get('schema') != CONFIG_SCHEMA:
        raise ValueError('working config schema is %r, expected %r' % (cfg.get('schema'), CONFIG_SCHEMA))
    extra = sorted(set(cfg) - set(CONFIG_KEYS))
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if extra or missing:
        raise ValueError('working config keys: missing %s, not known %s' % (missing or 'none', extra or 'none'))
    if not isinstance(cfg['source'], dict) or set(cfg['source']) != set(SOURCE_KEYS):
        raise ValueError('working config source must hold exactly %s' % ', '.join(SOURCE_KEYS))
    for k in ('main', 'packages', 'links'):
        if not isinstance(cfg[k], dict):
            raise ValueError('working config %s must be an object' % k)
    for blk, params in cfg['packages'].items():
        if not isinstance(params, dict):
            raise ValueError('package block %s must be an object' % blk)


def history_record(**fields):
    """A history record with every key present; unknown keys are refused."""
    bad = sorted(set(fields) - set(HISTORY_KEYS))
    if bad:
        raise ValueError('not history keys: %s' % ', '.join(bad))
    from sicopr_assist import __version__
    rec = {k: None for k in HISTORY_KEYS}
    rec.update(format=HISTORY_FORMAT, time=now(), tool_version=__version__, unplaced=[], options=[],
               channels=[], overrides=[], run_ids=[], points=[], shown=[])
    rec.update(fields)
    if rec['status'] is not None and rec['status'] not in STATUSES:
        raise ValueError('history status must be one of %s' % ', '.join(STATUSES))
    if rec['kind'] is not None and rec['kind'] not in KINDS:
        raise ValueError('history kind must be one of %s' % ', '.join(KINDS))
    if rec['origin'] is not None and rec['origin'] not in ORIGINS:
        raise ValueError('history origin must be one of %s' % ', '.join(ORIGINS))
    return rec


def result_record(**fields):
    bad = sorted(set(fields) - set(RESULT_KEYS))
    if bad:
        raise ValueError('not result keys: %s' % ', '.join(bad))
    rec = {k: None for k in RESULT_KEYS}
    rec.update(format=RESULT_FORMAT, channels=[], cases=[])
    rec.update(fields)
    if rec['status'] not in RESULT_STATUSES:
        raise ValueError('result status must be one of %s' % ', '.join(RESULT_STATUSES))
    return rec


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=1)
        f.write('\n')
    os.replace(tmp, path)


def _read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


class Project:
    """The state of one project folder. Nothing is created until something is written."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.dir = os.path.join(self.root, STATE_DIR)

    # ---- paths
    @property
    def history_path(self):
        return os.path.join(self.dir, 'history.jsonl')

    @property
    def settings_path(self):
        return os.path.join(self.dir, SETTINGS_FILE)

    @property
    def pending_path(self):
        return os.path.join(self.dir, 'pending.json')

    @property
    def configs_dir(self):
        return os.path.join(self.dir, 'configs')

    @property
    def runs_dir(self):
        return os.path.join(self.dir, 'runs')

    def working_config_path(self, rid):
        return os.path.join(self.configs_dir, rid + '.json')

    def run_csv_path(self, rid):
        return os.path.join(self.configs_dir, rid + '.csv')

    def run_dir(self, rid):
        return os.path.join(self.runs_dir, rid)

    def result_path(self, rid):
        return os.path.join(self.run_dir(rid), 'result.json')

    def relative(self, path):
        return os.path.relpath(path, self.root)

    # ---- history
    def read_history(self, log=False):
        """The history records, oldest first. The GUI's log records (LOG_KINDS) are left out unless log is set:
        only the history view and the feedback export read them."""
        if not os.path.exists(self.history_path):
            return []
        out = []
        with open(self.history_path, encoding='utf-8') as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    rec = json.loads(line)
                    if rec.get('format') != HISTORY_FORMAT:
                        raise ValueError('%s line %d: history format %r' % (self.history_path, n, rec.get('format')))
                    if log or rec.get('kind') not in LOG_KINDS:
                        out.append(rec)
        return out

    def append_history(self, record):
        """Append one record; seq is given the next number when the record has none."""
        if record.get('seq') is None:
            hist = self.read_history(log=True)
            record = dict(record, seq=(hist[-1]['seq'] + 1) if hist else 1)
        os.makedirs(self.dir, exist_ok=True)
        with open(self.history_path, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(record) + '\n')
        return record

    def update_history(self, seq, **fields):
        """Fill in the record with this seq once its plan has been carried out (the runs it made, the files it
        used). Only HISTORY_KEYS may be set; the file is rewritten whole and replaced in one step."""
        bad = sorted(set(fields) - set(HISTORY_KEYS))
        if bad:
            raise ValueError('not history keys: %s' % ', '.join(bad))
        hist = self.read_history(log=True)
        rec = next((r for r in hist if r.get('seq') == seq), None)
        if rec is None:
            raise ValueError('no history record with seq %r' % seq)
        if fields.get('status') is not None and fields['status'] not in STATUSES:
            raise ValueError('history status must be one of %s' % ', '.join(STATUSES))
        rec.update(fields)
        tmp = self.history_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            for r in hist:
                f.write(json.dumps(r) + '\n')
        os.replace(tmp, self.history_path)
        return rec

    def last_record(self, with_runs=False):
        for rec in reversed(self.read_history()):
            if not with_runs or rec.get('run_ids'):
                return rec
        return None

    # ---- runs
    def run_numbers(self):
        if not os.path.isdir(self.configs_dir):
            return []
        out = []
        for name in os.listdir(self.configs_dir):
            stem, ext = os.path.splitext(name)
            if ext == '.json' and stem.startswith('run_') and stem[4:].isdigit():
                out.append(int(stem[4:]))
        return sorted(out)

    def next_run_id(self):
        nums = self.run_numbers()
        return run_id((nums[-1] + 1) if nums else 1)

    def write_working_config(self, rid, cfg):
        check_working_config(cfg)
        _write_json(self.working_config_path(rid), cfg)
        return self.working_config_path(rid)

    def read_working_config(self, rid):
        cfg = _read_json(self.working_config_path(rid))
        check_working_config(cfg)
        return cfg

    def write_result(self, rid, result):
        _write_json(self.result_path(rid), result)
        return self.result_path(rid)

    def read_result(self, rid):
        rec = _read_json(self.result_path(rid))
        if rec.get('format') != RESULT_FORMAT:
            raise ValueError('%s: result format %r' % (self.result_path(rid), rec.get('format')))
        return rec

    # ---- the open question
    def write_pending(self, phrase, outcome, seq=None):
        _write_json(self.pending_path, {'format': PENDING_FORMAT, 'seq': seq, 'time': now(),
                                        'phrase': phrase, 'outcome': outcome})

    def read_pending(self):
        if not os.path.exists(self.pending_path):
            return None
        rec = _read_json(self.pending_path)
        if rec.get('format') != PENDING_FORMAT:
            raise ValueError('%s: pending format %r' % (self.pending_path, rec.get('format')))
        return rec

    def clear_pending(self):
        if os.path.exists(self.pending_path):
            os.remove(self.pending_path)

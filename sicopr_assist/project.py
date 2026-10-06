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
)
STATUSES = ('ok', 'question', 'cancelled', 'stopped', 'failed')

RESULT_KEYS = ('format', 'run_id', 'status', 'release', 'sicopr_sha256', 'config_csv', 'channels',
               'fingerprint', 'cases', 'message')
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
    def read_history(self):
        if not os.path.exists(self.history_path):
            return []
        out = []
        with open(self.history_path, encoding='utf-8') as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    rec = json.loads(line)
                    if rec.get('format') != HISTORY_FORMAT:
                        raise ValueError('%s line %d: history format %r' % (self.history_path, n, rec.get('format')))
                    out.append(rec)
        return out

    def append_history(self, record):
        """Append one record; seq is given the next number when the record has none."""
        if record.get('seq') is None:
            hist = self.read_history()
            record = dict(record, seq=(hist[-1]['seq'] + 1) if hist else 1)
        os.makedirs(self.dir, exist_ok=True)
        with open(self.history_path, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(record) + '\n')
        return record

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

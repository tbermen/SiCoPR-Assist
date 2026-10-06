"""The core: handle(phrase, project) -> outcome. Nothing here runs COM.

The outcome is one plain dictionary that can be written as JSON (prompt section 5):

    type       PLAN, QUESTION or STOP
    steps      [{"op": <a name in STEPS>, "args": {...}}, ...]
    changes    [{"json_path", "before", "after", "kind", "applied"}, ...]
    question   {"text", "options"}            QUESTION only
    reason     text                           STOP only
    announce   every line shown before anything runs
    points, new_runs, reused_runs             batches only
    pattern, unplaced                         how the phrase was read; goes to history

The principle is resolve exactly, or ask. A phrase is read by parse.py against the names of the config in
front of the tool; names are resolved by Rule 4 (COM keywords only, case and spaces ignored); every value is
checked by validate.py, which loads the candidate config with the engine's own loader. A QUESTION is stored
in the project as the pending question, and the next phrase is first read as its answer.

For a sweep or batch, each point is {"values", "writes", "new", "reused_from", "skipped"}: "values" are the
swept values as the user gives them (one per swept name), and "writes" are the cells of the working config
the point sets, in the config's own form (a [TX RX] pair written to both sides, a case list in brackets).

Inputs and outcome stay plain data so that a language-model layer can work upstream of this function: it may
turn loose wording into a phrase, and the core resolves it exactly as it resolves typed input.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import hashlib
import itertools
import json
import math
import os
import re

from sicopr_assist import config_model, engine, parse, validate, xlsx_io
from sicopr_assist.project import read_settings

# The step vocabulary, frozen in Phase 1 from the expected_detail chains of the use-case table
# (tests/cases/l4.py extracts it again and tests/test_l4_normaliser.py checks that the two agree).
STEPS = (
    'add_param', 'batch_summary', 'build_matrix', 'clear_overrides', 'compare_config', 'diff_results',
    'download', 'drop_override', 'export_feedback', 'export_mat', 'export_xlsx', 'extract', 'fetch_index',
    'import_config', 'infer_interface', 'inventory', 'list_parameters', 'open_report', 'recompute_linked',
    'render_dashboard', 'result_stats', 'result_vs_param', 'revert_override', 'run_batch', 'run_com',
    'select_zip', 'set_param', 'set_setting', 'show_config', 'show_history', 'show_overrides', 'show_param',
    'show_settings', 'show_tutor', 'summarize', 'validate_config', 'validate_inputs',
)

OUTCOME_TYPES = ('PLAN', 'QUESTION', 'STOP')
CHANGE_KINDS = ('set', 'add', 'linked', 'revert')

NONE_OF_THESE = 'none of these'
CANCEL = 'cancel'
EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sicopr_config_example.json')
CONFIG_EXT = ('.xlsx', '.xls', '.csv', '.json')

# Version 2 features (Decision 16): what to do instead, in this version.
NOT_IN_V1 = {
    'dashboard': 'The dashboard is not in this version of SiCoPR-Assist. Use the run summary (Show me the summary '
                 'again) or the CSV summary that each run writes in its results folder.',
    'fetch': 'Downloading channels is not in this version of SiCoPR-Assist. Download the channel files from the IEEE '
             'P802.3dj tools page (https://www.ieee802.org/3/dj/public/tools/index.html), unpack them into the '
             'project folder, and name them in the phrase, for example Run COM on data\\thru.s4p with data\\config.xlsx.',
    'tutor': 'The tutor is not in this version of SiCoPR-Assist. What can I change? lists the parameters of the '
             'config, and a phrase such as Re-run with DER_0 = 1e-4 changes one of them.',
    'feedback': 'Feedback export is not in this version of SiCoPR-Assist.',
}


def outcome(kind, **fields):
    """An outcome with every key present, so the scorer and the history never meet a missing key."""
    if kind not in OUTCOME_TYPES:
        raise ValueError('outcome type must be one of %s, not %r' % (', '.join(OUTCOME_TYPES), kind))
    out = {'type': kind, 'steps': [], 'changes': [], 'announce': [], 'points': [], 'new_runs': 0,
           'reused_runs': 0, 'pattern': '', 'unplaced': []}
    if kind == 'QUESTION':
        out['question'] = {'text': '', 'options': []}
    if kind == 'STOP':
        out['reason'] = ''
    out.update(fields)
    return out


def _step(op, **args):
    if op not in STEPS:
        raise ValueError('not a step: %s' % op)
    return {'op': op, 'args': args}


def _stop(reason, **fields):
    return outcome('STOP', reason=reason, **fields), {}


def _ask(text, options, answers, **fields):
    """A QUESTION and the map from each option to what choosing it does (None: cancel)."""
    return outcome('QUESTION', question={'text': text, 'options': list(options)}, **fields), dict(answers)


show = validate.show


# ----------------------------------------------------------------------------- the project in front of the tool
class Context:
    """What a phrase is read against: the settings, the history, the working config of the last run (or the
    config in the project folder), its source workbook, and the runs already on disk. Read lazily."""

    def __init__(self, project):
        self.project = project
        self.root = project.root
        self._c = {}

    def _get(self, key, make):
        if key not in self._c:
            self._c[key] = make()
        return self._c[key]

    @property
    def settings(self):
        return self._get('settings', lambda: read_settings(self.project))

    def setting(self, name):
        return self.settings['values'][name]

    @property
    def history(self):
        def make():
            try:
                return self.project.read_history()
            except (OSError, ValueError):
                return []
        return self._get('history', make)

    @property
    def last(self):
        """The last history record that names a working config."""
        return self._get('last', lambda: next((r for r in reversed(self.history) if r.get('working_config')), None))

    def path(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.root, *re.split(r'[\\/]', rel))

    @property
    def base(self):
        """(working config the next command starts from, how it was found, import issues) or (None, why, [])."""
        def make():
            rec = self.last
            if rec is not None:
                try:
                    with open(self.path(rec['working_config']), encoding='utf-8') as f:
                        return json.load(f), 'last run', []
                except (OSError, ValueError) as e:
                    return None, 'the working config of the last run cannot be read: %s' % e, []
            return None, 'no run in this project yet', []
        return self._get('base', make)

    @property
    def wc(self):
        return self.base[0]

    def config_files(self):
        out = []
        for d in (self.root, os.path.join(self.root, 'data')):
            if os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    p = os.path.join(d, n)
                    if os.path.isfile(p) and n.lower().endswith(CONFIG_EXT) and not n.startswith('~$'):
                        out.append(os.path.relpath(p, self.root))
        return out

    def channel_files(self):
        out = []
        for d in (self.root, os.path.join(self.root, 'data')):
            if os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    if parse.CHANNEL_EXT.search(n) and os.path.isfile(os.path.join(d, n)):
                        out.append(os.path.relpath(os.path.join(d, n), self.root))
        return out

    @property
    def source_path(self):
        """The workbook in front of the tool: the source of the last run, else the one config in the folder."""
        def make():
            rec = self.last
            if rec and rec.get('source') and rec['source'].get('path'):
                p = self.path(rec['source']['path'])
                if os.path.exists(p) and p.lower().endswith(('.xlsx', '.xls')):
                    return p
            xl = [c for c in self.config_files() if c.lower().endswith(('.xlsx', '.xls'))]
            return self.path(xl[0]) if len(xl) == 1 else None
        return self._get('source_path', make)

    @property
    def descriptions(self):
        def make():
            p = self.source_path
            if p and p.lower().endswith(('.xlsx', '.xls')):
                try:
                    return xlsx_io.keyword_descriptions(p)
                except Exception:                                  # a workbook that cannot be read has none
                    return {}
            return {}
        return self._get('descriptions', make)

    @property
    def selections(self):
        def make():
            p = self.source_path
            if p and p.lower().endswith(('.xlsx', '.xls')):
                try:
                    return xlsx_io.selection_lists(p)
                except Exception:
                    return {}
            return {}
        return self._get('selections', make)

    def names(self, wc):
        out = list(wc['main'])
        for b in wc['packages'].values():
            out += [k for k in b if k not in out]
        out += engine.keyword_names('main') + engine.keyword_names('package block')
        return out

    # ---- runs on disk, for reuse (Decision 6)
    def channels(self):
        """[(path, sha256 now)] of the channel files the last run used, in its order."""
        rec = self.last
        out = []
        for c in (rec or {}).get('channels') or []:
            p = self.path(c['path'])
            out.append((c['path'], _sha(p) if os.path.exists(p) else None, c.get('role')))
        return out

    @property
    def runs(self):
        """[(run id, fingerprint)] of every run in the history, oldest first."""
        def make():
            out, seen = [], set()
            for rec in self.history:
                for rid in rec.get('run_ids') or []:
                    if rid in seen:
                        continue
                    seen.add(rid)
                    try:
                        wc = self.project.read_working_config(rid)
                        res = self.project.read_result(rid)
                    except (OSError, ValueError):
                        continue
                    if res.get('status') != 'complete':
                        continue
                    fields, err = config_model.loaded_fields(wc)
                    if err:
                        continue
                    out.append((rid, _fingerprint(fields, [c.get('sha256') for c in res.get('channels') or []],
                                                  res.get('sicopr_sha256'))))
            return out
        return self._get('runs', make)

    def last_run_id(self):
        rec = next((r for r in reversed(self.history) if r.get('run_ids')), None)
        if rec is None:
            return None
        if rec.get('working_config'):
            stem = os.path.splitext(os.path.basename(rec['working_config']))[0]
            if stem in rec['run_ids']:
                return stem
        return rec['run_ids'][-1]


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _fingerprint(fields, channel_shas, sicopr_sha):
    """What decides reuse: the loaded fields (without where output goes), the channel files, the engine."""
    keep = {k: v for k, v in fields.items() if not k.endswith('RESULT_DIR')}
    return keep, sorted(s or '' for s in channel_shas), sicopr_sha


def _same_fingerprint(a, b):
    fa, ca, sa = a
    fb, cb, sb = b
    if ca != cb or sa != sb or set(fa) != set(fb):
        return False
    return all(config_model.field_equal(fa[k], fb[k]) for k in fa)


# ----------------------------------------------------------------------------- the entry point
def handle(phrase, project):
    """Turn one phrase and the project state into a PLAN, a QUESTION or a STOP. Never runs COM."""
    ctx = Context(project)
    try:
        pending = project.read_pending()
    except (OSError, ValueError):
        pending = None
    try:
        got = None
        if pending:
            got = _answer(phrase, ctx, pending)
        if got is None:
            out, answers, resume = _resolve(phrase, ctx, {})
        else:
            out, answers, resume = got
    except engine.EngineMissing as e:
        out, answers, resume = outcome('STOP', reason=str(e), pattern='no engine'), {}, None
    if out['type'] == 'QUESTION' and resume is not None:
        stored = dict(out, resume=dict(resume, answers=answers))
        project.write_pending(resume['phrase'], stored)
    elif pending:
        project.clear_pending()
    return out


def _resolve(phrase, ctx, mods):
    """(outcome, answers, resume) for a phrase read with the modifications chosen so far."""
    text = phrase
    for old, new in mods.get('replace', []):
        text = _replace_words(text, old, new)
    out, answers = _plan(text, ctx, mods)
    return out, answers, {'phrase': phrase, 'mods': mods}


def _replace_words(text, old, new):
    pat = re.compile(r'(?<![\w(])%s(?![\w)])' % r'\s+'.join(re.escape(w) for w in old.split()), re.I)
    return pat.sub(lambda m: new, text, count=1)


# ----------------------------------------------------------------------------- answers to a pending question
_ORDINALS = {'first': 1, 'second': 2, 'third': 3}


def _option_key(text):
    t = re.sub(r'\s*\([^()]*\)\s*$', '', str(text).strip())
    return re.sub(r'[\s.!?]+', ' ', t).strip().lower()


def _answer(phrase, ctx, pending):
    """(outcome, answers, resume) when the phrase answers the pending question, else None."""
    stored = pending.get('outcome') or {}
    resume = stored.get('resume') or {'phrase': pending.get('phrase') or '', 'mods': {}}
    answers = resume.get('answers')
    options = (stored.get('question') or {}).get('options') or []
    if answers is None:                         # a question stored without its answers: ask it again to get them
        q, answers, _ = _resolve(resume['phrase'], ctx, resume.get('mods') or {})
        if q['type'] != 'QUESTION':
            return None
        options = q['question']['options']
    said = phrase.strip()
    key = _option_key(said)
    chosen = None
    if re.fullmatch(r'\d+', key) and 1 <= int(key) <= len(options):
        chosen = options[int(key) - 1]
    for opt in options:
        if chosen is None and (_option_key(opt) == key or str(opt).strip().lower() == said.lower()):
            chosen = opt
    words = re.findall(r"[a-z]+", key)
    if chosen is None and key in ('no', 'stop', 'cancel', 'never mind', 'nothing'):
        chosen = next((o for o in options if _option_key(o) == CANCEL), None)
        if chosen is None:
            return _stop('Cancelled: nothing changed and nothing runs.', pattern='answer: cancel') + (None,)
    if chosen is None and words and set(words) <= parse.CONFIRM:
        chosen = next((o for o in options if _option_key(o).startswith('run')), None)
    mods = copy.deepcopy(resume.get('mods') or {})
    if chosen is None:
        req = None
        if any(_option_key(o).startswith('edit') for o in options):
            req = parse.read(phrase)
        if req and req['edits'] and not req['sets'] and not req['sweeps'] and not req['attempts']:
            mods.setdefault('sweep_edit', {}).update(req['edits'][-1])
            mods.pop('confirm_limit', None)
            out, ans, res = _resolve(resume['phrase'], ctx, mods)
            out['pattern'] = 'answer: edit the sweep; ' + out['pattern']
            return out, ans, res
        return None
    what = answers.get(chosen, answers.get(_option_key(chosen)))
    if what is None:
        return _stop('Cancelled: nothing changed and nothing runs.', pattern='answer: %s' % chosen) + (None,)
    if what.get('stop'):
        return _stop(what['stop'], pattern='answer: %s' % chosen) + (None,)
    for k, v in what.items():
        if k == 'replace':
            mods.setdefault('replace', []).append(v)
        elif k in ('allow',):
            mods.setdefault('allow', [])
            mods['allow'] += [x for x in v if x not in mods['allow']]
        elif k == 'set':
            mods.setdefault('set', {}).update(v)
        else:
            mods[k] = v
    out, ans, res = _resolve(resume['phrase'], ctx, mods)
    out['pattern'] = 'answer: %s; %s' % (chosen, out['pattern'])
    return out, ans, res


# ----------------------------------------------------------------------------- reading the phrase
def _plan(text, ctx, mods):
    wc = ctx.wc
    names = ctx.names(wc) if wc else engine.keyword_names('main') + engine.keyword_names('package block')
    blocks = list(wc['packages']) if wc else []
    req = parse.read(text, names, blocks)
    acts = req['actions']
    base = dict(pattern=req['pattern'], unplaced=list(req['unplaced']))

    # out of scope and version 2 features first: they never run anything
    if 'why' in acts:
        return _stop('SiCoPR-Assist reports results and does not diagnose them. It can show the summary of the last '
                     'run (Show me the summary again), statistics of a result over the last set of runs, and how a '
                     'parameter relates to a result.', **base)
    for feat in ('dashboard', 'fetch', 'tutor', 'feedback'):
        if feat in acts:
            return _stop(NOT_IN_V1[feat], **base)
    low = text.lower()
    if re.search(r'\bwhat can i (say|type)\b|\bexample commands\b', low):
        return _stop(NOT_IN_V1['tutor'], **base)
    if re.search(r'\bemail\b|\bsend\b', low) and not req['sets'] and not req['sweeps']:
        return _stop('SiCoPR-Assist does not send anything. Each run leaves its results in its own folder under '
                     '.sicopr\\runs, which you can attach yourself.', **base)

    # questions about the config and the project
    asked = _show(req, text, ctx, base)
    if asked is not None:
        return asked
    if 'save' in acts:
        return _save(req, ctx, base)
    if 'compare' in acts and req['files']:
        return _compare(req, ctx, base)

    # a run with files named, or the files in the folder
    first_run = bool(req['files'] or 'these_files' in req['flags'] or 'this_config' in req['flags']
                     or 'example' in req['flags']) and not req['sweeps']
    if first_run:
        return _first_run(req, ctx, mods, base)

    if 'reset' in acts and not req['sets'] and not req['sweeps']:
        return _reset(req, ctx, base)

    if req['sweeps'] or any(s.get('op') == 'all' and not _is_case_list(s['name']) for s in req['sets']):
        if wc is None:
            return _no_history(ctx, base)
        return _sweep(req, ctx, mods, base)

    if req['sets'] or req['packages'] or req['attempts']:
        if wc is None and (req['sets'] or req['packages'] or any(a.get('value') is not None for a in req['attempts'])):
            return _no_history(ctx, base)
        if wc is not None:
            return _change(req, ctx, mods, base, wc)
    if 'thru_only' in req['flags'] and wc is not None:
        return _ask('The last run had no crosstalk files, so a run without crosstalk would be the same run. Run it '
                    'thru-only anyway?', ['run thru-only', CANCEL],
                    {'run thru-only': {'thru_only': True}, CANCEL: None}, **base) \
            if not mods.get('thru_only') else _replay(req, ctx, base, thru_only=True)
    if any(a in acts for a in ('rerun', 'run')) or 'again' in req['flags']:
        if req['unplaced']:
            return _unplaced_only(req, base)
        if wc is None:
            return _first_run(req, ctx, mods, base) if 'run' in acts and 'rerun' not in acts and 'again' not in req['flags'] \
                else _no_history(ctx, base)
        return _replay(req, ctx, base)
    return _stop('Not a supported request. SiCoPR-Assist runs a config (Run COM on data\\thru.s4p with data\\config.xlsx), '
                 're-runs it with changes (Re-run with DER_0 = 1e-4), sweeps a parameter (Sweep C_b from 1e-5 to 5e-5 '
                 'in 5 steps), and shows the config (What can I change?).', **base)


def _unplaced_only(req, base):
    return _ask('Strict mode: %s could not be placed, so nothing runs. Rephrase the request with COM keywords.'
                % _words(req['unplaced']), [CANCEL], {CANCEL: None}, **base)


def _words(ws):
    ws = list(dict.fromkeys(ws))
    return ', '.join(ws[:-1]) + ' and ' + ws[-1] if len(ws) > 1 else (ws[0] if ws else '')


def _no_history(ctx, base):
    opts = ['the example setup', 'provide files']
    return _ask('There is no run in this project folder yet, so there is nothing to re-run. Name a config and a channel '
                'file (Run COM on data\\thru.s4p with data\\config.xlsx), or run the example setup.', opts,
                {'the example setup': {'stop': 'Run the example setup with: Run SiCoPR on the example setup.'},
                 'provide files': {'stop': 'Name the files, for example: Run COM on data\\thru.s4p with data\\config.xlsx.'}},
                **base)


# ----------------------------------------------------------------------------- names (Rule 4)
def _schema_row(name, scope='main'):
    return validate.schema_row(name, scope) or validate.schema_row(name, 'package block' if scope == 'main' else 'main')


def _is_case_list(name):
    row = _schema_row(name)
    return bool(row) and row['shape'].strip() == 'list of case numbers'


def _key_in(scope, name):
    if name in scope:
        return name
    sq = parse.squash(name)
    return next((k for k in scope if parse.squash(k) == sq), None)


def near_names(attempt, pool, cutoff):
    """Names that a typed name that is not exact could have meant, best first: the same letters (fb for f_b),
    then names that start with it (z_p for z_p select), then, for one word, names within the cutoff."""
    a = parse.letters(attempt)
    raw = attempt.strip().lower()
    if not a:
        return []
    import difflib
    pool = list(dict.fromkeys(pool))
    exact = [n for n in pool if parse.letters(n) == a]
    if exact:
        return sorted(exact, key=lambda n: -difflib.SequenceMatcher(None, raw, n.lower()).ratio())
    prefix = [n for n in pool if len(raw) >= 2 and n.lower().startswith(raw) and len(n) > len(raw)]
    if prefix:
        return prefix
    if len(attempt.split()) == 1:
        scored = [(difflib.SequenceMatcher(None, a, parse.letters(n)).ratio(), i, n) for i, n in enumerate(pool)]
        return [n for r, i, n in sorted(scored, key=lambda x: (-x[0], x[1])) if r >= cutoff]
    return []


_SKIP = {'the', 'a', 'an', 'of', 'to', 'and', 'in', 'for', 'is', 'as', 'on', 'all', 'every', 'with', 'without', 'at'}


def described_names(words, wc, descriptions, limit):
    """Names whose keywords-sheet description holds the words, most relevant first: descriptions with every
    word, then those with most of them; sheet order within a tie. Only plain words are looked up."""
    toks = [t.lower() for t in words if re.fullmatch(r'[A-Za-z]+', t) and t.lower() not in _SKIP]
    if not toks:
        return []
    low = {k.strip().lower(): v for k, v in descriptions.items()}
    names = list(dict.fromkeys(list(wc['main']) + [k for b in wc['packages'].values() for k in b]))
    scored = []
    for i, n in enumerate(names):
        desc = set(re.findall(r'[a-z0-9]+', low.get(n.strip().lower(), '').lower()))
        hit = sum(1 for t in toks if {t, t[:-1] if t.endswith('s') else t + 's'} & desc)
        if hit:
            scored.append((0 if hit == len(toks) else 1, -hit, i, n))
    return [n for *_, n in sorted(scored)][:limit]


def _current(wc, name):
    k = _key_in(wc['main'], name)
    if k is not None:
        return wc['main'][k]
    for b in _selected(wc) or list(wc['packages']):
        if b in wc['packages']:
            k = _key_in(wc['packages'][b], name)
            if k is not None:
                return wc['packages'][b][k]
    return None


def _name_option(wc, n):
    v = _current(wc, n)
    return '%s (now %s)' % (n, show(v)) if v is not None and len(show(v)) <= 24 else n


def _selected(wc):
    k = _key_in(wc['main'], 'PKG_NAME')
    return str(wc['main'].get(k) or '').split() if k else []


def _attempt_question(req, ctx, wc, mods, base):
    """The question for a name that is not a COM keyword, or a STOP when nothing resembles it; None when the
    phrase has no such name."""
    pool = []
    seen = set()
    for n in ctx.names(wc):
        if parse.squash(n) not in seen:
            seen.add(parse.squash(n))
            pool.append(n)
    for at in sorted(req['attempts'], key=lambda a: a.get('value') is None):
        if at.get('block'):
            continue
        near = near_names(at['text'], pool, ctx.setting('name_match_cutoff'))
        if near:
            limit = ctx.setting('max_options')
            near = near[:limit]
            opts = [_name_option(wc, n) for n in near]
            answers = {o: {'replace': [at['text'], n]} for o, n in zip(opts, near)}
            changes = []
            if len(near) == 1:
                opts.append(NONE_OF_THESE)
                answers[NONE_OF_THESE] = {'stop': 'Name the parameter by its COM keyword. What can I change? lists them.'}
                if at.get('value') is not None:
                    trial, _, _ = _resolve(_replace_words(req['phrase'], at['text'], near[0]), ctx, dict(mods))
                    changes = [dict(c, applied=False) for c in trial.get('changes') or []]
            text = ('Strict mode: %s is not a COM parameter name, so nothing runs. Did you mean %s?'
                    % (at['text'], ' or '.join(near)))
            return _ask(text, opts, answers, changes=changes, **base)
        desc = described_names(at['words'], wc, ctx.descriptions, ctx.setting('max_options'))
        if desc:
            opts = [_name_option(wc, n) for n in desc] + [NONE_OF_THESE]
            answers = {o: {'replace': [at['text'], n]} for o, n in zip(opts, desc)}
            answers[NONE_OF_THESE] = {'stop': 'Name the parameter by its COM keyword. What can I change? lists them.'}
            lines = ['%s: %s' % (n, ctx.descriptions.get(n) or next((v for k, v in ctx.descriptions.items()
                                                                      if k.strip().lower() == n.lower()), ''))
                     for n in desc]
            others = [w for w in req['unplaced'] if w not in at['words']]
            text = ('Strict mode: %s is not a COM parameter name%s, so nothing runs. These keywords have it in their '
                    'description: %s' % (at['text'], (' and %s could not be placed' % _words(others)) if others else '',
                                         '; '.join(lines)))
            return _ask(text, opts, answers, **base)
        if at.get('value') is not None and not re.fullmatch(r'[A-Za-z ]+', at['text']):
            return _stop('No parameter in the config or the keyword list resembles %s. What can I change? lists the '
                         'parameters.' % at['text'], **base)
    return None


def _block_options(ctx, wc, typed):
    """(unique best block or None, blocks best first) for a block name that is not exact."""
    blocks = list(wc['packages'])
    t = parse.letters(typed)
    inside = [b for b in blocks if t and t in parse.letters(b)]
    if len(inside) == 1:
        return inside[0], inside
    parts = [p.lower() for p in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', typed)]
    score = {b: sum(1 for p in parts if p and p in parse.letters(b)) for b in blocks}
    order = sorted(blocks, key=lambda b: (-score[b], blocks.index(b)))
    top = [b for b in blocks if score[b] == max(score.values())] if score else []
    return (top[0] if len(top) == 1 and score[top[0]] > 0 else None), order


# ----------------------------------------------------------------------------- one change or several
def _target(name, wc, block=None):
    """{'jp', 'key', 'block'} for a name, or ('ask', text, options, answers) when the block is not clear."""
    if block is not None:
        if block not in wc['packages']:
            b = next((x for x in wc['packages'] if x.lower() == str(block).lower()), None)
            if b is None:
                return ('noblock', block)
            block = b
        k = _key_in(wc['packages'][block], name)
        return {'jp': '/packages/%s/%s' % (block, k or name), 'key': k or name, 'block': block}
    k = _key_in(wc['main'], name)
    if k is not None:
        return {'jp': '/main/' + k, 'key': k, 'block': None}
    holders = [b for b, p in wc['packages'].items() if _key_in(p, name) is not None]
    if holders:
        sel = [b for b in _selected(wc) if b in wc['packages']]
        if len(set(sel)) > 1:
            return ('sides', sel)
        b = sel[0] if sel else holders[0]
        k = _key_in(wc['packages'][b], name)
        return {'jp': '/packages/%s/%s' % (b, k or name), 'key': k or name, 'block': b}
    return {'jp': '/main/' + name, 'key': name, 'block': None}


def _pair(value):
    p = validate.parse_numbers(value)
    if p and len(p[0]) == 1 and len(p[0][0]) == 2 and not p[1]:
        return p[0][0]
    return None


def _num_text(x):
    return validate.short(validate._round(x))


def _prepare(item, tgt, wc, ctx):
    """The value to hand to validate for one set item, or an outcome-making tuple when it cannot be resolved."""
    name = tgt['key']
    cur = config_model.get_value(wc, config_model.key_of(tgt['jp'])) if _exists(wc, tgt['jp']) else None
    row = _schema_row(name, 'package block' if tgt['block'] else 'main')
    op = item.get('op')
    value = item.get('value')
    unit = item.get('unit')
    if op == 'all':
        return _all_cases(wc, name)
    if value is None:
        return ('novalue', cur)
    typed = value + (' ' + unit if unit else '')
    if op == 'element':
        return ('element', cur)
    if op == 'part':
        return _range_part(cur, item['part'], value)
    if item.get('side'):
        two = _pair(cur) if cur is not None else None
        if two is None:
            return ('noside', cur)
        conv, _ = validate.check_value(wc, tgt['jp'], typed)
        if not isinstance(conv, (int, float)):
            return typed
        el = [show(two[0]), show(two[1])]
        el[0 if item['side'] == 'TX' else 1] = show(conv)
        return '[%s %s]' % tuple(el)
    if row and row['shape'].strip() == 'list of case numbers' and re.fullmatch(r'\d+', value.strip()):
        return '[ %s ]' % value.strip()
    if row is None and not unit and validate._plain_number(value) is not None:
        return validate._plain_number(value)           # a label only a link uses (T_t): a number, so links can follow
    return typed


def _exists(wc, jp):
    try:
        config_model.get_value(wc, config_model.key_of(jp))
        return True
    except (KeyError, ValueError):
        return False


def _all_cases(wc, name):
    """Every package case of the selected block, as a case list: [ 1 2 3 4 ]."""
    tx = None
    for b in _selected(wc)[:1]:
        if b in wc['packages']:
            k = _key_in(wc['packages'][b], 'z_p (TX)')
            tx = wc['packages'][b].get(k) if k else None
    if tx is None:
        k = _key_in(wc['main'], 'z_p (TX)')
        tx = wc['main'].get(k) if k else None
    shape = validate._shape(tx) if tx is not None else None
    if not shape:
        return ('novalue', None)
    return '[ %s ]' % ' '.join(str(i) for i in range(1, shape[1] + 1))


def _range_part(cur, part, value):
    """A range min:step:max with one part replaced, keeping the rest of the text as the sheet writes it."""
    if not isinstance(cur, str) or ':' not in cur:
        return ('norange', cur)
    inner = cur.strip().strip('[]').strip()
    bits = inner.split(':')
    if len(bits) not in (2, 3):
        return ('norange', cur)
    if len(bits) == 2:
        bits = [bits[0], '1', bits[1]]
    i = {'start': 0, 'step': 1, 'end': 2}[part]
    new = value.strip()
    old = bits[i].strip()
    if re.match(r'^-?\.', old) and re.match(r'^-?0\.', new):
        new = new.replace('0.', '.', 1)
    bits[i] = new
    return '[%s]' % ':'.join(b.strip() for b in bits)


def _change_items(req, wc, ctx, mods):
    """[(item, target)] for every change the phrase asks for, or an outcome when one cannot be resolved."""
    out = []
    for p in req['packages']:
        kw = _key_in(wc['main'], 'PKG_NAME') or 'PKG_NAME'
        if not wc['packages']:
            one = p.get('both') or p.get('tx') or p.get('rx')
            out.append(({'name': kw, 'value': '%s %s' % (one, one), 'op': 'set'},
                        {'jp': '/main/' + kw, 'key': kw, 'block': None}))
            continue
        cur = _selected(wc)
        if 'both' in p:
            names = [p['both'], p['both']]
        else:
            names = [p.get('tx') or (cur[0] if cur else None), p.get('rx') or (cur[-1] if cur else None)]
        fixed = []
        for typed in names:
            exact = next((b for b in wc['packages'] if b.lower() == str(typed).lower()), None)
            if exact is None:
                best, order = _block_options(ctx, wc, str(typed))
                if best is not None:
                    return ('block', typed, best, order)
            fixed.append(typed)
        out.append(({'name': kw, 'value': ' '.join(fixed), 'op': 'set'}, {'jp': '/main/' + kw, 'key': kw, 'block': None}))
    for s in req['sets']:
        blk = s.get('block')
        if isinstance(blk, dict):
            best, order = _block_options(ctx, wc, blk['attempt'])
            return ('blockattempt', blk['attempt'], best, order)
        tgt = _target(s['name'], wc, blk)
        if isinstance(tgt, tuple):
            return tgt + (s,)
        out.append((s, tgt))
    return out


def _change(req, ctx, mods, base, wc):
    q = _attempt_question(req, ctx, wc, mods, base)
    if q is not None:
        return q
    items = _change_items(req, wc, ctx, mods)
    if isinstance(items, tuple):
        return _item_question(items, req, ctx, wc, mods, base)
    if not items:
        if req['unplaced'] or req['attempts']:
            return _unplaced_only(dict(req, unplaced=req['unplaced'] or [a['text'] for a in req['attempts']]), base)
        return _replay(req, ctx, base)
    # the same name twice with two values
    seen = {}
    for it, tgt in items:
        if tgt['jp'] in seen and it.get('value') != seen[tgt['jp']]:
            a, b = seen[tgt['jp']], it.get('value')
            return _ask('%s is given two values, %s and %s: which one?' % (tgt['key'], a, b), [a, b, 'run both'],
                        {a: {'stop': 'Re-run with %s = %s.' % (tgt['key'], a)},
                         b: {'stop': 'Re-run with %s = %s.' % (tgt['key'], b)},
                         'run both': {'stop': 'Run %s at %s and %s.' % (tgt['key'], a, b)}}, **base)
        seen[tgt['jp']] = it.get('value')
    changes = []
    for it, tgt in items:
        v = _prepare(it, tgt, wc, ctx)
        if isinstance(v, tuple):
            return _value_question(v, it, tgt, wc, ctx, base)
        changes.append((tgt['jp'], v))
    changes += list((mods.get('set') or {}).items())
    work = wc
    links = _plain_links_question(changes, wc, mods, base)
    if links is not None:
        if links[0] == 'ask':
            out, ans = links[1]
            plain = validate.validate(wc, changes, None, allow=mods.get('allow') or ())
            out['changes'] = _changes_from(plain, changes, wc, False)
            return out, ans
        work = links[1]
    res = validate.validate(work, changes, _selections_for(changes, ctx), allow=mods.get('allow') or ())
    return _change_outcome(res, changes, req, ctx, mods, base, work)


def _selections_for(changes, ctx):
    for jp, _ in changes:
        row = _schema_row(validate.name_of(jp))
        if row and 'selections' in row['legal_values']:
            return ctx.selections
    return None


def _item_question(info, req, ctx, wc, mods, base):
    kind = info[0]
    if kind in ('block', 'blockattempt'):
        typed, best, order = info[1], info[2], info[3]
        if best is not None:
            trial, _, _ = _resolve(_replace_words(req['phrase'], typed, best), ctx, dict(mods))
            if trial['type'] == 'STOP' and trial['changes'] and all(not c['applied'] for c in trial['changes']) \
                    and all(config_model.same_value(c['before'], c['after']) for c in trial['changes']):
                return _stop('%s is read as %s, which is already selected: nothing would change, and the results would '
                             'equal the last run.' % (typed, best), changes=trial['changes'], **base)
            changes = [dict(c, applied=False) for c in trial.get('changes') or []]
            if len([b for b in order if parse.letters(typed) in parse.letters(b)]) == 1:
                opts = [best, NONE_OF_THESE]
            else:
                opts = list(order)
            answers = {b: {'replace': [typed, b]} for b in opts if b != NONE_OF_THESE}
            answers[NONE_OF_THESE] = {'stop': 'Name the package block as the config spells it: %s.' % ', '.join(wc['packages'])}
            return _ask('Strict mode: there is no package block named %s in this config, so nothing runs. The blocks are '
                        '%s; the closest is %s.' % (typed, ', '.join(wc['packages']), best), opts, answers,
                        changes=changes, **base)
        opts = list(wc['packages'])
        return _ask('There is no package block named %s in this config. The blocks are %s.' % (typed, ', '.join(opts)),
                    opts, {b: {'replace': [typed, b]} for b in opts}, **base)
    if kind == 'noblock':
        opts = list(wc['packages'])
        return _ask('There is no package block named %s in this config.' % info[1], opts or [CANCEL],
                    {b: {'replace': [info[1], b]} for b in opts}, **base)
    if kind == 'sides':
        sel = info[1]
        s = info[2]
        opts = ['%s (TX)' % sel[0], '%s (RX)' % sel[-1], 'both']
        return _ask('TX and RX use different package blocks (%s for TX, %s for RX): which one should %s change?'
                    % (sel[0], sel[-1], s['name']), opts,
                    {opts[0]: {'replace': [s['name'], '%s in %s' % (s['name'], sel[0])]},
                     opts[1]: {'replace': [s['name'], '%s in %s' % (s['name'], sel[-1])]},
                     'both': {'stop': 'Change %s in each block: Re-run with %s = %s in %s and %s = %s in %s.'
                              % (s['name'], s['name'], s.get('value'), sel[0], s['name'], s.get('value'), sel[-1])}},
                    **base)
    return _stop('That cannot be resolved.', **base)


def _value_question(v, it, tgt, wc, ctx, base):
    kind, cur = v[0], v[1]
    name = tgt['key']
    if kind == 'novalue':
        return _ask('No value was given for %s, which is now %s. What should it be? Say for example: Re-run with %s = '
                    '<value>.' % (name, show(cur), name), ['give a value', CANCEL],
                    {'give a value': {'stop': 'Re-run with %s = <value>.' % name}, CANCEL: None}, **base)
    if kind == 'element':
        p = validate.parse_numbers(cur) if cur is not None else None
        rows = p[0] if p else []
        if len(rows) == 2:
            opts = ['TX row', 'RX row', 'both rows']
            text = '%s has two rows ([TX RX]) of %d values (%s): which should change?' % (name, len(rows[0]), show(cur))
        else:
            opts = ['TX', 'RX', 'both']
            text = '%s holds %s: which element should change?' % (name, show(cur))
        return _ask(text, opts, {o: {'stop': 'Give the whole value: Re-run with %s = [ ... ].' % name}
                                 for o in opts}, **base)
    if kind == 'noside':
        return _ask('%s holds one value (%s), not a [TX RX] pair: set it for both sides?' % (name, show(cur)),
                    ['both sides', CANCEL], {'both sides': {'stop': 'Re-run with %s = %s.' % (name, it['value'])}}, **base)
    if kind == 'norange':
        return _ask('%s is %s, not a range min:step:max, so there is no %s to change.' % (name, show(cur), it.get('part')),
                    [CANCEL], {}, **base)
    return _stop('That value cannot be resolved.', **base)


def _plain_links_question(changes, wc, mods, base):
    """A config whose linked values are plain numbers that still equal the usual formulas of the example config
    (row ST07): a change to the value they follow asks whether to scale them. Returns None, ('ask', outcome) or
    ('links', working config with the formulas put back)."""
    try:
        with open(EXAMPLE, encoding='utf-8') as f:
            example = json.load(f)
    except (OSError, ValueError):
        return None
    usual = {k: t for k, t in example.get('links', {}).items() if not k.startswith('packages.')}
    changed = {config_model.key_of(jp) for jp, _ in changes}
    follow = []
    for k, t in usual.items():
        if k in wc['links'] or k not in wc['main'] or k in changed:
            continue
        refs = config_model.link_names(t)
        if not set(refs) & changed:
            continue
        if not all(r in wc['main'] and r not in wc['links'] for r in refs):
            continue
        tmp = {'main': wc['main'], 'packages': {}, 'links': {k: t}}
        try:
            v = config_model.link_value(tmp, k)
        except (config_model.LinkError, config_model.LinkRefused, KeyError):
            continue
        cur = wc['main'][k]
        if isinstance(cur, (int, float)) and isinstance(v, (int, float)) and abs(cur - v) <= 1e-9 * max(1.0, abs(v)):
            follow.append(k)
    if not follow:
        return None
    if mods.get('links') == 'scale':
        new = copy.deepcopy(wc)
        for k in follow:
            new['links'][k] = usual[k]
        return ('links', new)
    if mods.get('links') == 'keep':
        return None
    src = ', '.join(sorted({r for k in follow for r in config_model.link_names(usual[k])} & changed))
    opts = ['scale them with %s' % src, 'change %s only' % src, CANCEL]
    out, ans = _ask('%s are plain values in this config, with no links, and they equal the usual ratios of the current %s. '
                    'Scale them with %s, or change %s only?' % (', '.join(follow), src, src, src), opts,
                    {opts[0]: {'links': 'scale'}, opts[1]: {'links': 'keep'}, CANCEL: None}, **base)
    return ('ask', (out, ans))


def _change_outcome(res, changes, req, ctx, mods, base, wc):
    applied = res['status'] == 'ok' and not req['unplaced']
    out_changes = _changes_from(res, changes, wc, applied)
    announce = list(res['announce'])
    if res['status'] == 'stop':
        return _stop(_sentence(res['text']), changes=out_changes, announce=announce, **base)
    if res['status'] == 'ask':
        opts = list(res['options'])
        answers = {}
        for o in opts:
            a = res['answers'].get(o)
            answers[o] = None if a is None else ({'set': a['set']} if 'set' in a else {'allow': a.get('allow', [])})
        return _ask(_sentence(res['text']), opts, answers, changes=out_changes, announce=announce, **base)
    if req['unplaced'] and not mods.get('ignore_unplaced'):
        said = '; '.join('%s: %s -> %s' % (validate.name_of(c['json_path']), show(c['before']), show(c['after']))
                         for c in out_changes if c['kind'] != 'linked')
        opt = 'run the change that was understood (%s)' % said
        return _ask('Strict mode: %s could not be placed, so nothing runs. What was understood: %s.'
                    % (_words(req['unplaced']), said), [opt, CANCEL], {opt: {'ignore_unplaced': True}, CANCEL: None},
                    changes=out_changes, announce=announce, **base)
    steps = []
    for c in out_changes:
        if c['kind'] in ('set', 'add'):
            steps.append(_step('set_param' if c['kind'] == 'set' else 'add_param', json_path=c['json_path'],
                               before=c['before'], after=c['after']))
    linked = [c for c in out_changes if c['kind'] == 'linked']
    if linked:
        steps.append(_step('recompute_linked', changes=[{'json_path': c['json_path'], 'before': c['before'],
                                                         'after': c['after']} for c in linked]))
    steps += [_step('validate_config'), _step('run_com', thru_only=bool(mods.get('thru_only') or
                                                                       'thru_only' in req['flags'])), _step('summarize')]
    announce = _change_lines(out_changes, wc) + announce + _context_lines(ctx, out_changes, wc)
    return outcome('PLAN', steps=steps, changes=out_changes, announce=announce, **base), {}


def _sentence(text):
    t = text.strip()                      # a COM keyword keeps its spelling, so the first letter is left as it is
    return t + ('' if t.endswith('.') else '.') if t else t


def _changes_from(res, changes, wc, applied):
    out = [dict(c, applied=applied) for c in res['changes']]
    have = {c['json_path'] for c in out}
    for c in res['unchanged']:
        out.append(dict(c, applied=False))
        have.add(c['json_path'])
    if res['config'] is None:
        for jp, v in res['values'].items():
            if jp in have:
                continue
            before = config_model.get_value(wc, config_model.key_of(jp)) if _exists(wc, jp) else None
            out.append({'json_path': jp, 'before': before, 'after': v, 'kind': 'set' if before is not None else 'add',
                        'applied': False})
        order = [jp for jp, _ in changes]
        out.sort(key=lambda c: order.index(c['json_path']) if c['json_path'] in order else len(order))
    return out


def _change_lines(changes, wc):
    lines = []
    for c in changes:
        n = validate.name_of(c['json_path'])
        where = '' if c['json_path'].startswith('/main/') else ' in %s' % c['json_path'].split('/')[2]
        if c['kind'] == 'add':
            lines.append('%s%s was not in this config, so the loader default was in use; an entry %s = %s is added'
                         % (n, where, n, show(c['after'])))
        elif c['kind'] == 'linked':
            lines.append('%s%s follows by its link: %s -> %s' % (n, where, show(c['before']), show(c['after'])))
        else:
            key = config_model.key_of(c['json_path'])
            link = wc['links'].get(key)
            lines.append('%s%s: %s -> %s%s' % (n, where, show(c['before']), show(c['after']),
                                                '; it was linked (=%s), and the explicit value removes the link in the '
                                                'working config' % link if link else ''))
    return lines


def _context_lines(ctx, changes, wc):
    lines = []
    rec = ctx.last
    ov = (rec or {}).get('overrides') or []
    if ov:
        lines.append('active overrides kept from earlier runs: %s'
                     % '; '.join('%s = %s' % (validate.name_of(o['json_path']), show(o['after'])) for o in ov))
    if any(validate.name_of(c['json_path']).strip().lower() == 'pkg_name' for c in changes if c['kind'] == 'set'):
        rt = _current(wc, 'RUNTAG')
        lines.append('RUNTAG (%s) and the source file name are not changed by this; they may still name the package '
                     'that was selected before' % show(rt))
    if rec and rec.get('source') and rec['source'].get('path'):
        p = ctx.path(rec['source']['path'])
        if os.path.exists(p) and rec['source'].get('sha256') and _sha(p) != rec['source']['sha256']:
            lines.append('the source config %s changed since the last run; the run uses the working config of the last '
                         'run with this change' % rec['source']['path'])
        lock = os.path.join(os.path.dirname(p), '~$' + os.path.basename(p))
        if os.path.exists(lock):
            lines.append('%s is open in Excel: unsaved edits there are not included' % rec['source']['path'])
    return lines


# ----------------------------------------------------------------------------- sweeps (Decisions 5, 6, 7)
def _count_or_step(sw):
    """('count', n) | ('step', size) | ('ask', why, options) from the words of a range (Decision 5)."""
    if sw.get('how') == 'step' or (sw.get('step') is not None):
        return 'step', float(sw['step'])
    if sw.get('count') is None:
        return 'ask', 'no step given', ['give a step', 'give a number of points', CANCEL]
    x = float(sw['count'])
    if x == int(x):
        if x == 0:
            return 'ask', '0 cannot be a count or a step size', ['give a count of 2 or more', 'give a step size', CANCEL]
        if x == 1:
            return 'ask', 'a count of 1 cannot cover a range (the step formula divides by zero)', \
                ['give a count of 2 or more', 'give a step size', CANCEL]
        if x < 0:
            return 'ask', 'a count cannot be negative', ['give a count of 2 or more', 'give a step size', CANCEL]
        return 'count', int(x)
    if sw.get('how') == 'points':
        return 'ask', 'a number of points must be a whole number', ['give a count of 2 or more', 'give a step size', CANCEL]
    return 'step', x


def _range_points(a, b, how, n_or_step):
    if how == 'count':
        n = n_or_step
        return [validate._round(a + i * (b - a) / (n - 1)) for i in range(n)]
    s = abs(n_or_step)
    if s == 0:
        return []
    s = s if b >= a else -s
    vals, _ = validate.matlab_range(a, s, b)
    return [validate._round(v) for v in vals]


def _legal(name, wc, ctx, tgt):
    """[(spoken, write)] of a name with a closed list of values, else None."""
    row = _schema_row(name, 'package block' if tgt['block'] else 'main')
    if row is None:
        return None
    kind = row['kind']
    if kind == 'switch':
        return [(0, 0), (1, 1)]
    if kind == 'choice':
        out = []
        for v in validate.legal_values(row):
            num = validate._plain_number(str(v))
            out.append((num if num is not None else v, num if num is not None else v))
        return out
    if kind == 'choice from the config':
        if row['shape'].strip() == 'list of case numbers':
            allc = _all_cases(wc, name)
            if isinstance(allc, tuple):
                return None
            n = len(allc.strip('[] ').split())
            return [(i, '[ %d ]' % i) for i in range(1, n + 1)]
        if 'package block' in row['legal_values']:
            return [(b, '%s %s' % (b, b)) for b in wc['packages']]
        if 'selections' in row['legal_values']:
            orders = next((v for k, v in ctx.selections.items() if 'port' in k.lower()), [])
            return [(str(o), str(o)) for o in orders] or None
    return None


def _dimension(sw, req, ctx, wc, mods):
    """One swept name: {'jp', 'name', 'points': [(spoken, write)], 'notes'} or an outcome tuple."""
    base = dict(pattern=req['pattern'], unplaced=list(req['unplaced']))
    name = sw['name']
    tgt = _target(name, wc, sw.get('block') if not isinstance(sw.get('block'), dict) else None)
    if isinstance(tgt, tuple):
        return _item_question(tgt + ({'name': name, 'value': None},), req, ctx, wc, mods, base)
    name = tgt['key']
    row = _schema_row(name, 'package block' if tgt['block'] else 'main')
    kind = row['kind'] if row else 'number'
    cur = config_model.get_value(wc, config_model.key_of(tgt['jp'])) if _exists(wc, tgt['jp']) else None
    legal = _legal(name, wc, ctx, tgt)
    notes = []
    dim = {'jp': tgt['jp'], 'name': name}
    if sw.get('every'):
        if legal:
            dim['points'] = legal
            return dim
        if kind == 'text':
            return _stop('%s is text with no list of legal values: there is nothing to sweep.' % name, **base)
        what = {'search range': 'already holds a search range for one run', 'matrix': 'holds several values',
                'vector': 'holds several values'}.get(kind, 'is a number')
        if kind == 'number' and _pair(cur) is not None:
            what = 'is a [TX RX] pair of numbers'
        elif kind == 'number' and cur is not None and len(validate._flat(validate.parse_numbers(cur) or ([], []))) > 2:
            what = 'holds several values'
        return _ask('%s %s, with no closed list of values: give a range (Sweep %s from <a> to <b> in <count> steps) or a '
                    'list of values (Run %s at <v1>, <v2> and <v3>).' % (name, what, name, name),
                    ['give a range', 'give a list of values', CANCEL],
                    {'give a range': {'stop': 'Sweep %s from <a> to <b> in <count> steps.' % name},
                     'give a list of values': {'stop': 'Run %s at <v1>, <v2> and <v3>.' % name}, CANCEL: None}, **base)
    # the numbers asked for
    unit = sw.get('unit')
    factor = 1.0
    if unit:
        stored = (row or {}).get('stored_unit', '').strip()
        accepted = [u.strip().lower() for u in (row or {}).get('accepted_units', '').split(',') if u.strip()]
        if unit.lower() not in accepted or stored.lower() not in validate.UNIT_FACTORS:
            return _ask('%s is not a unit %s takes%s.' % (unit, name, ' (it is stored in %s)' % stored if stored else ''),
                        [CANCEL], {}, **base)
        factor = validate.UNIT_FACTORS[unit.lower()] / validate.UNIT_FACTORS[stored.lower()]
        if unit != stored:
            notes.append('%s is converted from %s to %s, the unit %s is stored in' % (name, unit, stored, name))
    if 'values' in sw:
        try:
            nums = [float(v) * factor for v in sw['values']]
            spoken = [validate._round(x) for x in nums]
        except ValueError:
            spoken = list(sw['values'])
        how = 'list'
    else:
        a, b = float(sw['start']) * factor, float(sw['end']) * factor
        edit = mods.get('sweep_edit') or {}
        if edit.get('count'):
            sw = dict(sw, count=edit['count'], step=None, how='steps')
        elif edit.get('step'):
            sw = dict(sw, step=edit['step'], count=None, how='step')
        cs = _count_or_step(sw)
        if cs[0] == 'ask':
            return _ask('%s: %s.' % (_sentence(cs[1]).rstrip('.'), 'say how the range is divided'), cs[2],
                        {o: {'stop': 'Give the sweep again with a %s.' % o.replace('give ', '')} for o in cs[2] if o != CANCEL},
                        **base)
        how, x = cs
        if how == 'step':
            x = x * factor
        spoken = _range_points(a, b, how, x)
        if how == 'step' and len(spoken) == 1 and a != b:
            return _ask('%s is not a whole number, so it is a step size, and it is larger than the whole range (%s): only the '
                        'start point would run.' % (show(x), _num_text(abs(b - a))),
                        ['one run at %s' % _num_text(a), 'give a smaller step size', 'give a count', CANCEL],
                        {'one run at %s' % _num_text(a): {'stop': 'Re-run with %s = %s.' % (name, _num_text(a))},
                         'give a smaller step size': {'stop': 'Give the sweep again with a smaller step size.'},
                         'give a count': {'stop': 'Give the sweep again with a count of points.'}, CANCEL: None}, **base)
        dim['how'] = how
        if how == 'count' and len(spoken) > 1:
            notes.append('a whole number after in is a count of points that includes both ends: %d points, step %s'
                         % (len(spoken), _num_text((b - a) / (len(spoken) - 1))))
    # what kind of name it is
    if kind == 'text':
        return _stop('%s is text, not a number, and has no list of legal values: it cannot be swept.' % name, **base)
    if kind == 'search range' and 'values' not in sw:
        rng = '[%s:%s:%s]' % (sw['start'], show(x) if how == 'step' else _num_text((b - a) / (len(spoken) - 1)), sw['end'])
        o1, o2 = 'one run with %s searched over %s' % (name, rng), 'a batch of runs with %s held at each value' % name
        if mods.get('held') is None:
            return _ask('%s is itself a search range inside one run.' % name, [o1, o2],
                        {o1: {'stop': 'Re-run with %s = %s.' % (name, rng)}, o2: {'held': True}}, **base)
    if legal is not None and kind in ('switch', 'choice', 'choice from the config'):
        spoken_legal = {validate.show(sp): (sp, wr) for sp, wr in legal}
        nums_legal = all(isinstance(sp, (int, float)) for sp, _ in legal)
        if not nums_legal and 'values' in sw:
            by = {str(sp).lower(): (sp, wr) for sp, wr in legal}
            if all(str(v).lower() in by for v in sw['values']):
                dim['points'] = [by[str(v).lower()] for v in sw['values']]
                dim['notes'] = notes
                return dim
        if not nums_legal:
            return _ask('%s takes named values (%s), not a numeric range.' % (name, ', '.join(show(s) for s, _ in legal)),
                        ['sweep all of them', CANCEL], {'sweep all of them': {'stop': 'Sweep %s.' % name}, CANCEL: None},
                        **base)
        want = [validate.show(validate._plain_number(show(p)) if validate._plain_number(show(p)) is not None else p)
                for p in spoken]
        if not all(w in spoken_legal for w in want):
            return _ask('%s only takes the values %s, and the range asks for %s.' % (
                name, ', '.join(show(s) for s, _ in legal), ', '.join(show(p) for p in spoken)),
                ['sweep the legal values', CANCEL], {'sweep the legal values': {'stop': 'Sweep %s.' % name}, CANCEL: None},
                **base)
        dim['points'] = [spoken_legal[w] for w in want]
        dim['notes'] = notes
        return dim
    whole = row is not None and row['whole_number'].startswith('yes')
    if whole and any(isinstance(p, float) and p != int(p) for p in spoken):
        if mods.get('whole') is not None:
            spoken = mods['whole']
        elif dim.get('how') == 'count':
            rounded = list(dict.fromkeys(int(math.floor(p + 0.5)) for p in spoken))
            o = 'run %s' % _and([str(r) for r in rounded])
            return _ask('%d points from %s to %s are %s and %s must be a whole number.' % (
                len(spoken), show(spoken[0]), show(spoken[-1]), ', '.join(validate.short(round(p, 3)) for p in spoken), name),
                [o, 'give another count', 'give a step size', CANCEL],
                {o: {'whole': rounded}, 'give another count': {'stop': 'Give the sweep again with another count.'},
                 'give a step size': {'stop': 'Give the sweep again with a step size.'}, CANCEL: None}, **base)
        else:
            keep = [int(p) for p in spoken if p == int(p)]
            o = 'run %s only' % _and([str(k) for k in keep])
            asked = next(p for p in spoken if p != int(p))           # the first value the loader would refuse
            return _ask('%s must be a whole number and the range asks for %s.' % (name, ', '.join(show(p) for p in spoken)),
                        [o, CANCEL], {o: {'whole': keep}, CANCEL: None},
                        changes=[{'json_path': tgt['jp'], 'before': cur, 'after': asked, 'kind': 'set', 'applied': False}],
                        **base)
    spoken = [int(p) if whole and isinstance(p, float) and p == int(p) else p for p in spoken]
    # how each value is written
    nums = validate.parse_numbers(cur) if cur is not None else None
    flat = validate._flat(nums) if nums else []
    if kind in ('matrix', 'vector') and len(flat) > 1 or (kind == 'number' and len(flat) > 2) or \
            (kind == 'number' and len(flat) == 2 and 'TX RX' not in (row or {}).get('shape', '')):
        return _ask('%s holds %d values (%s): a sweep needs to know which of them.' % (name, len(flat), show(cur)),
                    ['name the element', 'sweep all of them together'],
                    {'name the element': {'stop': 'Give the whole value at each point: Run %s at [ ... ], [ ... ].' % name},
                     'sweep all of them together': {'stop': 'Give the whole value at each point: Run %s at [ ... ], [ ... ].'
                                                    % name}}, **base)
    side = sw.get('side') or mods.get('side')
    if len(flat) == 2:
        if flat[0] != flat[1] and not side:
            o = ['sweep TX', 'sweep RX', 'sweep both together']
            return _ask('%s is a [TX RX] pair with different values (%s).' % (name, show(cur)), o,
                        {o[0]: {'side': 'TX'}, o[1]: {'side': 'RX'}, o[2]: {'side': 'both'}, CANCEL: None}, **base)
        txt = [show(x) for x in flat]

        def write(p):
            el = list(txt)
            if side in (None, 'both'):
                el = [show(p), show(p)]
            else:
                el[0 if side == 'TX' else 1] = show(p)
            return '[%s %s]' % tuple(el)
        if side in (None, 'both'):
            notes.append('%s is a [TX RX] pair, so each point is written to both sides' % name)
        else:
            notes.append('only the %s element of %s changes; the other keeps %s' % (side, name, txt[1 if side == 'TX' else 0]))
        dim['points'] = [(p, write(p)) for p in spoken]
    elif isinstance(cur, str) and cur.strip().startswith('[') and len(flat) == 1 and kind != 'search range':
        dim['points'] = [(p, '[%s]' % show(p)) for p in spoken]
    else:
        dim['points'] = [(p, p) for p in spoken]
    dim['notes'] = notes
    return dim


def _and(items):
    return ', '.join(items[:-1]) + ' and ' + items[-1] if len(items) > 1 else (items[0] if items else '')


def _sweep(req, ctx, mods, base_fields):
    wc = ctx.wc
    base = base_fields
    q = _attempt_question(req, ctx, wc, mods, base)
    if q is not None:
        return q
    sweeps = list(req['sweeps'])
    fixed = []
    for s in req['sets']:
        if s.get('op') == 'all' and not _is_case_list(s['name']):
            sweeps.append({'name': s['name'], 'every': True})
            continue
        tgt = _target(s['name'], wc, s.get('block') if not isinstance(s.get('block'), dict) else None)
        if isinstance(tgt, tuple):
            return _item_question(tgt + (s,), req, ctx, wc, mods, base)
        v = _prepare(s, tgt, wc, ctx)
        if isinstance(v, tuple):
            return _value_question(v, s, tgt, wc, ctx, base)
        fixed.append((tgt['jp'], v))
    dims = []
    for sw in sweeps:
        d = _dimension(sw, req, ctx, wc, mods)
        if isinstance(d, tuple):
            return d
        dims.append(d)
    if req['unplaced'] and not mods.get('ignore_unplaced'):
        return _unplaced_only(req, base)
    notes = [n for d in dims for n in d.get('notes', [])]
    combos = list(itertools.product(*[d['points'] for d in dims]))
    channels = ctx.channels()
    chan_shas = [s for _, s, _ in channels]
    sic = engine.engine_sha256()
    prior = ctx.runs
    last = ctx.last_run_id()
    last_fp = next((fp for rid, fp in prior if rid == last), None)
    sel = _selections_for([(d['jp'], None) for d in dims] + fixed, ctx)
    points, asks, new_fps = [], [], []
    for combo in combos:
        values = {d['jp']: sp for d, (sp, _) in zip(dims, combo)}
        writes = dict(fixed)
        writes.update({d['jp']: wr for d, (_, wr) in zip(dims, combo)})
        res = validate.validate(wc, list(writes.items()), sel, allow=mods.get('allow') or ())
        pt = {'values': values, 'writes': writes, 'new': False, 'reused_from': None, 'skipped': None}
        eff = res.get('effect') or {}
        if res['config'] is None or eff.get('error'):
            pt['skipped'] = 'validate_config fails: %s' % (eff.get('error') or res['text'])
            points.append(pt)
            continue
        if res['status'] == 'ask':
            asks.append((pt, res))
        fields, err = config_model.loaded_fields(res['config'])
        if err:
            pt['skipped'] = 'validate_config fails: %s' % err
            points.append(pt)
            continue
        fp = _fingerprint(fields, chan_shas, sic)
        rid = next((r for r, f in prior if _same_fingerprint(f, fp)), None)
        if rid is not None:
            pt['reused_from'] = rid
        elif any(_same_fingerprint(f, fp) for f in new_fps):
            pt['reused_from'] = 'earlier point of this batch'
        else:
            pt['new'] = True
            new_fps.append(fp)
        points.append(pt)
    n_new = sum(1 for p in points if p['new'])
    n_reused = sum(1 for p in points if p['reused_from'])
    skipped = [p for p in points if p['skipped']]
    fields = dict(points=points, new_runs=n_new, reused_runs=n_reused, **base)
    label = lambda p: ', '.join(show(v) for v in p['values'].values())                  # noqa: E731
    if asks and not mods.get('only'):
        bad = [label(p) for p, _ in asks]
        good = [p for p in points if not p['skipped'] and label(p) not in bad]
        r = asks[0][1]
        o = 'run %s only' % _and([label(p) for p in good]) if good else None
        opts = ([o] if o else []) + [CANCEL]
        return _ask('%s: %s' % (_sentence(r['text']).rstrip('.'), 'the sweep asks for %s' % _and(bad)), opts,
                    {o: {'only': [label(p) for p in good]}} if o else {}, **fields)
    if mods.get('only'):
        keep = set(mods['only'])
        points = [p for p in points if label(p) in keep]
        n_new = sum(1 for p in points if p['new'])
        n_reused = sum(1 for p in points if p['reused_from'])
        fields.update(points=points, new_runs=n_new, reused_runs=n_reused)
    if not n_new and len(skipped) == len(points):
        return _stop('No value in the sweep passes validate_config: %s.' % '; '.join(
            '%s: %s' % (label(p), p['skipped']) for p in skipped), **fields)
    if not n_new and not skipped and last_fp is not None and all(p['reused_from'] == last for p in points):
        why = 'the value given changes no engine input' if len(points) == 1 else \
            'none of the %d values changes an engine input' % len(points)
        return _stop('%s: every result would equal the last run, so nothing runs.' % _sentence(why).rstrip('.'), **fields)
    limit = ctx.setting('max_new_runs')
    summary = '%d %s: %d new %s, %d reused' % (len(points), 'value' if len(points) == 1 else 'values', n_new,
                                               'run' if n_new == 1 else 'runs', n_reused) + \
              (', %d skipped because validate_config fails' % len(skipped) if skipped else '')
    if n_new > limit and not mods.get('confirm_limit'):
        o_run, o_edit = 'run all', 'edit the sweep (range, count or step size)'
        return _ask('%s. That is more new runs than max_new_runs (%d), so the batch waits for you: run all, edit the '
                    'sweep, or cancel.' % (_sentence(summary).rstrip('.'), limit), [o_run, o_edit, CANCEL],
                    {o_run: {'confirm_limit': True}, o_edit: {'stop': 'Say the edit, for example: Use 16 steps instead.'},
                     CANCEL: None}, announce=notes, **fields)
    diff = any(a in req['actions'] for a in ('summary', 'compare'))
    steps = []
    if n_new:
        steps += [_step('build_matrix', names=[d['name'] for d in dims], points=len(points)), _step('validate_config'),
                  _step('run_batch', new_runs=n_new)]
    steps.append(_step('batch_summary'))
    if diff:
        steps.append(_step('diff_results', against='the last run'))
    announce = ['%s = %s' % (d['name'], ', '.join(show(sp) for sp, _ in d['points'])) for d in dims]
    announce.append(summary)
    for p in points:
        if p['reused_from']:
            announce.append('%s is reused from %s' % (label(p), p['reused_from']))
        if p['skipped']:
            announce.append('%s is skipped: %s' % (label(p), p['skipped']))
    if not n_new:
        announce.append('every value was already run, so no new run is needed')
    announce += notes + _context_lines(ctx, [], wc)
    return outcome('PLAN', steps=steps, announce=announce, **fields), {}


# ----------------------------------------------------------------------------- runs from files
def _first_run(req, ctx, mods, base):
    """Run COM on a channel file with a config file (or the files in the folder)."""
    configs = [f['text'] for f in req['files'] if f['ext'] in CONFIG_EXT + ('.mat',)]
    chans = [f['text'] for f in req['files'] if f['ext'] == 'channel']
    found_cfg = ctx.config_files()
    found_ch = ctx.channel_files()
    announce = []
    if 'example' in req['flags'] and not configs:
        return _stop('The example setup has no channel file of its own in this version. Name a channel file and a '
                     'config, for example: Run COM on data\\thru.s4p with data\\config.xlsx.', **base)
    if not configs:
        cands = [c for c in found_cfg]
        if len(cands) == 1:
            configs = cands
            announce.append('the config was taken as %s, the only config in this folder' % cands[0])
        elif not cands:
            return _ask('There is no config in this project folder. Name one, for example: Run COM on data\\thru.s4p with '
                        'data\\config.xlsx.', ['the example setup', 'provide files'],
                        {'the example setup': {'stop': 'Run SiCoPR on the example setup.'},
                         'provide files': {'stop': 'Name the files: Run COM on <channel> with <config>.'}}, **base)
        else:
            opts = cands + ['the example setup']
            return _ask('There is more than one config in this folder: which one?', opts,
                        {c: {'stop': 'Run COM on <channel> with %s.' % c} for c in opts}, **base)
    if not chans:
        if len(found_ch) == 1:
            chans = found_ch
            announce.append('the channel was taken as %s, the only channel file in this folder' % found_ch[0])
        elif found_ch:
            return _ask('There is more than one channel file in this folder: which one?', found_ch + [CANCEL],
                        {c: {'stop': 'Run COM on %s with %s.' % (c, configs[0])} for c in found_ch}, **base)
    cfg = configs[0]
    path = ctx.path(cfg)
    if not os.path.exists(path):
        opts = [c for c in found_cfg if c != cfg] + ['the example setup']
        return _ask('%s does not exist in this project folder.' % cfg, opts,
                    {o: {'replace': [cfg, o]} for o in opts if o != 'the example setup'} |
                    {'the example setup': {'stop': 'Run SiCoPR on the example setup.'}}, **base)
    for c in chans:
        if not os.path.exists(ctx.path(c)):
            return _ask('%s does not exist in this project folder.' % c, [x for x in found_ch if x != c] + [CANCEL],
                        {x: {'replace': [c, x]} for x in found_ch if x != c}, **base)
        bad = touchstone_problem(ctx.path(c))
        if bad:
            return _stop('%s is not a valid Touchstone file: %s. Nothing runs.' % (c, bad), **base)
    sel = None
    if path.lower().endswith(('.xlsx', '.xls')):
        try:
            sel = xlsx_io.selection_lists(path)
        except Exception:
            sel = None
    fix = mods.get('import_fix')
    wc, res = validate.validate_import(path, sel, allow=mods.get('allow') or ())
    if fix and wc is not None:
        wc = copy.deepcopy(wc)
        old, new = fix
        wc['main'] = {(new if k == old else k): v for k, v in wc['main'].items()}
        res = validate.validate_config(wc, sel, allow=mods.get('allow') or ())
    announce += [f['text'] for f in res['findings'] if f['status'] == 'announce']
    if res['status'] == 'stop':
        return _stop(_sentence(res['text']), announce=announce, **base)
    if res['status'] == 'ask':
        lead = next(f for f in res['findings'] if f['status'] == 'ask')
        issue = _import_issue(path, lead)
        if issue is not None:
            return _ask(_sentence(lead['text']), issue[0], issue[1], announce=announce, **base)
        opts = list(res['options']) or [CANCEL]
        answers = {o: (None if res['answers'].get(o) is None else
                       ({'set': res['answers'][o]['set']} if 'set' in res['answers'][o] else {'allow': res['answers'][o].get('allow', [])}))
                   for o in opts}
        return _ask(_sentence(res['text']), opts, answers, announce=announce, **base)
    is_json = path.lower().endswith('.json')
    steps = [] if is_json else [_step('import_config', path=cfg)]
    changes = []
    if req['sets'] or req['packages'] or req['attempts']:
        ctx._c['base'] = (wc, 'import', [])
        ctx._c['source_path'] = path if path.lower().endswith(('.xlsx', '.xls')) else ctx.source_path
        q = _attempt_question(req, ctx, wc, mods, base)
        if q is not None:
            return q
        items = _change_items(req, wc, ctx, mods)
        if isinstance(items, tuple):
            return _item_question(items, req, ctx, wc, mods, base)
        ch = []
        for it, tgt in items:
            v = _prepare(it, tgt, wc, ctx)
            if isinstance(v, tuple):
                return _value_question(v, it, tgt, wc, ctx, base)
            ch.append((tgt['jp'], v))
        r = validate.validate(wc, ch, _selections_for(ch, ctx), allow=mods.get('allow') or ())
        sub = _change_outcome(r, ch, req, ctx, mods, base, wc)[0]
        if sub['type'] != 'PLAN':
            return sub, {}
        changes = sub['changes']
        steps += [s for s in sub['steps'] if s['op'] in ('set_param', 'add_param', 'recompute_linked')]
        steps.append(_step('validate_config'))
        announce += [a for a in sub['announce'] if a not in announce]
    elif is_json:
        steps.append(_step('validate_config'))
    elif req['unplaced'] and not mods.get('ignore_unplaced'):
        return _unplaced_only(req, base)
    steps += [_step('validate_inputs', channels=chans), _step('run_com', channels=chans, thru_only=len(chans) <= 1),
              _step('summarize')]
    return outcome('PLAN', steps=steps, changes=changes, announce=announce, **base), {}


def touchstone_problem(path):
    """Why a channel file does not read as Touchstone (version 1: an option line, then for each frequency one
    number and 2 x N x N more for an .sNp file), naming the line; None when it reads. Row R7."""
    m = parse.CHANNEL_EXT.search(path)
    ports = int(re.search(r'\d+', m.group(0)).group(0)) if m else 4
    per = 1 + 2 * ports * ports
    count, last = 0, 0
    option = False
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for n, line in enumerate(f, 1):
                text = line.split('!', 1)[0].strip()
                if not text:
                    continue
                if text.startswith('#'):
                    option = True
                    continue
                for tok in text.split():
                    try:
                        float(tok)
                    except ValueError:
                        return 'line %d holds %r, which is not a number' % (n, tok)
                    count += 1
                last = n
    except OSError as e:
        return 'it cannot be read (%s)' % e
    if not option:
        return 'it has no option line (#)'
    if count == 0:
        return 'it holds no data'
    if count % per:
        return 'the data ends in the middle of a frequency point at line %d (%d numbers, %d per point)' % (last, count, per)
    return None


def _import_issue(path, lead):
    """Options for the import questions no rule covers: a label that is nearly a keyword (row ST05), an unknown
    key in a working-config .json (row CP15)."""
    import difflib
    m = re.search(r'label "([^"]+)".*did you mean "([^"]+)"', lead['text'])
    if m:
        label, kw = m.group(1), m.group(2)
        o1, o2 = 'treat it as %s' % kw, 'leave it (%s keeps the loader default)' % kw
        return [o1, o2, CANCEL], {o1: {'import_fix': [label, kw]}, o2: {'allow': [lead['rule'] or 'near_keyword']},
                                  CANCEL: None}
    m = re.match(r'unknown key (\S+)', lead['text'])
    if m:
        key = m.group(1)
        known = engine.keyword_names('main')
        near = difflib.get_close_matches(key.lower(), [k.lower() for k in known], n=3, cutoff=0.6)
        near = [next(k for k in known if k.lower() == n) for n in near]
        opts = near + [NONE_OF_THESE]
        return opts, {n: {'import_fix': [key, n]} for n in near} | {NONE_OF_THESE: {'stop': 'Fix the key %s in the file.' % key}}
    return None


# ----------------------------------------------------------------------------- other requests
def _replay(req, ctx, base, thru_only=False):
    rec = ctx.last
    if rec is None:
        return _no_history(ctx, base)
    steps = [_step(s['op'], **(s.get('args') or {})) for s in ((rec.get('plan') or {}).get('steps') or [])
             if s.get('op') in STEPS] or [_step('validate_config'), _step('run_com'), _step('summarize')]
    announce = ['replays the last command: %s' % rec.get('phrase')]
    for path, sha, role in ctx.channels():
        old = next((c.get('sha256') for c in rec.get('channels') or [] if c['path'] == path), None)
        if sha != old:
            announce.append('%s changed since the last run' % path)
    from sicopr_assist import __version__
    if rec.get('tool_version') and rec['tool_version'] != __version__:
        announce.append('the record was written by SiCoPR-Assist %s; its stored plan is replayed' % rec['tool_version'])
    return outcome('PLAN', steps=steps, announce=announce + _context_lines(ctx, [], ctx.wc or {'links': {}, 'main': {}}),
                   **base), {}


def _reset(req, ctx, base):
    src = ctx.source_path
    if ctx.last is None or not src:
        return _no_history(ctx, base)
    return outcome('PLAN', steps=[_step('clear_overrides'), _step('run_com'), _step('summarize')],
                   announce=['every override is dropped: the run uses %s as imported' % os.path.relpath(src, ctx.root)],
                   **base), {}


def _show(req, text, ctx, base):
    low = text.lower().strip()
    wc = ctx.wc
    if re.search(r'\bwhat can i change\b|\blist (?:the |all )?param', low):
        if wc is None:
            return _no_history(ctx, base)
        return outcome('PLAN', steps=[_step('list_parameters')],
                       announce=['%d parameters in the main area, %d package blocks' % (len(wc['main']), len(wc['packages']))],
                       **base), {}
    if re.search(r'\bwhat (did you|have you) change|\bwhat changed\b|\bshow (me )?the overrides\b', low):
        rec = ctx.last
        ov = (rec or {}).get('overrides') or []
        lines = ['%s: %s -> %s' % (validate.name_of(o['json_path']), show(o['before']), show(o['after'])) for o in ov] or \
            ['the last run used the imported config as is']
        return outcome('PLAN', steps=[_step('show_overrides')], announce=lines, **base), {}
    if re.search(r'^show (me )?the config\b|^show config\b', low):
        if wc is None:
            return _no_history(ctx, base)
        return outcome('PLAN', steps=[_step('show_config')], announce=['the working config of the last run'], **base), {}
    if re.search(r'^(show|list) (me )?(the )?settings\b|^show limits\b|^what are my limits\b', low) and not req['sets']:
        s = ctx.settings
        lines = ['%s = %s (%s)' % (k, v, s['sources'][k]) for k, v in s['values'].items()] + s['warnings']
        return outcome('PLAN', steps=[_step('show_settings')], announce=lines, **base), {}
    if (re.search(r'\bwhat is\b.*\bset to\b|^show\b|\bcurrent\b', low) and len(req['sets']) == 1
            and req['sets'][0].get('value') is None and wc is not None and not req['sweeps']):
        n = req['sets'][0]['name']
        return outcome('PLAN', steps=[_step('show_param', name=n)],
                       announce=['%s is %s in the working config of the last run' % (n, show(_current(wc, n)))], **base), {}
    return None


def _save(req, ctx, base):
    wc = ctx.wc
    files = [f['text'] for f in req['files'] if f['ext'] in ('.xlsx', '.xls')]
    if wc is None:
        return _no_history(ctx, base)
    if not files:
        return _ask('Save the config under which name? For example: Save that config as data\\config_new.xlsx.',
                    [CANCEL], {}, **base)
    out = ctx.path(files[0])
    src = ctx.source_path
    if src and os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(src)):
        return _stop('%s is the source config, which is never written to. Name another file.' % files[0], **base)
    if os.path.exists(out):
        return _ask('%s exists already.' % files[0], ['overwrite it', 'give a new name', CANCEL],
                    {'overwrite it': {'stop': 'Remove %s first, then save again.' % files[0]},
                     'give a new name': {'stop': 'Save that config as <new name>.xlsx.'}, CANCEL: None}, **base)
    return outcome('PLAN', steps=[_step('export_xlsx', path=files[0])],
                   announce=['the working config of the last run is written into a copy of %s as %s; only the changed '
                             'cells are rewritten' % (os.path.relpath(src, ctx.root) if src else 'the source', files[0])],
                   **base), {}


def _fmt_field(v):
    import numpy as np

    def num(x):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return str(x)
        return str(int(x)) if x == int(x) and abs(x) < 1e9 else '%.6g' % x
    if isinstance(v, np.ndarray):
        if v.size <= 8:
            return '[' + ' '.join(num(x) for x in v.ravel()) + ']'
        return '%d values %s..%s' % (v.size, num(v.ravel()[0]), num(v.ravel()[-1]))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return num(v)
    return str(v)


def _compare(req, ctx, base):
    """How this config differs from another: keywords in only one, values that differ, loaded fields that differ."""
    files = [f['text'] for f in req['files'] if f['ext'] in CONFIG_EXT]
    ref = ctx.path(files[0])
    if not os.path.exists(ref):
        return _ask('%s does not exist in this project folder.' % files[0], [CANCEL], {}, **base)
    others = [c for c in ctx.config_files() if os.path.normcase(ctx.path(c)) != os.path.normcase(ref)]
    if len(others) != 1:
        return _ask('Which config should be compared with %s?' % files[0], others + [CANCEL],
                    {o: {'stop': 'How does %s differ from %s?' % (o, files[0])} for o in others}, **base)
    this = ctx.path(others[0])
    a, _ = config_model.import_config(ref)
    b, _ = config_model.import_config(this)
    if a is None or b is None:
        return _stop('One of the two configs cannot be imported.', **base)
    lines = []
    ka = {k.strip().lower(): k for k in a['main']}
    kb = {k.strip().lower(): k for k in b['main']}
    only_ref = [ka[k] for k in ka if k not in kb]
    only_this = [kb[k] for k in kb if k not in ka]
    if only_ref:
        lines.append('only in the reference: %s' % ', '.join(only_ref))
    if only_this:
        lines.append('only in %s: %s' % (others[0], ', '.join(only_this)))
    diff = ['%s: %s -> %s' % (ka[k], show(a['main'][ka[k]]), show(b['main'][kb[k]])) for k in ka
            if k in kb and not config_model.same_value(a['main'][ka[k]], b['main'][kb[k]])]
    if diff:
        lines.append('values that differ: %s' % '; '.join(diff))
    fa, ea = config_model.loaded_fields(a)
    fb, eb = config_model.loaded_fields(b)
    if fa and fb:
        moved = config_model.moved_fields(fa, fb)
        lines.append('loaded: %s' % (' | '.join('%s: %s -> %s' % (k, _fmt_field(x) if x is not config_model.ABSENT
                                                                  else '(absent)', _fmt_field(y) if y is not
                                                                  config_model.ABSENT else '(absent)')
                                                for k, (x, y) in moved.items()) or 'no loaded field differs'))
    else:
        lines.append('a config does not load: %s' % (ea or eb))
    return outcome('PLAN', steps=[_step('compare_config', reference=files[0], other=others[0])], announce=lines,
                   **base), {}

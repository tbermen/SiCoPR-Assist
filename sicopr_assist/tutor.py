"""The tutor and trouble detection. Everything here returns data; cli.py prints it.

The tutor shows phrases that work on the config in front of the tool:

  - on request ("What can I say?", help): a handful of example phrases, filled with names from this config;
  - on its own, while the history holds fewer successful commands than tutor_until_commands: the same examples
    after a PLAN, and the nearest form that works after a phrase that was not understood (row TU02);
  - on trouble, trouble_misses misses in the last trouble_window commands: the nearest form that works for each
    missed phrase, plus one line about Export feedback at most once in feedback_notice_gap commands (rows TU14
    to TU19). A miss is a phrase with a word that could not be placed, a phrase that matched nothing, or a
    question that was cancelled. Misses counted towards one showing of the tutor are not counted again.

The tutor may only teach phrases that work (row TU04): every phrase it would print is first resolved by the
core, against the config in front of it as if that config had just been run, and a phrase that does not give
the outcome it should is left out. A phrase that holds <value> is checked with the current value in its place.
With no run in the project yet, and no run in the plan the tutor follows, it offers only the phrase that runs now
(the config and channel in the folder, or the example setup): a re-run, a sweep or a dashboard would only ask for a
run first. A change that is already in effect (DER_0 = 1e-4 once DER_0 is 1e-4) is never offered.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import hashlib
import json
import os
import re

from sicopr_assist import config_model, parse

VALUE = '<value>'
# the line about feedback (row TU14); the address comes from core.FEEDBACK_ADDRESS
FEEDBACK_LINE = ('Export feedback writes the command history to a text file, names masked, that can be emailed to %s '
                 'to help improve SiCoPR-Assist.')
NOTHING_MATCHED = 'Not a supported request'      # how the core's STOP for a phrase that matched nothing begins
EXAMPLE_PHRASE = 'Run the example.'              # runs the example setup that ships with the tool
RUN_OPS = ('run_com', 'run_batch')               # the steps of a plan that make runs

_CACHE = {}                                       # examples by config, and imports by file, for this process


def _commands(history):
    """The typed phrases and chosen options of a history: an edit or a workbook opened in the GUI's Config view is
    not a command, so the tutor does not count it (GUI_DESIGN.md section 10)."""
    from sicopr_assist.project import is_command
    return [r for r in history if is_command(r)]


def successes(history):
    """How many commands in the history were successful (status ok)."""
    return sum(1 for r in _commands(history) if r.get('status') == 'ok')


def is_miss(rec):
    """A phrase with a word that could not be placed, a phrase that matched nothing, or a cancelled question.
    rec is a history record or an outcome (with 'status' added). A phrase that became a PLAN was understood,
    whatever words no clause took (Show settings. leaves settings to the rule that shows the settings)."""
    kind = rec.get('outcome') or rec.get('type')
    return (bool(rec.get('unplaced')) and kind != 'PLAN') or rec.get('status') == 'cancelled' or \
        (kind == 'STOP' and str(rec.get('reason') or '').startswith(NOTHING_MATCHED))


def _since_last_showing(history):
    """The records after the last one that showed the tutor."""
    k = max((i for i, r in enumerate(history) if 'tutor' in (r.get('shown') or [])), default=-1)
    return history[k + 1:]


def trouble(history, current, settings):
    """The missed records (the current outcome last) when this command brings up the tutor on trouble, else []."""
    need, window = settings['trouble_misses'], settings['trouble_window']
    if need <= 0:
        return []
    recent = (list(_since_last_showing(_commands(history))) + [current])[-window:]
    missed = [r for r in recent if is_miss(r)]
    return missed if len(missed) >= need else []


def feedback_notice_due(history, settings):
    """Whether the feedback line may be shown now: on, and not shown in the last feedback_notice_gap commands."""
    if not settings['feedback_notice']:
        return False
    history = _commands(history)
    k = max((i for i, r in enumerate(history) if 'feedback_notice' in (r.get('shown') or [])), default=None)
    return k is None or len(history) - k >= settings['feedback_notice_gap']


# ----------------------------------------------------------------------------- resolving a phrase quietly
def _scratch(ctx):
    """A context in which the config in front of the tool has just been run, for checking phrases. Nothing is
    read from or written to the history. None when there is no config to read."""
    from sicopr_assist import core
    wc = ctx.wc
    last = ctx.last
    src = ctx.source_path
    if wc is None:
        if src is None and not ctx.config_files():
            src = core.EXAMPLE
        if src is None:
            return None
        wc = _imported(src)
        if wc is None:
            return None
    if last is None:                             # no run yet: the config and the one channel in the folder
        chans = ctx.channel_files()
        try:                                     # the example setup can sit on another drive than the project
            rel = os.path.relpath(src, ctx.root) if src else None
        except ValueError:
            rel = src
        last = {'phrase': '', 'source': {'path': rel, 'sha256': None} if src else None,
                'channels': [{'path': chans[0], 'role': 'thru'}] if chans else [], 'overrides': [],
                'working_config': None, 'run_ids': [], 'plan': {}}
    s = core.Context(ctx.project)
    s._c.update(settings=ctx.settings, history=[last], last=last, base=(wc, 'last run', []), runs=[],
                source_path=ctx.source_path)
    for key, read in (('descriptions', 'keyword_descriptions'), ('selections', 'selection_lists')):
        if key not in ctx._c:                    # a workbook is read once per content in this process
            ctx._c[key] = _from_workbook(ctx.source_path, read)
        s._c[key] = ctx._c[key]
    return s


def _from_workbook(path, read):
    """xlsx_io.<read>(path), once per file content in this process; {} when there is none or it cannot be read."""
    from sicopr_assist import xlsx_io
    if not path or not path.lower().endswith(('.xlsx', '.xls')):
        return {}
    try:
        with open(path, 'rb') as f:
            key = (read, hashlib.sha256(f.read()).hexdigest())
    except OSError:
        return {}
    if key not in _CACHE:
        try:
            _CACHE[key] = getattr(xlsx_io, read)(path)
        except Exception:                        # a workbook that cannot be read has none, as core.Context says
            _CACHE[key] = {}
    return copy.deepcopy(_CACHE[key])


def _imported(path):
    """The working config of a config file, imported once per file content in this process."""
    if path.lower().endswith('.json'):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    try:
        with open(path, 'rb') as f:
            key = ('import', hashlib.sha256(f.read()).hexdigest())
    except OSError:
        return None
    if key not in _CACHE:
        wc, issues = config_model.import_config(path)
        _CACHE[key] = None if wc is None or config_model.stops(issues) else wc
    return copy.deepcopy(_CACHE[key])


def _resolve(phrase, scratch):
    from sicopr_assist import core
    try:
        out, answers, _ = core._resolve(phrase, scratch, {})
    except Exception:                                  # a phrase the core cannot read is not taught
        return None, {}
    return out, answers


def fill_values(phrase, wc):
    """The phrase with <value> filled in, as a list of tries: half the current value, twice it, and the value itself
    (a number); the current value alone otherwise. A phrase with no <value> is its own only try."""
    from sicopr_assist import core
    m = re.search(r'with (.+?) = %s' % re.escape(VALUE), phrase)
    if not m:
        return [phrase]
    v = core._current(wc, m.group(1))
    try:
        x = float(v)
        vals = ['%g' % (x / 2), '%g' % (x * 2), '%g' % x]
    except (TypeError, ValueError):
        vals = [core.show(v) if v is not None else '1']
    return [phrase.replace(VALUE, t) for t in vals]


def works(phrase, scratch, plan_only=False):
    """Whether a phrase the tutor would print resolves: no word left unplaced, not a STOP, and a PLAN when
    plan_only. A phrase that holds <value> works when one of its fills (fill_values) does."""
    for text in fill_values(phrase, scratch.wc):
        out, _ = _resolve(text, scratch)
        if out is None or out.get('unplaced') or out['type'] == 'STOP':
            continue
        if out['type'] == 'PLAN' or not plan_only:
            return True
    return False


# ----------------------------------------------------------------------------- the examples
def _blocks(wc):
    sel = str(next((v for k, v in wc['main'].items() if k.strip().lower() == 'pkg_name'), '') or '').split()
    return [b for b in wc['packages'] if b not in sel] + [b for b in wc['packages'] if b in sel]


PREFERRED_CHOICES = ('clip method', 'include pcb', 'ctle_type')    # choices that make a plain example first


def _choice_names(wc):
    from sicopr_assist import validate
    out = []
    for k in wc['main']:
        row = validate.schema_row(k.strip(), 'main')
        if row and row['kind'].startswith('choice') and len(validate.legal_values(row) or []) > 1 \
                and k.strip().lower() not in ('pkg_name', 'com version', 'z_p select'):
            out.append(k.strip())
    return sorted(out, key=lambda n: (PREFERRED_CHOICES.index(n.lower()) if n.lower() in PREFERRED_CHOICES else 99))


def _in_effect(wc, name, value):
    """Whether name already has value in wc (as numbers), so that a change to it would change nothing."""
    from sicopr_assist import core
    try:
        return float(core._current(wc, name)) == float(value)
    except (TypeError, ValueError):
        return False


def _example_candidates(wc):
    """(kind, [phrases to try, best first]) for each kind of example. A change already in effect is left out."""
    main = {k.strip().lower(): k.strip() for k in wc['main']}
    change = ['Re-run with %s = %s' % (main[n.lower()], v) for n, v in
              (('DER_0', '1e-4'), ('DER_0', '1e-5'), ('SNR_TX', '32.5'), ('SNR_TX', '30'))
              if n.lower() in main and not _in_effect(wc, main[n.lower()], v)]
    blocks = _blocks(wc)
    package = ['Re-run with package %s' % b for b in blocks[:3]] if len(blocks) > 1 else []
    in_pkg = {k for b in wc['packages'].values() for k in b}
    sweep = ['Sweep C_b from 1e-5 to 5e-5 in 3 steps'] if 'C_b' in in_pkg else []
    sweep += ['Sweep %s from %s in 3 steps' % (main[n.lower()], r) for n, r in
              (('DER_0', '1e-5 to 1e-4'), ('SNR_TX', '30 to 34')) if n.lower() in main]
    choice = ['Sweep %s' % n for n in _choice_names(wc)[:4]]
    from sicopr_assist import core
    return [('re-run with one change', change), ('re-run with another package', package),
            ('sweep a range', sweep), ('sweep a choice', choice),
            ('show the dashboard', [core.DASHBOARD_PHRASE, 'Show the dashboard.']),
            ('what did you change', ['What did you change?']),
            ('go back to the original', ['Re-run with the original config.', 'Reset and re-run.'])]


def examples(ctx):
    """[(kind, phrase)]: one phrase per kind that resolves to a PLAN on the config in front of the tool. A phrase
    that gives a STOP is never taught: with no Rscript on this machine the dashboard example is left out (row D3)."""
    scratch = _scratch(ctx)
    if scratch is None:
        return []
    wc = scratch.wc
    from sicopr_assist import engine
    key = ('examples', json.dumps(wc, sort_keys=True, default=str), json.dumps(scratch.last.get('channels'),
                                                                              sort_keys=True), engine.find_rscript())
    if key not in _CACHE:
        got = []
        for kind, cands in _example_candidates(wc):
            phrase = next((p for p in cands if works(p, scratch, plan_only=True)), None)
            if phrase:
                got.append((kind, phrase))
        _CACHE[key] = got
    return list(_CACHE[key])


def _runs_now(phrase, ctx):
    """Whether phrase resolves to a PLAN with no word left unplaced in the project as it is now."""
    from sicopr_assist import core
    out, _ = _resolve(phrase, core.Context(ctx.project))
    return out is not None and out['type'] == 'PLAN' and not out.get('unplaced')


def first_run(ctx):
    """The phrase that runs now when the project has no run yet: the one config and the one channel file in the
    project folder, or the example setup when the folder holds no config; None when the phrase does not resolve to a
    PLAN, or the folder holds several configs or channel files."""
    cfgs, chans = ctx.config_files(), ctx.channel_files()
    if not cfgs:
        phrase = EXAMPLE_PHRASE
    elif len(cfgs) == 1 and len(chans) == 1:
        phrase = 'Run COM on %s with %s' % (chans[0], cfgs[0])
    else:
        return None
    return phrase if _runs_now(phrase, ctx) else None


def no_run_offer(ctx):
    """(lines, phrases) when the project has no run yet: only phrases that run now. The re-runs, sweeps and the
    dashboard would only ask for a run first, so they wait until there is one."""
    first = first_run(ctx)
    if first:
        what = 'the example setup' if first == EXAMPLE_PHRASE else 'the config and the channel file here'
        return (['There is no run in this project yet. This phrase runs %s:' % what, '  %s' % first,
                 'After that run, What can I say? lists phrases that work on its config.'], [first])
    lines = ['There is no run in this project yet. Name the config and the channel file to run: Run COM on <channel '
             'file> with <config file>.']
    if _runs_now(EXAMPLE_PHRASE, ctx):
        return lines + ['Or run the example setup:', '  %s' % EXAMPLE_PHRASE], [EXAMPLE_PHRASE]
    return lines, []


# ----------------------------------------------------------------------------- the nearest form of a phrase
def _without(phrase, words):
    out = phrase
    for w in words:
        out = re.sub(r'(?<![\w-])%s(?![\w-])' % re.escape(w), ' ', out, count=1)
    return re.sub(r'\s+', ' ', out).strip().rstrip('.').strip()


def nearest(phrase, scratch):
    """The nearest phrase that works for a phrase that was not understood, or None.

    A name that is not a COM keyword is replaced by the first keyword the core offers for it (Re-run with
    f_b = <value> when no value was given); otherwise the words that could not be placed are left out, when
    what is left still asks for something definite (a change, a sweep, files or a package)."""
    from sicopr_assist import engine
    if scratch is None or not phrase:
        return None
    out, answers = _resolve(phrase, scratch)
    if out is None:
        return None
    wc = scratch.wc
    req = parse.read(phrase, scratch.names(wc), list(wc['packages']))
    form = None
    if out['type'] == 'QUESTION':
        first = next((answers.get(o) for o in out['question']['options'] if (answers.get(o) or {}).get('replace')),
                     None)
        if first:
            typed, name = first['replace']
            at = next((a for a in req['attempts'] if a['text'] == typed), None)
            if at is not None and at.get('value') is not None:
                form = _without(re.sub(r'(?<![\w-])%s(?![\w-])' % re.escape(typed), name, phrase, count=1),
                                [w for w in req['unplaced'] if w not in typed.split()])
            elif name.strip().lower() in [n.lower() for n in engine.keyword_names('main') +
                                          engine.keyword_names('package block')]:
                form = 'Re-run with %s = %s' % (name, VALUE)
    if form is None and (req['sets'] or req['sweeps'] or req['files'] or req['packages']) and req['unplaced']:
        form = _without(phrase, req['unplaced'])
    if not form or form.rstrip('.') == phrase.strip().rstrip('.') or not works(form, scratch):
        return None
    return form


# ----------------------------------------------------------------------------- what is shown after an outcome
def lines_for_examples(found):
    return ['Phrases that work on this config:'] + ['  %s' % p for _, p in found]


def after(phrase, out, ctx, asked=False):
    """What the tutor adds to an outcome: {'lines', 'phrases', 'shown', 'why'}, or None when it adds nothing.

    asked: the phrase asked for the tutor ("What can I say?"). Otherwise the tutor comes up on its own for a new
    user (fewer successful commands than tutor_until_commands) or on trouble."""
    from sicopr_assist import core
    st = ctx.settings['values']
    history = ctx.history
    current = dict(out, status={'PLAN': 'ok', 'QUESTION': 'question'}.get(out['type'], 'stopped'),
                   phrase=phrase)
    if out['type'] == 'STOP' and (out.get('reason') or '').startswith('Cancelled'):
        current['status'] = 'cancelled'
    if asked:
        if ctx.last is None:                     # no run yet: only what runs now
            lines, phrases = no_run_offer(ctx)
            return {'lines': lines, 'phrases': phrases, 'shown': ['tutor'], 'why': 'asked'}
        found = examples(ctx)
        if not found:
            return {'lines': ['There is no config here to take examples from. Name one: Run COM on <channel file> '
                              'with <config file>.'], 'phrases': [], 'shown': ['tutor'], 'why': 'asked'}
        return {'lines': lines_for_examples(found), 'phrases': [p for _, p in found], 'shown': ['tutor'],
                'why': 'asked'}
    missed = trouble(history, current, st)
    if missed:
        scratch = _scratch(ctx)
        lines, phrases, seen = ['Some recent phrases were not understood. The nearest phrase that works:'], [], set()
        for rec in missed:
            ph = rec.get('phrase') or ''
            if ph in seen:
                continue
            seen.add(ph)
            form = nearest(ph, scratch)
            if form:
                phrases.append(form)
                lines.append('  %s  ->  %s' % (ph, form))
            else:
                lines.append('  %s  ->  no near phrase; What can I say? lists phrases that work' % ph)
        shown = ['tutor']
        if feedback_notice_due(history, st):
            lines.append(FEEDBACK_LINE % core.FEEDBACK_ADDRESS)
            shown.append('feedback_notice')
        return {'lines': lines, 'phrases': phrases, 'shown': shown, 'why': 'trouble'}
    if successes(history) >= st['tutor_until_commands']:
        return None
    if out['type'] == 'PLAN':
        if ctx.last is None and not any(s.get('op') in RUN_OPS for s in out.get('steps') or []):
            lines, phrases = no_run_offer(ctx)   # a plan that makes no run, and no run yet: only what runs now
            if not phrases:
                return None
            return {'lines': lines, 'phrases': phrases, 'shown': ['tutor'], 'why': 'new'}
        found = examples(ctx)
        if not found:
            return None
        return {'lines': lines_for_examples(found), 'phrases': [p for _, p in found], 'shown': ['tutor'],
                'why': 'new'}
    if is_miss(current):
        form = nearest(phrase, _scratch(ctx))
        if form:
            return {'lines': ['The nearest phrase that works: %s' % form], 'phrases': [form], 'shown': ['tutor'],
                    'why': 'new'}
    return None

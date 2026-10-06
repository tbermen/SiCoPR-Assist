"""The scoring harness of prompt section 7, as a library: tests\\test_use_cases.py runs it over the
table, and tests\\test_harness_levels.py feeds it wrong outcomes to show that each level catches one.

For every row and config pair whose applies_when holds, it builds the prior state, calls the core
once with the phrase, and scores the outcome:

    L1  type          outcome type against expected_type
    L2  target        changes (or points) against json_path, value_before, value_after, linked_changes
    L3  loader        the outcome's changes applied to the prior working config, written as the run
                      CSV, loaded by the real loader; the fields that moved against loader_effect
    L4  detail        the frozen list l4_rows.csv: step names in order, or the options offered

It never runs COM. Values are put in the table's text form with the oracle's val, norm, fmt and diff.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import csv
import os
import re

import fixtures
import l4
import prior_states
from sicopr_assist import engine
from sicopr_assist.project import Project

DEFERRED = ('tutor', 'feedback', 'report', 'fetch')
FROZEN = os.path.join(fixtures.HERE, 'l4_rows.csv')
FROZEN_COLUMNS = ['id', 'starting_config', 'group', 'priority', 'expected_type', 'kind', 'expected']
REVIEW = os.path.join(fixtures.HERE, 'l4_review.csv')
SCORE_COLUMNS = ['id', 'config', 'group', 'priority', 'applies', 'L1', 'L2', 'L3', 'L4', 'paraphrases_ok',
                 'paraphrases_asked', 'paraphrases_wrong', 'note']
OUTCOME_KEYS = ('type', 'steps', 'changes', 'announce', 'pattern', 'unplaced')
SWEEP_TEXT_LIMIT = 1500                     # the generator cut sweep effects at 1500 characters
L3_DEFAULT_LABELS = ('Case1',) + fixtures.VARIANTS


# ----------------------------------------------------------------------------- the frozen L4 list
def write_frozen(rows, path=FROZEN, review_path=REVIEW):
    vocab = l4.extract_vocabulary(rows)
    out, rev = [], []
    for r, (kind, x) in l4.build(rows, vocab):
        base = {'id': r['id'], 'starting_config': r['starting_config'], 'group': r['group'],
                'priority': r['priority'], 'expected_type': r['expected_type']}
        if kind == 'review':
            rev.append(dict(base, kind='review', expected=x))
        else:
            out.append(dict(base, kind=kind, expected=(' > ' if kind == 'chain' else ' | ').join(x)))
    for p, data in ((path, out), (review_path, rev)):
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=FROZEN_COLUMNS, lineterminator='\n')
            w.writeheader()
            w.writerows(data)
    return out, rev


def read_frozen(path=FROZEN):
    """{row key: (kind, expected list)}."""
    out = {}
    for r in csv.DictReader(open(path, newline='', encoding='utf-8')):
        sep = ' > ' if r['kind'] == 'chain' else ' | '
        out['%s|%s' % (r['id'], r['starting_config'])] = (r['kind'], r['expected'].split(sep))
    return out


# ----------------------------------------------------------------------------- which pairs apply
def labels_of(row):
    return ['Case1'] if row['starting_config'] == 'any' else row['starting_config'].split('; ')


def applies(row):
    """(True, '') when the row's applies_when holds for the engine under test, else (False, why)."""
    cond = row['applies_when'].strip()
    if not cond:
        return True, ''
    kind, _, arg = cond.partition(':')
    sup, dflt = engine.supported_releases(), engine.default_release()
    holds = {'loader_reads': lambda: engine.reads_keyword(arg),
             'loader_lacks': lambda: not engine.reads_keyword(arg),
             'release_supported': lambda: arg in sup,
             'release_unsupported': lambda: arg not in sup,
             'release_default': lambda: arg == dflt,
             'release_supported_not_default': lambda: arg in sup and arg != dflt}[kind]()
    return holds, '' if holds else '%s does not hold for this engine' % cond


# ----------------------------------------------------------------------------- value helpers
def split_points(text):
    return [x.strip() for x in l4.split_top(text, '; ') if x.strip()]


def same(product_value, expected_text):
    O = fixtures.oracle()
    if expected_text == '(absent)':
        return product_value is None
    if product_value is None:
        return False
    return O.norm(O.val(product_value)) == O.norm(expected_text)


def strip_linked(text):
    return re.sub(r' \(linked to [^)]*\)$', '', text.strip())


def parse_linked(text, wc):
    """'f_z 42.5 -> 21.25; f_p1 ...' -> [(name, after)]. A name is the longest key of the working config
    that starts the item, so names with spaces (z_p (NEXT)) are read whole."""
    names = set(wc['main'])
    for p in wc['packages'].values():
        names.update(p)
    out = []
    for item in split_points(text):
        left, _, after = item.rpartition(' -> ')
        name = max((n for n in names if left == n or left.startswith(n + ' ')), key=len, default=None)
        if name is None:
            name = left.split(' ')[0]
        out.append((name, after.strip()))
    return out


def option_naming(outcome, target):
    t = target.strip().lower()
    for opt in (outcome.get('question') or {}).get('options') or []:
        txt = l4.option_text(opt)
        if txt == t or t in txt:
            return opt
    return None


def well_formed(o):
    if not isinstance(o, dict):
        return 'the outcome is not a dictionary'
    missing = [k for k in OUTCOME_KEYS if k not in o]
    if missing:
        return 'the outcome lacks %s' % ', '.join(missing)
    if o['type'] not in ('PLAN', 'QUESTION', 'STOP'):
        return 'outcome type %r' % o['type']
    if o['type'] == 'QUESTION' and not isinstance(o.get('question'), dict):
        return 'a QUESTION without a question'
    if o['type'] == 'STOP' and 'reason' not in o:
        return 'a STOP without a reason'
    return ''


# ----------------------------------------------------------------------------- the levels
def level2(row, o, prior_wc):
    """(passed, note) for L2."""
    paths = [p.strip() for p in row['json_path'].split(';') if p.strip()]
    va = row['value_after']
    pts = o.get('points') or []
    grid = re.fullmatch(r'(\d+) x (\d+) grid', va.strip())
    if grid:
        n = int(grid.group(1)) * int(grid.group(2))
        ok = len(pts) == n and all(all(p in (pt.get('values') or {}) for p in paths) for pt in pts)
        return ok, '' if ok else 'expected a %s grid of points over %s, got %d points' % (va, ', '.join(paths), len(pts))
    want = split_points(va)
    jp = paths[0]
    if pts or len(want) > 1:
        got = [(pt.get('values') or {}).get(jp) for pt in pts]
        ok = len(got) == len(want) and all(same(g, w) for g, w in zip(got, want))
        return ok, '' if ok else 'points at %s: expected %s, got %s' % (jp, want, got)
    ch = [c for c in o.get('changes') or [] if c.get('json_path') == jp and c.get('kind') != 'linked']
    if not ch:
        return False, 'no change at %s' % jp
    c = ch[0]
    if not same(c.get('after'), va):
        return False, '%s after: expected %s, got %r' % (jp, va, c.get('after'))
    vb = strip_linked(row['value_before'])
    if vb and not same(c.get('before'), vb):
        return False, '%s before: expected %s, got %r' % (jp, vb, c.get('before'))
    want_l = parse_linked(row['linked_changes'], prior_wc) if row['linked_changes'].strip() else []
    got_l = {c['json_path'].rsplit('/', 1)[-1]: c.get('after') for c in o.get('changes') or [] if c.get('kind') == 'linked'}
    if sorted(n for n, _ in want_l) != sorted(got_l):
        return False, 'linked: expected %s, got %s' % (sorted(n for n, _ in want_l), sorted(got_l))
    bad = [n for n, a in want_l if not same(got_l[n], a)]
    return not bad, '' if not bad else 'linked values differ: %s' % ', '.join(bad)


class Scorer:
    def __init__(self, fx, rows, handle, frozen=None, full_l3=False):
        self.fx = fx
        self.rows = rows
        self.handle = handle
        self.frozen = frozen if frozen is not None else read_frozen()
        self.full_l3 = full_l3
        self.by_id = {}
        for r in rows:
            self.by_id.setdefault(r['id'], []).append(r)

    # ---- prior state and the call
    def context(self, row, label):
        ctx = prior_states.Ctx(self.fx, label, row, self.by_id)
        prior_states.build(row['prior_state'], ctx)
        return ctx

    def call(self, ctx, phrase):
        old = {k: os.environ.get(k) for k in ctx.env}
        os.environ.update(ctx.env)
        try:
            return self.handle(phrase, Project(ctx.root))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    # ---- L3
    def fields(self, wc):
        return self.fx.load_working_config(wc)

    def effect(self, base, wc):
        f, err = self.fields(wc)
        if err:
            return 'loader error: ' + err
        bf, berr = self.fields(base)
        if berr:
            return 'base config does not load: ' + berr
        return ' | '.join(fixtures.oracle().diff(bf, f))

    def candidates(self, o, prior_wc):
        """[(point index or None, working config or an error text)]"""
        out = []
        pts = o.get('points') or []
        sets = ([{prior_states.key_of(jp): v for jp, v in (pt.get('values') or {}).items() if jp.startswith('/')}
                 for pt in pts] if pts else
                [{prior_states.key_of(c['json_path']): c.get('after') for c in o.get('changes') or []}])
        for i, values in enumerate(sets):
            try:
                out.append((i if pts else None, prior_states.with_values(prior_wc, values) if values else copy.deepcopy(prior_wc)))
            except Exception as e:                       # a value the oracle cannot apply (a link over text)
                out.append((i if pts else None, 'harness could not apply %s: %s' % (values, e)))
        return out

    def level3(self, row, ctx, o):
        special = SPECIAL_L3.get(row['id'])
        if special:
            return special(self, row, ctx, o)
        return self.standard_l3(row, ctx, o, row['loader_effect'])

    def standard_l3(self, row, ctx, o, expected, normalise=lambda s: s):
        exp = expected.strip()
        exp = '' if exp == 'no loaded field changes' else exp
        exp = exp.replace('same as source config', 'same as the last run')
        if exp.startswith('the loader stops: '):
            exp = 'loader error: ' + exp[len('the loader stops: '):]
        base = ctx.prior_wc
        cands = self.candidates(o, base)
        if ' || ' in exp or len(cands) > 1:
            items = exp.split(' || ')
            labels = [it.split(': ', 1)[0] for it in items]
            parts = []
            for i, wc in cands:
                eff = wc if isinstance(wc, str) else self.effect(base, wc)
                label = labels[i] if i is not None and i < len(labels) else str(i)
                parts.append('%s: %s' % (label, eff or 'same as the last run'))
            got = ' || '.join(parts)
            ok = normalise(got)[:SWEEP_TEXT_LIMIT] == normalise(exp)[:SWEEP_TEXT_LIMIT]
        else:
            wc = cands[0][1]
            got = wc if isinstance(wc, str) else self.effect(base, wc)
            ok = normalise(got) == normalise(exp)
        return ok, '' if ok else 'L3 expected %r, got %r' % (exp[:160], got[:160])

    # ---- one pair
    def score(self, row, label, paraphrases=True):
        res = dict(id=row['id'], config=label, group=row['group'], priority=row['priority'], applies='yes',
                   L1='', L2='', L3='', L4='', paraphrases_ok='', paraphrases_asked='', paraphrases_wrong='', note='')
        ok, why = applies(row)
        if not ok:
            res.update(applies='no', note=why)
            return res
        notes = []
        ctx = self.context(row, label)
        try:
            o = self.call(ctx, row['phrase'])
            bad = well_formed(o)
            if bad:
                res.update(L1='FAIL', note=bad)
                return res
            res['L1'] = 'PASS' if o['type'] == row['expected_type'] else 'FAIL'
            if res['L1'] == 'FAIL':
                notes.append('L1 expected %s, got %s' % (row['expected_type'], o['type']))
            needs_l2 = bool(row['json_path'] and row['value_after'])
            needs_l3 = 'loader' in row['verified'] and (self.full_l3 or label in L3_DEFAULT_LABELS)
            scored = o
            if (needs_l2 or needs_l3) and o['type'] == 'QUESTION' and not o.get('changes') and not o.get('points'):
                opt = option_naming(o, row['target_param'].split(';')[0])
                if opt is not None:
                    scored = self.call(ctx, opt)
                    notes.append('answered %r' % opt)
            if needs_l2:
                if ctx.prior_wc is None:
                    res['L2'], n = 'FAIL', 'no prior working config to compare with'
                else:
                    p2, n = level2(row, scored, ctx.prior_wc)
                    res['L2'] = 'PASS' if p2 else 'FAIL'
                if n:
                    notes.append(n)
            if needs_l3:
                p3, n = self.level3(row, ctx, scored)
                res['L3'] = 'PASS' if p3 else 'FAIL'
                if n:
                    notes.append(n)
            key = l4.row_key(row)
            if key in self.frozen:
                kind, exp = self.frozen[key]
                res['L4'] = 'PASS' if l4.score(kind, exp, o) else 'FAIL'
                if res['L4'] == 'FAIL':
                    notes.append('L4 expected %s, got %s' % (exp, l4.outcome_steps(o) if kind == 'chain' else l4.outcome_options(o)))
            else:
                res['L4'] = 'review'
        finally:
            self.fx.remove_project(ctx.root)
        if paraphrases and row['paraphrases'].strip():
            okn = asked = wrong = 0
            for ph in [p.strip() for p in row['paraphrases'].split(' | ') if p.strip()]:
                c2 = self.context(row, label)
                try:
                    o2 = self.call(c2, ph)
                finally:
                    self.fx.remove_project(c2.root)
                if not isinstance(o2, dict) or well_formed(o2):
                    wrong += 1
                elif o2['type'] == row['expected_type']:
                    if o2['type'] == 'PLAN' and row['json_path'] and row['value_after'] and c2.prior_wc is not None \
                            and not level2(row, o2, c2.prior_wc)[0]:
                        wrong += 1
                    else:
                        okn += 1
                elif o2['type'] == 'QUESTION':
                    asked += 1
                elif o2['type'] == 'PLAN':
                    wrong += 1
            res.update(paraphrases_ok=okn, paraphrases_asked=asked, paraphrases_wrong=wrong)
        res['note'] = '; '.join(notes)
        return res


# ----------------------------------------------------------------------------- rows with their own L3 check
def _product(name):
    """A product function by dotted name, or None while it is not built."""
    mod, _, fn = name.rpartition('.')
    try:
        m = __import__('sicopr_assist.' + mod, fromlist=[fn])
    except ImportError:
        return None
    return getattr(m, fn, None)


def _text_of(o):
    q = o.get('question') or {}
    return '\n'.join(list(o.get('announce') or []) + [q.get('text', '')] + list(q.get('options') or [])
                     + [o.get('reason', '')])


def l3_import_matches(s, row, ctx, o):
    """CP02, CP03: the product's import, written as the run CSV, loads to the same fields as the workbook."""
    imp = _product('config_model.import_config')
    if imp is None:
        return False, 'needs config_model.import_config (Phase 2)'
    wc = imp(ctx.data('config.xlsx'))
    wc = wc[0] if isinstance(wc, tuple) else wc
    f, err = s.fields(wc)
    x, xerr = s.fx.load_file(ctx.data('config.xlsx'))
    ok = err is None and xerr is None and not fixtures.oracle().diff(x, f)
    if ok and row['id'] == 'CP03':
        ok = len(wc.get('links', {})) == 18
    return ok, '' if ok else 'import does not load to the workbook fields (or CP03 links != 18)'


def l3_export(s, row, ctx, o):
    """CP06, CP07: the exported workbook loads to the same fields as the working config (CP07: and the
    added keyword's field moves from the source config as loader_effect says)."""
    exp = _product('xlsx_io.export_workbook')
    if exp is None:
        return False, 'needs xlsx_io.export_workbook (Phase 2)'
    out = os.path.join(ctx.root, 'data', 'exported.xlsx')
    exp(ctx.prior_wc, ctx.data('config.xlsx'), out)
    x, xerr = s.fx.load_file(out)
    f, err = s.fields(ctx.prior_wc)
    if xerr or err:
        return False, 'export or working config does not load: %s %s' % (xerr, err)
    if row['id'] == 'CP07':
        src = s.fields(s.fx.working_config(ctx.label))[0]
        got = ' | '.join(fixtures.oracle().diff(src, x))
        return got == row['loader_effect'], 'CP07 expected %r, got %r' % (row['loader_effect'], got)
    d = fixtures.oracle().diff(f, x)
    return not d, '' if not d else 'export differs: %s' % ' | '.join(d)[:160]


def l3_compare(s, row, ctx, o):
    """ST03: the comparison of V01 with the Case1 sheet, as the engine sees it, appears in the outcome."""
    O = fixtures.oracle()
    truth = ' | '.join(O.diff(s.fx.load_file(ctx.data('config.xlsx'))[0], s.fields(ctx.prior_wc)[0]))
    want = row['loader_effect'].split('loaded: ', 1)[-1]
    if truth != want:
        return False, 'the table says %r, the engine says %r' % (want, truth)
    text = _text_of(o)
    ok = 'P_peak' in text and want in text
    return ok, '' if ok else 'the outcome does not name P_peak and %s' % want


def l3_label_typo(s, row, ctx, o):
    """ST05: the import names the label P_peek and the keyword P_peak."""
    text = _text_of(o)
    ok = 'P_peek' in text and 'P_peak' in text
    return ok, '' if ok else 'the outcome does not name P_peek and P_peak'


def l3_source_error(s, row, ctx, o):
    """ST14, IV21: the error comes from opening the source file itself, so it is checked there."""
    name = 'config.xls' if row['id'] == 'IV21' else 'config.xlsx'
    f, err = s.fx.load_file(ctx.data(name))
    got = 'loader error: ' + err if err else 'loads'
    exp = row['loader_effect']
    ok = got == exp or (row['id'] == 'IV21' and got.startswith(exp))
    return ok, '' if ok else 'expected %r, got %r' % (exp, got[:160])


def l3_lost_results(s, row, ctx, o):
    """ST16: the workbook itself does not load; its import, with the links recomputed, does."""
    f, err = s.fx.load_file(ctx.data('config.xlsx'))
    xlsx_part, json_part = row['loader_effect'].split(' | ')
    if 'xlsx: ' + (err or 'loads') != xlsx_part:
        return False, 'xlsx: expected %r, got %r' % (xlsx_part, err)
    imp = _product('config_model.import_config')
    if imp is None:
        return False, 'needs config_model.import_config (Phase 2)'
    wc = imp(ctx.data('config.xlsx'))
    wc = wc[0] if isinstance(wc, tuple) else wc
    jf, jerr = s.fields(wc)
    got = 'JSON import: %s' % ('%d fields' % len(jf) if jf else jerr)
    return got == json_part, 'expected %r, got %r' % (json_part, got)


def l3_grid(s, row, ctx, o):
    """SX15: all 6 combinations load, and 5 differ from the last run."""
    base = ctx.prior_wc
    cands = s.candidates(o, base) if o.get('points') else []
    effects = [wc if isinstance(wc, str) else s.effect(base, wc) for _, wc in cands]
    loads = [e for e in effects if not e.startswith(('loader error', 'harness'))]
    ok = len(cands) == 6 and len(loads) == 6 and sum(1 for e in loads if e) == 5
    return ok, '' if ok else '%d points, %d load, %d differ' % (len(cands), len(loads), sum(1 for e in loads if e))


def l3_missing_f_z(s, row, ctx, o):
    """SC06: with f_z removed from Case1, the loader default moves CTLE_fz as loader_effect says."""
    O = fixtures.oracle()
    want = row['loader_effect'].split(': ', 1)[1]
    x, err = s.fx.load_file(ctx.data('config.xlsx'))
    base, _ = s.fields(s.fx.working_config(ctx.label))
    if err:
        return False, 'the config without f_z does not load: %s' % err
    field = want.split(':', 1)[0]
    got = ' | '.join(d for d in O.diff(base, x) if d.startswith(field + ':'))
    return got == want, 'expected %r, got %r' % (want, got)


def l3_default_release(s, row, ctx, o):
    """SC14: the table names the default release as it was; compare with the engine's default."""
    exp = re.sub(r'(matlab_version: )\S+( ->)', r'\g<1>%s\g<2>' % engine.default_release(), row['loader_effect'])
    return s.standard_l3(row, ctx, o, exp)


def l3_date_paths(s, row, ctx, o):
    """PA013: the date of the run and the path separators are normalised on both sides."""
    def norm(t):
        return re.sub(r'\d{2}-[A-Z][a-z]{2}-\d{4}', '<date>', t).replace('\\', '/')
    return s.standard_l3(row, ctx, o, row['loader_effect'], normalise=norm)


def l3_remark(s, row, ctx, o):
    """C5: '(accepted by the loader)' is a remark, not part of the effect."""
    return s.standard_l3(row, ctx, o, row['loader_effect'].replace(' (accepted by the loader)', ''))


def l3_sentence_as_effect(s, row, ctx, o):
    """SX25: listed with the sentence rows, but its text is a plain effect; compared as one."""
    return s.standard_l3(row, ctx, o, row['loader_effect'])


def l3_release_stop(s, row, ctx, o):
    """SC12: the loader stops on a release it does not support."""
    return s.standard_l3(row, ctx, o, row['loader_effect'])


SPECIAL_L3 = {
    'CP02': l3_import_matches, 'CP03': l3_import_matches, 'CP06': l3_export, 'CP07': l3_export,
    'ST03': l3_compare, 'ST05': l3_label_typo, 'ST14': l3_source_error, 'IV21': l3_source_error,
    'ST16': l3_lost_results, 'SX15': l3_grid, 'SX25': l3_sentence_as_effect, 'SC06': l3_missing_f_z,
    'SC12': l3_release_stop, 'SC14': l3_default_release, 'PA013': l3_date_paths, 'C5': l3_remark,
}


# ----------------------------------------------------------------------------- the whole table
def pairs(rows):
    for r in rows:
        for label in labels_of(r):
            yield r, label


def write_scores(results, path):
    order = sorted(results, key=lambda x: x['group'] in DEFERRED)        # the deferred groups in their own section
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=SCORE_COLUMNS, lineterminator='\n')
        w.writeheader()
        w.writerows(order)


def summarise(results):
    """One line per group: pairs scored, and passes per level out of the pairs the level applies to."""
    groups = {}
    for r in results:
        if r['applies'] != 'yes':
            continue
        g = groups.setdefault(r['group'], {'n': 0, 'L1': [0, 0], 'L2': [0, 0], 'L3': [0, 0], 'L4': [0, 0]})
        g['n'] += 1
        for lv in ('L1', 'L2', 'L3', 'L4'):
            if r[lv] in ('PASS', 'FAIL'):
                g[lv][1] += 1
                g[lv][0] += r[lv] == 'PASS'
    lines = []
    for section, names in (('gated groups', [g for g in groups if g not in DEFERRED]),
                           ('deferred to version 2 (not gated)', [g for g in groups if g in DEFERRED])):
        lines.append('-- %s' % section)
        for g in sorted(names):
            v = groups[g]
            lines.append('%-10s pairs %4d  L1 %4d/%-4d  L2 %4d/%-4d  L3 %4d/%-4d  L4 %4d/%-4d'
                         % (g, v['n'], v['L1'][0], v['L1'][1], v['L2'][0], v['L2'][1], v['L3'][0], v['L3'][1],
                            v['L4'][0], v['L4'][1]))
    return lines

"""Run summary, statistics over a set of runs, and a parameter against a result.

No diagnosis: these functions report numbers and say nothing about why. Every function returns plain data
(a dictionary with a "lines" list among its keys) and prints nothing, so the command line and a later GUI
show the same thing. Results are named by their field name in the result file, case ignored;
"COM" is the built-in name of channel_operating_margin_dB.

A not-a-number result is shown as it is and left out of the statistics, and the number left out is stated
(finding F10). The standard deviation is the sample one (n - 1), as MATLAB's std and Python's
statistics.stdev give it.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import math
import os
import re

from sicopr_assist import config_model, validate

COM_FIELD = 'channel_operating_margin_dB'
# Where a result has a pass threshold in the config (the keyword holds it).
THRESHOLDS = {COM_FIELD: 'COM Pass threshold', 'ERL': 'ERL Pass threshold'}
# The order results are listed in: COM first, then these, then the rest by name (row SM07). FOM is not named here:
# it is also a legal value of FFE_OPT_METHOD, and no legal value is written in the code: it is read from the schema.
FIRST = (COM_FIELD, 'ERL', 'VEC_dB', 'VEO_mV', 'DER_thresh')
# What a run summary shows for each package case (row D4), after COM.
RUN_FIELDS = ('ERL', 'VEC_dB', 'VEO_mV', 'DER_thresh')
BATCH_FILE = 'batch_summary.csv'
BATCH_COLUMNS = ('command', 'point', 'values', 'run_id', 'status', 'release') + FIRST + ('note',)


# ----------------------------------------------------------------------------- numbers
def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fmt(v):
    """A value as the lines show it: numbers with six significant digits, the rest as text."""
    if is_number(v):
        if v != v:
            return 'NaN'
        return '%d' % v if float(v).is_integer() and abs(v) < 1e15 else '%.6g' % v
    return validate.show(v) if v is not None else '(none)'


def describe(values):
    """Statistics of a list of values: {'count', 'left_out', 'minimum', 'maximum', 'mean', 'median', 'stdev'}.
    Not-a-number and non-numeric values are left out and counted in left_out. With one value the standard
    deviation is None; with none, every statistic is None."""
    nums = [float(v) for v in values if is_number(v) and v == v]
    out = {'count': len(nums), 'left_out': len(values) - len(nums), 'minimum': None, 'maximum': None, 'mean': None,
           'median': None, 'stdev': None}
    if not nums:
        return out
    n = len(nums)
    mean = math.fsum(nums) / n
    s = sorted(nums)
    out.update(minimum=s[0], maximum=s[-1], mean=mean,
               median=s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)
    if n > 1:
        out['stdev'] = math.sqrt(math.fsum((x - mean) ** 2 for x in nums) / (n - 1))
    return out


def pearson(xs, ys):
    """(coefficient, slope of y on x) by least squares; None for either when x (or y, for the coefficient)
    does not vary. xs and ys are lists of numbers of the same length, at least 2."""
    n = len(xs)
    mx, my = math.fsum(xs) / n, math.fsum(ys) / n
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    syy = math.fsum((y - my) ** 2 for y in ys)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else None
    r = sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None
    return r, slope


# ----------------------------------------------------------------------------- the runs on disk
def _scalar_fields(case):
    return {k: v for k, v in case.items() if is_number(v)}


def param_value(wc, name):
    """The value of a keyword in a working config: the main area first, then the selected package block,
    then any block. Case and spaces ignored. None when the config does not hold it."""
    key = name.strip().lower()
    for k, v in wc['main'].items():
        if k.strip().lower() == key:
            return v
    sel = []
    for k, v in wc['main'].items():
        if k.strip().lower() == 'pkg_name':
            sel = str(v or '').split()
    for b in sel + [b for b in wc['packages'] if b not in sel]:
        for k, v in wc['packages'].get(b, {}).items():
            if k.strip().lower() == key:
                return v
    return None


def as_number(value):
    """A config value as one number when it holds one (a [TX RX] pair with both sides equal counts), else None."""
    if is_number(value):
        return float(value)
    p = validate.parse_numbers(value) if isinstance(value, str) else None
    flat = validate._flat(p) if p else []
    if flat and all(x == flat[0] for x in flat):
        return float(flat[0])
    return None


def last_set(project):
    """The last set of runs: the runs of the most recent command that made or reused runs (a sweep, a list,
    a grid, or one run), reused points included. None when the project has no run.

    {'seq', 'phrase', 'runs': [{'run_id', 'status', 'release', 'wc', 'cases', 'message', 'values'}],
     'results': [{'label', 'run_id', 'case', 'fields', 'wc', 'values'}], 'skipped': [point], 'failed': [run]}"""
    try:
        hist = project.read_history()
    except (OSError, ValueError):
        return None
    rec = next((r for r in reversed(hist) if r.get('run_ids')), None)
    if rec is None:
        return None
    points = rec.get('points') or []
    runs, results, failed = [], [], []
    for rid in dict.fromkeys(rec['run_ids']):
        try:
            res = project.read_result(rid)
            wc = project.read_working_config(rid)
        except (OSError, ValueError) as e:
            failed.append({'run_id': rid, 'message': 'cannot be read: %s' % e})
            continue
        values = next((p.get('values') for p in points if p.get('run_id') == rid), None) or {}
        run = {'run_id': rid, 'status': res.get('status'), 'release': res.get('release'), 'wc': wc,
               'cases': res.get('cases') or [], 'message': res.get('message'), 'values': values}
        runs.append(run)
        if res.get('status') != 'complete':
            failed.append(run)
            continue
        many = len(run['cases']) > 1
        for i, case in enumerate(run['cases'], 1):
            results.append({'label': '%s case %d' % (rid, i) if many else rid, 'run_id': rid, 'case': i,
                            'fields': case, 'wc': wc, 'values': values})
    skipped = [p for p in points if p.get('skipped')]
    return {'seq': rec.get('seq'), 'phrase': rec.get('phrase'), 'runs': runs, 'results': results,
            'skipped': skipped, 'failed': failed}


def result_names(s):
    """The numeric result fields of a set (or of one run's cases), COM first, then FIRST, then by name."""
    names = []
    for r in s['results']:
        for k in _scalar_fields(r['fields']):
            if k not in names:
                names.append(k)
    return [n for n in FIRST if n in names] + sorted(n for n in names if n not in FIRST)


def result_field(word, names):
    """The result field a word names, or None: COM is channel_operating_margin_dB; otherwise the field whose
    name equals the word, case ignored."""
    w = word.strip().lower()
    if w == 'com':
        return COM_FIELD
    return next((n for n in names if n.lower() == w), None)


def label_of(field):
    return 'COM (%s)' % COM_FIELD if field == COM_FIELD else field


def varied(s, skip=()):
    """Keywords whose value differs between the runs of the set, in config order, with their values per run.
    Linked keywords move with what they follow and are left out, as is RESULT_DIR (it only says where output
    goes). {name: [value of each result]}"""
    wcs = [r['wc'] for r in s['results']]
    if len(wcs) < 2:
        return {}
    skip = {k.strip().lower() for k in skip} | {'result_dir'}
    links = set()
    for wc in wcs:
        links.update(k.rsplit('.', 1)[-1].strip().lower() for k in wc['links'])
    names = []
    for wc in wcs:
        for k in list(wc['main']) + [k for b in wc['packages'].values() for k in b]:
            if k not in names and k.strip().lower() not in skip and k.strip().lower() not in links:
                names.append(k)
    out = {}
    for n in names:
        vals = [param_value(wc, n) for wc in wcs]
        if any(not config_model.same_value(vals[0], v) for v in vals[1:]):
            out[n] = vals
    return out


def _threshold(wc, field):
    kw = THRESHOLDS.get(field)
    v = param_value(wc, kw) if kw else None
    return float(v) if is_number(v) else as_number(v)


# ----------------------------------------------------------------------------- statistics (rows SM01, SM09 to SM14)
def result_stats(s, field):
    """Statistics of one result over the set s (from last_set). Returns the numbers and the lines to show."""
    vals = [r['fields'].get(field) for r in s['results']]
    st = describe(vals)
    lines = []
    name = label_of(field)
    if len(s['results']) <= 12 or st['count'] < 2:
        for r, v in zip(s['results'], vals):
            lines.append('%s of %s%s: %s' % (name, r['label'], _point_text(s, r), fmt(v)))
    thr = None
    passed = None
    if field in THRESHOLDS and s['results']:
        thrs = [_threshold(r['wc'], field) for r in s['results']]
        if all(t is not None for t in thrs) and all(t == thrs[0] for t in thrs):
            thr = thrs[0]
        if all(t is not None for t in thrs):
            passed = sum(1 for v, t in zip(vals, thrs) if is_number(v) and v == v and v >= t)
    st.update(field=field, threshold=thr, pass_count=passed)
    if st['count'] == 0:
        lines.append('no result holds a number for %s' % name)
    elif st['count'] == 1:
        lines.append('one value has no statistics')
    else:
        lines.append('%s over %d results: minimum %s, maximum %s, mean %s, median %s, standard deviation %s'
                     % (name, st['count'], fmt(st['minimum']), fmt(st['maximum']), fmt(st['mean']), fmt(st['median']),
                        fmt(st['stdev'])))
        lo = next(r for r, v in zip(s['results'], vals) if v == st['minimum'])
        hi = next(r for r, v in zip(s['results'], vals) if v == st['maximum'])
        lines.append('minimum at %s%s; maximum at %s%s' % (lo['label'], _point_text(s, lo), hi['label'],
                                                           _point_text(s, hi)))
    if passed is not None and st['count']:
        kw = THRESHOLDS[field]
        lines.append('%d of %d results at or above %s (%s)' % (
            passed, st['count'], kw, fmt(thr) if thr is not None else 'per run'))
    if st['left_out']:
        lines.append('%d result%s not a number and %s left out of the statistics' % (
            st['left_out'], ' is' if st['left_out'] == 1 else 's are', 'is' if st['left_out'] == 1 else 'are'))
    lines += _set_notes(s)
    st['lines'] = lines
    st['values'] = [{'label': r['label'], 'value': v} for r, v in zip(s['results'], vals)]
    return st


def _point_text(s, r):
    v = varied(s)
    if not v:
        return ''
    i = s['results'].index(r)
    return ' (%s)' % ', '.join('%s = %s' % (n, fmt(vals[i])) for n, vals in v.items())


def _set_notes(s):
    lines = []
    for p in s['skipped']:
        lines.append('skipped, not counted: %s: %s' % (
            ', '.join('%s = %s' % (validate.name_of(k) if k.startswith('/') else k, fmt(v))
                      for k, v in (p.get('values') or {}).items()), p['skipped']))
    for r in s['failed']:
        lines.append('failed, not counted: %s: %s' % (r['run_id'], r.get('message') or 'no result'))
    return lines


# ----------------------------------------------------------------------------- a parameter against a result
def relation(s, x, y, x_is_param, min_points):
    """How x relates to the result y over the set s (rows SM02 to SM04, SM08, SM15).

    x is a keyword (x_is_param) or a result field. Returns {'kind', 'lines', ...} where kind is:
    'one_value' (x had one value: nothing to compare), 'named' (x takes named values: COM per value and the
    differences), 'few' (fewer than min_points pairs: the pairs and the difference), 'grouped' (another keyword
    varied as well: one table and one coefficient per value of it), or 'pearson'."""
    if x_is_param:
        xv = [param_value(r['wc'], x) for r in s['results']]
    else:
        xv = [r['fields'].get(x) for r in s['results']]
    yv = [r['fields'].get(y) for r in s['results']]
    distinct = []
    for v in xv:
        if not any(config_model.same_value(v, d) for d in distinct):
            distinct.append(v)
    out = {'x': x, 'y': y, 'lines': []}
    if len(distinct) < 2:
        out.update(kind='one_value', value=distinct[0] if distinct else None)
        out['lines'].append('%s had one value (%s) in the last set of runs, so there is nothing to compare'
                            % (x, fmt(distinct[0]) if distinct else 'none'))
        return out
    others = {k: v for k, v in varied(s, skip=[x]).items()} if x_is_param else {}
    if others:
        other = next(iter(others))
        groups = []
        for g in [d for i, d in enumerate(others[other]) if not any(config_model.same_value(d, e) for e in others[other][:i])]:
            idx = [i for i, v in enumerate(others[other]) if config_model.same_value(v, g)]
            sub = {'results': [s['results'][i] for i in idx], 'skipped': [], 'failed': []}
            part = relation(sub, x, y, x_is_param, min_points)
            groups.append({'value': g, 'relation': part})
        out.update(kind='grouped', by=other, groups=groups)
        out['lines'].append('%s varied as well in the last set of runs, so the answer is given for each %s value '
                            'separately' % (', '.join(others), other))
        for g in groups:
            out['lines'].append('%s = %s:' % (other, fmt(g['value'])))
            out['lines'] += ['  ' + line for line in g['relation']['lines']]
        return out
    xn = [as_number(v) if x_is_param else (float(v) if is_number(v) else None) for v in xv]
    pairs = [(xv[i], xn[i], yv[i], s['results'][i]['label']) for i in range(len(xv))]
    nan = [p for p in pairs if not (is_number(p[2]) and p[2] == p[2])]
    good = [p for p in pairs if p not in nan]
    yname = label_of(y)
    if any(v is None for v in xn):
        # named values (or values that are not one number): the result for each value and the differences
        out['kind'] = 'named'
        table = []
        for d in sorted(distinct, key=lambda v: str(v)):
            ys = [p[2] for p in good if config_model.same_value(p[0], d)]
            table.append({'value': d, 'results': ys})
            out['lines'].append('%s = %s: %s %s' % (x, fmt(d), yname, ', '.join(fmt(v) for v in ys) or 'none'))
        first = table[0]
        for t in table[1:]:
            if len(first['results']) == 1 and len(t['results']) == 1:
                out['lines'].append('difference in %s, %s minus %s: %s' % (
                    yname, fmt(first['value']), fmt(t['value']), fmt(first['results'][0] - t['results'][0])))
        out['table'] = table
        out['lines'].append('%s takes named values, so there is no correlation coefficient' % x)
    else:
        good.sort(key=lambda p: p[1])
        out['pairs'] = [(p[1], p[2]) for p in good]
        for p in good:
            out['lines'].append('%s = %s: %s %s (%s)' % (x, fmt(p[0]), yname, fmt(p[2]), p[3]))
        if len(good) < max(2, min_points):
            out['kind'] = 'few'
            if len(good) >= 2:
                out['difference'] = good[-1][2] - good[0][2]
                out['lines'].append('difference in %s from %s = %s to %s = %s: %s' % (
                    yname, x, fmt(good[0][0]), x, fmt(good[-1][0]), fmt(out['difference'])))
            out['lines'].append('%d results are fewer than min_correlation_points (%d), so no correlation '
                                'coefficient is given' % (len(good), min_points))
        else:
            r, slope = pearson([p[1] for p in good], [float(p[2]) for p in good])
            out.update(kind='pearson', coefficient=r, slope=slope, count=len(good))
            out['lines'].append('Pearson correlation coefficient %s over %d results; least-squares slope %s%s per unit '
                                'of %s' % (fmt(r) if r is not None else 'undefined (no spread)', len(good),
                                           fmt(slope) if slope is not None else 'undefined',
                                           ' dB' if y == COM_FIELD else '', x))
    if nan:
        out['lines'].append('%d result%s not a number and %s left out' % (
            len(nan), ' is' if len(nan) == 1 else 's are', 'is' if len(nan) == 1 else 'are'))
    out['left_out'] = len(nan)
    out['lines'] += _set_notes(s)
    return out


# ----------------------------------------------------------------------------- one run, and a batch
def engine_notes(project, rid, limit=20):
    """The INFO and warning lines the engine printed during a run (from run.log in its folder)."""
    path = os.path.join(project.run_dir(rid), 'run.log')
    out = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                t = line.strip()
                if re.match(r'(INFO\b|Warning\b|WARNING\b)', t) or 'Warning:' in t:
                    if t not in out:
                        out.append(t)
    except OSError:
        return []
    return out[:limit]


def run_summary(project, rid):
    """What one run gave (row D4, rule VR02): the release emulated, then for each package case COM against
    COM Pass threshold, ERL when it was computed, VEC_dB, VEO_mV, DER_thresh; the result folder; and the
    warnings of the run (its input checks and the engine's own INFO and warning lines)."""
    res = project.read_result(rid)
    try:
        wc = project.read_working_config(rid)
    except (OSError, ValueError):
        wc = None
    lines = ['%s: %s, emulating COM release %s' % (rid, res.get('status'), res.get('release') or 'unknown')]
    cases = res.get('cases') or []
    eye = eye_mode(wc) if wc else None
    thr = None if eye else (_threshold(wc, COM_FIELD) if wc else None)
    for i, case in enumerate(cases, 1):
        com = case.get(COM_FIELD)
        verdict = ''
        if thr is not None and is_number(com):
            verdict = ' (%s; COM Pass threshold %s)' % ('pass' if com == com and com >= thr else 'fail', fmt(thr))
        if eye:
            verdict = ' (not judged: PMD_type = %s is eye height and VEC mode)' % eye['mode']
        parts = ['COM %s dB%s' % (fmt(com), verdict)]
        for f in RUN_FIELDS:
            if f in case and (f != 'ERL' or is_number(case[f])):
                parts.append('%s %s' % (f, fmt(case[f])))
        line = '%s%s' % ('case %d: ' % i if len(cases) > 1 else '', ', '.join(parts))
        if eye:
            line += '; ' + eye_verdict(case, eye)['text']
        lines.append(line)
    if res.get('status') != 'complete':
        lines.append('the run did not complete: %s' % (res.get('message') or 'no message'))
    elif res.get('message'):
        lines += [m for m in str(res['message']).split('\n') if m]
    lines += ['engine: %s' % n for n in engine_notes(project, rid)]
    lines.append('results: %s' % project.relative(project.run_dir(rid)))
    return {'run_id': rid, 'status': res.get('status'), 'release': res.get('release'), 'cases': cases,
            'threshold': thr, 'eye': eye, 'lines': lines}


def _eye_values():
    """The PMD_type values that switch the engine to eye height and VEC mode: the schema's legal values other than its
    loader default (the default is COM mode). Read from the schema, never written here."""
    row = validate.schema_row('PMD_type', 'main')
    if row is None:
        return set()
    default = str(row['loader_default']).strip(" '\"").upper()
    return {str(v).strip().upper() for v in validate.legal_values(row) or [] if str(v).strip().upper() != default}


def eye_mode(wc):
    """In eye height and VEC mode (PMD_type C2M, the 802.3ck Annex 120G measurement) a run is judged by VEC Pass
    threshold and EH_min, not by COM (core fix 5, row CF12): {'mode', 'vec_max', 'eh_min'}, or None in COM mode."""
    mode = param_value(wc, 'PMD_type')
    if not isinstance(mode, str) or mode.strip().upper() not in _eye_values():
        return None
    vec, eh = as_number(param_value(wc, 'VEC Pass threshold')), as_number(param_value(wc, 'EH_min'))
    return {'mode': mode.strip(), 'vec_max': vec, 'eh_min': eh}


def eye_verdict(case, eye):
    """pass or fail of one case in eye height and VEC mode: VEC_dB at or below VEC Pass threshold and the eye height
    (VEO_mV) at or above EH_min. {'pass': True, False or None, 'text'}."""
    vec, veo = case.get('VEC_dB'), case.get('VEO_mV')
    why, ok = [], True
    known = False
    if is_number(vec) and eye['vec_max'] is not None:
        known = True
        if vec <= eye['vec_max']:
            why.append('VEC_dB %s is within VEC Pass threshold (%s)' % (fmt(vec), fmt(eye['vec_max'])))
        else:
            ok = False
            why.append('VEC_dB %s is above VEC Pass threshold (%s)' % (fmt(vec), fmt(eye['vec_max'])))
    if is_number(veo) and eye['eh_min'] is not None:
        known = True
        if veo >= eye['eh_min']:
            why.append('the eye height (VEO_mV %s) is at or above EH_min (%s)' % (fmt(veo), fmt(eye['eh_min'])))
        else:
            ok = False
            why.append('the eye height (VEO_mV %s) is below EH_min (%s)' % (fmt(veo), fmt(eye['eh_min'])))
    if not known:
        return {'pass': None, 'text': 'not judged: the run has no VEC_dB or VEO_mV to compare with VEC Pass threshold '
                                      'and EH_min'}
    return {'pass': ok, 'text': '%s: %s' % ('pass' if ok else 'fail', '; '.join(why))}


def batch_rows(project, seq, points):
    """One row per point of a batch, as BATCH_COLUMNS: what batch_summary.csv gets and what is shown."""
    rows = []
    for i, p in enumerate(points, 1):
        values = '; '.join('%s = %s' % (validate.name_of(k) if str(k).startswith('/') else k, fmt(v))
                           for k, v in (p.get('values') or {}).items())
        rid = p.get('run_id')
        status = 'skipped' if p.get('skipped') else ('reused' if p.get('reused_from') else 'new')
        row = {'command': seq, 'point': i, 'values': values, 'run_id': rid or '', 'status': status,
               'release': '', 'note': p.get('skipped') or ('reused from %s' % p['reused_from'] if p.get('reused_from')
                                                           else '')}
        if rid:
            try:
                res = project.read_result(rid)
            except (OSError, ValueError) as e:
                res = {'status': 'failed', 'message': str(e), 'cases': []}
            row['release'] = res.get('release') or ''
            if res.get('status') != 'complete':
                row['status'] = 'failed'
                row['note'] = res.get('message') or ''
            cases = res.get('cases') or []
            for f in FIRST:
                vals = [c.get(f) for c in cases if f in c]
                row[f] = ' '.join(repr(v) if is_number(v) else str(v) for v in vals)
            row['verdict'] = _point_verdict(project, rid, cases) if res.get('status') == 'complete' else None
        rows.append(row)
    return rows


def _point_verdict(project, rid, cases):
    """pass or fail of one point against its own config's COM Pass threshold (every package case), or None when the
    run's config has no threshold or the run is in eye height and VEC mode (judged there, not by COM)."""
    try:
        wc = project.read_working_config(rid)
    except (OSError, ValueError):
        return None
    if eye_mode(wc):
        return None
    thr = _threshold(wc, COM_FIELD)
    coms = [c.get(COM_FIELD) for c in cases]
    if thr is None or not coms or not all(is_number(c) and c == c for c in coms):
        return None
    return 'pass' if all(c >= thr for c in coms) else 'fail'


def batch_verdict(rows):
    """The batch as a whole: whether COM passes at every point that ran (row B165 of the blind set: does the system
    pass?). None when no point has a verdict."""
    judged = [r for r in rows if r.get('verdict') in ('pass', 'fail')]
    if not judged:
        return None
    bad = [r for r in judged if r['verdict'] == 'fail']
    left = len(rows) - len(judged)
    tail = '' if not left else '; %d point%s not judged' % (left, '' if left == 1 else 's')
    if not bad:
        return 'overall: COM passes at every point that ran (%d of %d)%s' % (len(judged), len(judged), tail)
    return 'overall: COM fails at %d of %d points (%s)%s' % (len(bad), len(judged),
                                                           ', '.join('point %d' % r['point'] for r in bad), tail)


def write_batch_summary(project, seq, points):
    """Append one row per point to .sicopr\\runs\\batch_summary.csv (the header once); returns its path and the
    rows. Full precision: numbers are written with repr."""
    rows = batch_rows(project, seq, points)
    path = os.path.join(project.runs_dir, BATCH_FILE)
    os.makedirs(project.runs_dir, exist_ok=True)
    new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=BATCH_COLUMNS, lineterminator='\n')
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in BATCH_COLUMNS})
    return path, rows


def write_results_file(project, seq, rows, name):
    """The rows of one batch in a file of their own, .sicopr\\runs\\command_<seq>\\<name>, with every result at full
    precision and the pass or fail of each point (the batch over configs and THRUs, blind row B151)."""
    folder = os.path.join(project.runs_dir, 'command_%04d' % int(seq))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    cols = BATCH_COLUMNS + ('verdict',)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) if r.get(k) is not None else '' for k in cols})
    return path


def batch_lines(rows):
    out = []
    for r in rows:
        com = r.get(COM_FIELD, '')
        out.append('%d. %s: %s%s%s%s' % (r['point'], r['values'] or 'as configured', r['status'],
                                        ' %s' % r['run_id'] if r['run_id'] else '',
                                        ', COM %s' % ' '.join(fmt(float(x)) for x in com.split()) if com else
                                        (', %s' % r['note'] if r['note'] else ''),
                                        ', %s' % r['verdict'] if r.get('verdict') else ''))
    overall = batch_verdict(rows)
    return out + ([overall] if overall else [])

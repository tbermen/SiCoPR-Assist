"""Checks a change or a whole config against the schema and the rules: ok, ask or stop.

The two tables in data/ are the source and are read once: sicopr_param_schema.csv (one row per keyword
and scope: kind, legal values, stored unit, accepted units, stop_if, ask_if) and sicopr_param_rules.csv
(84 rules by id: Q limits by quantity, LS loader stops, LF settings the loader changes, DF defaults that
follow another keyword, EN engine checks, NC things the loader does not check, VR release rules).

Nothing here names a release or lists legal values: the releases come from SiCoPR's VERSION.json when
the tool runs (engine.py), whether a keyword is read comes from the engine's own loader, and every list
of values comes from the schema or from the config itself. Checking a config means writing it as the run
CSV and loading it with the real loader (config_model.loaded_fields).

Every function returns data (Decision 13). A result is a dictionary:

    status     'ok', 'ask' or 'stop'; stop wins over ask
    rule       the id of the rule that decided it (None when the loader or the schema alone did)
    text       the line shown to the user for that decision
    options    for ask: the options offered, in order
    answers    for ask: {option: {'set': {json_path: value}, 'allow': [rule id]} or None for cancel}
    findings   every ask, stop and announce found, each {status, rule, code, text, options, answers,
               keyword, json_path}; code names a finding no rule covers
    announce   the texts of the announce findings, in order
    values     {json_path: value as it will be written}, after unit conversion and spelling
    changes    the changes apply_changes made (set, add, linked), when the candidate was built
    unchanged  values the config already holds
    config     the candidate working config, or None when a value was refused before it was built
    effect     {'error': loader error or None, 'moved': [loaded fields that moved]}

stop_if stops and ask_if asks; the user may still choose to run an ask by passing its rule id (or its
code) in allow, which turns it into an announcement. An entry 'rule:keyword' passes that rule for that keyword only
(a preset's values from the standard, rule Q14). A request for values the config already holds
stops and says so, and so does a change the engine would not see (rules LF13, LF14, VR01, or a setting
the loader overrides).
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import functools
import math
import os
import re

from sicopr_assist import config_model, engine

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SCHEMA_FILE = os.path.join(DATA, 'sicopr_param_schema.csv')
RULES_FILE = os.path.join(DATA, 'sicopr_param_rules.csv')

# Unit prefixes and the units the schema's accepted_units column uses, as factors of one base unit per
# dimension. Which units a keyword accepts, and which one it is stored in, comes from the schema.
UNIT_FACTORS = {
    'hz': 1.0, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9, 'bd': 1.0, 'gbd': 1e9,
    'v': 1.0, 'mv': 1e-3, 'mm': 1.0, 'um': 1e-3, 'mil': 0.0254, 'inch': 25.4,
    'ff': 1e-15, 'pf': 1e-12, 'nf': 1e-9, 'ph': 1e-12, 'nh': 1e-9,
    'fs': 1e-15, 'ps': 1e-12, 'ns': 1e-9, 's': 1.0, 'ui': 1.0, 'mui': 1e-3,
    'db': 1.0, 'ohm': 1.0, 'v^2/ghz': 1.0,
}
NUMERIC_KINDS = ('number', 'count', 'vector', 'matrix', 'search range')
_NUM = r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
TOL = 1e-9


# ----------------------------------------------------------------------------- the two tables
@functools.lru_cache(maxsize=None)
def schema_rows():
    with open(SCHEMA_FILE, newline='', encoding='utf-8') as f:
        return tuple(csv.DictReader(f))


@functools.lru_cache(maxsize=None)
def _schema_index():
    return {(r['keyword'].strip().lower(), r['scope']): r for r in schema_rows()}


def schema_row(keyword, scope='main'):
    """The schema row of a keyword in a scope ('main' or 'package block'); case and spaces ignored."""
    return _schema_index().get((str(keyword).strip().lower(), scope))


@functools.lru_cache(maxsize=None)
def rules():
    """{rule id: row} in the order of the rules file."""
    with open(RULES_FILE, newline='', encoding='utf-8') as f:
        return {r['id']: r for r in csv.DictReader(f)}


def rule(rid):
    return rules()[rid]


@functools.lru_cache(maxsize=None)
def rule_keywords(rid):
    """The schema keywords a rule's applies_to names, in its order and spelling ('73 switches' names none)."""
    known = {r['keyword'].strip().lower(): r['keyword'] for r in schema_rows()}
    out = []
    for item in re.split(r',\s*|\s+and\s+', rule(rid)['applies_to'].split(';')[0]):
        item = re.sub(r'\s+and [0-9]+ more$', '', item.strip())
        if item.lower() in known and known[item.lower()] not in out:
            out.append(known[item.lower()])
    return tuple(out)


def _rules_naming(keyword):
    k = keyword.strip().lower()
    return [rid for rid in rules() if k in {x.lower() for x in rule_keywords(rid)}]


def _rule_text(rid):
    """The rule as a sentence for the user: the text after the 'quantity:' prefix of a Q rule."""
    t = rule(rid)['rule']
    return t.split(': ', 1)[1] if rule(rid)['kind'] == 'limit by quantity' and ': ' in t else t


# ----------------------------------------------------------------------------- values
def short(x):
    """A number as text: 1700000000.0 -> 1.7e9, 0.005 -> 0.005, 4.0 -> 4."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    if x == 0 or 1e-3 <= abs(x) < 1e6:
        s = '%.12g' % x
        return s
    m, e = ('%.12e' % x).split('e')
    m = m.rstrip('0').rstrip('.')
    return '%se%d' % (m, int(e))


def show(v):
    return short(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _round(x):
    """x with the binary noise of a unit conversion removed (5 ps in ns is 0.005, not 0.005000000000000001)."""
    return float('%.12g' % x)


def _plain_number(text):
    t = text.strip()
    if re.fullmatch(r'[+-]?[0-9]+', t):
        return int(t)
    if re.fullmatch(_NUM, t):
        return float(t)
    return None


def matlab_range(a, step, b):
    """(values, lands) of MATLAB a:step:b. It stops short of b when the steps do not land on it."""
    if step == 0:
        return [], False
    q = (b - a) / step
    if q < -TOL:
        return [], False
    n = int(math.floor(q + TOL)) + 1
    return [a + k * step for k in range(n)], abs(q - round(q)) <= TOL


def parse_numbers(value):
    """A value as numbers: (rows, ranges), rows a list of lists of floats (one per ';' row), ranges a list
    of {text, start, step, end, values, lands}. None when the value is not numeric text."""
    if isinstance(value, bool):
        return [[float(value)]], []
    if isinstance(value, (int, float)):
        return [[float(value)]], []
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.startswith('[') and t.endswith(']'):
        t = t[1:-1]
    elif '[' in t or ']' in t:
        return None
    t = re.sub(r'\s*:\s*', ':', t)
    rows, ranges = [], []
    for part in t.split(';'):
        row = []
        for item in [x for x in re.split(r'[\s,]+', part.strip()) if x]:
            if ':' in item:
                bits = item.split(':')
                if len(bits) not in (2, 3) or not all(re.fullmatch(_NUM, x) for x in bits):
                    return None
                a, s, b = (float(bits[0]), 1.0, float(bits[1])) if len(bits) == 2 else tuple(float(x) for x in bits)
                vals, lands = matlab_range(a, s, b)
                ranges.append({'text': item, 'bits': bits, 'start': a, 'step': s, 'end': b, 'values': vals,
                               'lands': lands})
                row += vals
            elif re.fullmatch(_NUM, item):
                row.append(float(item))
            else:
                return None
        rows.append(row)
    if all(not r for r in rows) and not ranges:
        rows = []
    return rows, ranges


def _flat(parsed):
    return [x for r in parsed[0] for x in r] if parsed else []


def _shape(value):
    """(rows, columns) of a matrix value, or None."""
    p = parse_numbers(value)
    if not p or not p[0]:
        return None
    return len(p[0]), len(p[0][0])


def split_unit(text):
    """('1.7', 'GHz') for '1.7 GHz'; None when the text does not end in a known unit after a number."""
    if not isinstance(text, str):
        return None
    m = re.fullmatch(r'\s*(%s)\s*([A-Za-z][A-Za-z0-9^/]*)\s*' % _NUM, text)
    if not m or m.group(2).lower() not in UNIT_FACTORS or not m.group(1):
        return None
    if _plain_number(m.group(1)) is None:
        return None
    return m.group(1), m.group(2)


def name_of(json_path):
    """The keyword of a json_path: '/main/b_max(2..N_b)' -> 'b_max(2..N_b)', '/packages/B/C_p' -> 'C_p'."""
    return json_path.split('/', 3)[3] if json_path.startswith('/packages/') else json_path.split('/', 2)[2]


def _units(row):
    return [u.strip() for u in row['accepted_units'].split(',') if u.strip()]


def _member_list(text, row):
    if text.strip() == 'a listed value':
        return legal_values(row)
    return [x.strip() for x in re.split(r',\s*|\s+or\s+', text) if x.strip()]


def legal_values(row):
    """The legal values of a choice: VERSION.json's releases when the schema says so, else the schema's
    list."""
    if 'VERSION.json' in row['legal_values_basis']:
        return engine.supported_releases()
    return [x.strip() for x in row['legal_values'].split(',') if x.strip()]


def _same_choice(value, legal):
    a, b = _plain_number(show(value)), _plain_number(str(legal))
    if a is not None and b is not None:
        return float(a) == float(b)
    return str(value).strip().lower() == str(legal).strip().lower()


def _conditions(text):
    """A stop_if or ask_if text as clauses: ('member', [values]) or ('whole', text) or ('cmp', atoms, text)."""
    t = text.strip()
    if not t:
        return []
    if t.startswith('not ') and not t.startswith('not whole'):
        return [('member', t[4:])]
    out = []
    for c in t.split(' or '):
        c = c.strip()
        if c == 'not whole':
            out.append(('whole', c))
            continue
        atoms = []
        for a in c.split(' and '):
            m = re.fullmatch(r'(<=|>=|<|>|above|below)\s*(\S+)', a.strip())
            if not m:
                raise ValueError('condition not understood: %r' % text)
            atoms.append((m.group(1), float(m.group(2))))
        out.append(('cmp', atoms, c))
    return out


def _cmp(x, op, y):
    return {'<=': x <= y, '>=': x >= y, '<': x < y, '>': x > y, 'above': x > y, 'below': x < y}[op]


def _triggered(text, numbers):
    """The clause of text that one of the numbers meets, or None."""
    for cl in _conditions(text):
        if cl[0] == 'whole' and any(x != int(x) for x in numbers if math.isfinite(x)):
            return cl[1]
        if cl[0] == 'cmp' and any(all(_cmp(x, op, y) for op, y in cl[1]) for x in numbers):
            return cl[2]
    return None


# ----------------------------------------------------------------------------- findings and results
def finding(status, rule_id, text, keyword=None, json_path=None, options=None, answers=None, code=None):
    """One thing found. code names a finding that no rule covers, so that allow can still name it."""
    return {'status': status, 'rule': rule_id, 'code': code, 'text': text, 'options': list(options or []),
            'answers': dict(answers or {}), 'keyword': keyword, 'json_path': json_path}


UNSELECTED_BLOCK = 'unselected_block'


def _tag(text, rid):
    return '%s (rule %s)' % (text, rid) if rid else text


def _result(findings, allow=(), **fields):
    allow = set(allow)
    scoped = {a.lower() for a in allow if isinstance(a, str) and ':' in a}    # allow may hold None (no rule, no code)
    for f in findings:
        rid = f['rule'] or f['code']
        if f['status'] == 'ask' and rid in allow:
            f['status'] = 'announce'
            f['text'] = f['text'] + '; run as asked'
        elif f['status'] == 'ask' and f['keyword'] and ('%s:%s' % (rid, f['keyword'])).lower() in scoped:
            # a pass for one rule on one keyword: a value a preset takes from the standard (owner ruling, 21 October
            # 2026, rule Q14); the same value typed by hand is still asked about
            f['status'] = 'announce'
            f['text'] = f['text'] + '; the preset takes it from the standard, so it is not asked about'
    lead = next((f for f in findings if f['status'] == 'stop'), None) or \
        next((f for f in findings if f['status'] == 'ask'), None)
    out = {'status': lead['status'] if lead else 'ok', 'rule': lead['rule'] if lead else None,
           'text': lead['text'] if lead else '', 'options': lead['options'] if lead and lead['status'] == 'ask' else [],
           'answers': lead['answers'] if lead and lead['status'] == 'ask' else {},
           'findings': findings, 'announce': [f['text'] for f in findings if f['status'] == 'announce'],
           'values': {}, 'changes': [], 'unchanged': [], 'config': None, 'effect': None}
    out.update(fields)
    return out


# ----------------------------------------------------------------------------- one value
_WORDS = {'<=': 'at or below', '<': 'below', '>=': 'at or above', '>': 'above', 'above': 'above', 'below': 'below'}


def _stop_text(rid, kw, clause):
    """Why a value stops: the rule's own sentence, unless the rule only asks and the schema stops this
    keyword (Delta_f under the frequency rule); then the clause in words."""
    if rid and 'asked about' not in _rule_text(rid):
        return _rule_text(rid)
    if clause == 'not whole':
        return '%s must be a whole number' % kw
    words = ' and '.join('%s %s' % (_WORDS[op], short(y)) for op, y in _conditions(clause)[0][1])
    return '%s must not be %s' % (kw, words)


def _quantity_rule(row):
    q = row['quantity'].strip().lower()
    return next((rid for rid, r in rules().items()
                 if r['kind'] == 'limit by quantity' and q and r['rule'].lower().startswith(q + ':')), None)


def _limit_rule(row, clause, status):
    """Which rule a stop_if or ask_if clause of a keyword's row comes from."""
    kw = row['keyword']
    for rid in _rules_naming(kw):                                        # a rule that names the clause (Q19)
        if rule(rid)['kind'] == 'limit by quantity' and clause in rule(rid)['rule']:
            return rid
    if clause == 'not whole' and row['whole_number'].startswith('yes'):
        return next((rid for rid in _rules_naming(kw) if rule(rid)['kind'] == 'loader stops'
                     and 'whole' in rule(rid)['rule']), None)
    if status == 'stop':                                                 # an engine stop that names the keyword (M)
        for rid in _rules_naming(kw):
            r = rule(rid)
            if r['kind'] == 'engine' and r['assist_behaviour'].startswith('STOP'):
                return rid
    return _quantity_rule(row)


def _list_rule(row):
    """The rule behind a choice's list: an engine or loader rule that asks with the list, else Q18."""
    for rid in _rules_naming(row['keyword']):
        if 'with the list' in rule(rid)['assist_behaviour'] and rule(rid)['kind'] != 'limit by quantity':
            return rid
    return next(rid for rid, r in rules().items() if r['rule'].startswith('choice:'))


def _switch_words():
    """{word: 0 or 1} from the switch rule's own text ('yes, on and true are written as 1 and no, off ...')."""
    rid = next(rid for rid, r in rules().items() if r['rule'].startswith('switch:'))
    out = {}
    for words, bit in re.findall(r'([a-z, ]+?) (?:are written )?as ([01])', rule(rid)['rule'].split(';', 1)[1]):
        for w in re.split(r',\s*|\s+and\s+', words.strip()):
            if w.strip():
                out[w.strip()] = int(bit)
    return rid, out


def _named(rid, keyword):
    """The value a rule's text gives a keyword ('FFE_OPT_METHOD = MMSE'), so no choice value is written here."""
    return re.search(re.escape(keyword) + r' (?:=|is) ([A-Za-z0-9_-]+)', rule(rid)['rule']).group(1)


def _read_as_unit(keyword):
    """(threshold, unit, rule id) for a keyword the loader reads below a threshold in another unit (LF11)."""
    for rid in _rules_naming(keyword):
        m = re.search(r'below (\S+) is read as (\S+)', rule(rid)['rule'])
        if m and rule(rid)['kind'] == 'loader changes another setting':
            return float(m.group(1)), m.group(2), rid
    return None


_VEC_NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
_VEC_TERM = re.compile(r'^(?:(?P<a>%s)\*)?(?P<f>ones|zeros)\(1,(?P<n>\d+)\)(?:\*(?P<b>%s))?$|^(?P<x>%s)$'
                       % (_VEC_NUM, _VEC_NUM, _VEC_NUM))


def matlab_vector(text):
    """A MATLAB row vector built with ones(1,n) or zeros(1,n), such as [0.25 0.15*ones(1,3) 0.05*ones(1,7)], written
    out as the values MATLAB reads from it ('[0.25 0.15 0.15 0.15 0.05 ...]'); None for any other text. Core fix 3
    (Phase V2-10): the Reference Code evaluates such a cell, SiCoPR's loader does not, so the run CSV holds the values
    written out."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not (s.startswith('[') and s.endswith(']')) or not re.search(r'\b(?:ones|zeros)\s*\(', s) or ';' in s:
        return None
    s = re.sub(r'\s*\*\s*', '*', s[1:-1].strip())
    s = re.sub(r'\(\s*1\s*,\s*(\d+)\s*\)', r'(1#\1)', s)          # the comma of ones(1,n) is not a separator
    out = []
    for term in re.split(r'[\s,]+', s):
        if not term:
            continue
        m = _VEC_TERM.match(term.replace('#', ','))
        if not m:
            return None
        if m.group('x') is not None:
            out.append(m.group('x'))
            continue
        if m.group('a') is not None and m.group('b') is not None:
            return None
        v = m.group('a') or m.group('b') or '1'
        out += [('0' if m.group('f') == 'zeros' else v)] * int(m.group('n'))
    return '[%s]' % ' '.join(out) if out else None


def check_value(wc, json_path, value, selections=None):
    """One proposed value against the schema: (value as it will be written, findings). Units are converted
    to the stored unit and announced; a switch word becomes 0 or 1; a choice takes the listed spelling. A MATLAB
    vector expression the Reference Code accepts ([0.3 0.2*ones(1,4)]) is written out and announced."""
    config_model.key_of(json_path)                      # raises ValueError on a path that is not one
    block = json_path.split('/')[2] if json_path.startswith('/packages/') else None
    name = name_of(json_path)
    row = schema_row(name, 'package block' if block else 'main')
    out = []
    if row is None or value is None:
        return value, out
    kw = row['keyword']
    kind = row['kind']

    def add(status, rid, text, options=None, answers=None):
        out.append(finding(status, rid, _tag(text, rid), kw, json_path, options, answers))

    if kind in NUMERIC_KINDS:
        written = matlab_vector(value)
        if written is not None:
            add('announce', None, '%s = %s is written out as %s, the values MATLAB reads from it (SiCoPR reads the '
                'values, not the expression)' % (kw, value.strip(), written))
            value = written
        unit = split_unit(value)
        if unit:
            num, u = _plain_number(unit[0]), unit[1]
            accepted = {x.lower(): x for x in _units(row)}
            stored = row['stored_unit'].strip()
            if u.lower() not in accepted or stored.lower() not in UNIT_FACTORS:
                opts = ['%s %s' % (unit[0], a) for a in _units(row)] + ['cancel']
                add('ask', None, '%s is not a unit %s takes%s' % (u, kw, '; it is stored in %s' % stored if stored else ''),
                    opts, {o: {'set': {json_path: '%s %s' % (unit[0], a)}} for o, a in zip(opts, _units(row))})
                return value, out
            conv = _round(num * UNIT_FACTORS[u.lower()] / UNIT_FACTORS[stored.lower()])
            if accepted[u.lower()] != stored:
                add('announce', None, '%s %s is written as %s, in %s, the unit %s is stored in'
                    % (unit[0], accepted[u.lower()], short(conv), stored, kw))
            value = conv
        else:
            plain = _plain_number(value) if isinstance(value, str) else None
            if plain is not None:
                value = plain
            low = _read_as_unit(kw)
            if low and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < low[0]:
                f = UNIT_FACTORS.get(low[1].lower(), 1.0) / UNIT_FACTORS.get(row['stored_unit'].strip().lower(), 1.0)
                conv = _round(value * f)
                add('announce', low[2], '%s is below %s, so it is taken as %s %s and written in %s as %s'
                    % (show(value), short(low[0]), show(value), low[1], row['stored_unit'], short(conv)))
                value = conv
        parsed = parse_numbers(value)
        if parsed is None:
            add('stop', None, '%s needs a number, not %s' % (kw, show(value)))
            return value, out
        nums = _flat(parsed)
        for rg in parsed[1]:
            if not rg['values']:
                swapped = '[%s]' % ':'.join([rg['bits'][-1]] + rg['bits'][1:-1] + [rg['bits'][0]])
                add('stop', 'NC05', '%s = %s: the range produces no values; perhaps %s was meant' % (kw, show(value), swapped))
                return value, out
            if not rg['lands']:
                last = short(_round(rg['values'][-1]))
                fixed = show(value).replace(rg['text'], ':'.join(rg['bits'][:-1] + [last]))
                opts = ['change the end to %s' % last, 'keep it as typed', 'cancel']
                add('ask', 'NC05', '%s = %s: the range does not land on its end value; MATLAB would search %d values '
                    'ending at %s' % (kw, show(value), len(rg['values']), last), opts,
                    {opts[0]: {'set': {json_path: fixed}}, opts[1]: {'allow': ['NC05']}, 'cancel': None})
        clause = _triggered(row['stop_if'], nums)        # 'not whole' there names LS12 where the loader stops
        if clause:
            rid = _limit_rule(row, clause, 'stop')
            add('stop', rid, '%s = %s cannot be used: %s' % (kw, show(value), _stop_text(rid, kw, clause)))
            return value, out
    if kind == 'switch':
        rid, words = _switch_words()
        if isinstance(value, bool):
            value = int(value)
        elif isinstance(value, str) and value.strip().lower() in words:
            new = words[value.strip().lower()]
            add('announce', rid, '%s is written as %d for the switch %s' % (value.strip(), new, kw))
            value = new
    if kind in ('switch', 'choice'):
        if isinstance(value, str) and _plain_number(value) is not None:
            value = _plain_number(value)
        legal = legal_values(row)
        hit = next((x for x in legal if _same_choice(value, x)), None)
        if hit is not None:
            if isinstance(value, str) and value.strip() != hit:
                add('announce', _list_rule(row), '%s is written as %s, the spelling the schema lists' % (value.strip(), hit))
                value = hit
            return value, out
        nums = _flat(parse_numbers(value))
        if nums and row['whole_number'].startswith('yes') and any(x != int(x) for x in nums):
            rid = _limit_rule(row, 'not whole', 'stop')
            add('stop', rid, '%s = %s: %s must be a whole number, and the loader stops on a fraction' % (kw, show(value), kw))
            return value, out
        clause = _triggered(row['stop_if'], nums) if nums else None
        if clause:
            rid = _limit_rule(row, clause, 'stop')
            add('stop', rid, '%s = %s cannot be used: %s' % (kw, show(value), _stop_text(rid, kw, clause)))
            return value, out
        cl = _conditions(row['ask_if'])
        members = _member_list(cl[0][1], row) if cl and cl[0][0] == 'member' else legal
        if not cl or any(_same_choice(value, m) for m in members):
            return value, out
        rid = _switch_words()[0] if kind == 'switch' else _list_rule(row)
        opts = [str(x) for x in legal]
        answers = {o: {'set': {json_path: _plain_number(o) if _plain_number(o) is not None else o}} for o in opts}
        if kind == 'choice' and row['stop_if']:                         # a value the schema does not stop can be kept
            keep = 'keep %s' % show(value)
            opts.append(keep)
            answers[keep] = {'allow': [rid]}
        add('ask', rid, '%s = %s is not one of the listed values: %s' % (kw, show(value), ', '.join(str(x) for x in legal)),
            opts, answers)
        return value, out
    if kind == 'choice from the config':
        return _check_from_config(wc, row, json_path, value, selections, add), out
    if kind in NUMERIC_KINDS and row['ask_if']:
        clause = _triggered(row['ask_if'], nums)
        if clause:
            rid = _limit_rule(row, clause, 'ask')
            low = re.search(r'meant in ([A-Za-z]+)', rule(rid)['rule']) if rid else None
            if low and isinstance(value, (int, float)):
                f = UNIT_FACTORS[low.group(1).lower()] / UNIT_FACTORS[row['stored_unit'].strip().lower()]
                conv = _round(value * f)
                opts = ['take it as %s %s and write %s' % (show(value), low.group(1), short(conv)),
                        'keep %s as typed' % show(value), 'cancel']
                add('ask', rid, '%s is stored in %s and %s is far too small to have an effect, so it is almost certainly '
                    'meant in %s' % (kw, row['stored_unit'], show(value), low.group(1)), opts,
                    {opts[0]: {'set': {json_path: conv}}, opts[1]: {'allow': [rid]}, 'cancel': None})
            else:
                opts = ['run it anyway', 'cancel']
                add('ask', rid, _limit_text(kw, value, clause, rid, row), opts, {opts[0]: {'allow': [rid]}, 'cancel': None})
    return value, out


def _limit_text(kw, value, clause, rid, row):
    """What an ask on a limit says. A DFE limit is asked about for its sign as well as its size (rule Q14), and the
    sign has its own sentence: a b_min above 0 forces the tap up, a b_max below 0 forces it down (core fix 1)."""
    low = kw.lower()
    tap = 'the first DFE tap' if low.endswith('(1)') else 'DFE taps 2 to N_b'
    nums = _flat(parse_numbers(value)) if parse_numbers(value) else []
    if rid == 'Q14' and low.startswith('b_min') and clause.startswith('>') and any(x > 0 for x in nums):
        top = max(x for x in nums if x > 0)
        return ('%s = %s is a minimum above 0, which forces %s to at least %s, not a limit on how negative it may go'
                % (kw, show(value), tap, short(top)))
    if rid == 'Q14' and low.startswith('b_max') and clause.startswith('<') and any(x < 0 for x in nums):
        bot = min(x for x in nums if x < 0)
        return ('%s = %s is a maximum below 0, which forces %s to at most %s'
                % (kw, show(value), tap, short(bot)))
    return '%s = %s: %s' % (kw, show(value), _rule_text(rid) if rid else
                            'the schema asks when it is %s (%s)' % (clause, row['limit_basis']))


def _check_from_config(wc, row, json_path, value, selections, add):
    """The three choices whose values come from the config itself: package blocks (LS01, LS02), port orders
    (NC03) and package cases (NC02, checked on the candidate config with the cross-parameter rules)."""
    kw = row['keyword']
    rids = _rules_naming(kw)
    if 'LS01' in rids:
        tokens = str(value).split()
        blocks = list(wc['packages'])
        if tokens and not blocks:
            add('stop', 'LS02', '%s names %s, but this config defines no package blocks (.START rows)' % (kw, ' '.join(tokens)))
            return value
        fixed, unknown = [], []
        for t in tokens:
            if t in blocks:
                fixed.append(t)
                continue
            ci = next((b for b in blocks if b.lower() == t.lower()), None)
            fixed.append(ci or t)
            if ci is None and t not in unknown:
                unknown.append(t)
        if unknown:
            opts = list(blocks)
            add('ask', 'LS01', 'there is no package block %s in this config; the blocks are %s'
                % (', '.join(unknown), ', '.join(blocks)), opts,
                {b: {'set': {json_path: ' '.join(b if t in unknown else t for t in fixed)}} for b in opts})
            return value
        new = ' '.join(fixed)
        if new != ' '.join(tokens):
            add('announce', 'LS01', 'block names are case sensitive in the loader: %s is written as %s, the spelling '
                'used in the sheet' % (' '.join(tokens), new))
            return new
        return value
    if 'NC03' in rids:
        m = re.search(r'ports ([0-9]+) to ([0-9]+)', row['legal_values'])
        want = list(range(int(m.group(1)), int(m.group(2)) + 1))
        got = _flat(parse_numbers(value))
        if sorted(got) != want:
            orders = next((v for k, v in (selections or {}).items() if 'port' in k.lower()), [])
            opts = [str(o) for o in orders] or ['cancel']
            used = [int(x) for x in got if got.count(x) > 1]
            why = ('port %d used twice' % used[0]) if used else 'it needs the ports %d to %d, each used once' % (want[0], want[-1])
            add('ask', 'NC03', '%s = %s: %s' % (kw, show(value), why), opts,
                {o: {'set': {json_path: o}} for o in opts if o != 'cancel'})
    return value


# ----------------------------------------------------------------------------- the candidate config
class _View:
    """Case-insensitive reads of a working config's main area, with numbers parsed."""

    def __init__(self, wc):
        self.wc = wc
        self.names = {k.strip().lower(): k for k in wc['main']}

    def has(self, name):
        return name.strip().lower() in self.names

    def key(self, name):
        return self.names.get(name.strip().lower(), name)

    def raw(self, name, default=None):
        k = self.names.get(name.strip().lower())
        return self.wc['main'][k] if k is not None else default

    def num(self, name, default=0.0):
        v = self.raw(name)
        p = parse_numbers(v) if v is not None and v != '' else None
        f = _flat(p)
        return f[0] if f else default

    def nums(self, name):
        v = self.raw(name)
        return _flat(parse_numbers(v)) if v is not None else []

    def text(self, name, default=''):
        v = self.raw(name)
        return default if v is None else str(v).strip()


def _hit(touched, rid, extra=()):
    if touched is None:
        return True
    return bool(touched & ({k.lower() for k in rule_keywords(rid)} | {e.lower() for e in extra}))


def _zp_default_shape(name, scope, tx_shape):
    row = schema_row(name, scope)
    return _shape(row['loader_default']) if row and _shape(row['loader_default']) else tx_shape


def _cross(view, touched):
    """The cross-parameter rules on a candidate config. touched is the set of lower-case keywords a change
    moved, or None for a whole config. Rules that only make sense for a change are skipped for a whole
    config."""
    F = []
    wc = view.wc
    change = touched is not None

    def add(status, rid, text, keyword=None, json_path=None, options=None, answers=None):
        F.append(finding(status, rid, _tag(text, rid), keyword, json_path, options, answers))

    mlse = view.num('MLSE', view.num('MLSD', 0))
    phy = view.text('PHY', view.text('PMD_type', '')).upper()
    c2m, c2c = _named('LF02', 'PMD_type').upper(), _named('LF03', 'PMD_type').upper()
    mmse_name = _named('LS08', 'FFE_OPT_METHOD')
    mmse = view.text('FFE_OPT_METHOD', mmse_name) == mmse_name        # compared as the loader compares it
    tdmode = view.num('TDMODE', 0)
    rxffe = view.num('ffe_pre_tap_len', 0) != 0 or view.num('ffe_post_tap_len', 0) != 0

    # LS04 and LS05: the package case matrices
    zp = rule_keywords('LS04')
    if _hit(touched, 'LS04'):
        scopes = [(None, wc['main'], 'main')] + [(b, p, 'package block') for b, p in wc['packages'].items()]
        for block, vals, scope in scopes:
            low = {k.strip().lower(): k for k in vals}
            tx_row = schema_row(zp[0], scope)
            tx_val = vals.get(low.get(zp[0].lower())) if zp[0].lower() in low else (tx_row['loader_default'] if tx_row else None)
            txs = _shape(tx_val)
            if txs is None:
                continue
            bad = []
            for other in zp[1:]:
                v = vals.get(low[other.lower()]) if other.lower() in low else None
                s = _shape(v) if v is not None else _zp_default_shape(other, scope, txs)
                if s != txs:
                    bad.append((other, s))
            if bad:
                where = 'package block %s' % block if block else 'the main area'
                prefix = '/packages/%s/' % block if block else '/main/'
                opts = ['apply the same matrix to all four', 'cancel']
                add('ask', 'LS04', '%s in %s has %d cases, but %s there %s %s; the loader stops unless all four agree, in '
                    'every block, selected or not' % (zp[0], where, txs[1], ', '.join(o for o, _ in bad),
                                                      'has' if len(bad) == 1 else 'have',
                                                      ' and '.join(sorted({'%d cases' % s[1] if s else 'another shape' for _, s in bad}))),
                    zp[0], prefix + zp[0], opts,
                    {opts[0]: {'set': {prefix + o: tx_val for o in zp[1:]}}, 'cancel': None})
    if _hit(touched, 'LS05') and view.has(zp[0]):
        s = _shape(view.raw(zp[0]))
        allowed = [int(x) for x in re.findall(r'\b([0-9]+)\b', rule('LS05')['rule'].split('must have', 1)[1])]
        if s and s[0] not in allowed:
            add('stop', 'LS05', '%s in the main area has %d values for each case; it must have %s'
                % (zp[0], s[0], ', '.join(str(a) for a in allowed)), zp[0], '/main/' + view.key(zp[0]))
    # LS06, LS07: MLSE
    if _hit(touched, 'LS06') and mlse != 0 and view.num('N_b', 0) == 0:
        opts = ['also set MLSE = 0', 'cancel']
        add('ask', 'LS06', 'MLSE = 1 needs at least one DFE tap, and N_b is 0', 'N_b', None, opts,
            {opts[0]: {'set': {'/main/' + view.key('MLSE'): 0}}, 'cancel': None})
    if _hit(touched, 'LS07') and mlse != 0 and view.num('T_O', 0) != 0 and phy == c2m:
        opts = ['set MLSE = 0', 'cancel']
        add('ask', 'LS07', 'MLSE = 1 cannot be used with T_O above 0 in a C2M config', 'MLSE', None, opts,
            {opts[0]: {'set': {'/main/' + view.key('MLSE'): 0}}, 'cancel': None})
    # LS08: PSDRXCAL, after what TDMODE and RX_CALIBRATION do to it (LF06, LF07)
    if _hit(touched, 'LS08'):
        psd = view.num('PSDRXCAL', 0) != 0 and not tdmode
        rxcal = view.num('RX_CALIBRATION', 0) != 0 and not tdmode
        if rxcal and mmse and rxffe:
            psd, rxcal = True, False
        if psd and (rxcal or not mmse or not rxffe):
            add('stop', 'LS08', rule('LS08')['rule'], 'PSDRXCAL')
    # LS09: G_Qual and G2_Qual
    gq, g2 = rule_keywords('LS09')
    if _hit(touched, 'LS09') and (view.nums(gq) or view.nums(g2)):
        s = _shape(view.raw(gq)) if view.nums(gq) else (0, 0)
        if s[0] != len(view.nums(g2)) or s[1] != 2:
            add('stop', 'LS09', rule('LS09')['rule'], gq)
    # NC01: ERL needs TDR
    if _hit(touched, 'NC01') and view.num('ERL', 0) != 0 and view.num('TDR', 0) == 0 and view.num('WC_PORTZ', 0) == 0 \
            and not tdmode:
        if touched is not None and 'tdr' in touched:
            opts = ['also set ERL = 0', 'keep TDR on', 'cancel']
            ans = {opts[0]: {'set': {'/main/' + view.key('ERL'): 0}}, opts[1]: {'set': {'/main/' + view.key('TDR'): 1}}}
        else:
            opts = ['also set TDR = 1', 'keep ERL off', 'cancel']
            ans = {opts[0]: {'set': {'/main/' + view.key('TDR'): 1}}, opts[1]: {'set': {'/main/' + view.key('ERL'): 0}}}
        ans['cancel'] = None
        add('ask', 'NC01', 'ERL = 1 needs TDR = 1 (keywords sheet), and TDR is 0', 'TDR', None, opts, ans)
    # NC02: package case numbers
    sel_kw, tx_kw = rule_keywords('NC02')
    if _hit(touched, 'NC02') and view.has(sel_kw):
        names = view.text('PKG_NAME').split()
        src = wc['packages'].get(names[0], {}) if names and names[0] in wc['packages'] else wc['main']
        low = {k.strip().lower(): k for k in src}
        tx = src[low[tx_kw.lower()]] if tx_kw.lower() in low else schema_row(tx_kw)['loader_default']
        s = _shape(tx)
        sel = view.nums(sel_kw)
        if s and sel and any(x != int(x) or x < 1 or x > s[1] for x in sel):
            opts = [str(i) for i in range(1, s[1] + 1)]
            why = 'case numbers start at 1' if any(x < 1 for x in sel) else '%s defines %d cases' % (tx_kw, s[1])
            add('ask', 'NC02', '%s = %s: %s' % (sel_kw, show(view.raw(sel_kw)), why), sel_kw, '/main/' + view.key(sel_kw),
                opts, {o: {'set': {'/main/' + view.key(sel_kw): '[ %s ]' % o}} for o in opts})
    # NC04: package_Z_c rows in a block against the line sections of z_p (TX)
    zc_kw, tx4 = rule_keywords('NC04')
    if _hit(touched, 'NC04'):
        for b, vals in wc['packages'].items():
            low = {k.strip().lower(): k for k in vals}
            if zc_kw.lower() in low:
                tx = vals[low[tx4.lower()]] if tx4.lower() in low else schema_row(tx4, 'package block')['loader_default']
                a, t = _shape(vals[low[zc_kw.lower()]]), _shape(tx)
                if a and t and a[0] != t[0]:
                    opts = ['run it anyway', 'cancel']
                    add('ask', 'NC04', '%s in package block %s has %d rows, but %s there has %d line sections'
                        % (zc_kw, b, a[0], tx4, t[0]), zc_kw, '/packages/%s/%s' % (b, low[zc_kw.lower()]), opts,
                        {opts[0]: {'allow': ['NC04']}, 'cancel': None})
    # NC06
    if _hit(touched, 'NC06') and view.num('SAVE_CONFIG2MAT', 0) != 0 and view.num('DIAGNOSTICS', 0) == 0:
        add('announce', 'NC06', rule('NC06')['rule'])
    # EN07: the CTLE type the rule names, with RX_CALIBRATION
    m = re.match(r'(\S+) with RX_CALIBRATION', rule('EN07')['rule'].split('; ')[-1])
    if _hit(touched, 'EN07', ('f_HP_Z', 'g_DC_HP')) and m:
        eff = view.text('CTLE_type')                       # what the loader makes of it (LF09)
        for given, pat in (('g_DC_HP', r'g_DC_HP given sets CTLE_type to ([^;\s]+)'), ('f_HP_Z', r'f_HP_Z given sets it to (\S+)')):
            sets = re.search(pat, rule('LF09')['rule'])
            if view.nums(given) and sets:
                eff = sets.group(1)
        rxcal = view.num('RX_CALIBRATION', 0) != 0 and not tdmode and not (mmse and rxffe)    # LF06, LF07 first
        if eff.lower() == m.group(1).lower() and rxcal:
            opts = ['also set RX_CALIBRATION = 0', 'cancel']
            add('ask', 'EN07', 'CTLE_type %s cannot be used with RX_CALIBRATION = 1: the engine stops' % m.group(1),
                'CTLE_type', None, opts, {opts[0]: {'set': {'/main/' + view.key('RX_CALIBRATION'): 0}}, 'cancel': None})
    # EN08: the RIT references that need f_hp
    rit_kw = rule_keywords('EN08')[0]
    m = re.match(r'(.+?) also need f_hp above 0', schema_row(rit_kw)['note'])
    if change and _hit(touched, 'EN08') and m:
        need = [x.strip() for x in m.group(1).split(' and ')]
        rit = view.text(rit_kw, schema_row(rit_kw)['loader_default'].strip("'"))
        if rit in need and view.num('f_hp', 0) <= 0:
            opts = ['give f_hp a value above 0', 'cancel']
            add('ask', 'EN08', '%s = %s needs f_hp above 0, and f_hp is %s' % (rit_kw, rit, show(view.raw('f_hp', 0))),
                rit_kw, None, opts, {'cancel': None})
    # EN01, EN05: settings with no effect in this config, run anyway and announced
    if change and _hit(touched, 'EN01') and touched & {k.lower() for k in rule_keywords('EN01')[:2]} \
            and view.num('N_qb', 0) == 0:
        add('announce', 'EN01', '%s; with N_qb = 0 the results will not change' % rule('EN01')['rule'])
    board = [k for k in rule_keywords('EN05')[1:]]
    if change and touched & {k.lower() for k in board} and view.num('Include PCB', 0) == 0:
        add('announce', 'EN05', '%s; the results will not change' % rule('EN05')['rule'])
    # LF: settings the loader changes, announced
    lf = {
        'LF01': mlse != 0 and view.num('COM_CONTRIBUTION', 0) != 0,
        'LF02': (phy == c2m and view.num('EW', 0) == 0) or (phy != c2m and view.num('T_O', 0) != 0),
        'LF03': view.num('EH_min', 0) != 0 and phy == c2c,
        'LF04': view.num('FORCE_TR', 0) != 0,
        'LF05': view.num('WC_PORTZ', 0) != 0 and view.num('TDR', 0) == 0,
        'LF06': tdmode != 0,
        'LF07': view.num('RX_CALIBRATION', 0) != 0 and mmse and rxffe and not tdmode,
        'LF08': view.num('N_bg', 0) == 0 and any(view.has(k) and view.num(k) != view.num('N_b') for k in ('N_bmax', 'N_f'))
        or (view.has('N_bmax') and view.has('N_f')),
        'LF09': bool(view.nums('g_DC_HP') or view.nums('f_HP_Z')),
        'LF10': view.num('Gx', 0) == 1,
        'LF12': rxffe and view.num('N_bg', 0) > 0,
    }
    extra = {'LF09': ('f_HP_Z',)}
    for rid, holds in lf.items():
        if holds and _hit(touched, rid, extra.get(rid, ())):
            add('announce', rid, rule(rid)['rule'])
    return F


def _follow_announcements(view, touched):
    """DF rules: a keyword the config lacks takes its default from another; when that one changes, say so."""
    F = []
    for rid, r in rules().items():
        if r['kind'] != 'default follows another keyword':
            continue
        kws = rule_keywords(rid)
        if len(kws) < 2 or 'moves with the first' not in r['assist_behaviour'] or kws[0].lower() not in touched:
            continue
        for k in kws[1:]:
            if not view.has(k):
                F.append(finding('announce', rid, _tag('%s is not in this config, so it takes its default from %s and moves '
                                                       'with it' % (k, kws[0]), rid), k))
    return F


def emulated_release(wc):
    """The release a run of wc emulates (VR02): its COM Version, else the default of the SiCoPR under test."""
    v = _View(wc).text(rule_keywords('VR02')[0])
    return v or engine.default_release()


def _release_announcements(before, after):
    """VR02 and VR03 when COM Version changes."""
    F = []
    kw = rule_keywords('VR02')[0]
    old, new = emulated_release(before), emulated_release(after)
    had = _View(before).has(kw)
    if old == new:
        return F
    F.append(finding('announce', 'VR02', _tag('%s: the release emulated was %s%s, and is now %s' % (
        kw, old, '' if had else ' (%s was not in this config, so the SiCoPR default was in use)' % kw, new), 'VR02'), kw))
    view = _View(after)
    for row in schema_rows():
        if not row['default_by_release'] or view.has(row['keyword']):
            continue
        by = {}
        for part in row['default_by_release'].split(';'):
            m = re.match(r'\s*(.+?) in (.+)$', part)
            if m:
                for rel in m.group(2).split(','):
                    by[rel.strip()] = m.group(1).strip()
        if by.get(old) != by.get(new):
            F.append(finding('announce', 'VR03', _tag('%s is not in this config, so its default moves with %s: %s under %s, '
                                                      '%s under %s' % (row['keyword'], kw, by.get(old), old, by.get(new), new),
                                                      'VR03'), row['keyword']))
    return F


# ----------------------------------------------------------------------------- the entry points
def validate(wc, changes, selections=None, allow=()):
    """A proposed change, {json_path: value} or [(json_path, value)], against wc: ok, ask or stop.

    Each value is checked against the schema first; a value that stops is refused before the working
    config is touched. The others are applied (links downstream recomputed), the cross-parameter rules
    run on the candidate, and the candidate is written as the run CSV and loaded by the real loader."""
    items = list(changes.items() if isinstance(changes, dict) else changes)
    findings, values = [], {}
    for jp, v in items:
        try:
            nv, f = check_value(wc, jp, v, selections)
        except ValueError as e:
            findings.append(finding('stop', None, str(e), json_path=jp))
            continue
        values[jp] = nv
        findings += f
    if any(f['status'] == 'stop' for f in findings):
        return _result(findings, allow, values=values)
    res = config_model.apply_changes(wc, values, check=True)
    for r in res['refused']:
        findings.append(finding('stop', None, r['reason'], json_path=r['json_path']))
    cand = res['config']
    touched = {name_of(c['json_path']).lower() for c in res['changes']} | {name_of(jp).lower() for jp in values}
    view = _View(cand)
    prim = [c for c in res['changes'] if c['kind'] != 'linked']
    if res['changes']:
        findings += _cross(view, touched)
        findings += _follow_announcements(view, touched)
        if rule_keywords('VR02')[0].lower() in touched:
            findings += _release_announcements(wc, cand)
        findings += _unselected_block(view, prim)
    elif res['unchanged'] and not res['refused']:
        held = ', '.join('%s is already %s' % (name_of(c['json_path']), show(c['before']))
                         for c in res['unchanged'])
        findings.append(finding('stop', None, '%s: nothing would change, and the results would equal the last run' % held))
    for w in res['warnings']:
        findings.append(finding('announce', None, w))
    eff = res.get('effect') or {}
    if eff.get('error'):
        _loader_stop(findings, eff['error'])
    elif res.get('no_effect'):
        ne = res['no_effect']
        text, rid = ne['text'], ne['rule']
        ver = rule_keywords('VR02')[0]
        name = name_of(prim[0]['json_path']) if prim else ''
        if prim and name.lower() == ver.lower() and str(prim[0]['after']).strip() == engine.default_release():
            text, rid = '%s is already the default release of this SiCoPR, so the engine inputs would not change and the ' \
                        'results would equal the last run' % prim[0]['after'], 'VR02'
        elif rid is None:                       # a setting the loader overrides in the config as it was (LF rules)
            lf = [f['rule'] for f in _cross(_View(wc), touched) if f['status'] == 'announce' and f['rule']
                  and rule(f['rule'])['kind'] == 'loader changes another setting'
                  and name.lower() in {k.lower() for k in rule_keywords(f['rule'])}]
            if lf:
                rid = lf[0]
                text = '%s, so changing %s has no effect on what the engine reads' % (rule(rid)['rule'], name)
        findings.append(finding('stop', rid, _tag(text, rid), json_path=prim[0]['json_path'] if prim else None))
    return _result(findings, allow, values=values, changes=res['changes'], unchanged=res['unchanged'], config=cand,
                   effect={'error': eff.get('error'), 'moved': sorted(eff.get('moved') or {})})


def _unselected_block(view, prim):
    """An edit inside a package block that PKG_NAME does not select leaves the run inputs as they were:
    ask whether to switch to that block (decided for the table's param rows; no rule covers it)."""
    names = view.text('PKG_NAME').split()
    F = []
    for b in dict.fromkeys(c['json_path'].split('/')[2] for c in prim if c['json_path'].startswith('/packages/')):
        if b in names:
            continue
        opts = ['also switch TX and RX to %s and run' % b, 'save the edit and run with the current package', 'cancel']
        F.append(finding('ask', None, '%s is not the package selected by PKG_NAME (%s), so this edit alone leaves the run '
                         'inputs unchanged' % (b, ' '.join(names) or 'no package'), 'PKG_NAME', '/main/' + view.key('PKG_NAME'),
                         opts, {opts[0]: {'set': {'/main/' + view.key('PKG_NAME'): '%s %s' % (b, b)}},
                                opts[1]: {'allow': [UNSELECTED_BLOCK]}, 'cancel': None}, code=UNSELECTED_BLOCK))
    return F


def _loader_stop(findings, error):
    """The loader refused the candidate. A rule that already asks or stops explains it; the loader's own
    message is added to a rule that says to show it. Otherwise the loader's message is the stop."""
    lead = [f for f in findings if f['status'] in ('ask', 'stop')]
    for f in lead:
        if f['rule'] and 'loader message' in rule(f['rule'])['assist_behaviour']:
            f['text'] += ': the loader says %s' % error
    if not lead:
        findings.append(finding('stop', None, 'the engine\'s loader refuses this config: %s' % error))


def validate_config(wc, selections=None, allow=()):
    """A whole working config: every value against the schema, the cross-parameter rules, keywords the
    loader needs a usable value for (DF17), and a load by the real loader."""
    findings = []
    for block, vals in [(None, wc['main'])] + list(wc['packages'].items()):
        for k, v in vals.items():
            jp = '/main/%s' % k if block is None else '/packages/%s/%s' % (block, k)
            try:
                _, f = check_value(wc, jp, v, selections)
            except ValueError as e:
                f = [finding('stop', None, str(e), json_path=jp)]
            findings += [x for x in f if x['status'] != 'announce']
    view = _View(wc)
    findings += _cross(view, None)
    for k in rule_keywords('DF17'):
        if not view.has(k):
            opts = ['give a value', 'cancel']
            findings.append(finding('ask', 'DF17', _tag('%s is missing and its default cannot be used: %s'
                                                         % (k, rule('DF17')['rule'].split(': ', 1)[-1]), 'DF17'),
                                    k, '/main/' + k, opts, {'cancel': None}))
    fields, err = config_model.loaded_fields(wc)
    if err:
        _loader_stop(findings, err)
    return _result(findings, allow, config=wc, effect={'error': err, 'moved': []})


# Import problems that a rule covers: the issue code of config_model.import_config, and the rule.
IMPORT_RULES = {'start_end': 'LS03', 'duplicate_keyword': 'LS13', 'missing_required': 'LS14'}


def validate_import(path, selections=None, allow=()):
    """Import a config file and validate it: (working config or None, result). Import problems that stop
    or ask come first; a config that imports is then checked as a whole (validate_config)."""
    wc, issues = config_model.import_config(path)
    findings = []
    for i in issues:
        rid = IMPORT_RULES.get(i['code'])
        status = i['level'] if i['level'] in ('stop', 'ask') else 'announce'
        findings.append(finding(status, rid, _tag(i['text'], rid), i.get('keyword'), i.get('json_path'),
                                ['cancel'] if status == 'ask' else []))
    if wc is None or any(f['status'] == 'stop' for f in findings):
        return wc, _result(findings, allow, config=wc)
    whole = validate_config(wc, selections, allow)
    return wc, _result(findings + whole['findings'], allow, config=wc, effect=whole['effect'])

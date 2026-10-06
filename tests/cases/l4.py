"""The L4 normaliser: what the expected_detail column of the use-case table says, in a form a machine
can compare with an outcome.

  PLAN      the step names of the chain, in order (set_param > validate_config > run_com > summarize)
  QUESTION  the options named in the detail, in order
  STOP      not compared by machine: whether a reason names the same cause is left to a person

A detail the normaliser cannot read with confidence goes to the review list with the reason, so
nothing is scored on a guess. The rows it can read are frozen once, in l4_rows.csv, and every later
L4 gate uses that list (prompt section 7).

The step vocabulary itself lives in one place, sicopr_assist.core.STEPS. extract_vocabulary() reads
it back out of the table, and tests/test_l4_normaliser.py checks that the two agree.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, 'sicopr_use_cases.csv')
SCHEMA = os.path.join(HERE, '..', '..', 'sicopr_assist', 'data', 'sicopr_param_schema.csv')

# chain elements that name a step without its snake_case name
SYNONYMS = {'validate': 'validate_config'}           # "validate each", "validate" in the sweep chains
COUNT_WORDS = {'two': 2, 'three': 3, 'four': 4}       # "three set_param steps (N_b, ...)"
# chain elements that annotate the step before them and are not steps: "4 working configs"
ANNOTATION = re.compile(r'^\d+ working configs?\b')
LEAD = re.compile(r'^([a-z][a-z0-9_]*)(?=$|[\s(:,])')
REF = re.compile(r'^(?:same plan as|same as|as) ([A-Z]{1,3}\d+)(?=$|[:;]| only\b)')

# option lists that describe options rather than name them
DESCRIBED = re.compile(r'^(?:the (?:two|three|four|five|six|seven|eight|nine|ten|available|releases|next|list)\b'
                       r'|each\b|are\b|for\b)')
MAX_OPTION_WORDS = 12
# a one-step chain whose step is described, not named in order with the rest
# ("import_config writes a config JSON ...", "import_config from .csv ..., then run")
PROSE_CHAIN = re.compile(r'^[a-z_]+ writes\b|, then run\b')


def split_top(s, sep):
    """Split at sep where no parenthesis or bracket is open."""
    out, depth, cur, i = [], 0, '', 0
    while i < len(s):
        ch = s[i]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if depth == 0 and s.startswith(sep, i):
            out.append(cur)
            cur = ''
            i += len(sep)
            continue
        cur += ch
        i += 1
    out.append(cur)
    return out


def _element(el, vocab):
    """One chain element -> list of step names ([] for an annotation), or None when it cannot be mapped."""
    el = el.strip()
    if ANNOTATION.match(el):
        return []
    m = re.match(r'^(two|three|four) ([a-z_]+) steps\b', el)
    if m and m.group(2) in vocab:
        return [m.group(2)] * COUNT_WORDS[m.group(1)]
    m = LEAD.match(el)
    if m and m.group(1) in vocab:
        return [m.group(1)]
    if m and m.group(1) in SYNONYMS:
        return [SYNONYMS[m.group(1)]]
    return None


def _label_ends(seg):
    """Where the text after each top-level label ('xxx: ') starts; a colon inside parentheses
    (set_param(f_b: 106.25 -> 53.125)) is not a label."""
    out, depth = [], 0
    for i, ch in enumerate(seg):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and seg.startswith(': ', i):
            out.append(i + 2)
    return out


def _chain_candidates(detail):
    """Each top-level segment, and the text after each label ('xxx: ') inside it."""
    for seg in split_top(detail, '; '):
        yield seg.strip()
        for k in _label_ends(seg):
            yield seg[k:].strip()


def chain_of(detail, vocab):
    """(steps, unmapped) for the first chain in the detail, or (None, []) when there is none.

    A chain starts at the beginning of a segment or right after a label, and its first element is a
    step. A chain with an element that cannot be mapped is returned with the element in unmapped."""
    for cand in _chain_candidates(detail):
        parts = split_top(cand, ' > ')
        first = _element(parts[0], vocab)
        if not first:
            continue
        steps, unmapped = [], []
        for el in parts:
            got = _element(el, vocab)
            if got is None:
                unmapped.append(el.strip())
            else:
                steps.extend(got)
        return steps, unmapped
    return None, []


def _keywords():
    rows = csv.DictReader(open(SCHEMA, newline='', encoding='utf-8'))
    return {r['keyword'].strip().lower() for r in rows}


_KW = None


def option_text(s):
    """An option as compared: spaces collapsed, lower case, a trailing remark in parentheses dropped
    unless the parentheses belong to a COM keyword (z_p (TX), c(-1))."""
    global _KW
    if _KW is None:
        _KW = _keywords()
    s = ' '.join(str(s).split())
    while True:
        low = s.lower()
        if low in _KW:
            return low
        m = re.match(r'^(.*\S)\s*\([^()]*\)$', s)
        if not m:
            return low
        s = m.group(1)


def options_of(detail):
    """(options, why_not) for the option list in a QUESTION detail. options is None when the detail has
    no list the normaliser can read; why_not then says why."""
    m = re.search(r'\boptions\b:?\s*', detail)
    if not m:
        return None, 'no option list'
    rest = detail[m.end():]
    head = split_top(rest, '; ')[0]
    k = head.find('from the keyword descriptions')
    if k >= 0:
        c = head.find(': ', k)
        if c < 0:
            return None, 'keyword-description options with no list'
        rest = head[c + 2:]
    text = split_top(rest, '; ')[0]
    text = re.split(r'\. (?=[A-Z])', text)[0].strip().rstrip('.')
    if DESCRIBED.match(text):
        return None, 'options described, not named: ' + text[:60]
    items = [x.strip() for x in split_top(text, ', ')]
    out = []
    for i, it in enumerate(items):
        it = re.sub(r'^(?:or|then) ', '', it)
        if DESCRIBED.match(it) or ' as in ' in it:
            return None, 'options described, not named: ' + it[:60]
        if re.match(r'^[-\d.]', it) and i > 0 and not re.match(r'^[-\d.]', items[i - 1]):
            return None, 'a list of numbers inside one option: ' + text[:60]
        stripped = option_text(it)
        stripped = re.sub(r' first$', '', stripped)
        if not stripped or len(stripped.split()) > MAX_OPTION_WORDS:
            return None, 'an option too long to be a name: ' + it[:60]
        out.append(stripped)
    return out, ''


def load_table(path=TABLE):
    return list(csv.DictReader(open(path, newline='', encoding='utf-8')))


def extract_vocabulary(rows):
    """Every step name the chains of the table use.

    In a chain of two or more elements (a > b), the leading snake_case word of each element, and an
    element that is a single plain word (download, extract, inventory). In a PLAN detail with no chain,
    a snake_case word that opens a segment and is followed by '(' or ':' or the end, or by a space
    and more words (show_param(DER_0): ..., show_settings: ..., list_parameters grouped by ...).
    A snake_case word in prose after a label (max_runs is not a setting) is not a step."""
    names = set()
    for r in rows:
        found = False
        for seg in split_top(r['expected_detail'], '; '):
            for cand in [seg.strip()] + [seg[k:].strip() for k in _label_ends(seg)]:
                parts = split_top(cand, ' > ')
                if len(parts) < 2:
                    continue
                found = True
                for el in parts:
                    el = el.strip()
                    m = LEAD.match(el)
                    if m and ('_' in m.group(1) or (el == m.group(1) and el not in SYNONYMS)):
                        names.add(m.group(1))
        if not found and r['expected_type'] == 'PLAN':
            first = split_top(r['expected_detail'], '; ')[0].strip()
            m = re.match(r'^([a-z]+_[a-z_]+)(?=$|[(:]| [a-z])', first)
            if m:
                names.add(m.group(1))
    return names


def _referenced(row, by_id):
    """The row a detail such as 'as PH22' or 'same plan as R3' points to, or None."""
    m = REF.match(row['expected_detail'])
    if not m:
        return None
    for r in by_id.get(m.group(1), []):
        if r['expected_type'] == row['expected_type']:
            return r
    return None


def classify(row, by_id, vocab):
    """('chain', [steps]) | ('options', [options]) | ('review', reason)."""
    t = row['expected_type']
    d = row['expected_detail']
    if t == 'STOP':
        return 'review', 'STOP: whether the reason names the same cause is read by a person'
    if t == 'PLAN':
        steps, unmapped = chain_of(d, vocab)
        if steps is None:
            ref = _referenced(row, by_id)
            if ref is not None and ref is not row:
                steps, unmapped = chain_of(ref['expected_detail'], vocab)
        if steps is None:
            return 'review', 'no step chain in the detail'
        if unmapped:
            return 'review', 'chain items with no step name: ' + ' | '.join(unmapped)
        if len(steps) == 1 and PROSE_CHAIN.search(d):
            return 'review', 'a one-step chain that goes on in prose: ' + d[:60]
        return 'chain', steps
    opts, why = options_of(d)
    if opts is None and why == 'no option list':
        ref = _referenced(row, by_id)
        if ref is not None and ref is not row:
            opts, why = options_of(ref['expected_detail'])
    if opts is None:
        return 'review', why
    return 'options', opts


def row_key(row):
    return '%s|%s' % (row['id'], row['starting_config'])


def build(rows, vocab):
    by_id = {}
    for r in rows:
        by_id.setdefault(r['id'], []).append(r)
    return [(r, classify(r, by_id, vocab)) for r in rows]


# ----------------------------------------------------------------------------- scoring
def outcome_steps(outcome):
    return [s.get('op') for s in outcome.get('steps') or []]


def outcome_options(outcome):
    q = outcome.get('question') or {}
    return [re.sub(r' first$', '', option_text(o)) for o in q.get('options') or []]


def score(kind, expected, outcome):
    """True when the outcome matches the frozen expectation of one row."""
    if kind == 'chain':
        return outcome.get('type') == 'PLAN' and outcome_steps(outcome) == list(expected)
    if kind == 'options':
        return outcome.get('type') == 'QUESTION' and outcome_options(outcome) == list(expected)
    return False

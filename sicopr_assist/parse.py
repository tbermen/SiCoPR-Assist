"""Words to a request: action, names, values, units, ranges, files, and the words left over.

Strict mode (Rule 4): a parameter is named by its COM keyword, case and spaces ignored. There is no alias
table. Two words are built in: "package" means PKG_NAME, and "COM" as a result means the result field
channel_operating_margin_dB. A word that cannot be placed is reported in "unplaced"; the core asks about
it and never guesses. A mistyped action or filler word of four or more letters, one letter or one swap of
neighbouring letters away from the known word, is read as that word (row PH08); a shorter word never is.

read(phrase, names, blocks) returns a plain dictionary:

    actions     the action words found, as tags: run, rerun, change, sweep, show, save, compare, reset,
                undo, summary, list, why, and the version 2 tags dashboard, fetch, tutor, feedback
    sets        [{name | attempt, value, unit, block, block_attempt, side, op, part}]  one change each
    sweeps      [{name | attempt, start, end, count, step, unit, values, every, side}]  one swept name each
    packages    [{'value': [TX, RX] or [both], 'attempt': text}]                  "package X" and its forms
    files       [{'text', 'ext', 'role'}]   role: thru, fext or next when a role word comes right before it
    attempts    [{'text', 'words', 'value'}]   names that are not a known name, as typed
    unplaced    words that could not be placed: every word that is not a filler word, an action word, or part of
                a clause above lands here, so no word is ever dropped
    corrected   {typed: read as} for the typo rule
    flags       set of plain markers: again, this_config, these_files, example, thru_only, crosstalk,
                different, instead, all, diff, both, last_config, last_run, and selection with sel_config and
                sel_channel (the config and the channel files selected in the GUI's tabs, Decision 20)
    pattern     a short text of how the phrase was read (goes to history)

Nothing here reads a config or the engine: the caller passes the known names and block names.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import re

from sicopr_assist.validate import UNIT_FACTORS

# ----------------------------------------------------------------------------- the vocabulary
# Words that name an action. Each maps to a tag the core plans from.
ACTION_WORDS = {
    'run': 'run', 'rerun': 'rerun', 're-run': 'rerun', 'redo': 'rerun', 'repeat': 'rerun', 'rn': None,
    'analyze': 'run', 'analyse': 'run', 'go': 'run', 'start': 'run',
    'change': 'change', 'set': 'change', 'try': 'change', 'use': 'change', 'fix': 'change', 'hold': 'change',
    'add': 'change', 'put': 'change', 'turn': 'change', 'disable': 'change', 'enable': 'change',
    'sweep': 'sweep', 'vary': 'sweep',
    'show': 'show', 'list': 'list', 'print': 'show', 'display': 'show',
    'save': 'save', 'export': 'save',
    'compare': 'compare', 'differ': 'compare',
    'reset': 'reset', 'original': 'reset', 'undo': 'undo', 'restore': 'undo', 'revert': 'undo',
    'summary': 'summary', 'summarize': 'summary', 'summarise': 'summary', 'statistics': 'summary',
    'correlate': 'summary', 'correlation': 'summary',
    'why': 'why', 'explain': 'why', 'limiting': 'why', 'diagnose': 'why',
    # version 2 features: the dashboard, the tutor, feedback and channel download
    'dashboard': 'dashboard', 'plot': 'dashboard', 'interactive': 'dashboard', 'report': 'dashboard',
    'download': 'fetch', 'fetch': 'fetch', 'grab': 'fetch',
    'tutor': 'tutor', 'hints': 'tutor', 'help': 'tutor',
    'feedback': 'feedback',
}
del ACTION_WORDS['rn']

# Words that carry no meaning of their own here. Each is placed, never asked about.
FILLER = {
    'with', 'the', 'a', 'an', 'and', 'then', 'but', 'same', 'now', 'it', 'please', 'ahead', 'for', 'me',
    'setup', 'to', 'at', 'by', 'from', 'in', 'of', 'again', 'also', 'this', 'that', 'these', 'here', 'files',
    'file', 'on', 'can', 'you', 'is', 'be', 'should', 'as', 'well', 'instead', 'up', 'i', 'my', 'do', 'using',
    'config', 'both', 'ends', 'off', 'all', 'steps', 'step', 'points', 'point', 'value', 'values', 'give',
    'results', 'result', 'differences', 'difference', 'what', 'did', 'how', 'does', 'last', 'one', 'com',
    'sicopr', 'analysis', 'side', 'only', 'thru', 'every', 'packages', 'gives', 'w', 'thing',
}
CONFIRM = {'yes', 'ok', 'okay', 'sure', 'go', 'ahead', 'run', 'them', 'all', 'it', 'please', 'do'}
OPTION_WORDS = {'option', 'options', 'value', 'values', 'setting', 'settings', 'case', 'cases'}

SIDES = {'tx': 'TX', 'rx': 'RX'}
WORD_NUMBERS = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
RANGE_PARTS = {'step': 'step', 'minimum': 'start', 'min': 'start', 'start': 'start', 'maximum': 'end', 'max': 'end',
               'end': 'end'}
CONFIG_EXT = ('.xlsx', '.xls', '.csv', '.json', '.mat')
CHANNEL_EXT = re.compile(r'\.s\d+p$', re.I)
# "the previous config" and its two other wordings mean the config of the last run (Decision 18). Only before
# the word config: "previous" alone is not placed.
LAST_CONFIG_WORDS = ('previous', 'same', 'last')
# a word right before a channel file that says which channel it is (row CH08)
CHANNEL_ROLES = {'thru': 'thru', 'fext': 'fext', 'next': 'next'}
# words for the crosstalk files of the THRU in use (Decision 19), and the verbs taken only together with them
# ("include the matching xtalk files in the simulation")
CROSSTALK_WORDS = ('crosstalk', 'xtalk', 'cross-talk')
CROSSTALK_VERBS = ('add', 'include')
# words for the config and the channel files selected in the GUI's tabs (Decision 20). They are read only in the
# forms _selection lists, and are not known words on their own: "selected" alone is still asked about.
SELECT_WORDS = ('selected', 'specified', 'chosen')
SELECT_THINGS = {'config': 'config', 'channel': 'channel', 'channels': 'channel', 'files': 'files'}

# Every word the reader can place: the typo rule reads a near miss of one of these as the word itself.
KNOWN_WORDS = set(ACTION_WORDS) | FILLER | set(SIDES) | set(WORD_NUMBERS) | {
    'package', 'packages', 'first', 'different', 'example', 'sample', 'demo', 'crosstalk', 'xtalk', 'thru-only',
    'without', 'into', 'as', 'back', 'everything', 'changes', 'change', 'other', 'yes', 'option', 'options'}

_UNITS = sorted(UNIT_FACTORS, key=len, reverse=True)
_UNIT_RE = re.compile(r'\s*(%s)(?![\w^/])' % '|'.join(re.escape(u) for u in _UNITS), re.I)
_NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
_TOKEN = re.compile(r'''
     (?P<bracket>\[[^\[\]]*\])
    |(?P<path>(?:[A-Za-z]:[\\/])?(?:[\w.{}~$-]+[\\/])+[\w.{}~$-]*\.(?:s\d+p|xlsx|xls|csv|json|mat)\b
             |(?:[A-Za-z]:)?[\w.{}~$-]*(?:\\[\w.{}~$-]*)+\\?(?=[\s,;?!]|\.?$)|[\w~$-]+\.(?:s\d+p|xlsx|xls|csv|json|mat)\b)
    |(?P<num>%s(?![\w]|\.\d))
    |(?P<word>[A-Za-z_\d][\w'.-]*?(?:\([^()\s]*\))?(?=[\s,;=&?!:\[]|\.(?:\s|$)|$))
    |(?P<paren>\([^()]*\))
    |(?P<eq>=)
    |(?P<sep>[,;&])
    |(?P<punct>[.?!:/"])
''' % _NUM, re.X)


def squash(text):
    """A name as it is compared: lower case, spaces removed (the loader ignores case and spaces at the ends;
    strict mode ignores spaces anywhere, so z_p(TX) is z_p (TX))."""
    return re.sub(r'\s+', '', str(text)).lower()


def letters(text):
    """Only the letters and digits, lower case: the form near matches are measured on."""
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


def one_edit(a, b):
    """True when a and b differ by one letter (substituted, added or removed) or by one swap of neighbours."""
    if a == b:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if abs(len(a) - len(b)) != 1:
        return False
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return any(t[:i] + t[i + 1:] == s for i in range(len(t)))


def typo_of(word):
    """The action or filler word a mistyped word is read as, or None. Only words of four or more letters."""
    w = word.lower()
    if len(w) < 4 or not w.isalpha() or w in KNOWN_WORDS:
        return None
    hits = sorted(k for k in KNOWN_WORDS if len(k) >= 4 and one_edit(w, k))
    return hits[0] if len(hits) == 1 else None


# ----------------------------------------------------------------------------- tokens
def tokenize(phrase):
    """[{kind, text, low, num, unit}] in order. kind is bracket, path, num, word, paren, eq, sep or punct."""
    out, i, s = [], 0, str(phrase)
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        m = _TOKEN.match(s, i)
        if not m:
            out.append({'kind': 'word', 'text': s[i], 'low': s[i].lower(), 'num': None, 'unit': None})
            i += 1
            continue
        kind = m.lastgroup
        text = m.group(0)
        tok = {'kind': kind, 'text': text, 'low': text.lower(), 'num': None, 'unit': None}
        i = m.end()
        if kind == 'path':
            if text.lower() in ('w/', 'w\\'):
                tok.update(kind='word', text='with', low='with')
            elif text.endswith('.') and not text.endswith('..'):
                tok.update(text=text[:-1], low=text[:-1].lower())
        elif kind == 'num':
            if text.endswith('.'):                                  # "N_b = 3." ends the sentence
                tok.update(text=text[:-1], low=text[:-1].lower())
            tok['num'] = float(tok['text'])
            u = _UNIT_RE.match(s, i)
            if u:
                tok['unit'] = u.group(1)
                i = u.end()
        elif kind == 'word':
            while tok['text'].endswith('.') and not tok['text'].endswith(')'):
                tok['text'] = tok['text'][:-1]
            tok['low'] = tok['text'].lower()
            if not tok['text']:
                continue
        out.append(tok)
    return out


def value_text(tok):
    """A value token as typed, with its unit (validate converts units)."""
    if tok['kind'] == 'num':
        return tok['text'] + (' ' + tok['unit'] if tok['unit'] else '')
    return tok['text']


# ----------------------------------------------------------------------------- the reader
class _Reader:
    def __init__(self, phrase, names, blocks):
        self.phrase = phrase
        self.toks = tokenize(phrase)
        self.n = len(self.toks)
        self.used = [False] * self.n
        self.names = {}
        for nm in names:
            self.names.setdefault(squash(nm), nm)
        self.blocks = {b.lower(): b for b in blocks}
        self.longest = max([len(re.findall(r'\S+', n)) for n in names] + [1]) + 1
        self.out = {'phrase': phrase, 'actions': [], 'sets': [], 'sweeps': [], 'packages': [], 'files': [],
                    'attempts': [], 'unplaced': [], 'corrected': {}, 'flags': [], 'edits': [], 'pattern': ''}
        self.marks = [None] * self.n               # what each token was read as
        self.roles = {}                            # token index of a channel file: the role word before it
        self._mark_files()
        self._mark_names()
        self._mark_words()

    # ---- first pass: what each token is
    def _mark_files(self):
        for i, t in enumerate(self.toks):
            if t['kind'] == 'path' or (t['kind'] == 'word' and (t['low'].endswith(CONFIG_EXT) or CHANNEL_EXT.search(t['low']))):
                self.marks[i] = ('file', t['text'])

    def _mark_names(self):
        i = 0
        while i < self.n:
            hit = None
            for k in range(min(self.longest, self.n - i), 0, -1):
                span = self.toks[i:i + k]
                if any(t['kind'] not in ('word', 'paren') or self.marks[i + j] for j, t in enumerate(span)):
                    continue
                key = squash(''.join(t['text'] for t in span))
                if key in self.names:
                    hit = (k, self.names[key])
                    break
            if hit:
                for j in range(hit[0]):
                    self.marks[i + j] = ('name', hit[1], i)
                i += hit[0]
            else:
                i += 1

    def _mark_words(self):
        for i, t in enumerate(self.toks):
            if self.marks[i]:
                continue
            if t['kind'] in ('num', 'bracket'):
                self.marks[i] = ('value',)
            elif t['kind'] == 'eq':
                self.marks[i] = ('eq',)
            elif t['kind'] in ('sep', 'punct'):
                self.marks[i] = ('sep', t['text'])
            elif t['kind'] == 'word':
                w = t['low']
                if w in self.blocks:
                    self.marks[i] = ('block', self.blocks[w])
                elif w in KNOWN_WORDS or w in ("what's", "here's", "it's", "let's"):
                    self.marks[i] = ('word', w)
                else:
                    fixed = typo_of(w)
                    if fixed:
                        self.out['corrected'][t['text']] = fixed
                        self.marks[i] = ('word', fixed)
                    else:
                        self.marks[i] = ('unknown', t['text'])
            else:
                self.marks[i] = ('unknown', t['text'])

    # ---- helpers
    def kind(self, i):
        return self.marks[i][0] if 0 <= i < self.n else None

    def word(self, i):
        return self.marks[i][1] if 0 <= i < self.n and self.marks[i][0] == 'word' else None

    def is_value(self, i):
        return 0 <= i < self.n and self.marks[i][0] == 'value'

    def name_at(self, i):
        """(name, first token, token after) when a name starts at i."""
        if self.kind(i) != 'name' or self.marks[i][2] != i:
            return None
        j = i
        while j < self.n and self.kind(j) == 'name' and self.marks[j][2] == i:
            j += 1
        return self.marks[i][1], i, j

    def take(self, *idx):
        for i in idx:
            if 0 <= i < self.n:
                self.used[i] = True

    def value_after(self, j, allow_word=False, pkg=False):
        """(value text, unit, end) of a value starting at j (after =, to, at, is or nothing)."""
        if j >= self.n:
            return None
        t = self.toks[j]
        if self.is_value(j):
            return t['text'], t['unit'], j + 1
        if t['kind'] == 'path' and allow_word:
            return t['text'], None, j + 1
        if allow_word and self.kind(j) in ('unknown', 'block', 'word', 'name') and t['kind'] == 'word':
            if self.kind(j) == 'word' and t['low'] in FILLER:
                return None
            if pkg and j + 1 < self.n and self.kind(j + 1) in ('block', 'unknown') and self.toks[j + 1]['kind'] == 'word':
                return t['text'] + ' ' + self.toks[j + 1]['text'], None, j + 2
            return t['text'], None, j + 1
        return None

    def values_list(self, j):
        """A list of two or more values: v1, v2 and v3 (or v1 and v2). (values, end) or None."""
        vals, k = [], j
        while self.is_value(k):
            vals.append(value_text(self.toks[k]))
            k += 1
            if k < self.n and (self.kind(k) == 'sep' and self.toks[k]['text'] == ',' or self.word(k) == 'and') \
                    and self.is_value(k + 1):
                k += 1
                continue
            break
        return (vals, k) if len(vals) >= 2 else None

    # ---- the grammar
    def read(self):
        o = self.out
        i = 0
        while i < self.n:
            j = self._clause(i)
            i = j if j > i else i + 1
        self._attempts()
        for i, m in enumerate(self.marks):
            if self.used[i]:
                continue
            if m[0] == 'word':
                # A known word is placed here only when it carries no meaning beyond its own: a filler word, or
                # an action word. Any other known word (crosstalk, package, tx, three, back, ...) means something
                # only inside a clause; when no clause took it, it is unplaced, so it is asked about and never
                # dropped (the maintainer's "Add xtalk files and re-run." once replayed the last command).
                tag = ACTION_WORDS.get(m[1])
                if tag is None and m[1] not in FILLER and m[1] not in ("what's", "here's", "it's", "let's"):
                    continue
                if tag and tag not in o['actions']:
                    o['actions'].append(tag)
                if m[1] in ('again', 'repeat'):
                    self.flag('again')
                self.used[i] = True
            elif m[0] in ('sep', 'eq'):
                self.used[i] = True
            elif m[0] == 'file':
                o['files'].append({'text': m[1], 'ext': _ext(m[1]), 'role': self.roles.get(i)})
                self.used[i] = True
        for i, m in enumerate(self.marks):
            if not self.used[i]:
                o['unplaced'].append(self.toks[i]['text'])
        o['pattern'] = self._pattern()
        return o

    def flag(self, f):
        if f not in self.out['flags']:
            self.out['flags'].append(f)

    def _clause(self, i):
        """Try the patterns that start at token i; return the index after what was consumed, or i."""
        o = self.out
        w = self.word(i)
        # words that set a flag
        if w in ('this', 'these', 'that'):
            k = i + 1 + (self.word(i + 1) == 'here')
            if self.word(k) in ('config', 'files', 'file'):
                self.flag('this_config' if self.word(k) == 'config' else 'these_files')
                self.take(*range(i, k + 1))
                return k + 1
        # yes, ok: an answer to a pending question (the core reads those itself); in a request they place nothing
        # and are left unplaced, so "Add yes files and re-run." asks
        # the previous config, the same config, the last config: the config of the last run (Decision 18)
        low = self.toks[i]['low']
        if low in LAST_CONFIG_WORDS and self.word(i + 1) == 'config':
            self.flag('last_config')
            self.take(i, i + 1)
            return i + 2
        # a role word before a channel file: FEXT data\fext1.s4p (Decision 18, row CH08)
        if low in CHANNEL_ROLES and self.kind(i + 1) == 'file' and CHANNEL_EXT.search(self.toks[i + 1]['low']):
            self.roles[i + 1] = CHANNEL_ROLES[low]
            self.take(i)
            return i + 1
        # an edit of a pending sweep: use 16 steps (instead), use steps of 2e-6, use 5 points
        if self.is_value(i) and self.word(i + 1) in ('steps', 'step', 'points', 'point') and not self.toks[i]['unit']:
            self.out['edits'].append({'count': self.toks[i]['text']})
            self.take(i, i + 1)
            return i + 2
        if w in ('steps', 'step') and self.word(i + 1) == 'of' and self.is_value(i + 2):
            self.out['edits'].append({'step': self.toks[i + 2]['text'], 'unit': self.toks[i + 2]['unit']})
            self.take(i, i + 1, i + 2)
            return i + 3
        # every NAME case, all four NAME: all of its values in one run; every NAME option: a sweep of them
        k = i + 1 + (self.word(i + 1) in WORD_NUMBERS)
        if w in ('every', 'all') and self.name_at(k):
            nm = self.name_at(k)
            tail = self.toks[nm[2]]['low'] if nm[2] < self.n else ''
            if tail in ('case', 'cases') or (k > i + 1 and tail not in OPTION_WORDS):
                self.out['sets'].append({'name': nm[0], 'value': None, 'unit': None, 'op': 'all'})
                end = nm[2] + (tail in ('case', 'cases'))
                self.take(*range(i, end))
                return end
            if tail in OPTION_WORDS:
                self.out['sweeps'].append({'name': nm[0], 'every': True})
                self.take(*range(i, nm[2] + 1))
                return nm[2] + 1
        if self.kind(i) == 'unknown' and self.toks[i]['low'] in ('example', 'sample', 'demo'):
            return i
        if w in ('example', 'sample', 'demo'):
            self.flag('example')
            self.take(i)
            return i + 1
        if w in ('crosstalk', 'xtalk') and self.word(i - 1) == 'without' or w == 'thru-only' \
                or (w == 'thru' and self.word(i + 1) == 'only'):
            self.flag('thru_only')
            self.take(i, i - 1 if self.word(i - 1) == 'without' else i, i + 1 if self.word(i + 1) == 'only' else i)
            return i + 1
        # "the last run", "the previous run": a run already made, not a request to run (row SM16)
        if low in ('run', 'runs') and i > 0 and self.toks[i - 1]['low'] in ('last', 'previous') and not self.used[i - 1]:
            self.flag('last_run')
            self.take(i - 1, i)
            return i + 1
        end = self._crosstalk(i)
        if end > i:
            return end
        end = self._selection(i)
        if end > i:
            return end
        # "a different DER_0", "a different package": placed only before what it qualifies, else unplaced
        if w == 'different' and (self.kind(i + 1) == 'name' or self.word(i + 1) in ('package', 'packages')):
            self.flag('different')
            self.take(i)
            return i + 1
        if w == 'instead':
            self.flag('instead')
        # switches: turn off X, disable X, without X (and Y)
        if w in ('turn', 'disable', 'enable', 'without'):
            k = i + 1
            val = {'disable': 0, 'enable': 1, 'without': 0}.get(w)
            if w == 'turn' and self.word(k) in ('off', 'on'):
                val = 0 if self.word(k) == 'off' else 1
                k += 1
            if val is not None:
                got, end = self._switch_names(k, val)
                if got:
                    self.take(*range(i, end))
                    return end
        # package forms
        if w == 'package' or w == 'packages' or (w in SIDES and self.word(i + 1) == 'package'):
            end = self._package(i)
            if end > i:
                return end
        # a sweep: [sweep] [the] [TX|RX] NAME from A to B ..., or sweep NAME
        if w in ('sweep', 'vary') or (w == 'step' and self.kind(i + 1) == 'name'):
            end = self._sweep(i)
            if end > i:
                return end
        # NAME forms
        side = None
        k = i
        if w in SIDES and self.kind(i + 1) in ('name',):
            side, k = SIDES[w], i + 1
        nm = self.name_at(k)
        blk = None
        if nm is None and self.kind(k) == 'block' and self.name_at(k + 1):
            blk, k = self.marks[k][1], k + 1                                  # BLOCK NAME at V
            nm = self.name_at(k)
        if nm:
            return self._after_name(i, nm, side, blk)
        # V for NAME
        if self.is_value(i) and self.word(i + 1) == 'for' and self.name_at(i + 2):
            name, a, b = self.name_at(i + 2)
            o['sets'].append(self._set(name, self.toks[i], block=self._block_qual(b)[0]))
            end = self._block_qual(b)[1]
            self.take(*range(i, end))
            return end
        return i

    def _crosstalk(self, i):
        """[add | include] [the] [matching] crosstalk | xtalk | FEXT and NEXT [files] [in the simulation] [added]:
        the crosstalk files of the THRU in use (Decision 19). Sets the flag crosstalk; returns the index after it,
        or i. The words around it are taken only together with it."""
        low = lambda k: self.toks[k]['low'] if 0 <= k < self.n and not self.used[k] else None  # noqa: E731
        if low(i) in CROSSTALK_WORDS:
            k = i + 1
        elif low(i) in ('fext', 'next') and low(i + 1) == 'and' and low(i + 2) in ('fext', 'next') \
                and low(i + 2) != low(i) and self.kind(i + 3) != 'file':
            k = i + 3
        else:
            return i
        if low(k) in ('files', 'file'):
            k += 1
        if low(k) == 'in' and low(k + 1 + (low(k + 1) == 'the')) in ('simulation', 'run'):
            k += 2 + (low(k + 1) == 'the')
        elif low(k) == 'added':
            k += 1
        start = i
        if low(start - 1) == 'matching':
            start -= 1
        if low(start - 1) == 'the':
            start -= 1
        if low(start - 1) in CROSSTALK_VERBS:
            start -= 1
        self.flag('crosstalk')
        self.take(*range(start, k))
        return k

    def _selection(self, i):
        """The config and the channel files selected in the GUI's tabs (Decision 20), in these forms, where S is
        selected, specified or chosen and T is config, channel, channels or files:

            [the] S T [and [the] [S] T]         the selected config and channel; the chosen files
            [the] T [and [the] T] S             the config and channels specified; the channel selected
            [the] T [and [the] T] in the tabs   the config and channels in the tabs
            the selection                       what's S, what is S

        each with "in the tabs" after it or not. Sets the flag selection, and sel_config and sel_channel for what
        was named (files, the selection and what is selected name both). Returns the index after it, or i. The
        words are taken only together: one of them alone is left where it was, and is asked about."""
        def low(k):
            if 0 <= k < self.n and not self.used[k] and self.marks[k][0] in ('word', 'unknown'):
                return self.toks[k]['low']
            return None

        def things(k):
            got = []
            if low(k) not in SELECT_THINGS:
                return got, k
            got.append(SELECT_THINGS[low(k)])
            j = k + 1
            if low(j) == 'and':
                j += 1 + (low(j + 1) == 'the')
                j += low(j) in SELECT_WORDS
                if low(j) in SELECT_THINGS:
                    got.append(SELECT_THINGS[low(j)])
                    return got, j + 1
            return got, k + 1

        def tabs(k):
            return k + 3 if low(k) == 'in' and low(k + 1) == 'the' and low(k + 2) in ('tabs', 'tab') else k

        k = i + (low(i) == 'the')
        got, end = [], i
        if low(k) in SELECT_WORDS:
            got, e = things(k + 1)
            end = tabs(e) if got else i
        elif low(k) in SELECT_THINGS:
            got, e = things(k)
            if low(e) in SELECT_WORDS:
                end = tabs(e + 1)
            elif tabs(e) > e:
                end = tabs(e)
        elif low(k) == 'selection' and k > i:
            got, end = ['files'], tabs(k + 1)
        elif k == i and (low(i) == "what's" or (low(i) == 'what' and low(i + 1) == 'is')):
            j = i + 1 + (low(i) == 'what')
            if low(j) in SELECT_WORDS:
                got, end = ['files'], tabs(j + 1)
        if end == i:
            return i
        self.flag('selection')
        if 'config' in got or 'files' in got:
            self.flag('sel_config')
        if 'channel' in got or 'files' in got:
            self.flag('sel_channel')
        self.take(*range(i, end))
        return end

    def _switch_names(self, k, val):
        got = []
        while True:
            if self.word(k) == 'the':
                k += 1
            nm = self.name_at(k)
            if not nm:
                break
            self.out['sets'].append({'name': nm[0], 'value': str(val), 'unit': None, 'op': 'switch'})
            got.append(nm[0])
            k = nm[2]
            if self.word(k) == 'and' and self.name_at(k + 1):
                k += 1
                continue
            break
        return got, k

    def _set(self, name, tok, block=None, side=None, op='set', text=None):
        return {'name': name, 'value': text if text is not None else (tok['text'] if tok else None),
                'unit': tok['unit'] if tok else None, 'block': block, 'side': side, 'op': op}

    def _block_qual(self, j):
        """A block named after a value: 'in B' or 'for B' (B a block of this config, or words to resolve)."""
        if self.word(j) in ('in', 'for') and self.kind(j + 1) == 'block':
            return self.marks[j + 1][1], j + 2
        if self.word(j) in ('in', 'for') and self.kind(j + 1) == 'unknown':
            k = j + 1
            words = []
            while k < self.n and self.kind(k) == 'unknown' and len(words) < 3:
                words.append(self.toks[k]['text'])
                k += 1
            if self.kind(k) is None or self.kind(k) == 'sep':
                self.out['attempts'].append({'text': ' '.join(words), 'words': words, 'block': True})
                self.take(*range(j, k))
                return {'attempt': ' '.join(words)}, k
        return None, j

    def _after_name(self, i, nm, side, blk):
        """NAME = V, NAME to V, NAME at V, NAME V, NAME at V1, V2 and V3, NAME in B to V, NAME step to V."""
        o = self.out
        name, a, b = nm
        j = b
        block = blk
        element = self.word(a - 1) in ('first', 'second') or (self.word(a - 1) == 'the' and self.word(a - 2) in ('first', 'second'))
        if self.word(j) == 'in' and self.kind(j + 1) == 'block' and self.word(j + 2) == 'to':
            block, j = self.marks[j + 1][1], j + 2
        part = None
        if self.word(j) in RANGE_PARTS and self.word(j + 1) == 'to':
            part, j = RANGE_PARTS[self.word(j)], j + 1
        if self.word(j) == 'value' and self.word(j + 1) == 'to':
            j += 1
        # a range: NAME from A to B
        if self.word(j) == 'from':
            end = self._range(i, name, j, side)
            if end > j:
                return end
        marker = None
        if self.kind(j) == 'eq' or self.word(j) in ('to', 'at', 'is', 'be'):
            marker = j
            j += 1
            if self.word(j) == 'be':
                j += 1
        elif self.word(j) == 'should' and self.word(j + 1) == 'be':
            marker = j
            j += 2
        elif self.word(j) == 'set' and self.word(j + 1) == 'to':
            marker = j
            j += 2
        # a list: NAME at V1, V2 and V3
        lst = self.values_list(j)
        if lst:
            vals, end = lst
            o['sweeps'].append({'name': name, 'values': vals, 'side': side, 'block': block})
            self.take(*range(i, end))
            return end
        v = self.value_after(j, allow_word=marker is not None, pkg=squash(name) == 'pkg_name')
        if v is None:
            self.take(*range(i, b))
            o['sets'].append({'name': name, 'value': None, 'unit': None, 'block': block, 'side': side, 'op': 'set'})
            return b
        text, unit, end = v
        bq, end2 = self._block_qual(end)
        if bq is not None:
            block = bq
        o['sets'].append({'name': name, 'value': text, 'unit': unit, 'block': block, 'side': side,
                          'op': 'part' if part else ('element' if element else 'set'), 'part': part})
        self.take(*range(i, end2))
        return end2

    def _range(self, i, name, j, side):
        """NAME from A [up] to B [in N steps | in N points | in steps of S | by S | in S UNIT steps]."""
        if not self.is_value(j + 1):
            return j
        k = j + 2
        if self.word(k) == 'up':
            k += 1
        if self.word(k) != 'to' or not self.is_value(k + 1):
            return j
        start, end_t = self.toks[j + 1], self.toks[k + 1]
        sw = {'name': name, 'start': start['text'], 'end': end_t['text'], 'unit': start['unit'] or end_t['unit'],
              'count': None, 'step': None, 'side': side, 'how': None}
        k += 2
        if self.word(k) == 'in' and self.word(k + 1) in ('steps', 'step') and self.word(k + 2) == 'of' and self.is_value(k + 3):
            sw.update(step=self.toks[k + 3]['text'], how='step', unit=sw['unit'] or self.toks[k + 3]['unit'])
            k += 4
        elif self.word(k) == 'by' and self.is_value(k + 1):
            sw.update(step=self.toks[k + 1]['text'], how='step', unit=sw['unit'] or self.toks[k + 1]['unit'])
            k += 2
        elif self.word(k) == 'in' and self.is_value(k + 1) and self.word(k + 2) in ('steps', 'step', 'points', 'point'):
            t = self.toks[k + 1]
            if t['unit']:
                sw.update(step=t['text'], how='step', unit=t['unit'])
            else:
                sw.update(count=t['text'], how='points' if self.word(k + 2).startswith('point') else 'steps')
            k += 3
        self.out['sweeps'].append(sw)
        self.take(*range(i, k))
        return k

    def _sweep(self, i):
        """sweep [the] [TX|RX] NAME from ...; sweep NAME [and NAME]; sweep packages."""
        k = i + 1
        if self.word(k) == 'the':
            k += 1
        side = None
        if self.word(k) in SIDES:
            side, k = SIDES[self.word(k)], k + 1
        if self.word(k) in ('package', 'packages'):
            self.out['sweeps'].append({'name': 'PKG_NAME', 'every': True, 'side': side})
            self.take(*range(i, k + 1))
            return k + 1
        nm = self.name_at(k)
        if not nm:
            return i
        if self.word(nm[2]) == 'from':
            end = self._range(i, nm[0], nm[2], side)
            if end > nm[2]:
                return end
        self.out['sweeps'].append({'name': nm[0], 'every': True, 'side': side})
        end = nm[2]
        self.take(*range(i, end))
        while self.word(end) == 'and' and self.name_at(end + 1):
            nm = self.name_at(end + 1)
            self.out['sweeps'].append({'name': nm[0], 'every': True, 'side': side})
            self.take(*range(end, nm[2]))
            end = nm[2]
        return end

    def _package(self, i):
        """package X; package to X; TX package A and RX package B; packages A and B; every package;
        the X package (X words before it)."""
        o = self.out
        w = self.word(i)
        if w in SIDES:
            side_vals = {}
            k = i
            while self.word(k) in SIDES and self.word(k + 1) == 'package' and self.kind(k + 2) in ('block', 'unknown') \
                    and self.toks[k + 2]['kind'] == 'word':
                side_vals[SIDES[self.word(k)]] = self.toks[k + 2]['text']
                self.take(k, k + 1, k + 2)
                k += 3
                if self.word(k) == 'and' and self.word(k + 1) in SIDES:
                    self.take(k)
                    k += 1
            if side_vals:
                o['packages'].append({'tx': side_vals.get('TX'), 'rx': side_vals.get('RX')})
                return k
            return i
        if w == 'packages':
            vals, k = [], i + 1
            while self.kind(k) == 'block':
                vals.append(self.marks[k][1])
                k += 1
                if self.word(k) == 'and' and self.kind(k + 1) == 'block':
                    k += 1
            if vals:
                o['sweeps'].append({'name': 'PKG_NAME', 'values': vals})
                self.take(*range(i, k))
                return k
            if self.word(i - 1) in ('all', 'every'):
                o['sweeps'].append({'name': 'PKG_NAME', 'every': True})
                self.take(i - 1, i)
                return i + 1
            return i
        k = i + 1
        if self.word(i - 1) == 'every':
            o['sweeps'].append({'name': 'PKG_NAME', 'every': True})
            self.take(i - 1, i)
            return i + 1
        if self.word(k) == 'to' or self.kind(k) == 'eq':
            k += 1
        t = self.toks[k] if k < self.n else None
        if t is not None and t['kind'] == 'word' and self.kind(k) in ('block', 'unknown') and t['low'] not in OPTION_WORDS:
            nxt = k + 1
            if self.is_value(nxt) or self.kind(nxt) == 'eq' or self.word(nxt) in ('to', 'at'):
                return i                                                # "package case 7": a name attempt
            o['packages'].append({'both': t['text']})
            self.take(*range(i, k + 1))
            return k + 1
        # "the class B package": the words before it name the block
        words, j = [], i - 1
        while j >= 0 and self.kind(j) == 'unknown' and not self.used[j] and len(words) < 3:
            words.insert(0, self.toks[j]['text'])
            j -= 1
        if words and (self.kind(k) is None or self.kind(k) in ('sep', 'word')) and not self.is_value(k):
            o['packages'].append({'both': ' '.join(words)})
            self.take(*range(j + 1, i + 1))
            return i + 1
        return i

    def _attempts(self):
        """Runs of words that are not known, next to a value or a value marker, are names as typed."""
        o = self.out
        i = 0
        while i < self.n:
            starts = self.kind(i) == 'unknown' and self.toks[i]['kind'] == 'word' or (
                self.toks[i]['low'] == 'package' and self.kind(i + 1) == 'unknown')
            if self.used[i] or not starts:
                i += 1
                continue
            j = i + 1
            while j < self.n and not self.used[j] and (self.kind(j) == 'unknown' and self.toks[j]['kind'] == 'word'
                                                        or self.toks[j]['low'] == 'package'):
                j += 1
            words = [self.toks[k]['text'] for k in range(i, j)]
            k = j
            marker = False
            if self.kind(k) == 'eq' or self.word(k) in ('to', 'at'):
                marker = True
                k += 1
            if self.is_value(k):
                o['attempts'].append({'text': ' '.join(words), 'words': words, 'value': self.toks[k]['text'],
                                      'unit': self.toks[k]['unit']})
                self.take(*range(i, k + 1))
                i = k + 1
                continue
            if marker and k < self.n and self.toks[k]['kind'] == 'word' and self.kind(k) in ('unknown', 'block'):
                o['attempts'].append({'text': ' '.join(words), 'words': words, 'value': self.toks[k]['text'], 'unit': None})
                self.take(*range(i, k + 1))
                i = k + 1
                continue
            o['attempts'].append({'text': ' '.join(words), 'words': words, 'value': None, 'unit': None, 'loose': True})
            i = j

    def _pattern(self):
        o = self.out
        parts = []
        if o['actions']:
            parts.append('+'.join(o['actions']))
        parts += ['set %s' % (s['name']) for s in o['sets']]
        parts += ['sweep %s' % s['name'] for s in o['sweeps']]
        parts += ['package' for _ in o['packages']]
        parts += ['file' for _ in o['files']]
        parts += ['crosstalk' for f in o['flags'] if f == 'crosstalk']
        parts += ['selection' for f in o['flags'] if f == 'selection']
        parts += ['ask %s' % a['text'] for a in o['attempts']]
        return '; '.join(parts) or 'nothing matched'


def _ext(path):
    low = path.lower()
    if CHANNEL_EXT.search(low):
        return 'channel'
    for e in CONFIG_EXT:
        if low.endswith(e):
            return e
    return ''


def read(phrase, names=(), blocks=()):
    """Read one phrase against the names the config in front of the tool knows (see the module text)."""
    return _Reader(phrase, list(names), list(blocks)).read()

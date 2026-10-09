"""Feedback export (Decision 10): the command history as a plain-text file the user reads and emails.

Nothing here sends anything, and nothing here touches the network. The address is core.FEEDBACK_ADDRESS.

The file holds the tool version, counts by outcome and by pattern, every question with its options and the
answer chosen, the rephrase pairs, the words that could not be placed with their counts, the limits that differ
from the defaults, and every phrase. It holds no results, no config values beyond what was typed, and no channel
data. Its first lines say which masks were applied:

    mask_names = on     every path and file name reads <fileN> with its extension kept (<file1>.s4p), every
                        package block name <blockN>, and every other name that is not a COM keyword <nameN>
                        (a word written like an identifier: with an underscore, a digit or a capital inside it).
                        COM keywords, their legal values, the words the parser knows, and the words that could
                        not be placed are kept: those are the point of the export (row FB05)
    mask_numbers = on   every number reads <num>; units are kept (row FB16)

The same text masked the same way gets the same placeholder throughout the file.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import collections
import datetime
import json
import os
import re

from sicopr_assist import engine, parse, validate
from sicopr_assist.project import LOG_KINDS, VIEW_KINDS, read_settings, setting_defaults, setting_text

_NUM_IN = re.compile(r'(?<![\w.<])[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?(?![\w>])')
_EXT = re.compile(r'(\.s\d+p|\.xlsx|\.xls|\.csv|\.json|\.mat|\.txt|\.zip)$', re.I)
_IDENTIFIER = re.compile(r'_|\d|[a-z][A-Z]|^[A-Z]{2,}[a-z]')
# any path, with or without an extension the parser knows (a traceback names .py files and folders)
_ANY_PATH = re.compile(r'(?:[A-Za-z]:)?[\\/]?(?:[\w.{}~$-]+[\\/])+[\w.{}~$-]*')
_SEP = re.compile(r'[\\/]')


def masks_text(values):
    """What the file's first lines say about masking, from the settings in force."""
    names, nums = values['mask_names'], values['mask_numbers']
    if names and nums:
        return 'names and numbers masked'
    if names:
        return 'names masked, numbers not masked'
    if nums:
        return 'numbers masked, names not masked'
    return 'nothing masked'


class Masker:
    """Masks phrases one at a time, with one placeholder per distinct path, block or name in the whole file."""

    def __init__(self, names=True, numbers=False, blocks=()):
        self.names = names
        self.numbers = numbers
        self.blocks = {b.lower() for b in blocks if b}
        self.seen = {'file': {}, 'block': {}, 'name': {}}
        kws = engine.keyword_names('main') + engine.keyword_names('package block')
        keep = set()
        for k in kws:
            keep.add(parse.squash(k))
            keep.update(w.lower() for w in re.split(r'[\s()]+', k) if w)
        for row in validate.schema_rows():
            for v in validate.legal_values(row) or []:
                keep.update(w.lower() for w in str(v).split())
        keep.update(w.lower() for w in parse.KNOWN_WORDS | set(parse.ACTION_WORDS) | parse.CONFIRM |
                    parse.OPTION_WORDS | set(parse.RANGE_PARTS))
        keep.update(u.lower() for u in validate.UNIT_FACTORS)
        self.keep = keep

    def _placeholder(self, kind, key):
        table = self.seen[kind]
        if key not in table:
            table[key] = '<%s%d>' % (kind, len(table) + 1)
        return table[key]

    def _file(self, text):
        m = _EXT.search(text)
        ext = m.group(1) if m else ''
        return self._placeholder('file', text.replace('\\', '/').lower()) + ext

    def _numbers(self, text):
        return _NUM_IN.sub('<num>', text) if self.numbers else text

    def _word(self, w, unplaced):
        low = w.lower()
        if not self.names:
            return self._numbers(w) if _NUM_IN.fullmatch(w) else w
        if low in self.blocks:
            return self._placeholder('block', low)
        if _EXT.search(w):
            return self._file(w)
        if low in unplaced or low in self.keep or parse.squash(w) in self.keep:
            return w
        if _NUM_IN.fullmatch(w):
            return self._numbers(w)
        if _IDENTIFIER.search(w):
            return self._placeholder('name', low)
        return w

    def mask_record(self, value):
        """A GUI record's detail (GUI_DESIGN.md section 7a) as one line, masked as a phrase is; every path in it,
        whatever its extension, reads as a file."""
        def flat(v):
            if isinstance(v, dict):
                return '; '.join('%s: %s' % (k, flat(x)) for k, x in v.items() if x not in (None, [], {}, ''))
            if isinstance(v, (list, tuple)):
                return '[%s]' % ', '.join(flat(x) for x in v)
            return str(v)
        text = ' '.join(flat(value).split())
        if self.names:
            text = _ANY_PATH.sub(lambda m: self._file(m.group(0)) if _SEP.search(m.group(0)) else m.group(0), text)
        return self.mask(text)

    def mask(self, text, unplaced=()):
        """The text with the masks in force applied. unplaced: words of this phrase that could not be placed."""
        if text is None:
            return ''
        text = str(text)
        unplaced = {u.lower() for u in unplaced}
        out, pos = [], 0
        for m in parse._TOKEN.finditer(text):
            out.append(text[pos:m.start()])
            pos = m.end()
            tok, kind = m.group(0), m.lastgroup
            if kind == 'path':
                out.append(self._file(tok) if self.names else tok)
            elif kind == 'num':
                out.append(self._numbers(tok))
            elif kind in ('bracket', 'paren'):
                out.append(tok[0] + self.mask(tok[1:-1], unplaced) + tok[-1])
            elif kind == 'word':
                out.append(self._word(tok, unplaced))
            else:
                out.append(tok)
        out.append(text[pos:])
        return ''.join(out)


def _blocks_of(project, history):
    """Package block names known in this project: those of the working configs on disk, and those a phrase named."""
    out = set()
    d = project.configs_dir
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith('.json'):
                try:
                    with open(os.path.join(d, n), encoding='utf-8') as f:
                        out.update(json.load(f).get('packages') or {})
                except (OSError, ValueError, AttributeError):
                    pass
    names = engine.keyword_names('main') + engine.keyword_names('package block')
    for rec in history:
        req = parse.read(rec.get('phrase') or '', names, [])
        for p in req['packages']:
            for k, v in p.items():
                if k != 'attempt' and isinstance(v, str):
                    out.add(v)
        for s in req['sets'] + req['sweeps']:
            b = s.get('block')
            b = b.get('attempt') if isinstance(b, dict) else b      # a block the config does not hold is an attempt
            if isinstance(b, str) and b:
                out.add(b)
            if s.get('name', '').strip().lower() == 'pkg_name' and s.get('value'):
                out.update(str(s['value']).strip('[] ').split())
    return out


def _unplaced(rec, names):
    """The words of a phrase kept as typed under mask_names: the words that could not be placed, as recorded and as
    the parser reads the phrase now, and the words of a name that is not a COM keyword (zp in Re-run with zp
    select 2, row FB05)."""
    req = parse.read(rec.get('phrase') or '', names, [])
    words = list(rec.get('unplaced') or []) + list(req['unplaced'])
    for at in req['attempts']:
        words += at.get('words') or []
    return list(dict.fromkeys(words))


def _option(text):
    """An option without the remark after it, which can hold config values: f_b (now 106.25) reads f_b, and
    run the change that was understood (DER_0: 2e-4 -> 1e-4) reads run the change that was understood. A COM
    keyword whose name holds parentheses (z_p (TX), c(-1)) is kept whole."""
    t = str(text).strip()
    names = {parse.squash(n) for n in engine.keyword_names('main') + engine.keyword_names('package block')}
    while parse.squash(t) not in names:
        m = re.match(r'^(.*\S)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)$', t)
        if not m:
            break
        t = m.group(1)
    return t


def _missed_words(rec):
    """The words a command could not place, for the count: those recorded for a command that did not become a
    PLAN, and the words of the names it asked about (its pattern says ask <name>)."""
    if rec.get('outcome') == 'PLAN':
        return []
    words = list(rec.get('unplaced') or [])
    for part in (rec.get('pattern') or '').split(';'):
        part = part.strip()
        if part.startswith('ask '):
            words += part[4:].split()
    return list(dict.fromkeys(words))


def export_lines(project, day=None):
    """The feedback file of this project, as lines. Reads the history and the settings; writes nothing."""
    from sicopr_assist import __version__, core
    every = project.read_history(log=True)          # the GUI's log records too (GUI_DESIGN.md section 7a)
    history = [r for r in every if r.get('kind') not in LOG_KINDS]
    st = read_settings(project)
    values = st['values']
    names = engine.keyword_names('main') + engine.keyword_names('package block')
    m = Masker(values['mask_names'], values['mask_numbers'], _blocks_of(project, history) if values['mask_names'] else ())
    for r in history:                            # placeholders are numbered in the order the commands name things
        m.mask(r.get('phrase'), _unplaced(r, names))
    day = day or datetime.date.today().isoformat()
    c = core.feedback_contact()
    lines = ['SiCoPR-Assist feedback file',
             'masks: %s' % masks_text(values),
             'mask_names = %s, mask_numbers = %s (settings); placeholders: <fileN> for a path or file name, <blockN> '
             'for a package block, <nameN> for another name that is not a COM keyword, <num> for a number'
             % (setting_text(values['mask_names']), setting_text(values['mask_numbers'])),
             'written %s by SiCoPR-Assist %s from %d commands; read it before you send it' % (day, __version__,
                                                                                            len(history)),
             'to send it, email it yourself to %s with the subject %s; SiCoPR-Assist sends nothing'
             % (c['address'], c['subject']),
             '']
    by_outcome = collections.Counter(r.get('outcome') for r in history)
    by_status = collections.Counter(r.get('status') for r in history)
    lines.append('outcomes: %s' % ', '.join('%s %d' % (k, by_outcome[k]) for k in ('PLAN', 'QUESTION', 'STOP')))
    lines.append('status: %s' % ', '.join('%s %d' % (k, n) for k, n in sorted(by_status.items(), key=lambda x: str(x[0]))))
    lines += ['', 'patterns (count, pattern):']
    def pattern(r):                              # an answer's pattern names the option: without its remark
        p = re.sub(r'^answer: ([^;]*)', lambda x: 'answer: ' + _option(x.group(1)), r.get('pattern') or '')
        return m.mask(p, _unplaced(r, names))
    for pat, n in collections.Counter(pattern(r) for r in history).most_common():
        lines.append('  %d  %s' % (n, pat))
    answers = {r.get('answers'): r for r in history if r.get('answers') is not None}
    qs = [r for r in history if r.get('outcome') == 'QUESTION']
    lines += ['', 'questions (%d): the phrase, the options offered, the answer' % len(qs)]
    for q in qs:
        un = _unplaced(q, names)
        a = answers.get(q.get('seq'))
        chosen = (a or {}).get('chosen') or q.get('chosen') or ('cancelled' if q.get('status') == 'cancelled' or
                                                                 (a or {}).get('status') == 'cancelled' else 'no answer')
        lines.append('  %s: %s | options: %s | answer: %s' % (q.get('seq'), m.mask(q.get('phrase'), un),
                                                              '; '.join(m.mask(_option(o)) for o in q.get('options') or []),
                                                              m.mask(_option(chosen))))
    by_seq = {r.get('seq'): r for r in history}
    pairs = [r for r in history if r.get('rephrase_of') is not None]
    lines += ['', 'rephrase pairs (%d): a phrase that did not work, then the one that followed' % len(pairs)]
    for r in pairs:
        old = by_seq.get(r['rephrase_of']) or {}
        lines.append('  %s -> %s: %s  ->  %s' % (old.get('seq'), r.get('seq'), m.mask(old.get('phrase'), _unplaced(old, names)),
                                                m.mask(r.get('phrase'), _unplaced(r, names))))
    words = collections.Counter(w for r in history for w in _missed_words(r))
    lines += ['', 'words that could not be placed (count, word): %d' % len(words)]
    for w, n in words.most_common():                     # kept as typed, unless it is a path, a file or a block
        lines.append('  %d  %s' % (n, m.mask(w, [w])))
    defaults = setting_defaults()
    differ = ['%s = %s' % (k, setting_text(v)) for k, v in values.items() if v != defaults[k][0]]
    lines += ['', 'limits that differ from the defaults: %s' % (', '.join(differ) or 'none')]
    lines += ['', 'commands (%d): seq, outcome, status, phrase; config view marks an edit or a workbook opened in the '
              "GUI's Config view, which is not a typed command" % len(history)]
    for r in history:
        lines.append('  %s  %s  %s  %s%s' % (r.get('seq'), r.get('outcome'), r.get('status'),
                                             m.mask(r.get('phrase'), _unplaced(r, names)),
                                             '  (config view)' if r.get('kind') in VIEW_KINDS else ''))
    gui = [r for r in every if r.get('kind') in VIEW_KINDS + LOG_KINDS]
    lines += ['', 'GUI records (%d): seq, kind, what was recorded' % len(gui)]
    for r in gui:
        lines.append('  %s  %s  %s' % (r.get('seq'), r.get('kind'), m.mask_record(r.get('detail') or {})))
    return lines


def write(project, path, day=None):
    """Write the feedback file at path (inside the project's .sicopr folder) and return the path."""
    lines = export_lines(project, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return path

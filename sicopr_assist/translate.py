"""Translator mode (Decision 26, Phase V2-10): a layer of rules and interface presets in front of the strict core.

When the strict reading of a phrase misses (a word it cannot place, a name that is not a COM keyword, nothing matched),
this layer reads the phrase again with what the strict core does not know: the owner's rulings and the study's synonym
list (baud rate is f_b, DFE taps is N_b, SNDR is SNR_TX), filler and typos in command words, references to the
project's files (the 500mm thru, the original thru, the other package), number words, and the interface presets (KR,
CR, C2C and C2M in 802.3dj and 802.3ck). It never plans anything itself. It returns:

    candidates   phrases for the core, best first; the core reads each as typed input, validates and plans it, and the
                 first one it does not miss is the outcome
    outcome      a QUESTION or a STOP of the layer's own: a proposal where an amount or a choice is missing (about 10%
                 more Rx FFE taps, the CR host classes, the low-power receivers, the 802.3ck C2M run), or a
                 which-question for a word with several readings. Every option of a proposal is a phrase the core
                 resolves (answers)

with the rules that fired, the preset, the proposal and the lines to announce, so the history records them. It never
writes the run CSV, runs the engine or skips validation (version 1 prompt, section 1).

The miss gate (decision 26, item 5) is applied by the core and here: a reply to a pending question never reaches the
layer, nor does a request that is out of scope (email, slides, diagnose, convert, optimise) or a value the core refused
on a request it understood (an illegal value). Typo tolerance is for command words only, never for keyword names or
values: a name that is one letter from a keyword is asked about, as the strict core does.

Preset values come from data/presets.csv, each with its source and licence. Owner ruling, 21 October 2026: COM
parameter values from the IEEE 802.3 standards and drafts, the COM 3.70 workbooks and OIF-CEI-05.3 ship under the terms
of the COM configuration workbooks (NOTICE), so every preset works on a fresh install. A value a preset takes from the
standard is not asked about by rule Q14 (the plan carries a pass for that rule and those keywords only); the same value
typed by hand still is.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import hashlib
import math
import os
import re

from sicopr_assist import config_model, parse

NAME = 'rules and presets'
ENV = 'SICOPR_ASSIST_TRANSLATOR'            # on or off: overrides the setting translator (tests, a scripted session)
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
PRESETS = os.path.join(DATA, 'presets.csv')
TEMPLATES = os.path.join(DATA, 'templates')
CANCEL = 'cancel'
NONE_OF_THESE = 'none of these'

# the interfaces, their words and their clause in each standard: data/interfaces.csv (the names are data, not code:
# two of them are also values of PMD_type, which the code never names, gate G3.3)
INTERFACES = os.path.join(DATA, 'interfaces.csv')


def _interfaces():
    with open(INTERFACES, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


_IFACE_ROWS = _interfaces()
ROLE = {r['role']: r['interface'] for r in _IFACE_ROWS}
KR, CR, C2C, C2M = ROLE['kr'], ROLE['cr'], ROLE['c2c'], ROLE['c2m']
# what each standard means, and where its values come from
STANDARDS = {
    '802.3dj': {'f_b': 106.25, 'lane': '200G per lane', 'clause': {r['interface']: r['802.3dj'] for r in _IFACE_ROWS}},
    '802.3ck': {'f_b': 53.125, 'lane': '100G per lane', 'clause': {r['interface']: r['802.3ck'] for r in _IFACE_ROWS}},
}
SOURCES = {'802.3ck': 'IEEE Std 802.3ck-2022 and the IEEE COM 3.70 workbooks',
           'OIF': 'OIF-CEI-05.3 (the CEI-112G-XSR and CEI-112G-MR reference receivers)'}
HOSTS = ('HL', 'HN', 'HH')
CR_PAIRS = (('HL', 'HL'), ('HN', 'HN'), ('HL', 'HN'), ('HH', 'HL'))

# requests the layer never reads (the miss gate): what SiCoPR-Assist does not do
OUT_OF_SCOPE = re.compile(r"\b(?:e-?mail|mail|send|slides?|deck|powerpoint|diagnos\w*|why|convert\w*|optimi[sz]\w*|"
                          r"optimal|explain\w*)\b", re.I)


# ----------------------------------------------------------------------------- mode, data
def is_on(settings_values):
    """Whether translator mode is on: the environment override ENV when set, else the setting translator."""
    env = os.environ.get(ENV, '').strip().lower()
    if env in ('on', 'off'):
        return env == 'on'
    return bool(settings_values.get('translator', True))


def _sha(paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, 'rb') as f:
            h.update(f.read())
    return h.hexdigest()


def rules_sha256():
    """What the history records as the translator's model SHA-256: the rules (this module) and the preset file."""
    return _sha([os.path.abspath(__file__), PRESETS])


_PRESET_ROWS = None


def preset_rows():
    global _PRESET_ROWS
    if _PRESET_ROWS is None:
        with open(PRESETS, newline='', encoding='utf-8') as f:
            _PRESET_ROWS = list(csv.DictReader(f))
    return _PRESET_ROWS


def preset(name, when=''):
    """[(keyword, value)] of a preset, in the order of the preset file."""
    return [(r['keyword'], r['value']) for r in preset_rows() if r['preset'] == name and r['when'] in ('', when)]


def preset_cell(name, keyword):
    return next((r['value'] for r in preset_rows() if r['preset'] == name and r['keyword'] == keyword), None)


def q14_pass(values):
    """Owner ruling, 21 October 2026: a value a preset takes from the standard does not trigger rule Q14. The pass names
    the rule and each keyword of the preset (validate.py reads 'Q14:<keyword>'), so a value typed by hand is still
    asked about."""
    return {'allow': ['Q14:%s' % k for k, _ in values]}


# ----------------------------------------------------------------------------- the config in view
def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def standard_of(wc):
    """The standard of a config by its f_b, or None."""
    fb = _num(_get(wc, 'f_b')) if wc else None
    for std, d in STANDARDS.items():
        if fb is not None and abs(fb - d['f_b']) < 1e-6:
            return std
    return None


def _key(scope, name):
    want = parse.squash(name)
    return next((k for k in scope if parse.squash(k) == want), None)


def _get(wc, name):
    k = _key(wc['main'], name)
    return wc['main'][k] if k else None


def selected_blocks(wc):
    k = _key(wc['main'], 'PKG_NAME')
    return [b for b in str(wc['main'].get(k) or '').split() if b in wc['packages']] if k else []


def block_of_class(wc, cls):
    """The package block of class A or B in this config (by its name), or None."""
    tag = 'CLASS' + cls.upper()
    hits = [b for b in wc['packages'] if tag in b.upper()]
    return hits[0] if len(hits) == 1 else None


def class_in_view(wc):
    sel = selected_blocks(wc)
    if sel and 'CLASSB' in sel[0].upper():
        return 'B'
    return 'A'


def both_tests(wc):
    """z_p select for both package tests of the class in view (the shipped workbooks: cases 1, 2 class A; 3, 4 B)."""
    return preset_cell_when('802.3dj KR', 'z_p select', 'class ' + class_in_view(wc))


def preset_cell_when(name, keyword, when):
    return next((r['value'] for r in preset_rows() if r['preset'] == name and r['keyword'] == keyword
                 and r['when'] == when), None)


def preset_in_view(history):
    """The preset of the last command that fired one (its history record), or None."""
    for rec in reversed(history or []):
        t = rec.get('translation') or {}
        if t.get('preset') and rec.get('outcome') == 'PLAN' and rec.get('status') == 'ok':
            return t['preset']
        if rec.get('run_ids') and rec.get('status') == 'ok':
            return t.get('preset')
    return None


def interface_of(preset_name):
    for i in (C2C, C2M, KR, CR):
        if preset_name and i in preset_name.split():
            return i
    return None


# ----------------------------------------------------------------------------- words
STD_WORDS = (('802.3dj', re.compile(r'\b(?:802\.?3\s?dj|3dj|dj)\b|\b200\s?g(?:b/?s|bps)?\b(?:\s*(?:per|/)\s*lane)?', re.I)),
             ('802.3ck', re.compile(r'\b(?:802\.?3\s?ck|3ck|ck)\b|\b100\s?g(?:b/?s|bps)?\b(?:\s*(?:per|/)\s*lane)?', re.I)))
IFACE_WORDS = tuple((ROLE[k], re.compile(next(r['words'] for r in _IFACE_ROWS if r['role'] == k), re.I))
                    for k in ('c2c', 'c2m', 'cr', 'kr'))
SETUP_WORDS = re.compile(r'\bset\s?up\b|\bmake it\b|\bswitch\b|\bre-?run as\b|\brun (?:my channels|it|them) as\b|'
                         r'\bconfigure\b|\bconfig for\b|\bas (?:an? )?(?:802\.?3\s?(?:dj|ck) )?(?:kr|cr|c2c|c2m)\b|'
                         r'\bplease\s*$|\bplease\b|\bi need\b|\bgive me an?\b', re.I)
FETCH_WORDS = re.compile(r'\b(?:download|fetch|grab|get)\b.*\bchannels?\b|\bieee page\b', re.I)
RUN_WORDS = re.compile(r'\b(?:re-?run|run|go again|again)\b', re.I)


def standard_named(text):
    return next((s for s, rx in STD_WORDS if rx.search(text)), None)


def interface_named(text):
    return next((i for i, rx in IFACE_WORDS if rx.search(text)), None)


# filler and politeness around a known form (decision 26, item 3: command words only)
FILLER = (
    (r'^\s*(?:hey|hi|ok|okay)[,!]?\s+', ''),
    (r"^\s*(?:can|could|would) you(?: please)?\s+", ''),
    (r'^\s*please\s+', ''),
    (r'\s*[,.]?\s*\b(?:please|pls|plz|thanks|thank you|thx|pronto|asap)\b[.!]?', ''),
    (r'\bjust\s+', ''),
    (r'\bso (?:that )?i can see\b.*$', ''),
    (r'[?.!]\s*(?:i )?want(?:ed)? to (?:check|see|make sure)\b.*$', ''),
    (r'\buse the runs i (?:already )?have\b\.?', ''),
    (r"\bfrom the runs i (?:already )?have\b", ''),
    (r'\bin the existing runs\b', ''),
    (r'\bmy setup\b', 'the setup'),
)
# mistyped command words, read as the word (never a keyword name or a value)
COMMAND_TYPOS = (
    (r'\bre-?reun\b', 're-run'), (r'\bre-?rn\b', 're-run'), (r'\brn\b', 'run'), (r'\bagian\b', 'again'),
    (r'\bre run\b', 're-run'), (r'\brerun\b', 're-run'), (r'\bru-?run\b', 're-run'),
)
NUMBER_WORDS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
                'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
                'sixteen': 16, 'twenty': 20}
_NW = '|'.join(sorted(NUMBER_WORDS, key=len, reverse=True))


def _number_words(text, fired):
    """'one e minus four' -> 1e-4; a number word right after to, at or = and before taps -> digits."""
    def sci(m):
        a = NUMBER_WORDS[m.group(1).lower()]
        e = m.group(3)
        e = NUMBER_WORDS[e.lower()] if e.lower() in NUMBER_WORDS else int(e)
        return '%de%s%d' % (a, '-' if (m.group(2) or '').lower() in ('minus', 'negative') else '', e)
    new = re.sub(r'\b(%s)\s+e\s+(?:(minus|negative|plus)\s+)?(%s|\d+)\b' % (_NW, _NW), sci, text, flags=re.I)
    new = re.sub(r'(\b(?:to|at)\s+|=\s*)(%s)\b(?!\s+e\b)' % _NW,
                 lambda m: m.group(1) + str(NUMBER_WORDS[m.group(2).lower()]), new, flags=re.I)
    new = re.sub(r'\b(%s)(?=[\s-]+(?:dfe\s+)?taps?\b)' % _NW, lambda m: str(NUMBER_WORDS[m.group(1).lower()]), new,
                 flags=re.I)
    if new != text:
        fired.append('number words')
    return new


def clean(phrase, fired):
    """The phrase with filler and politeness dropped, command-word typos read as the word, and number words as
    numbers. Keyword names and values are left exactly as typed."""
    t = phrase.strip()
    for rx, rep in FILLER:
        new = re.sub(rx, rep, t, flags=re.I)
        if new != t:
            if 'filler' not in fired:
                fired.append('filler')
            t = new
    for rx, rep in COMMAND_TYPOS:
        new = re.sub(rx, rep, t, flags=re.I)
        if new != t:
            if rx not in (r'\brerun\b', r'\bre run\b'):
                if 'command-word typo' not in fired:
                    fired.append('command-word typo')
            elif 'filler' not in fired:
                fired.append('filler')
            t = new
    t = _number_words(t, fired)
    t = re.sub(r'\s{2,}', ' ', t).strip(' ,')
    return t


# ----------------------------------------------------------------------------- the result
def result(fired, candidates=(), outcome=None, answers=None, announce=(), preset_name=None, proposal=None, mods=None,
           override_plan=False):
    return {'fired': list(fired), 'candidates': [c for c in candidates if c], 'outcome': outcome,
            'answers': dict(answers or {}), 'announce': list(announce), 'preset': preset_name, 'proposal': proposal,
            'mods': dict(mods or {}), 'override_plan': override_plan}


def question(text, options, answers, fired, announce=(), preset_name=None, proposal=None):
    """A QUESTION of the layer: options and what choosing each does ({'phrase': ...}, {'stop': ...} or None)."""
    out = {'type': 'QUESTION', 'question': {'text': text, 'options': list(options)}}
    return result(fired, outcome=out, answers=answers, announce=announce, preset_name=preset_name, proposal=proposal)


def _and(items):
    return ' and '.join('%s = %s' % (k, v) for k, v in items)


class View:
    """What the layer reads from the project: the working config in view, the history, the last run's channels.
    Built by the core from its Context."""

    def __init__(self, wc, history, last, channels, root, folder_wc=None, folder_config=None, selection=None,
                 project=None):
        self.wc = wc                       # the working config of the last run, or None
        self.history = history or []
        self.last = last                   # the last history record that names a working config
        self.channels = channels or []     # [(path, role)] of the last run, in order
        self.root = root
        self.folder_wc = folder_wc         # the one config in the folder, imported, when there is no run yet
        self.folder_config = folder_config
        self.selection = selection
        self.project = project

    @property
    def config(self):
        return self.wc or self.folder_wc

    def has_run(self):
        return self.last is not None and self.wc is not None


# ----------------------------------------------------------------------------- the entry point
def translate(phrase, view, strict):
    """The layer's reading of a phrase the strict core missed (see the module text), or None when no rule applies.
    strict is the strict core's outcome."""
    if OUT_OF_SCOPE.search(phrase):
        return None
    fired = []
    text = clean(phrase, fired)
    for rule in (_original_thru,):                     # references the strict core reads as something else
        got = rule(text, view, list(fired))
        if got is not None:
            return got
    if strict.get('type') == 'PLAN':
        return None
    if _validation_outcome(strict):
        return None
    for rule in (_download, _folder_words, _com_versions, _package_grid, _show_words, _named_files, _presets,
                 _rx_ffe_more, _rx_ffe_off, _low_power, _xsr, _impedance, _ambiguous_name, _help, _results, _dashboard,
                 _selection, _crosstalk_words, _thru_reference, _swap_words, _sweep_list, _look_alike):
        got = rule(text, view, list(fired))
        if got is not None:
            return got
    syn = list(fired)
    rewritten = synonyms(text, view, syn)
    cands = []
    if _norm(rewritten) != _norm(phrase):
        cands.append(rewritten)
    re_comp = recompose(rewritten, view)
    if re_comp and _norm(re_comp) != _norm(phrase) and re_comp not in cands:
        cands.append(re_comp)
    if not cands:
        return None
    if re_comp and 'recomposed' not in syn:
        syn.append('recomposed')
    return result(syn, candidates=cands, announce=_synonym_lines(syn, rewritten, view))


def _norm(text):
    return re.sub(r'[\s.!?]+', ' ', str(text)).strip().lower()


# the words a request to run two named files may hold around them: a description of the files, never a request
DESCRIBE_WORDS = {'can', 'could', 'would', 'you', 'please', 'run', 'my', 'the', 'a', 'channel', 'thru', 'through', 'com',
                  'with', 'using', 'on', 'in', 'at', 'from', 'config', 'workbook', 'file', 'kr', 'cr', 'c2c', 'c2m',
                  'thanks', 'thank', 'against', 'and', 'it', 'this', 'that', 'sicopr', 'of', 'me', 'for'}


def _named_files(text, view, fired):
    """A request to run one named channel file with one named config file, in other words (filler, a description of
    the files): the core's own form, Run COM on <channel> with <config>. A description such as "the KR config" names
    the workbook and does not ask for the KR preset (row SY02)."""
    low = text.lower()
    if '=' in low or not re.search(r'\brun\b', low):
        return None
    toks = parse.tokenize(text)
    files = [t['text'] for t in toks if t['kind'] == 'path' or (t['kind'] == 'word' and (
        t['low'].endswith(parse.CONFIG_EXT) or parse.CHANNEL_EXT.search(t['low'])))]
    chans = [f for f in files if parse.CHANNEL_EXT.search(f)]
    cfgs = [f for f in files if f.lower().endswith(parse.CONFIG_EXT)]
    if len(chans) != 1 or len(cfgs) != 1 or len(files) != 2:
        return None
    rest = text
    for f in files:
        rest = rest.replace(f, ' ')
    left = set(re.findall(r"[a-z][a-z0-9'-]*", rest.lower())) - DESCRIBE_WORDS
    if left:
        return None                  # a word that asks for more than the two files (crosstalk, a change): the core reads it
    return result(fired + ['filler: the files named, run as named'], candidates=['Run COM on %s with %s.' % (chans[0],
                                                                                                         cfgs[0])],
                  announce=['the words around the two files describe them; the workbook is run as it is'])


def _download(text, view, fired):
    """Interface and standard words in a channel download (rows SY36 to SY38): the standard is the tools page's
    (802.3dj), and an interface named is the answer to the core's interface question, so it is passed as such."""
    low = text.lower()
    if not FETCH_WORDS.search(low):
        return None
    iface = interface_named(low)
    std = standard_named(low)
    if std == '802.3ck':
        return None                              # the tools page the core reads is 802.3dj's
    t = text
    for _, rx in STD_WORDS:
        t = rx.sub('802.3dj', t, count=1) if std else t
    if iface:
        t = dict(IFACE_WORDS)[iface].sub(' ', t)
    t = re.sub(r'\bget\b', 'download', t, flags=re.I)
    t = re.sub(r'\bthem all\b', 'them', t, flags=re.I)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    if _norm(t) == _norm(text) and not iface:
        return None
    ann = []
    if iface:
        ann.append('the interface %s was named in the request' % iface)
    if iface == C2M:
        ann.append('COM is not the C2M specification (176D.7.2): the results are informative margin')
    fired = fired + ['download: %s' % ' '.join(x for x in (std or '802.3dj', iface) if x)]
    return result(fired, candidates=[t], announce=ann, mods={'interface': iface} if iface else None)


def _folder_words(text, view, fired):
    """Every config of the folder across every channel file of it (blind row B151): the core's batch over configs and
    THRUs, thru-only and with crosstalk as the phrase asks, its results together in one file."""
    low = text.lower()
    if not (re.search(r'\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?configs?\b', low) and
            re.search(r'\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?(?:channel\s+files?|channels?|thrus?|thru\s+files?)\b',
                      low)):
        return None
    xt = bool(re.search(r'\b(?:xtalk|crosstalk|fext|next)\b', low))
    only = bool(re.search(r'\bthru[\s-]*only\b', low))
    modes = 'thru-only and with crosstalk' if (xt and only) or not (xt or only) else \
        ('with crosstalk' if xt else 'thru-only')
    return result(fired + ['synonym: every config across every channel file is the batch over configs and THRUs'],
                  candidates=['Run every config on every THRU, %s, into one results file.' % modes])


def _com_versions(text, view, fired):
    """A run for each COM release SiCoPR ships (row B150 of the blind set): the core's sweep of COM Version."""
    low = text.lower()
    if not re.search(r'\b(?:different|each|every|all|several|other)\s+com\s+(?:versions?|releases?)\b|'
                     r'\bcom\s+(?:versions?|releases?)\s*\(?\s*(?:i\.?e\.?|e\.?g\.?|like)?\s*\d+p\d+p\d+', low):
        return None
    if not view.has_run():
        return None
    return result(fired + ['synonym: different COM versions is a sweep of COM Version'],
                  candidates=['Sweep COM Version.'],
                  announce=['one run per COM release SiCoPR supports, on the last config and channels; a release already '
                            'run is reused'])


def _package_grid(text, view, fired):
    """Every combination of the package variables (row B165): the class A and class B blocks by every package case
    of z_p select, as one batch; the batch summary says whether every point passes."""
    low = text.lower()
    if not re.search(r'\b(?:every|all)\s+(?:the\s+)?combinations?\s+of\s+(?:the\s+)?package\s+(?:variables|settings|'
                     r'options|parameters)\b|\bfull\s+package\s+grid\b', low):
        return None
    wc = view.config
    if wc is None or not view.has_run():
        return None
    a, b = block_of_class(wc, 'A'), block_of_class(wc, 'B')
    if not a or not b:
        return None
    sel = selected_blocks(wc)
    zp = wc['packages'][sel[0] if sel else a].get(_key(wc['packages'][sel[0] if sel else a], 'z_p (TX)') or '')
    try:
        n = len(str(zp).strip(' []').split(';')[0].split())
    except AttributeError:
        n = 0
    if n < 1:
        return None
    cases = [str(i) for i in range(1, n + 1)]
    case_text = cases[0] if n == 1 else '%s and %s' % (', '.join(cases[:-1]), cases[-1])
    phrase = 'Run packages %s and %s and z_p select at %s.' % (a, b, case_text)
    return result(fired + ['synonym: every combination of package variables is the class blocks by the package cases'],
                  candidates=[phrase],
                  announce=['the package variables are PKG_NAME (the class A block %s and the class B block %s; '
                            'PKG_Module and PKG_Null are not backplane packages) and z_p select (the %d package cases): '
                            '%d points; the system passes when COM passes at every point' % (a, b, n, 2 * n)])


def _show_words(text, view, fired):
    """Show words the strict core does not read: the Tx FFE taps (the c keywords), the package parameters of a block
    (package B)."""
    low = text.lower()
    wc = view.config
    if wc is None:
        return None
    if re.search(r'\b(?:tx|transmitter)\s+ffe(?:\s+taps?)?\b', low) and re.search(r'^(?:what|show|list)', low):
        names = [k for k in wc['main'] if re.fullmatch(r'c\(-?\d+\)', k)]
        names.sort(key=lambda k: int(re.search(r'-?\d+', k).group(0)))
        if names:
            return result(fired + ['synonym: the Tx FFE taps are the c keywords'],
                          candidates=['Show %s.' % ', '.join(names)])
    m = re.search(r'\bpackage\s+(?:params|parameters|settings|keywords)\s+(?:for|of|in)\s+(?:package\s+|pkg\s+)?(\w+)|'
                  r"\b(?:what's|what\s+is)\s+in\s+(?:package|pkg)\s+(\w+)|\bshow\s+(?:me\s+)?(?:package|pkg)\s+(\w+)'?s?\s+"
                  r'(?:settings|parameters|params)', low)
    if m and re.search(r'^(?:what|show|list)', low):
        word = next(g for g in m.groups() if g)
        blk = block_of_class(wc, word) if len(word) == 1 else next((b for b in wc['packages'] if b.lower() == word), None)
        if blk:
            return result(fired + ['synonym: package %s is the block %s' % (word.upper(), blk)],
                          candidates=['Show the package block %s.' % blk])
    return None


def _validation_outcome(o):
    """A STOP the strict core gave on a request it understood: a value refused (the miss gate). An illegal value is
    never reinterpreted (row MG03)."""
    return o.get('type') == 'STOP' and bool(o.get('changes')) and not o.get('unplaced') and \
        'ask ' not in (o.get('pattern') or '')


# ----------------------------------------------------------------------------- synonyms (the owner's rulings and the study's list)
VERB_SET = r'(?:raise|lower|increase|decrease|bump|bring|move|change|set|put|make)'
SYNONYMS = (
    # (rule name, pattern, replacement); applied in order, each once over the phrase
    ('synonym: baud rate is f_b', r'\b(?:the\s+)?(?:baud|symbol|signal(?:l)?ing)\s+rate\b', 'f_b'),
    ('synonym: GBd is f_b', r'\bat\s+(\d+(?:\.\d+)?)\s*gbd\b', r'with f_b = \1'),
    ('synonym: pass threshold is COM Pass threshold', r'(?<!com )(?<!erl )(?<!vec )\b(?:the\s+)?pass\s+threshold\b',
     'COM Pass threshold'),
    ('synonym: SNDR is SNR_TX', r'\b(?:the\s+)?(?:tx\s+)?sndr\b', 'SNR_TX'),
    ('synonym: DFE taps is N_b', r'\b(?:a\s+)?(\d+)[\s-]+tap\s+dfe\b', r'N_b = \1'),
    ('synonym: DFE taps is N_b', r'\b(\d+)\s+(?:dfe\s+taps?|taps?\s+of\s+dfe)\b', r'N_b = \1'),
    ('synonym: DFE taps is N_b', r'\b(?:the\s+)?(?:number\s+of\s+)?dfe\s+taps?\b', 'N_b'),
    ('synonym: Rx FFE pre taps is ffe_pre_tap_len',
     r'\b(\d+)\s+(?:(?:rx|receiver)\s+ffe\s+)?pre[\s-]*(?:cursor\s+)?taps?\b', r'ffe_pre_tap_len = \1'),
    ('synonym: Rx FFE post taps is ffe_post_tap_len',
     r'\b(\d+)\s+(?:(?:rx|receiver)\s+ffe\s+)?post[\s-]*(?:cursor\s+)?taps?\b', r'ffe_post_tap_len = \1'),
    ('synonym: Rx FFE pre taps is ffe_pre_tap_len', r'\b(?:(?:the\s+)?(?:rx|receiver)\s+ffe\s+)pre[\s-]*(?:cursor\s+)?taps?\b',
     'ffe_pre_tap_len'),
    ('synonym: Rx FFE post taps is ffe_post_tap_len',
     r'(?<=ffe_pre_tap_len)(.*?)\bpost[\s-]*(?:cursor\s+)?taps?\b', r'\1ffe_post_tap_len'),
    ('synonym: full grid is Local Search = 0',
     r'\b(?:turn|switch)\s+(?:the\s+)?local\s+search\s+off\b(?:\s*\(full grid\))?|\b(?:turn|switch)\s+off\s+(?:the\s+)?'
     r'local\s+search\b(?:\s*\(full grid\))?|\b(?:with\s+)?a\s+full[\s-]+grid(?:\s+search)?\b|\bno\s+local\s+search\b',
     'with Local Search = 0'),
    ('synonym: on is 1, off is 0', r'\b(ERL|MLSE|Include PCB|FORCE_TR|EW|Local Search)\s+(?:turned\s+)?(on|enabled)\b',
     r'\1 = 1'),
    ('synonym: on is 1, off is 0', r'\b(ERL|MLSE|Include PCB|FORCE_TR|EW)\s+(?:turned\s+)?(off|disabled)\b', r'\1 = 0'),
    ('synonym: on is 1, off is 0', r'\bturn\s+(ERL|Include PCB|FORCE_TR|EW)\s+on\b', r'\1 = 1'),
    ('synonym: switch to is use', r'\bswitch\s+(?:over\s+)?to\b', 'use'),
    ('synonym: bump is set',r'\b%s\s+(?=[A-Za-z_][\w() .-]*?\s+(?:to|down to|up to)\s+[-+.\d])' % VERB_SET, 'set '),
    ('synonym: sweep over is at', r'\b(?:sweep|try|run)\s+([A-Za-z_][\w()]*)\s+(?:over|across)\s+', r'Run \1 at '),
)
SYNONYM_LINES = {
    'synonym: full grid is Local Search = 0': 'Local Search = 0 is a full grid: it searches every Tx FFE, CTLE and '
                                               'sampling point, so it takes far longer than the last run',
}


def synonyms(text, view, fired):
    t = text
    for name, rx, rep in SYNONYMS:
        new = re.sub(rx, rep, t, flags=re.I)
        if new != t:
            if name not in fired:
                fired.append(name)
            t = new
    t = _package_words(t, view, fired)
    t = _halve(t, view, fired)
    t = re.sub(r'\bdown to\b|\bup to\b', 'to', t)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    return t


def _synonym_lines(fired, text, view):
    lines = ['translator: %s' % '; '.join(fired)] if fired else []
    lines += [SYNONYM_LINES[f] for f in fired if f in SYNONYM_LINES]
    if any(f.startswith('package:') for f in fired):
        lines.append('RUNTAG and the result file name are not changed by this')
    return lines


def _halve(text, view, fired):
    m = re.search(r'\b(halve|double)\s+(?:the\s+)?(f_b)\b', text, re.I)
    wc = view.config
    if not m or wc is None:
        return text
    cur = _num(_get(wc, m.group(2)))
    if cur is None:
        return text
    new = cur / 2 if m.group(1).lower() == 'halve' else cur * 2
    fired.append('relative change: %s' % m.group(1).lower())
    return text[:m.start()] + 'set %s to %s' % (m.group(2), _fmt(new)) + text[m.end():]


def _fmt(x):
    return ('%.12g' % x) if isinstance(x, float) else str(x)


def _package_words(text, view, fired):
    """Package words of the standards: class B / high-loss package (the class B block with both of its tests),
    package A or B (the block only), the other package, both package tests, Test 1 and Test 2."""
    wc = view.config
    if wc is None:
        return text
    t = text
    m = re.search(r'\b(?:the\s+)?(?:class[\s-]*b|high[\s-]*loss)\s+package\b|\bpackage\s+class\s+b\b', t, re.I)
    blk = block_of_class(wc, 'B')
    if m and blk:
        fired.append('package: class B is the class B block with both of its package tests')
        sel = preset_cell_when('802.3dj KR', 'z_p select', 'class B')
        t = t[:m.start()] + 'PKG_NAME = %s %s and z_p select = %s' % (blk, blk, sel) + t[m.end():]
    m = re.search(r'\b(?:package|pkg)\s+([ab])\b(?![\w-])', t, re.I)
    if m and block_of_class(wc, m.group(1)):
        fired.append('package: package %s is the class %s block' % (m.group(1).upper(), m.group(1).upper()))
        t = t[:m.start()] + 'package %s' % block_of_class(wc, m.group(1)) + t[m.end():]
    m = re.search(r'\b(?:the\s+)?other\s+package\b', t, re.I)
    if m:
        a, b = block_of_class(wc, 'A'), block_of_class(wc, 'B')
        other = b if class_in_view(wc) == 'A' else a
        if a and b:
            fired.append('reference: the other package is the other class block')
            t = t[:m.start()] + 'package %s' % other + t[m.end():]
    m = re.search(r'\b(?:both\s+package\s+(?:tests?|lengths?)(?:\s+cases?)?|test\s*1\s+and\s+test\s*2|both\s+tests)\b',
                  t, re.I)
    if m:
        fired.append('package: both package tests are z_p select %s' % both_tests(wc))
        t = t[:m.start()] + 'z_p select = %s' % both_tests(wc) + t[m.end():]
    return t


def recompose(text, view):
    """The request in the core's own form: 'Re-run with a = b and c = d.' (or a first run on the files in the folder)
    for a phrase that names keywords with values and asks to run, when the words around them are what the core
    missed. None when the phrase is not that."""
    wc = view.config
    if wc is None:
        return None
    names = list(wc['main'])
    for b in wc['packages'].values():
        names += [k for k in b if k not in names]
    req = parse.read(text, names, list(wc['packages']))
    sets = [s for s in req['sets'] if s.get('value') is not None and s.get('op') in ('set', None)
            and not isinstance(s.get('block'), dict)]
    pkgs = ['package %s' % p['both'] for p in req['packages'] if p.get('both') in wc['packages']]
    if not (sets or pkgs) or req['sweeps'] or req['files'] or req['attempts'] or len(sets) != len(req['sets']) \
            or len(pkgs) != len(req['packages']):
        return None
    if not (RUN_WORDS.search(text) or {'rerun', 'run'} & set(req['actions']) or 'again' in req['flags']):
        return None
    items = ['%s = %s%s' % (s['name'], s['value'] + (' ' + s['unit'] if s.get('unit') else ''),
                            ' in %s' % s['block'] if s.get('block') else '') for s in sets]
    body = ' and '.join(pkgs + items)
    if view.has_run():
        return 'Re-run with %s.' % body
    return 'Run COM on these files with %s.' % body


# ----------------------------------------------------------------------------- references to the project's files
def _thru_paths(view):
    """The THRU files beside the last run's THRU, project-relative."""
    thru = next((p for p, r in view.channels if (r or 'thru') == 'thru'), None)
    if thru is None:
        return None, []
    folder = os.path.dirname(os.path.join(view.root, thru))
    from sicopr_assist import core
    out = []
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            if parse.CHANNEL_EXT.search(n) and core.channel_kind(n) == 'thru':
                out.append(os.path.relpath(os.path.join(folder, n), view.root))
    return thru, out


def _thru_reference(text, view, fired):
    """the 500mm thru, BPK_500mm version of the thru, the 1400mm one, the 500 mm channel: the THRU among those beside
    the last THRU whose name holds that length token."""
    if not view.has_run() or re.search(r'\b(?:undo|revert|restore|reset)\b', text, re.I):
        return None                  # a reference beside another action the core does not chain (blind row B130)
    m = re.search(r'\b(?:bpk_)?(\d+)\s*mm\b', text, re.I)
    if not m or not re.search(r'\bthru\b|\bchannel\b|\bone\b|\bthrough\b|\bversion\b', text, re.I):
        return None
    thru, thrus = _thru_paths(view)
    tok = '%smm' % m.group(1)
    hits = [p for p in thrus if re.search(r'(?:^|[_\-. ])%s(?:[_\-. ]|$)' % re.escape(tok),
                                          os.path.basename(p), re.I)]
    if len(hits) != 1:
        return None
    # the reference, with the words around it that belong to it, is replaced by the file in the phrase itself: every
    # other word stays for the core to read (and to ask about), so nothing the user said is dropped
    span = re.compile(r'(?:\b(?:the|a)\s+)?(?:\bbpk_)?%s\s*mm\b(?:\s+(?:version\s+of\s+the\s+)?(?:thru|through|channel|one)'
                      r'(?:\s+channel)?\b)?' % re.escape(m.group(1)), re.I)
    s = span.search(text)
    if s is None:
        return None
    cand = text[:s.start()] + hits[0] + text[s.end():]
    if not re.search(r'\b(?:re-?run|run|try|use|again)\b', cand, re.I):
        cand = 'Re-run with %s.' % cand
    fired = fired + ['reference: %s is the THRU beside the last one whose name holds %s' % (m.group(0), tok)]
    ann = ['the THRU %s was found by its length token %s among the THRUs beside the last one (%s); the config of the '
           'last run is kept' % (hits[0], tok, thru)]
    return result(fired, candidates=[cand], announce=ann)


def _names(view):
    wc = view.config
    names = list(wc['main'])
    for b in wc['packages'].values():
        names += [k for k in b if k not in names]
    return names


def _original_thru(text, view, fired):
    """the original thru, the first thru: the THRU of the first run in this project, with the config of the last run
    and its overrides (the strict core reads 'original' as a reset and drops the overrides: a wrong plan)."""
    m = re.search(r'\b(?:the\s+)?(?:original|first|initial)\s+(?:thru|through|channel)(?:\s+file)?\b', text, re.I)
    if not m or not view.has_run():
        return None
    first = None
    for rec in view.history:
        for c in rec.get('channels') or []:
            if (c.get('role') or 'thru') == 'thru':
                first = (c['path'], rec)
                break
        if first and rec.get('run_ids'):
            break
    if first is None:
        return None
    path, rec = first
    run = (rec.get('run_ids') or ['the first run'])[0]
    fired = fired + ['reference: the original thru is the THRU of the first run']
    ann = ['%s is the THRU of the first run (%s); the config of the last run is kept with its overrides' % (path, run)]
    return result(fired, candidates=['Re-run with %s.' % path], announce=ann, override_plan=True)


def _swap_words(text, view, fired):
    pats = (r'\bswap\s+(?:the\s+)?thru\s+(?:for|to|with)\s+(\S+?)[.?!]?$', r'\bswap\s+in\s+(\S+)\s+as\s+the\s+thru\b',
            r'\breplace\s+the\s+thru\s+with\s+(\S+?)[.?!]?$',
            r'\bsame\s+config,?\s+(?:but\s+)?(?:a\s+)?(?:different\s+)?channel:?\s+(\S+?)[.?!]?$',
            r'\bkeep\s+the\s+config,?\s+use\s+(\S+?)[.?!]?$')
    for rx in pats:
        m = re.search(rx, text, re.I)
        if m and parse.CHANNEL_EXT.search(m.group(1)) and view.has_run():
            fired = fired + ['synonym: swap the thru is a re-run with that THRU']
            return result(fired, candidates=['Re-run with %s.' % m.group(1)],
                          announce=['the config of the last run is kept and only the THRU changes'])
    return None


def _crosstalk_words(text, view, fired):
    low = text.lower()
    pair = re.search(r'\bwith\s+(?:vs\.?|versus|and)\s+without\s+(?:the\s+)?(?:xtalk|crosstalk)\b|'
                     r'\bthru[\s-]*only\s+(?:vs\.?|versus|and|or)\s+(?:with\s+)?(?:xtalk|crosstalk)\b|'
                     r'\b(?:xtalk|crosstalk)\s+(?:vs\.?|versus)\s+(?:thru[\s-]*only|no\s+(?:xtalk|crosstalk))\b', low)
    if pair and view.has_run():
        fired = fired + ['synonym: with vs without xtalk is the thru-only and crosstalk pair']
        return result(fired, candidates=['Run thru-only and with xtalk and compare results.'])
    inc = re.search(r'\binclud(?:e|ing)\s+(?:the\s+)?(?:fext\s+and\s+next|next\s+and\s+fext|crosstalk|xtalk)'
                    r'(?:\s+files?)?(?:\s+included)?\b|\bwith\s+fext\s+and\s+next\s+included\b', low)
    if inc and view.has_run() and RUN_WORDS.search(low):
        fired = fired + ['synonym: including FEXT and NEXT is the crosstalk of the THRU']
        return result(fired, candidates=['Re-run with crosstalk.'])
    return None


def _selection(text, view, fired):
    low = text.lower()
    if view.selection is None:
        return None
    if re.search(r'\b(?:the\s+)?channel\s+i\s+(?:just\s+)?(?:selected|picked|chose)\b|\b(?:newly|just)\s+selected\s+'
                 r'channel\b|\bthe\s+channel\s+selected\s+in\s+the\s+run\s+tab\b', low):
        fired = fired + ['synonym: the channel I selected is the selection in the tabs']
        return result(fired, candidates=['Re-run with the selected channel.'])
    if re.search(r'^(?:use|take)\s+(?:the\s+)?(?:channel\s+files?|channels?|files?)\s+(?:i\s+)?(?:selected|picked|chose)'
                 r'(?:\s+in\s+the\s+(?:run\s+)?tabs?)?$', low) and not RUN_WORDS.search(low):
        fired = fired + ['synonym: use the channel files selected is the selection in the tabs, taken without a run']
        return result(fired, candidates=['Use the selected channels.'])
    if re.search(r'\bwhat\s+i\s+(?:picked|selected|chose)\b|\b(?:my|the)\s+selection\b|\bthe\s+stuff\s+i\s+picked\b|'
                 r'\bthe\s+picked\s+config\b', low):
        fired = fired + ['synonym: what I picked is the selection in the tabs']
        return result(fired, candidates=['Run the selected config and channels.'])
    return None


def _sweep_list(text, view, fired):
    m = re.search(r'^(?:sweep|try|run)\s+([A-Za-z_][\w()]*)\s+(?:over|across|at)\s+(.+?)[.?!]?$', text, re.I)
    if not m or view.config is None:
        return None
    vals = [v.strip() for v in re.split(r',\s*(?:and\s+)?|\s+and\s+', m.group(2)) if v.strip()]
    if len(vals) < 2 or not all(re.fullmatch(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', v) for v in vals):
        return None
    fired = fired + ['synonym: over a list is a batch at those values']
    return result(fired, candidates=['Run %s at %s and %s.' % (m.group(1), ', '.join(vals[:-1]), vals[-1])])


# ----------------------------------------------------------------------------- results, help, the dashboard
RESULT_RULES = (
    (r"^what(?:'s| is| was)\s+(?:the\s+|my\s+)?com(?:\s+of\s+the\s+last\s+run)?\??$|^what\s+com\s+did\s+i\s+get\??$|"
     r"^what\s+was\s+com\??$", 'Give me the results summary of the last run.', 'synonym: what was the COM is the summary'),
    (r'^(?:did\s+(?:it|the\s+last\s+run)\s+pass(?:\s+com)?|pass\s+or\s+fail)\??$',
     'Give me the results summary of the last run.', 'synonym: did it pass is the summary'),
    (r'\b(?:stats|statistics)\b.*\bsweep\b|\bsweep\s+statistics\b|\bmin,?\s+max,?\s+(?:and\s+)?mean\b',
     "What's my COM summary statistics for the last set of runs?", 'synonym: stats on the sweep are the statistics'),
    (r'\bwhich\s+run\s+(?:had|gave)\s+the\s+(?:best|highest)\s+com\b|\b(?:best|highest)\s+com\b',
     "What's my COM summary statistics for the last set of runs?", 'synonym: the best COM is in the statistics'),
    (r'^what\s+(?:did|have)\s+i\s+changed?\b|\bshow\s+me\s+what\s+i\s+changed\b|^what\s+did\s+i\s+change\s+from\b',
     'What did you change?', 'synonym: what did I change is the overrides'),
)


def _results(text, view, fired):
    low = text.lower().strip()
    if not view.has_run():
        return None
    for rx, phrase, name in RESULT_RULES:
        if re.search(rx, low):
            ann = []
            if 'best' in name:
                ann = _best_run_lines(view)
            return result(fired + [name], candidates=[phrase], announce=ann)
    m = re.search(r"^(?:is|how)\s+(?:com\s+)?sensitive\s+(?:is\s+com\s+)?to\s+([A-Za-z_][\w()]*)|"
                  r"^how\s+does\s+com\s+depend\s+on\s+([A-Za-z_][\w()]*)|"
                  r"^is\s+com\s+sensitive\s+to\s+([A-Za-z_][\w()]*)", low)
    if m:
        name = next(g for g in m.groups() if g)
        real = next((n for n in _names(view) if parse.squash(n) == parse.squash(name)), None)
        if real:
            return result(fired + ['synonym: sensitive to is how a parameter relates to COM'],
                          candidates=['How does %s correlate to COM?' % real])
    m = re.search(r"^what(?:'s|\s+is)\s+([A-Za-z_][\w()]*)\s+(?:right\s+now|now|currently|set\s+to)\??$", low)
    if m:
        real = next((n for n in _names(view) if parse.squash(n) == parse.squash(m.group(1))), None)
        if real:
            return result(fired + ["synonym: what's X right now is show X"], candidates=['What is %s set to?' % real])
    return None


def _best_run_lines(view):
    try:
        from sicopr_assist import summary
        s = summary.last_set(view.project)
    except Exception:                            # noqa: BLE001 - only an extra line
        return []
    rows = [r for r in (s or {}).get('runs') or [] if isinstance(r, dict)]
    best = None
    for r in rows:
        com = r.get('com')
        if isinstance(com, (int, float)) and com == com and (best is None or com > best[1]):
            best = (r.get('run_id'), com, r.get('values'))
    if best is None:
        return []
    return ['the run with the highest COM is %s (COM %s dB%s)' % (best[0], _fmt(float(best[1])),
                                                                   ', %s' % best[2] if best[2] else '')]


def _help(text, view, fired):
    low = text.lower().strip().rstrip('?.!')
    if re.search(r'^(?:tell me about yourself|what are you|introduce yourself|tell me what you can do|who are you|'
                 r'what can you do)$', low) or re.search(r'^how (?:do i|can i|should i) use (?:you|this(?: tool)?)$', low) \
            or re.search(r'^how does this tool work$|^what do i type$', low) or \
            re.search(r'^how (?:do i|can i) (?:do |run )?(?:a )?sweeps?(?: a parameter)?$|^how do sweeps work(?: here)?$', low):
        return result(fired + ['synonym: help is What can I say?'], candidates=['What can I say?'])
    return None


DASHBOARD_WORDS = {'i', 'want', 'would', 'like', "i'd", 'the', 'a', 'for', 'this', 'that', 'run', 'last', 'of', 'me',
                   'give', 'show', 'get', 'open', 'make', 'build', 'can', 'and', 'tell', 'how', 'long', "it'll", 'it',
                   'will', 'take', 'takes', 'an', 'my', 'please', 'now', 'results'}


def _dashboard(text, view, fired):
    low = text.lower()
    if not re.search(r'\binteractive\s+r\s+report\b|\br\s+dashboard\b|\binteractive\s+report\b|^dashboard\b|'
                     r'\bthe\s+dashboard\b', low):
        return None
    rest = re.sub(r'\binteractive\s+r\s+report\b|\br\s+dashboard\b|\binteractive\s+report\b|\bdashboard\b', ' ', low)
    left = set(re.findall(r"[a-z][a-z0-9'_-]*", rest)) - DASHBOARD_WORDS
    if left:
        return None                  # the dashboard asked for with something else (a change, crosstalk): the core reads it
    ann = []
    if re.search(r'\bhow\s+long\b', low):
        ann.append('export_mat re-runs the working config of the last run with the .mat export on: a full COM run, '
                   'about as long as the last run took')
    return result(fired + ['synonym: the interactive R report is the dashboard'],
                  candidates=['Now give me the results in a dynamic dashboard.'], announce=ann)


# ----------------------------------------------------------------------------- words with several readings
AMBIGUOUS = {
    'z_c': ('package_Z_c', 'board_Z_c'),
    'zc': ('package_Z_c', 'board_Z_c'),
    'snr': ('SNR_TX', 'SNR_TXwC0', 'FFE_SNR'),
}


def _ambiguous_name(text, view, fired):
    """A word that is not a keyword and has several readings among the keywords: a which-question with the
    candidates; nothing runs until one is chosen."""
    m = re.search(r'\b(z_c|zc|snr)\b(?=\s*(?:=|to|at)\s*[-+.\d])', text, re.I)
    if not m or view.config is None:
        return None
    word = m.group(1)
    cands = AMBIGUOUS[word.lower()]
    wc = view.config
    lines = []
    for c in cands:
        where = _where(wc, c)
        lines.append('%s (%s)' % (c, where))
    opts = list(cands) + [NONE_OF_THESE]
    answers = {c: {'replace': [word, c]} for c in cands}
    answers[NONE_OF_THESE] = {'stop': 'Name the parameter by its COM keyword. What can I change? lists them.'}
    txt = ('%s is not a keyword name and has %s readings: %s; nothing runs until one is chosen'
           % (word, 'two' if len(cands) == 2 else 'several', '; '.join(lines)))
    return question(txt, opts, answers, fired + ['ambiguous word: %s' % word])


def _where(wc, name):
    k = _key(wc['main'], name)
    if k is not None:
        extra = ''
        if name.lower() == 'board_z_c':
            pcb = _get(wc, 'Include PCB')
            extra = ', used only with Include PCB = 1, which is %s here' % pcb
        return 'now %s%s' % (wc['main'][k], extra)
    sel = selected_blocks(wc)
    for b in sel[:1]:
        kk = _key(wc['packages'][b], name)
        if kk:
            return 'the selected block %s, now %s' % (b, wc['packages'][b][kk])
    return 'not in this config, the loader default is used'


LOOK_ALIKE = (('o', '0'), ('0', 'o'), ('l', '1'), ('1', 'l'), ('i', '1'))


def _look_alike(text, view, fired):
    """A name that is one look-alike character from a keyword (DER_O for DER_0): asked about, never corrected."""
    if view.config is None:
        return None
    m = re.search(r'\bwith\s+([A-Za-z_][\w()]*)\s*=', text)
    if not m:
        return None
    typed = m.group(1)
    names = _names(view)
    if any(parse.squash(n) == parse.squash(typed) for n in names):
        return None
    hits = []
    for i, ch in enumerate(typed.lower()):
        for a, b in LOOK_ALIKE:
            if ch == a:
                cand = typed[:i] + b + typed[i + 1:]
                hits += [n for n in names if parse.squash(n) == parse.squash(cand) and n not in hits]
    if len(hits) != 1:
        return None
    opts = [hits[0], NONE_OF_THESE]
    return question('%s is not a keyword; it differs from %s in one look-alike character, and a typo in a keyword name '
                    'is not corrected, so nothing runs' % (typed, hits[0]), opts,
                    {hits[0]: {'replace': [typed, hits[0]]},
                     NONE_OF_THESE: {'stop': 'Name the parameter by its COM keyword. What can I change? lists them.'}},
                    fired + ['look-alike name: %s' % typed])


def _impedance(text, view, fired):
    """trace impedance: package_Z_c (the package lines of the selected block) or board_Z_c (the host PCB), with a
    proposal of package line 1 at the values given."""
    m = re.search(r'\b(?:trace|line)\s+impedance\b', text, re.I)
    wc = view.config
    if not m or wc is None:
        return None
    vals = re.findall(r'[-+]?\d+(?:\.\d+)?', text[m.end():])
    sel = selected_blocks(wc)
    blk = sel[0] if sel else None
    zc = wc['packages'][blk].get(_key(wc['packages'][blk], 'package_Z_c')) if blk and _key(wc['packages'][blk],
                                                                                           'package_Z_c') else None
    first = None
    try:
        first = str(zc).strip(' []').split(';')[0].split()[0]
    except (AttributeError, IndexError):
        pass
    pcb = _get(wc, 'Include PCB')
    if vals:
        prop = 'package line 1 at %s ohm, the other sections unchanged, %d runs and a table' % (
            ', '.join(vals[:-1]) + ' and ' + vals[-1] if len(vals) > 1 else vals[0], len(vals))
    else:
        prop = 'package line 1, the other sections unchanged'
    text_q = ('trace impedance can be package_Z_c (the package lines of the selected block %s; line 1, the long trace, '
              'is %s on Tx and Rx) or board_Z_c (the host PCB, used only with Include PCB = 1, which is %s here). '
              'Proposed: %s' % (blk, first, pcb, prop))
    opts = ['package line 1', 'board_Z_c', CANCEL]
    answers = {CANCEL: None}
    if vals and zc is not None:
        rows = [r.split() for r in str(zc).strip(' []').split(';')]
        pts = []
        for v in vals:
            new = [list(r) for r in rows]
            new[0] = [v] * len(new[0])
            pts.append('[%s]' % ' ; '.join(' '.join(r) for r in new))
        answers['package line 1'] = {'phrase': 'Run package_Z_c at %s.' % ', '.join(pts)}
        answers['board_Z_c'] = {'phrase': 'Run board_Z_c at %s.' % ', '.join(vals)}
    else:
        answers['package line 1'] = {'stop': 'Give the values: Run package_Z_c at [ ... ], [ ... ].'}
        answers['board_Z_c'] = {'stop': 'Give the values: Run board_Z_c at <values>.'}
    return question(text_q, opts, answers, fired + ['ambiguous word: trace impedance'], proposal=prop)


# ----------------------------------------------------------------------------- proposals (Rx FFE, low power)
def _rx_lengths(wc):
    return _num(_get(wc, 'ffe_pre_tap_len')), _num(_get(wc, 'ffe_post_tap_len'))


def _rx_ffe_more(text, view, fired):
    low = text.lower()
    if not re.search(r'\bmore\s+(?:rx\s+|receiver\s+)?ffe\b|\b(?:longer|bigger)\s+(?:rx\s+|receiver\s+)?ffe\b|'
                     r'\badd\s+(?:some\s+)?(?:more\s+)?(?:rx\s+|receiver\s+)?ffe\s+taps\b|'
                     r'\bincrease\s+(?:the\s+)?(?:rx\s+|receiver\s+)?ffe\b', low):
        return None
    wc = view.config
    if wc is None:
        return None
    pre, post = _rx_lengths(wc)
    fired = fired + ['proposal: about 10% more Rx FFE taps']
    std = standard_of(wc)
    if not pre and not post:
        txt = ('this %sconfig has no Rx FFE (ffe_pre_tap_len and ffe_post_tap_len are 0; the 802.3ck reference receiver '
               'is a CTLE and a DFE), so there is nothing to add 10%% to; adding one also turns N_bg into the FFE\'s '
               'floating taps (rule LF12) and needs N_qb looked at' % ('%s ' % std if std else ''))
        return question(txt, ['give the Rx FFE tap counts', CANCEL],
                        {'give the Rx FFE tap counts': {'stop': 'Give them: Re-run with ffe_pre_tap_len = <n> and '
                                                                 'ffe_post_tap_len = <m>.'}, CANCEL: None}, fired)
    npre, npost = int(math.ceil(pre * 1.1)), int(math.ceil(post * 1.1))
    tail = _linked_text(wc, [('ffe_pre_tap_len', npre), ('ffe_post_tap_len', npost)])
    phrase = 'Re-run with ffe_pre_tap_len = %d and ffe_post_tap_len = %d.' % (npre, npost) if view.has_run() else \
        'Run COM on these files with ffe_pre_tap_len = %d and ffe_post_tap_len = %d.' % (npre, npost)
    prop = ('ffe_pre_tap_len %d -> %d and ffe_post_tap_len %d -> %d (%d -> %d fixed taps%s)'
            % (pre, npre, post, npost, pre + post + 1, npre + npost + 1, tail))
    txt = ('more Rx FFE with no amount: about 10%% more taps, rounded up, is %s. %s with that?'
           % (prop, 'Re-run the last config and THRU' if view.has_run() else 'Run the config and THRU in this folder'))
    yes = 'yes (%s)' % phrase
    return question(txt, [yes, CANCEL], {yes: {'phrase': phrase}, CANCEL: None}, fired, proposal=prop)


def _linked_text(wc, changes):
    """'; N_tail_start follows by its link, 9 -> 10' for the links the changes move."""
    try:
        res = config_model.apply_changes(wc, [('/main/%s' % (_key(wc['main'], k) or k), v) for k, v in changes])
    except Exception:                            # noqa: BLE001 - only an extra clause
        return ''
    moved = [c for c in res.get('changes') or [] if c.get('kind') == 'linked']
    if not moved:
        return ''
    return '; %s by its link' % ', '.join('%s follows, %s -> %s' % (c['json_path'].rsplit('/', 1)[-1], _fmt(c['before']),
                                                                    _fmt(c['after'])) for c in moved)


def _rx_ffe_off(text, view, fired):
    low = text.lower()
    if not re.search(r'\b(?:turn|switch)\s+(?:the\s+)?(?:rx|receiver)\s+ffe\s+off\b|\b(?:turn|switch)\s+off\s+(?:the\s+)?'
                     r'(?:rx|receiver)\s+ffe\b|\bno\s+(?:rx|receiver)\s+ffe\b|\b(?:rx|receiver)\s+ffe\s+off\b', low):
        return None
    if view.config is None:
        return None
    vals = preset('Rx FFE off')
    lead = 'Re-run with' if view.has_run() else 'Run COM on these files with'
    ann = ['N_qb = 0 is added because the reference stops on N_qb not 0 without an Rx FFE '
           '(docs\\UPSTREAM_QUANTIZATION_WITHOUT_RXFFE.md in SiCoPR)',
           'with the Rx FFE off, the floating taps (N_bg) belong to the DFE (rule LF12)']
    return result(fired + ['preset: Rx FFE off'], candidates=['%s %s.' % (lead, _and(vals))], announce=ann,
                  preset_name='Rx FFE off')


LP_OPTIONS = ('MR-like', 'MR-like without floating taps', 'short fixed FFE', 'CTLE only', 'long DFE (112G-MR-like)')


def _low_power(text, view, fired):
    low = text.lower()
    if not re.search(r'\blow[\s-]*power\b', low) or not re.search(r'\b(?:receiver|rx|equali[sz]\w*|eq)\b', low):
        return None
    wc = view.config
    if wc is None:
        return None
    lead = 'Re-run with' if view.has_run() else 'Run COM on these files with'
    mr = preset('low power MR-like')
    nofl = mr + preset('low power no floating taps')
    short = preset('low power short FFE')
    ctle = preset('low power CTLE only')
    answers = {'MR-like': {'phrase': '%s %s.' % (lead, _and(mr))},
               'MR-like without floating taps': {'phrase': '%s %s.' % (lead, _and(nofl))},
               'short fixed FFE': {'phrase': '%s %s.' % (lead, _and(short))},
               CANCEL: None}
    head = ('"low power" is not a COM setting; these are the reference-receiver structures of receiver_eq_options.md, '
            'each applied on top of the current config, with DER_0, the noise and the threshold staying those of the '
            'current config. (1) MR-like (OIF CEI-224G-MR, the same structure as 802.3dj C2C): %s. (2) as 1 with no '
            'floating taps (N_bg = 0). (3) a short fixed FFE, proposed 2 pre and 2 post, MLSE = 0, no floating taps. '
            % _and(mr).replace(' and ', ', '))
    dfe = preset('low power long DFE')
    answers['CTLE only'] = {'phrase': '%s %s.' % (lead, _and(ctle)), 'mods': q14_pass(ctle)}
    answers['long DFE (112G-MR-like)'] = {'phrase': '%s %s.' % (lead, _and(dfe)), 'mods': q14_pass(dfe)}
    txt = head + ('(4) CTLE only (XSR-like): no FFE, no DFE, no MLSE, N_qb = 0, the XSR CTLE ranges of %s; on a '
                  'backplane or cable channel COM will be strongly negative. (5) the 112G-MR-like 14-tap DFE of '
                  'OIF-CEI-05.3, listed for completeness: not lower power at 106.25 GBd. Which?' % SOURCES['OIF'])
    opts = list(LP_OPTIONS) + [CANCEL]
    if re.search(r'\bdoes\s+com\s+still\s+pass\b|\bstill\s+pass\b', low):
        txt += ' The summary of the run answers whether COM still passes.'
    return question(txt, opts, answers, fired + ['proposal: the low-power receivers'],
                    proposal='the %d low-power receivers' % (len(opts) - 1))


def _xsr(text, view, fired):
    low = text.lower()
    if not re.search(r'\bxsr\b', low) or view.config is None:
        return None
    lead = 'Re-run with' if view.has_run() else 'Run COM on these files with'
    vals = preset('low power CTLE only')
    opt = 'CTLE only (XSR-like)'
    txt = ('an XSR receiver is CTLE only (OIF CEI-112G-XSR): %s. On a backplane or cable channel COM will be strongly '
           'negative. Run it?' % _and(vals).replace(' and ', ', '))
    return question(txt, [opt, CANCEL], {opt: {'phrase': '%s %s.' % (lead, _and(vals)), 'mods': q14_pass(vals)},
                                         CANCEL: None},
                    fired + ['proposal: the XSR-like receiver'], proposal=opt)


# ----------------------------------------------------------------------------- interface presets
def _channels_text(view):
    """'Run COM on <thru> [and FEXT <f> ...]' for the last run's channels, or 'Run COM on these files'."""
    if not view.has_run() or not view.channels:
        return 'Run COM on these files'
    parts = []
    for p, r in view.channels:
        role = (r or 'thru')
        parts.append(p if role == 'thru' else '%s %s' % (role.upper(), p))
    return 'Run COM on %s' % ' and '.join(parts)


def _first_run_phrase(view, values, config=None):
    """A first run on the files in the folder (or the last run's channels and a named workbook)."""
    head = _channels_text(view)
    if config:
        head += ' with %s' % config
    if not values:
        return head + '.'
    return '%s %s %s.' % (head, 'and' if config else 'with', _and(values))


def _rerun_phrase(values):
    return 'Re-run with %s.' % _and(values)


def _changed_only(wc, values):
    """values without those the config already holds (a value equal to the current one is not a change)."""
    out = []
    for k, v in values:
        cur = _get(wc, k)
        if cur is not None and config_model.same_value(cur, v):
            continue
        out.append((k, v))
    return out


def _presets(text, view, fired):
    low = text.lower()
    if FETCH_WORDS.search(low) or re.search(r'\.(?:xlsx|xls|csv|json)\b', low) or parse.CHANNEL_EXT.search(low) \
            or '=' in low:
        return None                     # files named, a download, or a keyword with a value: not a preset request
    iface = interface_named(low)
    std = standard_named(low)
    if iface is None and std is None:
        return None
    wc = view.config
    if re.match(r"^\s*(?:is|are|what|whats|what's|does|do|how|why|which|who|can|could|should)\b", low) or \
            low.rstrip().endswith('?'):
        return None                  # a question about an interface is not a request to set one up (B133, B175)
    if not SETUP_WORDS.search(low) and not (iface and std and _only_names(low)):
        return None
    in_view = interface_of(preset_in_view(view.history))
    if iface is None:
        iface = in_view or KR
    how_std = 'named'
    if std is None:
        std = standard_of(wc) if wc else None
        how_std = 'taken from the config in view (f_b = %s)' % _fmt(_num(_get(wc, 'f_b'))) if std else ''
    if std is None or (wc is None and std == '802.3dj'):
        return _no_config_question(iface, view, fired)
    if wc is None:                   # 802.3ck named, no config in view: the preset is built on a config
        return result(fired + ['preset: no config in view'],
                      outcome={'type': 'STOP', 'reason': 'There is no config in this folder for the 802.3ck %s preset '
                               'to start from. Put a config in the folder first (data\\config.xlsx), or start with '
                               'Run the example., then: Setup a 802.3ck config for %s and run my channels.'
                               % (iface, iface)})
    name = '%s %s' % (std, iface)
    fired = fired + ['preset: %s' % name]
    lead = ['the preset that fired: %s (%s, %s)%s' % (name, STANDARDS[std]['clause'][iface], STANDARDS[std]['lane'],
                                                      '; the standard was %s' % how_std if how_std != 'named' else '')]
    if std == '802.3dj':
        return _dj(iface, low, view, fired, lead, name)
    return _ck(iface, low, view, fired, lead, name)


def _only_names(low):
    """A phrase that is nothing but a standard and an interface (100G per lane backplane, after the filler went):
    a request to set that interface up (blind B170)."""
    rest = low
    for _, rx in STD_WORDS + IFACE_WORDS:
        rest = rx.sub(' ', rest)
    return not re.sub(r'\b(?:an?|the|for|config|setup)\b|[\s.,!]', '', rest)


def _no_config_question(iface, view, fired):
    """No config in view to take the standard from: 802.3dj is proposed, 802.3ck is the other option."""
    dj = '802.3dj %s' % iface
    ck = '802.3ck %s' % iface
    vals = _dj_values(iface, None)
    txt = ('there is no config in view to take the standard from, so 802.3dj is proposed: %s (%s, %s) from the shipped '
           '802.3dj KR workbook%s; 802.3ck %s is the other option'
           % (dj, STANDARDS['802.3dj']['clause'][iface], STANDARDS['802.3dj']['lane'],
              ' with %s and both package tests' % _and(vals).replace(' and ', ', ') if vals else '', iface))
    answers = {dj: {'phrase': 'Run the example with %s.' % _and(vals) if vals else 'Run the example.'},
               ck: {'stop': 'Put a config in this folder first (data\\config.xlsx), then: Setup a 802.3ck config for %s '
                            'and run my channels.' % iface},
               CANCEL: None}
    return question(txt, [dj, ck, CANCEL], answers, fired + ['preset: no config in view'], proposal=dj)


def _dj_values(iface, wc):
    vals = []
    if iface == C2C:
        vals = preset('802.3dj %s' % C2C)
    if iface in (KR, C2C) and wc is not None:
        vals = vals + [('z_p select', both_tests(wc))]
    return vals


def _rebuild(view):
    """Whether a preset is applied to the source workbook again rather than to the working config: when the last run
    came from another preset, its changes do not carry over."""
    return view.has_run() and preset_in_view(view.history) is not None


def _source_config(view):
    src = (view.last or {}).get('source') or {}
    return src.get('path')


def _plan_phrase(view, values, rebuild=None):
    rebuild = _rebuild(view) if rebuild is None else rebuild
    if view.has_run() and not rebuild:
        vals = _changed_only(view.wc, values)
        return _rerun_phrase(vals) if vals else 'Re-run.'
    if view.has_run() and rebuild:
        return _first_run_phrase(view, values, config=_source_config(view))
    return _first_run_phrase(view, values)


def _dj(iface, low, view, fired, lead, name):
    wc = view.config
    if iface in (KR, C2C):
        vals = _dj_values(iface, wc)
        lines = lead + []
        if iface == KR:
            lines.append('802.3dj KR is the shipped workbook as it is, with both package tests (Test 1 and Test 2, '
                         'z_p select %s for class %s)' % (both_tests(wc), class_in_view(wc)))
        else:
            lines.append('PMD_type is not touched (every 802.3dj workbook holds C2C)')
        lines.append(_run_control_line(wc))
        return result(fired, candidates=[_plan_phrase(view, vals)], announce=lines, preset_name=name)
    if iface == CR:
        return _dj_cr(low, view, fired, lead, name)
    # C2M: the 802-COM egress template, with the draft's eta_0 (the template holds 7.9e-9)
    template = os.path.join(TEMPLATES, preset_cell('802.3dj C2M', 'template'))
    vals = preset('802.3dj C2M')
    vals = [(k, v) for k, v in vals if k != 'template']
    order = ['c(-2)', 'c(-1)', 'c(1)', 'eta_0']
    vals = [x for o in order for x in vals if x[0] == o] + [x for x in vals if x[0] not in order]
    lines = lead + ['the base workbook is the 802-COM C2M TP0-TP2 egress template (BSD-3, shipped with SiCoPR-Assist); '
                    'the config in the folder is not used',
                    'the Tx FFE ranges go into the value cells (the template holds 0 there)',
                    'Local Search = 2 and Non-zero Local Search Method = 1 are added: the template holds Local Search = 0 '
                    'and no Non-zero Local Search Method, which runs a full grid',
                    'COM is not the C2M specification (176D.7.2): the result is informative margin and the summary gives '
                    'no pass or fail',
                    'the template leaves out the 280 mm partial host channel']
    if view.has_run():
        lines.append('the working config is rebuilt from the template, so the overrides of the last run do not carry over')
    head = _channels_text(view)
    return result(fired, candidates=['%s with %s.' % (head, _and(vals))], announce=lines, preset_name=name,
                  mods={'config_path': template})


def _run_control_line(wc):
    ls, nz = _get(wc, 'Local Search'), _get(wc, 'Non-zero Local Search Method')
    if _num(ls) == 2 and _num(nz) == 1:
        return 'Local Search = 2 and Non-zero Local Search Method = 1 are in the workbook already'
    return 'Local Search is %s and Non-zero Local Search Method is %s in this workbook' % (ls, nz)


def _cr_pair_values(wc, tx, rx):
    """The changes of a CR host-class pair on the config: Include PCB, PKG_NAME, the package length of each host's
    block, z_bp by side (FEXT follows the Tx host, NEXT the Rx host, as the template's formulas do), ERL, N, N_bx."""
    hosts = {}
    for h in HOSTS:
        blk, zp, zbp = [x.strip() for x in preset_cell('802.3dj CR', 'host %s' % h).split('|')]
        hosts[h] = {'block': blk, 'zp': zp, 'zbp': zbp}
    a = block_of_class(wc, 'A') or hosts['HL']['block']
    b = block_of_class(wc, 'B') or hosts['HN']['block']
    blk = {h: (a if 'CLASSA' in hosts[h]['block'].upper() else b) for h in HOSTS}
    vals = [('Include PCB', '1'), ('PKG_NAME', '%s %s' % (blk[tx], blk[rx]))]
    done = set()
    for h in (tx, rx):
        if blk[h] in done:
            continue
        done.add(blk[h])
        if blk[h] == a:
            vals.append(('z_p (TX)', '%s in %s' % (hosts[h]['zp'], blk[h])))
        else:
            for side in ('TX', 'NEXT', 'FEXT', 'RX'):
                vals.append(('z_p (%s)' % side, '%s in %s' % (hosts[h]['zp'], blk[h])))
    vals.append(('z_p select', '[ 1 ]'))
    vals += [('z_bp (TX)', hosts[tx]['zbp']), ('z_bp (RX)', hosts[rx]['zbp']), ('z_bp (NEXT)', hosts[rx]['zbp']),
             ('z_bp (FEXT)', hosts[tx]['zbp'])]
    vals += [(k, v) for k, v in preset('802.3dj CR') if k in ('ERL Pass threshold', 'N', 'N_bx')]
    return vals


def _pair_classes(tx, rx):
    return preset_cell('802.3dj CR', 'pair %s %s' % (tx, rx)) or ''


def _dj_cr(low, view, fired, lead, name):
    wc = view.config
    hosts = re.findall(r'\b(hl|hn|hh)\b', low)
    ca = re.search(r'\bca-?([abcd])\b', low)
    pair = None
    if len(hosts) >= 2:
        pair = (hosts[0].upper(), hosts[1].upper())
    elif len(hosts) == 1 and re.search(r'\bboth\s+(?:ends|sides)\b|\bat\s+both\b|\beach\s+end\b', low):
        pair = (hosts[0].upper(), hosts[0].upper())
    if pair is not None and pair in CR_PAIRS:
        classes = _pair_classes(*pair).split()
        if ca is None or ('CA-' + ca.group(1).upper()) in classes:
            vals = _changed_only(wc, _cr_pair_values(wc, *pair)) if wc is not None else []
            lines = lead + ['host classes %s to %s (cable classes %s)%s; the cable class sets only the cable loss limit, '
                            'not a COM setting' % (pair[0], pair[1], ', '.join(classes),
                                                   ', CA-%s given' % ca.group(1).upper() if ca else '')]
            return result(fired + ['classes given: %s to %s' % pair], candidates=[_plan_phrase(view, _vals_text(vals))],
                          announce=lines, preset_name=name)
    opts, answers = [], {}
    for tx, rx in CR_PAIRS:
        label = '%s to %s' % (tx, rx)
        opt = '%s (%s)' % (label, ', '.join(_pair_classes(tx, rx).split()))
        vals = _changed_only(wc, _cr_pair_values(wc, tx, rx)) if wc is not None else []
        opts.append(opt)
        answers[opt] = {'phrase': _plan_phrase(view, _vals_text(vals))}
    opts.append(CANCEL)
    answers[CANCEL] = None
    hl = preset_cell('802.3dj CR', 'host HL').split('|')
    txt = ('802.3dj CR (Clause 179): the cable class and the host classes are not given. The cable class (CA-A to CA-D) '
           'sets only the cable loss limit, not a COM setting; the host classes set the package and the partial host '
           'PCB (the 802-COM CR template, BSD-3). Proposed: Tx and Rx host HL, the one pair every cable class allows: '
           'Include PCB = 1, the class A package at 8 mm (z_p (TX) = %s in %s, with PKG_NAME = %s %s), z_bp (TX), (RX), '
           '(NEXT) and (FEXT) = %s, ERL Pass threshold = 8.25, N = 9000, N_bx = 0. Run it, or pick another pair%s'
           % (hl[1].strip(), hl[0].strip(), hl[0].strip(), hl[0].strip(), hl[2].strip(),
              ' (each on the last run\'s channels)' if view.has_run() else ''))
    return question(txt, opts, answers, fired + ['proposal: the CR host classes'], announce=lead, preset_name=name,
                    proposal='HL to HL')


def _vals_text(vals):
    """[(k, v)] where v may be 'value in BLOCK': kept as the phrase writes it."""
    return vals


def _q14_line(values):
    """The announcement that rule Q14 did not ask about the preset's DFE limits (b_min above 0), when it has some."""
    keys = [k for k, _ in values if k.lower().startswith('b_min')]
    if not keys:
        return []
    return ['rule Q14 does not ask about %s: a value a preset takes from the standard is not a validation question '
            '(the value comes from IEEE Std 802.3ck-2022); the same value typed by hand still is' % ' and '.join(keys)]


def _ck(iface, low, view, fired, lead, name):
    key = '802.3ck %s' % iface if iface != C2M else '802.3ck %s eye' % C2M
    wc = view.config
    if iface == C2M:
        eye = _ck_values(wc, preset('802.3ck %s eye' % C2M))
        c2c = _ck_values(wc, preset('802.3ck %s' % C2C))
        txt = ('802.3ck C2M (Annex 120G) has no COM: hosts and modules are specified by eye height and VEC through the '
               '120G-11 reference receiver (a CTLE and a 4-tap DFE). Which run? The first is PMD_type = C2M with that '
               'receiver (the 120G-11 values; the verdict is on VEC Pass threshold and EH_min, not COM); the second '
               'is COM with the 802.3ck C2C (120F) parameters, an approximation and not a C2M compliance result%s'
               % (', each on the last run\'s channels' if view.has_run() else ''))
        opts = ['eye height and VEC', 'C2C-parameter COM', CANCEL]
        answers = {'eye height and VEC': {'phrase': _plan_phrase(view, eye, rebuild=True), 'mods': q14_pass(eye)},
                   'C2C-parameter COM': {'phrase': _plan_phrase(view, c2c, rebuild=True), 'mods': q14_pass(c2c)},
                   CANCEL: None}
        return question(txt, opts, answers, fired + ['proposal: the 802.3ck C2M run'], announce=lead, preset_name=name)
    vals = _ck_values(wc, preset(key))
    lines = lead + ['the values are the standard\'s (%s, shipped under the COM workbook terms), on %s'
                    % (SOURCES['802.3ck'], 'the working config of the last run' if view.has_run() and not _rebuild(view)
                       else 'the workbook'),
                    'the f_b links follow (f_z, f_p1, f_p2, f_HP_PZ, f_v, f_f, f_n)', _run_control_line(wc)]
    lines += _q14_line(vals)
    return result(fired, candidates=[_plan_phrase(view, vals)], announce=lines, preset_name=name, mods=q14_pass(vals))


def _ck_values(wc, values):
    """The preset's values for the config in view: 802.3ck has one package model, written into the class A block (the
    PKG_NAME is set to it first when the config in view selects another block)."""
    a = block_of_class(wc, 'A') if wc is not None else None
    sel = selected_blocks(wc) if wc is not None else []
    out = []
    if a and sel and any(s != a for s in sel):
        out.append(('PKG_NAME', '%s %s' % (a, a)))
    return out + list(values)

"""The working config: import, links, applying a change, and writing the run CSV.

The working config is the JSON form of a config:

    {"schema": "sicopr-config/1", "source": {"file", "sheet", "sha256"},
     "main": {keyword: value}, "packages": {block: {keyword: value}}, "links": {key: "{f_b}/2.5"}}

Values keep the COM text the sheet holds ("[ -0.34:.02:0]" stays a string). A key is a keyword in the
main area, or packages.<block>.<keyword> in a package block; a json_path is /main/<keyword> or
/packages/<block>/<keyword>. A link names the keys it depends on in braces: {name} is a key of the same
block, else of the main area, and {packages.<block>.<keyword>} names a block key from anywhere.

Links are evaluated by a small evaluator built on the ast module, never by eval or exec, because link
text comes from a workbook. Its grammar is what the workbooks hold: a single {keyword}
reference, which copies the value whatever its type, or arithmetic over number literals and references
whose values are numbers, with + - * /, unary minus and parentheses. Anything else is refused.

Import problems are returned as issues, {level, code, text, ...}, with level one of
    stop       the config cannot be run as it is
    ask        the user has to say what was meant
    announce   something was done that the user must be told about
    warn       something was left as it was, and the user should know
    note       a fact about the config
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import ast
import copy
import csv
import difflib
import hashlib
import io
import json
import operator
import os
import re
import shutil
import tempfile
import zipfile

import numpy as np

from sicopr_assist import engine, xlsx_io
from sicopr_assist.project import CONFIG_SCHEMA, check_working_config

ABSENT = '(absent)'                    # a loaded field that one of two configs does not have


class LinkRefused(ValueError):
    """A link outside the grammar the working config accepts for a formula link."""


class LinkError(ValueError):
    """A link in the grammar that cannot be evaluated: a reference that is missing or not a number."""


# ----------------------------------------------------------------------------- keys and paths
def key_of(json_path):
    """'/main/DER_0' -> 'DER_0'; '/packages/B/C_p' -> 'packages.B.C_p'."""
    parts = json_path.split('/', 3)
    if len(parts) == 3 and parts[0] == '' and parts[1] == 'main' and parts[2]:
        return parts[2]
    if len(parts) == 4 and parts[0] == '' and parts[1] == 'packages' and parts[2] and parts[3]:
        return 'packages.%s.%s' % (parts[2], parts[3])
    raise ValueError('not a working-config path: %r' % json_path)


def json_path_of(key):
    if key.startswith('packages.'):
        _, block, name = key.split('.', 2)
        return '/packages/%s/%s' % (block, name)
    return '/main/' + key


def _split(key):
    """(block or None, name)"""
    if key.startswith('packages.'):
        _, block, name = key.split('.', 2)
        return block, name
    return None, key


def get_value(wc, key):
    block, name = _split(key)
    return (wc['main'] if block is None else wc['packages'][block])[name]


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def same_value(a, b):
    """Is b the value a already holds? Numbers compare as numbers (1e-4 and '0.0001' are equal); text
    compares with runs of spaces collapsed and spaces inside the brackets ignored ('[ 1 ]' and '[1]')."""
    def num(v):
        if _is_number(v):
            return float(v)
        try:
            return float(str(v).strip())
        except ValueError:
            return None
    na, nb = num(a), num(b)
    if na is not None or nb is not None:
        return na is not None and nb is not None and (na == nb or (na != na and nb != nb))

    def text(v):
        s = re.sub(r'\s+', ' ', str(v)).strip()
        return re.sub(r'\s*\]', ']', re.sub(r'\[\s*', '[', s))
    if a is None or b is None:
        return a is None and b is None
    return text(a) == text(b)


# ----------------------------------------------------------------------------- links
_BRACED = re.compile(r'\{([^{}]+)\}')
_PLACEHOLDER = re.compile(r'_ref[0-9]+')
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def parse_link(text):
    """Check a link against the grammar. Returns ('ref', name) for a single reference, else
    ('expr', tree, names). Raises LinkRefused, naming the link, for anything outside the grammar. Nothing
    here runs the text: it is parsed into a syntax tree, and the tree is only inspected."""
    if not isinstance(text, str):
        raise LinkRefused('a link is text, not %r' % (text,))
    if _PLACEHOLDER.search(text):
        raise LinkRefused('link %r is outside the grammar' % text)
    names = []

    def hold(m):
        names.append(m.group(1))
        return ' _ref%d ' % (len(names) - 1)
    src = _BRACED.sub(hold, text).strip()
    if '{' in src or '}' in src:
        raise LinkRefused('link %r has an unmatched brace' % text)
    if len(names) == 1 and src == '_ref0':
        return ('ref', names[0])
    try:
        tree = ast.parse(src, mode='eval')
    except SyntaxError:
        raise LinkRefused('link %r is not arithmetic' % text) from None

    def allowed(node):
        if isinstance(node, ast.Expression):
            return allowed(node.body)
        if isinstance(node, ast.BinOp):
            return type(node.op) in _OPS and allowed(node.left) and allowed(node.right)
        if isinstance(node, ast.UnaryOp):
            return isinstance(node.op, ast.USub) and allowed(node.operand)
        if isinstance(node, ast.Constant):
            return type(node.value) in (int, float)
        if isinstance(node, ast.Name):
            return isinstance(node.ctx, ast.Load) and re.fullmatch(r'_ref[0-9]+', node.id) is not None \
                and int(node.id[4:]) < len(names)
        return False
    if not allowed(tree):
        raise LinkRefused('link %r is outside the grammar: only numbers, {keyword} references, + - * /, '
                          'unary minus and parentheses are allowed' % text)
    return ('expr', tree, names)


def link_names(text):
    """The names a link refers to, as written in its braces."""
    return _BRACED.findall(text)


def evaluate_link(parsed, lookup):
    """The value of a parsed link. lookup(name) gives the value a name refers to."""
    if parsed[0] == 'ref':
        return lookup(parsed[1])
    _, tree, names = parsed

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            name = names[int(node.id[4:])]
            v = lookup(name)
            if not _is_number(v):
                raise LinkError('%s is %r, not a number' % (name, v))
            return v
        if isinstance(node, ast.UnaryOp):
            return -ev(node.operand)
        left, right = ev(node.left), ev(node.right)      # left before right, as Excel and Python do
        try:
            return _OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise LinkError('division by zero') from None
    return ev(tree)


def resolve(wc, link_key, name):
    """The key a name in the link of link_key refers to. Raises LinkError when there is none."""
    block, _ = _split(link_key)
    if name.startswith('packages.') and name.count('.') >= 2:
        _, b, n = name.split('.', 2)
        if b in wc['packages'] and n in wc['packages'][b]:
            return name
    if block is not None and name in wc['packages'].get(block, {}):
        return 'packages.%s.%s' % (block, name)
    if name in wc['main']:
        return name
    raise LinkError('the link of %s refers to %s, which is not in this config' % (link_key, name))


def link_value(wc, link_key, skip=()):
    """Evaluate the link of link_key in wc. A name that resolves to a key in skip counts as missing."""
    def lookup(name):
        key = resolve(wc, link_key, name)
        if key in skip:
            raise LinkError('%s has no value yet' % name)
        return get_value(wc, key)
    return evaluate_link(parse_link(wc['links'][link_key]), lookup)


def _depends(wc, link_key):
    return {resolve(wc, link_key, n) for n in link_names(wc['links'][link_key])}


def _recompute(wc, changed):
    """Recompute, in place, every link downstream of the keys in changed. Returns ([(key, before, after)],
    [warning])."""
    deps, warnings = {}, []
    for lk in wc['links']:
        try:
            deps[lk] = _depends(wc, lk)
        except LinkError as e:
            warnings.append(str(e))
    down = set()
    grew = True
    while grew:
        grew = False
        for lk, d in deps.items():
            if lk not in down and d & (set(changed) | down):
                down.add(lk)
                grew = True
    done, moved = set(), []
    while down - done:
        ready = [lk for lk in wc['links'] if lk in down - done and not (deps[lk] & (down - done))]
        if not ready:
            warnings.append('links that depend on each other were not recomputed: %s' % ', '.join(sorted(down - done)))
            break
        for lk in ready:
            done.add(lk)
            try:
                v = link_value(wc, lk)
            except (LinkError, LinkRefused) as e:
                warnings.append('%s was not recomputed: %s' % (lk, e))
                continue
            block, name = _split(lk)
            scope = wc['main'] if block is None else wc['packages'][block]
            before = scope[name]
            if not (before == v if _is_number(before) and _is_number(v) else type(before) is type(v) and before == v):
                scope[name] = v
                moved.append((lk, before, v))
    return moved, warnings


# ----------------------------------------------------------------------------- applying changes
def _change(json_path, before, after, kind, applied):
    return {'json_path': json_path, 'before': before, 'after': after, 'kind': kind, 'applied': applied}


def _locate(wc, key):
    """(scope dict, name as the config spells it), or None when the block does not exist. A name is
    matched ignoring case and surrounding spaces, as the loader matches it."""
    block, name = _split(key)
    if block is not None and block not in wc['packages']:
        return None
    scope = wc['main'] if block is None else wc['packages'][block]
    if name not in scope:
        name = next((k for k in scope if k.strip().lower() == name.strip().lower()), name)
    return scope, name


def apply_changes(wc, changes, check=False):
    """Apply {json_path: value} to a copy of wc; the source workbook is never touched.

    An explicit value removes that key's link; a value equal to the current one is not a change; a key the
    config does not hold is added; links downstream of a change are recomputed. With check set, both
    configs are loaded by the engine and a change that moves no loaded field is reported, with the rule
    that explains it where one does (LF13, LF14, VR01).

    Returns {'config', 'changes' (applied, with kind set, add or linked), 'unchanged' (values already
    held), 'refused', 'links_removed', 'warnings'}, plus 'effect' and 'no_effect' with check."""
    new = copy.deepcopy(wc)
    res = {'config': new, 'changes': [], 'unchanged': [], 'refused': [], 'links_removed': [], 'warnings': []}
    changed = []
    for jp, value in (changes.items() if isinstance(changes, dict) else changes):
        try:
            key = key_of(jp)
        except ValueError as e:
            res['refused'].append({'json_path': jp, 'after': value, 'reason': str(e)})
            continue
        loc = _locate(new, key)
        if loc is None:
            res['refused'].append({'json_path': jp, 'after': value,
                                   'reason': 'there is no package block %s in this config' % _split(key)[0]})
            continue
        scope, name = loc
        block = _split(key)[0]
        key = name if block is None else 'packages.%s.%s' % (block, name)
        jp = json_path_of(key)
        if name in scope and same_value(scope[name], value):
            res['unchanged'].append(_change(jp, scope[name], value, 'set', False))
            continue
        res['changes'].append(_change(jp, scope.get(name), value, 'set' if name in scope else 'add', True))
        scope[name] = value
        if key in new['links']:
            res['links_removed'].append({'json_path': jp, 'link': new['links'].pop(key)})
        changed.append(key)
    moved, warnings = _recompute(new, changed)
    res['changes'] += [_change(json_path_of(k), b, a, 'linked', True) for k, b, a in moved]
    res['warnings'] += warnings
    if check:
        res['effect'] = effect(wc, new)
        res['no_effect'] = None
        primary = [c for c in res['changes'] if c['kind'] != 'linked']
        if primary and not res['effect']['error'] and not res['effect']['moved']:
            res['no_effect'] = no_effect_reason(wc, primary[0]['json_path']) or \
                {'rule': None, 'text': 'the change moves no parameter the engine loads'}
    return res


def no_effect_reason(wc, json_path):
    """{'rule', 'text'} when a rule explains why a change to json_path has no effect on what the engine
    loads (LF13, LF14, VR01), else None."""
    block, name = _split(key_of(json_path))
    if block is not None:
        return None
    low = name.strip().lower()
    main = {k.strip().lower(): v for k, v in wc['main'].items()}
    if low in {k.lower() for k in engine.keyword_names('package block')} and wc['packages'] \
            and str(main.get('pkg_name') or '').strip():
        return {'rule': 'LF13', 'text': '%s in the main area has no effect: PKG_NAME selects package blocks, and the '
                                        'engine reads %s from them' % (name, name)}
    n_b = main.get('n_b')
    if _is_number(n_b) and ((low in ('b_max(2..n_b)', 'b_min(2..n_b)') and n_b < 2)
                            or (low in ('b_max(1)', 'b_min(1)') and n_b <= 0)):
        return {'rule': 'LF14', 'text': '%s has no effect while N_b = %s: the engine reads it only when N_b is %s'
                                        % (name, n_b, '2 or more' if '2..' in low else 'above 0')}
    used = any(name in link_names(t) for t in wc['links'].values())
    if not engine.reads_keyword(name) and not used:
        return {'rule': 'VR01', 'text': 'SiCoPR does not read %s, so changing it has no effect' % name}
    return None


# ----------------------------------------------------------------------------- the run CSV
def _csv_cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return repr(v)
    return str(v)


def run_csv_rows(wc):
    """The rows of the run CSV: keyword,value per main entry in order, then per package block a .START row,
    its pairs and a .END row. Nothing else of the working config reaches it."""
    rows = [[k, _csv_cell(v)] for k, v in wc['main'].items()]
    for block, params in wc['packages'].items():
        rows.append(['.START', block])
        rows += [[k, _csv_cell(v)] for k, v in params.items()]
        rows.append(['.END'])
    return rows


def run_csv_text(wc):
    """The run CSV as text, written by the csv module, so a value holding a comma or a quote is quoted."""
    buf = io.StringIO()
    csv.writer(buf).writerows(run_csv_rows(wc))
    return buf.getvalue()


def write_run_csv(wc, path):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(run_csv_text(wc))
    return path


_LOADED = {}                    # run CSV text -> (fields, error); a plan loads the same config many times
_LOADED_MAX = 512


def loaded_fields(wc):
    """(fields, None) as the engine loads wc written as the run CSV, else (None, '<ErrorType>: <message>').
    The CSV is written to a temporary folder, which is removed. Results are kept by the CSV text (the loader
    reads nothing else), so the fields returned are shared and must not be changed by the caller."""
    text = run_csv_text(wc)
    st = os.stat(engine.engine_path())
    key = (st.st_mtime_ns, st.st_size, text)
    if key in _LOADED:
        return _LOADED[key]
    tmp = tempfile.mkdtemp(prefix='sicopr_assist_csv_')
    try:
        path = os.path.join(tmp, 'run.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        got = engine.load_fields(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if len(_LOADED) >= _LOADED_MAX:
        _LOADED.pop(next(iter(_LOADED)))
    _LOADED[key] = got
    return got


def field_equal(a, b):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a, b = np.asarray(a), np.asarray(b)
        if a.shape != b.shape:
            return False
        if a.dtype.kind in 'fiuc' and b.dtype.kind in 'fiuc':
            return bool(np.array_equal(a, b, equal_nan=True))
        return bool(np.array_equal(a, b))
    if _is_number(a) and _is_number(b):
        return a == b or (a != a and b != b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(field_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def moved_fields(before, after):
    """{field: (before, after)} for the loaded fields that differ; a field one side lacks is ABSENT."""
    out = {}
    for k in sorted(set(before) | set(after)):
        a, b = before.get(k, ABSENT), after.get(k, ABSENT)
        if (a is ABSENT) != (b is ABSENT) or not field_equal(a, b):
            out[k] = (a, b)
    return out


def effect(base, new):
    """What the engine loads differently from new than from base: {'error' (new does not load),
    'base_error', 'moved'}."""
    bf, berr = loaded_fields(base)
    nf, nerr = loaded_fields(new)
    return {'error': nerr, 'base_error': berr, 'moved': moved_fields(bf, nf) if bf and nf else {}}


# ----------------------------------------------------------------------------- import
def _issue(level, code, text, **details):
    return dict(level=level, code=code, text=text, **details)


def stops(issues):
    return [i for i in issues if i['level'] == 'stop']


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def import_config(path):
    """Import a config file into a working config: (working config or None, issues).

    A workbook (.xlsx, or .xls holding an .xlsx) keeps every stored value exactly and turns each formula
    into a link by keyword name; a .csv is imported to the same form; a working-config .json is accepted
    after its schema version and keys are checked. The source file is only read."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.json':
        return _import_json(path)
    if ext == '.csv':
        return _import_csv(path)
    return _import_workbook(path)


def _import_workbook(path):
    try:
        doc = xlsx_io.read_workbook(path)
    except xlsx_io.LegacyXls as e:
        return None, [_issue('stop', 'legacy_xls', str(e))]
    except xlsx_io.StrictOOXML as e:
        return None, [_issue('stop', 'strict_ooxml', str(e))]
    except (xlsx_io.NotAWorkbook, zipfile.BadZipFile, KeyError, OSError) as e:
        return None, [_issue('stop', 'unreadable', 'cannot read %s: %s' % (os.path.basename(path), e))]
    except Exception as e:                       # noqa: BLE001 - a workbook openpyxl cannot read is a STOP, never a traceback
        return None, [_issue('stop', 'unreadable', 'cannot read %s: %s: %s' % (os.path.basename(path),
                                                                              type(e).__name__, e))]
    issues = [_issue('note', 'xls_is_xlsx', doc.note)] if doc.note else []
    found = xlsx_io.scan(doc.grid, doc.formulas)
    source = {'file': os.path.basename(path), 'sheet': doc.sheet, 'sha256': _sha256(path)}
    return _build(found, source, issues)


def _csv_value(text):
    """A CSV cell as the loader reads it: empty is no value, a number is a number (a whole one an int),
    anything else is the text as it stands."""
    if text.strip() == '':
        return None
    try:
        return xlsx_io.stored_value(float(text.strip()))
    except ValueError:
        return text


def _import_csv(path):
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            grid = [[_csv_value(c) for c in row] for row in csv.reader(f)]
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        return None, [_issue('stop', 'unreadable', 'cannot read %s: %s' % (os.path.basename(path), e))]
    found = xlsx_io.scan(grid, {})
    return _build(found, {'file': os.path.basename(path), 'sheet': None, 'sha256': _sha256(path)}, [])


def _build(found, source, issues):
    issues = issues + list(found.issues)
    cells = dict(found.main)
    for b, params in found.packages.items():
        cells.update({'packages.%s.%s' % (b, k): cl for k, cl in params.items()})
    wc = {'schema': CONFIG_SCHEMA, 'source': source,
          'main': {k: cl.value for k, cl in found.main.items()},
          'packages': {b: {k: cl.value for k, cl in params.items()} for b, params in found.packages.items()},
          'links': {}}
    for lk, text in found.links.items():
        try:
            parse_link(text)
            for n in link_names(text):
                resolve(wc, lk, n)
        except (LinkRefused, LinkError) as e:
            cl = cells[lk]
            issues.append(_issue('warn', 'link_refused', 'the formula of %s (=%s in %s) is not taken as a link (%s); '
                                                         '%s keeps its stored value' % (cl.name, cl.formula, cl.cell, e, cl.name),
                                 key=lk, formula=cl.formula))
            continue
        wc['links'][lk] = text
    # Formula cells with no stored result (a file last saved by a program that does not calculate): the
    # loader cannot read them, so they are recomputed from their formulas.
    lost = [k for k, cl in cells.items() if cl.lost]
    if lost:
        pending = set(lost)
        progress = True
        while pending and progress:
            progress = False
            for k in [k for k in lost if k in pending]:
                try:
                    if k in wc['links']:
                        v = link_value(wc, k, skip=pending)
                    elif not xlsx_io.REF.search(cells[k].formula):
                        v = evaluate_link(parse_link(cells[k].formula), lambda n: None)     # a constant such as =0.005
                    else:
                        continue
                except (LinkError, LinkRefused):
                    continue
                block, name = _split(k)
                (wc['main'] if block is None else wc['packages'][block])[name] = v
                pending.discard(k)
                progress = True
        done = [k for k in lost if k not in pending]
        if done:
            linked = [k for k in done if k in wc['links']]
            const = [k for k in done if k not in wc['links']]
            issues.append(_issue('announce', 'recomputed',
                                 '%d linked values have no stored result (the file was last saved by a program that '
                                 'does not calculate), so they were recomputed from their formulas: %s%s'
                                 % (len(linked), ', '.join(linked),
                                    '; so were the constant formulas of %s' % ', '.join(const) if const else ''),
                                 keys=done, linked=linked))
        if pending:
            issues.append(_issue('stop', 'not_recomputable',
                                 '%s %s no stored result and cannot be recomputed from %s formula; open the file in '
                                 'Excel and save it again' % (', '.join(sorted(pending)), 'has' if len(pending) == 1 else 'have',
                                                              'its' if len(pending) == 1 else 'their'),
                                 keys=sorted(pending)))
    _check_required(wc, issues)
    if not found.blocks and not any(i['code'] == 'start_end' for i in issues):
        pkg = {k.lower() for k in engine.keyword_names('package block')}
        inside = [k for k in wc['main'] if k.strip().lower() in pkg]
        issues.append(_issue('note', 'no_package_blocks',
                             'this config defines no package blocks (.START rows), so a package cannot be selected by '
                             'name; the package parameters are read from the main area%s'
                             % (': ' + ', '.join(inside) if inside else ''), keywords=inside))
    return wc, issues


def _check_required(wc, issues):
    have = {k.strip().lower() for k in wc['main']}
    for kw in engine.required_keywords():
        if kw.lower() not in have:
            issues.append(_issue('stop', 'missing_required', '%s is missing, and the loader has no default for it'
                                 % kw, keyword=kw))


def _import_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            wc = json.load(f)
        check_working_config(wc)
    except (OSError, ValueError) as e:
        return None, [_issue('stop', 'json_form', 'cannot use %s as a working config: %s' % (os.path.basename(path), e))]
    issues = []
    for lk, text in list(wc['links'].items()):
        try:
            block = _split(lk)[0]
            if block is not None and block not in wc['packages']:
                raise LinkError('there is no package block %s' % block)
            get_value(wc, lk)
            parse_link(text)
        except (LinkRefused, LinkError, KeyError) as e:
            issues.append(_issue('warn', 'link_refused', 'the link of %s (%r) is not used (%s); %s keeps its value'
                                 % (lk, text, e, lk), key=lk, formula=text))
            del wc['links'][lk]
    # A link may name a key the config lacks (a key renamed by hand): it is kept, and cannot follow until then.
    named, unresolved = set(), {}
    for lk, text in wc['links'].items():
        for n in link_names(text):
            named.add(n)
            try:
                resolve(wc, lk, n)
            except LinkError:
                unresolved.setdefault(n, []).append(lk)
    for n, lks in unresolved.items():
        issues.append(_issue('warn', 'link_unresolved', '%s is not in this config, so the links of %s cannot follow it'
                             % (n, ', '.join(lks)), name=n, keys=lks))
    for block, params, scope in [(None, wc['main'], 'main')] + [(b, p, 'package block') for b, p in wc['packages'].items()]:
        known = {k.lower(): k for k in engine.keyword_names(scope)}
        for k in params:
            key = k if block is None else 'packages.%s.%s' % (block, k)
            if k.strip().lower() in known or k in named or key in named:
                continue
            near = [known[n] for n in difflib.get_close_matches(k.strip().lower(), list(known), n=3, cutoff=0.6)]
            issues.append(_issue('ask', 'unknown_key', 'unknown key %s in %s%s' % (
                k, os.path.basename(path), '' if block is None else ' (package block %s)' % block),
                json_path=json_path_of(key), near=near))
    _check_required(wc, issues)
    return wc, issues

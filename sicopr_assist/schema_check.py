"""assist_schema_check.py -- does the SiCoPR-Assist parameter schema still describe this engine and these references?

In the SiCoPR-Assist repository this file is the module sicopr_assist\\schema_check.py:

    python -m sicopr_assist.schema_check                      # report only, exit 1 on drift
    python -m sicopr_assist.schema_check --remap-from-commit --write
    python -m sicopr_assist.schema_check --self-check         # checks the two readers on text built into this file

It also runs as a plain script from any folder, with --schema and --sicopr given.

The schema (sicopr_param_schema.csv, with sicopr_param_schema.meta.json beside it) was written against one
sicopr.py and a set of reference releases. Both move. This script names what moved:

  engine      keywords the loader reads now and the schema does not hold, and the other way round;
              keywords the schema marks "not read by SiCoPR" that the loader now reads;
              a loader default or scale factor that changed;
              a sicopr.py that is not the one the "port Lnnnn" citations were written for
  references  for every com_ieee8023_*.m found: keywords it reads that the schema does not hold,
              a line number that no longer matches, a default that differs from the schema's
              default_by_release column, and a release newer than the one the schema cites
  releases    VERSION.json supported_matlab_versions against the legal values of COM Version

Nothing here names a release. Releases come from the file names it finds and from VERSION.json, so a new
reference file is picked up by being present.

Where SiCoPR is: --sicopr PATH, else the environment variable SICOPR_REPO, else the folder the installed
sicopr module was imported from. SiCoPR is only read.

It only reads, unless --write is given together with a remap option (--remap-from-commit, which takes the old
sicopr.py from the SiCoPR git history, or --remap-port-lines OLD_SICOPR.py). Then it rewrites the "port Lnnnn"
citations and the port_line column from the old line numbers to the new ones, and lists every citation whose
line changed or disappeared, because those need a person to look at them.

loader_keywords() is also what the product uses to ask whether the engine reads a keyword.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import ast
import csv
import difflib
import glob
import hashlib
import json
import os
import re
import sys

LOADER_FUNCS = ('read_ParamConfigFile', '_read_ParamConfigFile__read_pkg_params')
READERS = ('_read_ParamConfigFile__xls_param', 'xp', '_read_ParamConfigFile__xls_param_txffe')
NOT_READ = 'not read by SiCoPR'


# ----------------------------------------------------------------------------- the reference side
def _split_call(text, start):
    """Arguments of the call whose opening parenthesis is at text[start], split at top-level commas."""
    depth, i, args, cur, quote = 0, start, [], '', False
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    cur += "'"
                    i += 1
                else:
                    quote = False
        elif ch == "'":
            prev = cur.rstrip()[-1:] if cur.strip() else ''
            if prev and (prev.isalnum() or prev in ')]_.'):
                cur += ch                               # a transpose, not the start of a string
            else:
                quote = True
                cur += ch
        elif ch in '([{':
            depth += 1
            if depth > 1:
                cur += ch
        elif ch in ')]}':
            depth -= 1
            if depth == 0:
                args.append(cur.strip())
                return args
            cur += ch
        elif ch == ',' and depth == 1:
            args.append(cur.strip())
            cur = ''
        else:
            cur += ch
        i += 1
    return None


def reference_keywords(text):
    """{keyword: [(line, default text)]} for every xls_parameter(sheet, 'keyword', ...) call that is code."""
    out = {}
    for n, line in enumerate(text.replace('\r\n', '\n').split('\n'), 1):
        code = line.lstrip()
        if code.startswith('%') or code.startswith('function') or 'xls_parameter(' not in line:
            continue
        for m in re.finditer(r'xls_parameter\(', line):
            if '%' in line[:m.start()]:
                break
            args = _split_call(line, m.end() - 1)
            if not args or len(args) < 2 or not (args[1].startswith("'") and args[1].endswith("'")):
                continue
            out.setdefault(args[1][1:-1], []).append((n, re.sub(r'\s+', '', args[3]) if len(args) > 3 else ''))
    return out


def release_of(path):
    m = re.search(r'com_ieee8023_(.+?)\.m$', os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def release_key(name):
    """Sort key that puts 4p9p0 before 4p10p0 and a suffixed build after its plain release."""
    nums = [int(x) for x in re.findall(r'\d+', name.split('_')[0])]
    return (nums, name)


# ----------------------------------------------------------------------------- the engine side
def loader_keywords(source):
    """{(keyword, scope): {'default', 'scale', 'lines'}} read out of the loader with the ast module.

    Covers a keyword given to the reader call directly, and a keyword handed to a small helper defined inside
    the loader that passes it on (the four z_p matrices are read that way)."""
    tree = ast.parse(source)
    out = {}

    def scale_of(v):
        if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Mult):
            for side in (v.left, v.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, (int, float)):
                    return side.value
        txt = ast.unparse(v)
        m = re.match(r'^(1000000000\.0|1e\+?09|1e-09)\s*\*', txt) or re.search(r'\*\s*(1000000000\.0|1e-09)$', txt)
        return float(m.group(1)) if m else None

    def add(key, scope, line, default, scale):
        rec = out.setdefault((key, scope), {'default': None, 'scale': None, 'lines': []})
        rec['lines'].append(line)
        if rec['default'] is None:
            rec['default'] = default
        if rec['scale'] is None:
            rec['scale'] = scale

    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in LOADER_FUNCS]:
        scope = 'main' if fn.name == LOADER_FUNCS[0] else 'package block'
        # A helper takes the keyword first; a second argument may carry the default on to the reader
        # (SiCoPR e1651c4 reads b_max(2..N_b) and b_min(2..N_b) through _dfe_limits(key, default)).
        helpers = {h.name: h for h in ast.walk(fn)
                   if isinstance(h, ast.FunctionDef) and h is not fn and h.args.args and h.name not in READERS}

        def passes_on(h, seen=()):
            arg = h.args.args[0].arg
            for c in [n for n in ast.walk(h) if isinstance(n, ast.Call)]:
                name = getattr(c.func, 'id', '')
                uses = any(isinstance(a, ast.Name) and a.id == arg for a in c.args)
                if name in READERS and uses:
                    rest = [a for a in c.args if not (isinstance(a, ast.Name) and a.id in (arg, 'parameter', 'block'))]
                    rest = [a for a in rest if not (isinstance(a, ast.Constant) and isinstance(a.value, bool))]
                    return (ast.unparse(rest[-1]) if rest else None), True
                if name in helpers and name not in seen and uses:
                    got = passes_on(helpers[name], seen + (h.name,))
                    if got[1]:
                        return got
            return None, False

        via = {n: passes_on(h) for n, h in helpers.items()}
        via = {n: d for n, (d, ok) in via.items() if ok}
        for st in ast.walk(fn):
            if not isinstance(st, (ast.Assign, ast.Return)) or st.value is None:
                continue
            for c in [n for n in ast.walk(st.value) if isinstance(n, ast.Call)]:
                name = getattr(c.func, 'id', '')
                if name in READERS:
                    is_xp = name == 'xp'
                    keynode = c.args[0] if is_xp else (c.args[1] if len(c.args) > 1 else None)
                    if keynode is None or not (isinstance(keynode, ast.Constant) and isinstance(keynode.value, str)):
                        continue
                    if is_xp:
                        default = ast.unparse(c.args[1]) if len(c.args) > 1 else None
                    else:
                        default = ast.unparse(c.args[3]) if len(c.args) > 3 else None
                    for kw in c.keywords:
                        if kw.arg in ('default_value', 'default'):
                            default = ast.unparse(kw.value)
                    add(keynode.value, scope, st.lineno, default, scale_of(st.value))
                elif name in via and c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str):
                    default = via[name]
                    params = [a.arg for a in helpers[name].args.args]
                    if default in params[1:] and params.index(default) < len(c.args):
                        default = ast.unparse(c.args[params.index(default)])
                    add(c.args[0].value, scope, st.lineno, default, None)
    return out


# ----------------------------------------------------------------------------- the comparison
def check(schema_path, repo, matlab_dir=None, quiet=False):
    rows = list(csv.DictReader(open(schema_path, newline='', encoding='utf-8')))
    meta = json.load(open(os.path.splitext(schema_path)[0] + '.meta.json', encoding='utf-8'))
    drift, notes = [], []

    def say(kind, text):
        (drift if kind == 'DRIFT' else notes).append('%-5s %s' % (kind, text))

    # ---- engine
    engine_path = os.path.join(repo, 'sicopr.py')
    src = open(engine_path, encoding='utf-8').read()
    sha = hashlib.sha256(open(engine_path, 'rb').read()).hexdigest()
    same_engine = sha == meta['sicopr']['sha256']
    if same_engine:
        say('OK', 'sicopr.py is the file the port citations were written for (%s...)' % sha[:12])
    else:
        say('DRIFT', 'sicopr.py has changed since the schema was written (schema %s..., now %s...): "port Lnnnn" '
                     'citations are stale until remapped; see --remap-port-lines' % (meta['sicopr']['sha256'][:12], sha[:12]))
    now = loader_keywords(src)
    snap = meta.get('loader_snapshot', {})
    have = {(r['keyword'], r['scope']) for r in rows if r['loaded_field'] != NOT_READ}
    pending = {r['keyword'] for r in rows if r['loaded_field'] == NOT_READ}
    moved = []
    for key, scope in sorted(set(now) - have):
        if key in pending:
            say('DRIFT', 'the loader now reads %s (%s), which the schema marks "%s": complete its row' % (key, scope, NOT_READ))
        else:
            say('DRIFT', 'the loader reads %s (%s, sicopr.py L%s) and the schema has no row for it' % (key, scope, now[(key, scope)]['lines'][0]))
    for key, scope in sorted(have - set(now)):
        if re.fullmatch(r'c\(-?\d+\)', key):
            continue                                    # the transmitter taps are read through a computed name
        say('DRIFT', 'the schema has a row for %s (%s) and the loader no longer reads it' % (key, scope))
    for (key, scope), rec in sorted(now.items()):
        old = snap.get('%s|%s' % (key, scope))
        if not old:
            continue
        if old['default'] != rec['default']:
            say('DRIFT', 'loader default of %s (%s) changed: %s -> %s' % (key, scope, old['default'], rec['default']))
        if old['scale'] != rec['scale']:
            say('DRIFT', 'loader scale factor of %s (%s) changed: %s -> %s' % (key, scope, old['scale'], rec['scale']))
        if not same_engine and old['lines'] != rec['lines']:
            moved.append('%s L%s -> L%s' % (key, old['lines'][0], rec['lines'][0]))
    if moved:
        say('NOTE', '%d keyword reads moved in sicopr.py, for example %s' % (len(moved), '; '.join(moved[:3])))

    # ---- references
    matlab_dir = matlab_dir or os.path.join(repo, 'matlab')
    files = sorted(glob.glob(os.path.join(matlab_dir, 'com_ieee8023_*.m')), key=lambda p: release_key(release_of(p)))
    found = {release_of(p): reference_keywords(open(p, 'rb').read().decode('latin-1')) for p in files}
    cited = meta['cited_release']
    schema_kw = {r['keyword'] for r in rows}
    by_kw = {}
    for r in rows:
        by_kw.setdefault(r['keyword'], r)
    for rel in [x['release'] for x in meta['releases']]:
        if rel not in found:
            say('NOTE', 'reference %s is named in the schema and is not in %s: its line numbers were not checked' % (rel, matlab_dir))
    for rel, kws in found.items():
        missing = sorted(k for k in kws if k not in schema_kw)
        if missing:
            say('DRIFT', 'reference %s reads keywords the schema has no row for: %s' % (rel, ', '.join(missing)))
        wrong = []
        for k, reads in kws.items():
            r = by_kw.get(k)
            if not r:
                continue
            want = ', '.join('L%d' % n for n, _ in reads[:2])
            if rel == cited:
                got = r['matlab_line'].replace('; ', ', ')
            else:
                m = re.search(r'(?:^|; )%s (L[\d, L]+)' % re.escape(rel), r['other_release_lines'])
                got = m.group(1).strip() if m else None
                if got is None and rel not in [x['release'] for x in meta['releases']]:
                    continue                            # a release the schema does not track line by line
            if got != want:
                wrong.append('%s (schema %s, file %s)' % (k, got, want))
        tracked = rel in [x['release'] for x in meta['releases']]
        if wrong:
            say('DRIFT', 'reference %s: %d line numbers differ from the schema: %s%s'
                % (rel, len(wrong), '; '.join(wrong[:6]), ' ...' if len(wrong) > 6 else ''))
        elif tracked:
            say('OK', 'reference %s: %d keywords, every line number matches the schema' % (rel, len(kws)))
        elif not missing:
            say('NOTE', 'reference %s: %d keywords, each has a schema row; the schema does not track its line numbers' % (rel, len(kws)))
        if release_key(rel) > release_key(cited):
            base = found.get(cited, {})
            added = sorted(set(kws) - set(base)) if base else []
            changed = sorted(k for k in set(kws) & set(base) if kws[k][0][1] != base[k][0][1]) if base else []
            say('DRIFT', 'reference %s is newer than the release the schema cites (%s)%s%s: rebuild the schema against it'
                % (rel, cited, '; keywords added: ' + ', '.join(added) if added else '',
                   '; defaults changed: ' + ', '.join(changed) if changed else ''))

    # ---- releases the engine supports
    vpath = os.path.join(repo, 'VERSION.json')
    if os.path.exists(vpath):
        ver = json.load(open(vpath, encoding='utf-8'))
        supported = list(ver.get('supported_matlab_versions', []))
        row = by_kw.get('COM Version')
        listed = [x.strip() for x in row['legal_values'].split(',')] if row else []
        if sorted(supported) != sorted(listed):
            say('DRIFT', 'VERSION.json supports %s; the COM Version row lists %s' % (', '.join(supported), ', '.join(listed)))
        else:
            say('OK', 'COM Version row lists the releases VERSION.json supports: %s' % ', '.join(supported))
        if ver.get('default_matlab_version') != meta['sicopr'].get('default_matlab_version'):
            say('DRIFT', 'default release is now %s (schema written when it was %s): the loader_default of COM Version and of '
                         'any keyword with a default_by_release entry need another look'
                % (ver.get('default_matlab_version'), meta['sicopr'].get('default_matlab_version')))

    if not quiet:
        for line in notes + drift:
            print(line)
        print('%d drift item(s), %d note(s)' % (len(drift), len(notes)))
    return drift, notes


# ----------------------------------------------------------------------------- remapping port citations
PORT = re.compile(r'port ((?:L\d+)(?:(?: to | and |, )L\d+)*)')


def remap_port_lines(schema_path, rules_path, old_engine, new_engine, write, new_commit=None):
    a = open(old_engine, encoding='utf-8').read().split('\n')
    b = open(new_engine, encoding='utf-8').read().split('\n')
    lmap = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            for d in range(i2 - i1):
                lmap[i1 + d + 1] = j1 + d + 1
    lost = []

    def conv_num(n, where):
        t = lmap.get(int(n))
        if t is None:
            lost.append('%s: L%s (%s)' % (where, n, a[int(n) - 1].strip()[:70] if int(n) <= len(a) else 'past the end'))
            return 'L%s?' % n
        return 'L%d' % t

    moved = 0
    for path in [p for p in (schema_path, rules_path) if p and os.path.exists(p)]:
        rows = list(csv.DictReader(open(path, newline='', encoding='utf-8')))
        cols = list(rows[0].keys())
        for r in rows:
            where = '%s %s' % (os.path.basename(path), r.get('id') or r.get('keyword'))
            for c in cols:
                before = r[c]
                if c == 'port_line':
                    r[c] = re.sub(r'L(\d+)', lambda m: conv_num(m.group(1), where), r[c])
                else:
                    r[c] = PORT.sub(lambda m: 'port ' + re.sub(r'L(\d+)', lambda mm: conv_num(mm.group(1), where), m.group(1)), r[c])
                moved += before != r[c]
        if write:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
    if write:
        mpath = os.path.splitext(schema_path)[0] + '.meta.json'
        meta = json.load(open(mpath, encoding='utf-8'))
        src = open(new_engine, encoding='utf-8').read()
        meta['sicopr']['sha256'] = hashlib.sha256(open(new_engine, 'rb').read()).hexdigest()
        meta['sicopr']['lines'] = len(b) - 1
        meta['sicopr']['commit'] = new_commit or 'set this to the commit of the sicopr.py just remapped to'
        meta['loader_snapshot'] = {'%s|%s' % k: v for k, v in loader_keywords(src).items()}
        json.dump(meta, open(mpath, 'w', encoding='utf-8'), indent=1)
    print('%d cell(s) %s' % (moved, 'rewritten' if write else 'would change (run again with --write)'))
    for item in lost:
        print('LOOK  the cited line changed or is gone, marked with "?": %s' % item)
    return lost


# ----------------------------------------------------------------------------- self-check
def self_check():
    ok = True

    def expect(name, cond):
        nonlocal ok
        print('%s %s' % ('PASS' if cond else 'FAIL', name))
        ok = ok and cond

    m = ("param.fb = xls_parameter(parameter, 'f_b')*1e9; % Baud rate\n"
         "%param.old = xls_parameter(parameter, 'gone', false, 3);\n"
         "param.f2 = xls_parameter(parameter, 'f_2', true, param.fb/1e9 )*1e9; % uses f_b\n"
         "x = 1; % see xls_parameter(parameter, 'in a comment')\n"
         "OP.clip = xls_parameter(parameter, 'Clip Method', false, 'Slow');\n")
    k = reference_keywords(m)
    expect('reference: keyword and line', k.get('f_b') == [(1, '')])
    expect('reference: a commented-out read is not a read', 'gone' not in k and 'in a comment' not in k)
    expect('reference: default with a slash and a nested name', k.get('f_2') == [(3, 'param.fb/1e9')])
    expect('reference: text default', k.get('Clip Method') == [(5, "'Slow'")])
    p = ("def _read_ParamConfigFile__read_pkg_params(block):\n"
         "    def xp(key, default=None):\n"
         "        return _read_ParamConfigFile__xls_param(block, key, eval_if_string=True, default_value=default)\n"
         "    pkg.C = xp('C_p', 0.0) * 1e-9\n"
         "    def _load(key):\n"
         "        return xp(key, 7)\n"
         "    pkg.z = _load('z_p (NEXT)')\n"
         "def read_ParamConfigFile(paramFile, OP):\n"
         "    param.fb = _read_ParamConfigFile__xls_param(parameter, 'f_b') * 1e9\n"
         "    param.x = _read_ParamConfigFile__xls_param(parameter, 'DER_0', True, 0.5)\n"
         "    def _dfe_limits(key, default):\n"
         "        return np.asarray(_read_ParamConfigFile__xls_param(parameter, key, True, default))\n"
         "    param.bmax[1:] = _dfe_limits('b_max(2..N_b)', 0.2)\n")
    k = loader_keywords(p)
    expect('loader: required keyword with scale', k.get(('f_b', 'main')) == {'default': None, 'scale': 1e9, 'lines': [9]})
    expect('loader: default', k.get(('DER_0', 'main'), {}).get('default') == '0.5')
    expect('loader: package block keyword with scale', k.get(('C_p', 'package block'), {}).get('scale') == 1e-9)
    expect('loader: keyword read through a helper', k.get(('z_p (NEXT)', 'package block'), {}).get('default') == '7')
    expect('loader: keyword and default read through a helper of two arguments (SiCoPR e1651c4)',
           k.get(('b_max(2..N_b)', 'main'), {}).get('default') == '0.2')
    expect('release order', sorted(['4p10p0', '4p9p0', '4p15p0_adaptive_local_search', '4p15p0'], key=release_key)
           == ['4p9p0', '4p10p0', '4p15p0', '4p15p0_adaptive_local_search'])
    return ok


def find_sicopr(given=None):
    """The folder that holds sicopr.py: the path given, else SICOPR_REPO, else where the module is installed."""
    for cand in (given, os.environ.get('SICOPR_REPO')):
        if cand:
            return cand
    try:
        import importlib.util
        spec = importlib.util.find_spec('sicopr')
        if spec and spec.origin:
            return os.path.dirname(os.path.abspath(spec.origin))
    except (ImportError, ValueError):
        pass
    return None


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--schema', default=os.path.join(here, 'data', 'sicopr_param_schema.csv'))
    ap.add_argument('--rules', default=None, help='default: sicopr_param_rules.csv beside the schema')
    ap.add_argument('--sicopr', '--repo', dest='sicopr', default=None,
                    help='the SiCoPR folder; default: SICOPR_REPO, else the installed sicopr module')
    ap.add_argument('--matlab-dir', default=None, help='default: <sicopr>/matlab')
    ap.add_argument('--remap-port-lines', metavar='OLD_SICOPR.py',
                    help='the sicopr.py the schema was written for, e.g. from: git show <commit>:sicopr.py > old_sicopr.py')
    ap.add_argument('--remap-from-commit', nargs='?', const='', metavar='COMMIT',
                    help='the same remap, with the old sicopr.py taken from the SiCoPR git history; '
                         'without a value, the commit named in the schema meta file')
    ap.add_argument('--write', action='store_true', help='with a remap option: rewrite the files')
    ap.add_argument('--self-check', action='store_true')
    args = ap.parse_args(argv)
    if args.self_check:
        return 0 if self_check() else 1
    repo = find_sicopr(args.sicopr)
    if not repo or not os.path.exists(os.path.join(repo, 'sicopr.py')):
        print('cannot find sicopr.py: give --sicopr PATH or set SICOPR_REPO')
        return 2
    new_commit = None
    if args.remap_from_commit is not None:
        # git writes the old file itself, so no shell redirection is involved (PowerShell's ">" re-encodes text)
        import subprocess
        import tempfile
        commit = args.remap_from_commit or json.load(
            open(os.path.splitext(args.schema)[0] + '.meta.json', encoding='utf-8'))['sicopr']['commit']
        got = subprocess.run(['git', '-C', repo, 'show', '%s:sicopr.py' % commit], capture_output=True)
        if got.returncode != 0:
            print('git could not show sicopr.py at %s: %s' % (commit, got.stderr.decode('utf-8', 'replace').strip()))
            return 2
        fd, old_path = tempfile.mkstemp(suffix='_sicopr_old.py')
        with os.fdopen(fd, 'wb') as fh:
            fh.write(got.stdout)
        args.remap_port_lines = old_path
        head = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True)
        dirty = subprocess.run(['git', '-C', repo, 'status', '--porcelain', '--', 'sicopr.py'], capture_output=True, text=True)
        if head.returncode == 0 and not dirty.stdout.strip():
            new_commit = head.stdout.strip()
        else:
            print('NOTE  sicopr.py is not at a clean commit, so the meta file cannot name one: set sicopr.commit by hand')
    if args.remap_port_lines:
        rules = args.rules or os.path.join(os.path.dirname(args.schema), 'sicopr_param_rules.csv')
        remap_port_lines(args.schema, rules, args.remap_port_lines, os.path.join(repo, 'sicopr.py'), args.write, new_commit)
        return 0
    drift, _ = check(args.schema, repo, args.matlab_dir)
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())

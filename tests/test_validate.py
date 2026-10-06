"""Phase 3: validation against the schema and the rules, checked by calling validate.py directly.

    python tests\\test_validate.py                 every part
    python tests\\test_validate.py --only rules    one or more parts, comma-separated

Gates (prompt section 8, Phase 3):
    G3.1  each of the 84 rules is exercised by at least one check here, or listed in NOT_EXERCISED with
          the reason it cannot be
    G3.2  the must rows of the groups invalid and schema that carry a json_path and a value_after give
          the expected type when the change is handed to validate directly, and pass L3
    G3.3  no release name and no list of legal values in the package code: the text 4p1 appears in no
          sicopr_assist .py file but schema_check.py, and no legal value of a choice is written there

The checks that need the four starting workbooks print SKIP: and are left out when they are absent (or
hidden by SICOPR_ASSIST_HIDE_CONFIGS=1); the rest need no workbook.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import copy
import csv
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

from sicopr_assist import config_model as cm  # noqa: E402
from sicopr_assist import engine, xlsx_io  # noqa: E402
from sicopr_assist import validate as V  # noqa: E402

PACKAGE = os.path.join(fixtures.ROOT, 'sicopr_assist')
TYPE_OF = {'ok': 'PLAN', 'ask': 'QUESTION', 'stop': 'STOP'}
# Legal values that are also plain English and appear in messages as words (project.py: "missing none").
ENGLISH = {'none'}
# A rule no check here can exercise, with the reason (G3.1).
NOT_EXERCISED = {
    'EN09': 'TDR_W_TXPKG = 1 with 2-port channel files: the check needs the channel files of a run, which '
            'validate_inputs reads in Phase 6; a working config alone does not say how many ports they have',
}
# G3.2: the value as the phrase typed it, where the table's value_after is that value after resolution.
TYPED = {'SC01': 50, 'SC09': '1.7 GHz', 'IV04': 'pkg_hir_classb pkg_hir_classb', 'IV13': 'yes'}
EXERCISED = {}                                   # rule id -> the checks that exercised it


def rcheck(rids, name, cond, info=''):
    """A check that exercises the rules named; a passing one counts toward G3.1."""
    rids = (rids,) if isinstance(rids, str) else tuple(rids)
    ok = check('%s: %s' % ('/'.join(rids), name), cond, info)
    if ok:
        for r in rids:
            EXERCISED.setdefault(r, []).append(name)
    return ok


def has(res, rid, status=None):
    return any(f['rule'] == rid and (status is None or f['status'] == status) for f in res['findings'])


def brief(res):
    return {'status': res['status'], 'rule': res['rule'], 'text': res['text'][:200], 'options': res['options'],
            'findings': [(f['status'], f['rule'], f['text'][:120]) for f in res['findings']]}


def table_value(text):
    t = text.strip()
    if re.fullmatch(r'[+-]?[0-9]+', t):
        return int(t)
    if re.fullmatch(r'[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?', t):
        return float(t)
    return text


def bare():
    return {'schema': cm.CONFIG_SCHEMA, 'source': {'file': None, 'sheet': None, 'sha256': None}, 'main': {},
            'packages': {}, 'links': {}}


# ----------------------------------------------------------------------------- no workbook needed
def check_tables():
    rows = V.schema_rows()
    rules = V.rules()
    check('the schema is read once from the package data: 269 rows', len(rows) == 269 and V.schema_rows() is rows, len(rows))
    with open(V.RULES_FILE, newline='', encoding='utf-8') as f:
        ids = [r['id'] for r in csv.DictReader(f)]
    check('the rules are read once: 84 rules with distinct ids', len(rules) == 84 == len(set(ids)) and V.rules() is rules,
          len(rules))
    bad = []
    for r in rows:
        for col in ('stop_if', 'ask_if'):
            try:
                V._conditions(r[col])
            except ValueError as e:
                bad.append('%s %s: %s' % (r['keyword'], col, e))
    check('every stop_if and ask_if of the schema is understood', not bad, bad[:5])
    check('a rule names its keywords from applies_to: LS04 the four z_p matrices, DF07 N_b and its four followers',
          V.rule_keywords('LS04') == ('z_p (TX)', 'z_p (NEXT)', 'z_p (FEXT)', 'z_p (RX)')
          and V.rule_keywords('DF07') == ('N_b', 'N_v', 'N_bx', 'N_bmax', 'N_f'), (V.rule_keywords('LS04'), V.rule_keywords('DF07')))


def check_values():
    vals, lands = V.matlab_range(-0.35, 0.02, 0)
    check('a range that does not land stops short, as MATLAB start:step:end does (SX25: 18 values ending at -0.01)',
          len(vals) == 18 and abs(vals[-1] + 0.01) < 1e-12 and not lands, (len(vals), vals[-1:], lands))
    check('an empty range and a landing range', V.matlab_range(0, 0.02, -0.34)[0] == []
          and V.matlab_range(-0.34, 0.02, 0)[1] and len(V.matlab_range(-0.34, 0.02, 0)[0]) == 18)
    p = V.parse_numbers('[ 8 24 ; 2 2 ; 1.3 1.3 ; 1.5 1.5]')
    check('a matrix value parses with its shape; text that is not numbers does not',
          p[0] == [[8, 24], [2, 2], [1.3, 1.3], [1.5, 1.5]] and V.parse_numbers('PKG_A PKG_B') is None
          and V.parse_numbers('[ ]') == ([], []), p)
    check('a unit is split off a number, and only a known unit after a number',
          V.split_unit('1.7 GHz') == ('1.7', 'GHz') and V.split_unit('40e9Hz') == ('40e9', 'Hz')
          and V.split_unit('1e-4') is None and V.split_unit('PKG_A') is None and V.split_unit('1e-8 V^2/GHz') == ('1e-8', 'V^2/GHz'))
    wc = bare()
    cases = [('SC09', '/main/beta_x', '1.7 GHz', 1.7e9, True), ('RS14', '/main/flim', '50 GHz', 5e10, True),
             ('RS15', '/main/T_r', '5 ps', 0.005, True), ('RS16', '/main/Delta_f', '5 MHz', 0.005, True),
             ('RS17', '/main/f_z', '40e9 Hz', 40, True), ('RS19', '/main/z_bp (TX)', '0.5 inch', 12.7, True),
             ('RS18', '/main/eta_0', '1e-8 V^2/GHz', 1e-8, False)]
    for rid, jp, typed, want, announced in cases:
        v, f = V.check_value(wc, jp, typed)
        conv = [x for x in f if x['status'] == 'announce']
        check('units (%s): %s is written as %s in the stored unit%s' % (rid, typed, V.short(want), ', and the conversion is '
              'announced' if announced else ', with nothing to announce'),
              v == want and bool(conv) == announced and not [x for x in f if x['status'] != 'announce'], (v, f))
    v, f = V.check_value(wc, '/main/f_b', '53 mV')
    check('units: a unit the keyword does not accept asks, offering the accepted ones',
          [x['status'] for x in f] == ['ask'] and f[0]['options'] == ['53 GBd', '53 Bd', 'cancel'], f)

    real = engine.supported_releases
    engine.supported_releases = lambda: ['r1x', 'r2x']
    try:
        bad, fb = V.check_value(wc, '/main/COM Version', 'r9x')
        good, fg = V.check_value(wc, '/main/COM Version', 'r2x')
    finally:
        engine.supported_releases = real
    rcheck('LS11', 'the releases COM Version may name are read from VERSION.json when the tool runs (an engine '
           'that supports made-up releases r1x, r2x: r9x asks with those two, r2x passes)',
           [x['rule'] for x in fb] == ['LS11'] and fb[0]['options'] == ['r1x', 'r2x'] and not fg, (fb, fg))
    v, f = V.check_value(wc, '/main/COM Version', 'not-a-release')
    rcheck('LS11', 'with the SiCoPR under test the options are its VERSION.json supported_matlab_versions',
           f and f[0]['status'] == 'ask' and f[0]['options'] == engine.supported_releases(), f)


def check_static():
    """G3.3: no release name and no list of legal values in the package code."""
    hits = []
    for p in sorted(glob.glob(os.path.join(PACKAGE, '*.py'))):
        if os.path.basename(p) == 'schema_check.py':
            continue
        with open(p, encoding='utf-8') as f:
            for n, line in enumerate(f, 1):
                if '4p1' in line:
                    hits.append('%s:%d' % (os.path.basename(p), n))
    check('G3.3: no sicopr_assist .py file but schema_check.py holds the text 4p1', not hits, hits)
    legal = set()
    for r in V.schema_rows():
        if r['kind'] in ('choice', 'switch'):
            for x in r['legal_values'].split(','):
                x = x.strip()
                if x and not re.fullmatch(r'[0-9.]+', x) and x not in ENGLISH:
                    legal.add(x)
    legal.update(engine.supported_releases())
    found = []
    for p in sorted(glob.glob(os.path.join(PACKAGE, '*.py'))):
        if os.path.basename(p) == 'schema_check.py':
            continue
        with open(p, encoding='utf-8') as f:
            text = f.read()
        for x in sorted(legal):
            if re.search(r"""['"]%s['"]""" % re.escape(x), text):
                found.append('%s in %s' % (x, os.path.basename(p)))
    check('G3.3: no legal value of a choice (%d values, the releases among them) is written as a literal in the package '
          'code' % len(legal), not found, found)


# ----------------------------------------------------------------------------- the rules, one by one
def check_rules(fx, tmp):
    case1 = cm.import_config(fx.configs['Case1'])[0]

    def run(changes, base=None, **kw):
        return V.validate(copy.deepcopy(base or case1), changes, **kw)

    def ask(rid, name, changes, base=None, options=None):
        r = run(changes, base)
        cond = r['status'] == 'ask' and has(r, rid, 'ask') and (options is None or r['options'] == options)
        return rcheck(rid, name, cond, brief(r))

    def stop(rid, name, changes, base=None, refused=False):
        r = run(changes, base)
        cond = r['status'] == 'stop' and has(r, rid, 'stop') and (not refused or r['config'] is None)
        return rcheck(rid, name, cond, brief(r))

    def announce(rid, name, changes, base=None, status='ok'):
        r = run(changes, base)
        cond = has(r, rid, 'announce') and (status is None or r['status'] == status)
        return rcheck(rid, name, cond, brief(r))

    # Q: limits by kind of quantity
    stop('Q01', 'f_b = -5 stops before the working config is touched (IV10)', {'/main/f_b': -5}, refused=True)
    ask('Q02', 'f_2 = 0 asks', {'/main/f_2': 0}, options=['run it anyway', 'cancel'])
    stop('Q02', 'Delta_f = 0 stops, as the rule says for Delta_f (IV12)', {'/main/Delta_f': 0}, refused=True)
    ask('Q03', 'f_v = 0 asks', {'/main/f_v': 0})
    ask('Q04', 'C_b = -1e-5 asks', {'/main/C_b': -1e-5})
    ask('Q05', 'L_s = -1 asks', {'/main/L_s': -1})
    ask('Q06', 'R_0 = 0 asks with run it anyway and cancel (SC03)', {'/main/R_0': 0}, options=['run it anyway', 'cancel'])
    ask('Q07', 'z_bp (TX) = -1 asks', {'/main/z_bp (TX)': -1})
    ask('Q08', 'board_tl_tau = 0 asks', {'/main/board_tl_tau': 0})
    ask('Q09', 'TR_TDR = -1 asks', {'/main/TR_TDR': -1})
    r1, r2 = run({'/main/fixture delay time': -1}), run({'/main/fixture delay time': -2})
    rcheck('Q09', 'fixture delay time = -1 (not set) passes; -2 asks', not has(r1, 'Q09') and has(r2, 'Q09', 'ask'),
           (brief(r1), brief(r2)))
    ask('Q10', 'A_ft = -0.1 asks', {'/main/A_ft': -0.1})
    ask('Q11', 'sigma_RJ = -0.01 asks', {'/main/sigma_RJ': -0.01})
    ask('Q12', 'eta_0 = -1e-8 asks', {'/main/eta_0': -1e-8})
    stop('Q13', 'DER_0 = 2 stops (SC02)', {'/main/DER_0': 2}, refused=True)
    stop('Q13', 'P_peak = 0 stops', {'/main/P_peak': 0})
    ask('Q14', 'c(-1) = [-1.5:0.5:0] asks: an element of the range is below -1', {'/main/c(-1)': '[-1.5:0.5:0]'})
    ask('Q14', 'b_min(1) = 0.1 asks: a b_min limit above 0', {'/main/b_min(1)': 0.1})
    stop('Q15', 'N_bg = -1 stops', {'/main/N_bg': -1})
    r = run({'/main/COM Pass threshold': -50})
    rcheck('Q16', 'a level in dB has no limit: COM Pass threshold = -50 passes', r['status'] == 'ok', brief(r))
    r = run({'/main/SAVE_FIGURES': 'yes'})
    rcheck('Q17', 'SAVE_FIGURES = yes is written as 1 and announced (IV13)', r['status'] == 'ok' and has(r, 'Q17', 'announce')
           and r['values'] == {'/main/SAVE_FIGURES': 1}, brief(r))
    ask('Q17', 'SAVE_FIGURES = maybe asks with 0 and 1 (IV14)', {'/main/SAVE_FIGURES': 'maybe'}, options=['0', '1'])
    ask('Q18', 'Clip Method = Medium asks with the listed values (IV09)', {'/main/Clip Method': 'Medium'}, options=['Slow', 'Fast'])
    ask('Q18', 'L = 3 asks with the listed values and keep 3, since the schema stops only below 2 (IV17)', {'/main/L': 3},
        options=['2', '4', '6', '8', '16', 'keep 3'])
    r = run({'/main/Clip Method': 'fast'})
    rcheck('Q18', 'a choice is matched ignoring case: fast is written as Fast', r['values'] == {'/main/Clip Method': 'Fast'}
           and has(r, 'Q18', 'announce'), brief(r))
    ask('Q19', 'beta_x = 1.7 asks whether GHz was meant (SC08)', {'/main/beta_x': 1.7},
        options=['take it as 1.7 GHz and write 1.7e9', 'keep 1.7 as typed', 'cancel'])
    ask('Q19', 'f_hp = 1.7 asks whether GHz was meant', {'/main/f_hp': 1.7})

    # LS: loader stops
    blocks = list(case1['packages'])
    ask('LS01', 'PKG_NAME naming a block the config lacks asks with the blocks that exist (IV03)',
        {'/main/PKG_NAME': 'PKG_Foo PKG_Foo'}, options=blocks)
    v06 = fx.working_config('V06')
    r = run({'/main/PKG_NAME': blocks[0]}, base=v06)
    cand = cm.apply_changes(v06, {'/main/PKG_NAME': blocks[0]})['config']
    _, lerr = cm.loaded_fields(cand)
    rcheck('LS02', 'PKG_NAME in a config with no .START blocks (V06) stops, as the loader does',
           r['status'] == 'stop' and has(r, 'LS02', 'stop') and lerr and 'START' in lerr, (brief(r), lerr))
    csv_path = os.path.join(tmp, 'no_end.csv')
    text = cm.run_csv_text(case1)
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(text[:text.rindex('.END')])
    wc, r = V.validate_import(csv_path)
    rcheck('LS03', 'a config whose .START and .END rows differ in number stops at import', r['status'] == 'stop'
           and has(r, 'LS03', 'stop'), brief(r))
    ask('LS04', 'z_p (TX) with two cases in a block whose other matrices keep four asks (IV15)',
        {'/packages/PKG_HiR_CLASSB/z_p (TX)': '[8 24 ; 2 2 ; 1.3 1.3 ; 1.5 1.5]'},
        options=['apply the same matrix to all four', 'cancel'])
    r = run({'/packages/PKG_HiR_CLASSB/z_p (TX)': '[8 24 ; 2 2 ; 1.3 1.3 ; 1.5 1.5]'})
    fixed = r['answers']['apply the same matrix to all four']['set']
    r2 = run(dict(fixed, **{'/packages/PKG_HiR_CLASSB/z_p (TX)': '[8 24 ; 2 2 ; 1.3 1.3 ; 1.5 1.5]'}))
    rcheck('LS04', 'its first answer applies the matrix to all four, and that loads', not has(r2, 'LS04')
           and r2['effect']['error'] is None, brief(r2))
    stop('LS05', 'z_p (TX) in the main area with 3 values for each case stops', {'/main/z_p (TX)': '[8 24 ; 1 1 ; 1 1]'})
    ask('LS06', 'N_b = 0 with MLSE = 1 asks (IV05)', {'/main/N_b': 0}, options=['also set MLSE = 0', 'cancel'])
    ask('LS07', 'MLSE = 1 with T_O above 0 in a C2M config asks', {'/main/T_O': 5, '/main/PMD_type': 'C2M'},
        options=['set MLSE = 0', 'cancel'])
    r = run({'/main/PSDRXCAL': 1, '/main/FFE_OPT_METHOD': 'FV-LMS'})
    rcheck('LS08', 'PSDRXCAL = 1 with FFE_OPT_METHOD other than MMSE stops, with the loader message',
           r['status'] == 'stop' and has(r, 'LS08', 'stop') and 'the loader says' in r['text'], brief(r))
    r = run({'/main/G_Qual': '[1 2 ; 3 4]'})
    rcheck('LS09', 'G_Qual with no matching G2_Qual stops, with the loader message', r['status'] == 'stop'
           and has(r, 'LS09', 'stop') and 'the loader says' in r['text'], brief(r))
    ask('LS10', 'TDECQ = foo asks with the list', {'/main/TDECQ': 'foo'}, options=['0', 'none', 'vma'])
    ask('LS11', 'COM Version = a release this SiCoPR lacks asks with VERSION.json supported_matlab_versions',
        {'/main/COM Version': 'not-a-release'}, options=engine.supported_releases())
    stop('LS12', 'N_b = 1.5 stops: a whole-number keyword given as a fraction', {'/main/N_b': 1.5}, refused=True)
    stop('LS12', 'ts_anchor = 1.5 stops: a whole-number choice given as a fraction', {'/main/ts_anchor': 1.5}, refused=True)
    for label, rid, code in (('V10', 'LS13', 'duplicate_keyword'), ('V11', 'LS14', 'missing_required')):
        q = os.path.join(tmp, label + '.xlsx')
        shutil.copyfile(fx.configs[label], q)
        wc, r = V.validate_import(q)
        rcheck(rid, 'the import of %s stops (%s), and the rule is named' % (label, code), r['status'] == 'stop'
               and has(r, rid, 'stop'), brief(r))

    # LF: settings the loader changes
    stop('LF01', 'COM_CONTRIBUTION 1 -> 0 with MLSE = 1 has no effect: the loader turns it off (PA028)',
         {'/main/COM_CONTRIBUTION': 0})
    announce('LF02', 'PMD_type = C2M turns EW on', {'/main/PMD_type': 'C2M', '/main/EW': 0})
    announce('LF03', 'EH_min other than 0 with PMD_type C2C changes PHY', {'/main/EH_min': 5})
    r = run({'/main/T_r_meas_point': 1})
    rcheck('LF04', 'T_r_meas_point = 1 with FORCE_TR = 1 is named under the rule (the loader sets it to 0)', has(r, 'LF04'),
           brief(r))
    r = run({'/main/TDR': 0, '/main/WC_PORTZ': 1})
    rcheck('LF05', 'WC_PORTZ = 1 turns TDR on, announced, and ERL then has its TDR (no NC01)', has(r, 'LF05', 'announce')
           and not has(r, 'NC01'), brief(r))
    announce('LF06', 'TDMODE = 1 turns off ERL, TDR and the rest', {'/main/TDMODE': 1}, status=None)
    announce('LF07', 'RX_CALIBRATION = 1 with MMSE and a receiver FFE becomes PSDRXCAL', {'/main/RX_CALIBRATION': 1}, status=None)
    announce('LF08', 'N_bg = 0 sets N_bmax to N_b (N_f = 80, N_b = 1)', {'/main/N_bg': 0}, status=None)
    announce('LF09', 'g_DC_HP given sets the CTLE type', {'/main/g_DC_HP': '[-3:1:0]'})
    announce('LF10', 'Gx = 1 sets Grr to 2', {'/main/Gx': 1}, status=None)
    r = run({'/main/flim': 50})
    rcheck('LF11', 'flim = 50 is taken as GHz, written in Hz and announced (SC01)', r['status'] == 'ok'
           and r['values'] == {'/main/flim': 5e10} and has(r, 'LF11', 'announce'), brief(r))
    announce('LF12', 'a receiver FFE with N_bg above 0', {'/main/ffe_pre_tap_len': 2}, status=None)
    stop('LF13', 'a main-area C_p with PKG_NAME set has no effect', {'/main/C_p': '[0.2e-4 0.2e-4]'})
    stop('LF14', 'b_max(2..N_b) with N_b = 1 has no effect', {'/main/b_max(2..N_b)': 0.3})

    # DF: defaults that follow another keyword, announced when the first moves and the second is absent
    new_values = {'DER_0': 1e-4, 'COM Pass threshold': 2, 'f_b': 53.125, 'f_2': 50, 'f_min': 0.02, 'N_b': 2,
                  'A_fe': 0.4, 'A_ne': 0.4, 'R_0': 50, 'b_max(1)': 0.3, 'b_max(2..N_b)': 0.1, 'MLSD': 1,
                  'PMD_type': 'C2M', 'COMPUTE_RILN': 1}
    for rid, r in V.rules().items():
        if r['kind'] != 'default follows another keyword' or rid == 'DF17':
            continue
        kws = V.rule_keywords(rid)
        base = copy.deepcopy(case1)
        for k in kws[1:]:
            base['main'].pop(k, None)
            base['links'].pop(k, None)
        res = run({'/main/' + kws[0]: new_values[kws[0]]}, base=base)
        rcheck(rid, '%s moves, %s absent: announced' % (kws[0], ', '.join(kws[1:])), has(res, rid, 'announce'), brief(res))
    no_fz = copy.deepcopy(case1)
    no_fz['main'].pop('f_z')
    no_fz['links'].pop('f_z', None)
    r = V.validate_config(no_fz)
    rcheck('DF17', 'a config without f_z asks at import: its default cannot be used (SC06)', r['status'] == 'ask'
           and has(r, 'DF17', 'ask') and r['options'] == ['give a value', 'cancel'], brief(r))

    # EN: engine checks
    announce('EN01', 'Clip Method with N_qb = 0 runs, and the results will not change (SX26)',
             {'/main/Clip Method': 'Fast', '/main/N_qb': 0})
    ask('EN02', 'TS_SRCH_MODE = box asks with the list (IV08)', {'/main/TS_SRCH_MODE': 'box'}, options=['full-sweep', 'middle'])
    ask('EN03', 'ts_anchor = 5 asks with the list', {'/main/ts_anchor': 5}, options=['0', '1', '2'])
    ask('EN04', 'Include PCB = 3 asks with 0, 1, 2 (SC05)', {'/main/Include PCB': 3}, options=['0', '1', '2'])
    r = run({'/main/Include PCB': 2})
    rcheck('EN04', 'Include PCB = 2 is a plan (SC04)', r['status'] == 'ok', brief(r))
    announce('EN05', 'a board keyword with Include PCB = 0 runs, and the results will not change', {'/main/z_bp (TX)': 100})
    ask('EN06', 'FFE_OPT_METHOD = WIENER-HOPF asks with the list', {'/main/FFE_OPT_METHOD': 'WIENER-HOPF'})
    no_hp = copy.deepcopy(case1)
    no_hp['main'].pop('g_DC_HP')                      # else the loader sets the CTLE type itself (LF09)
    ask('EN07', 'CTLE_type = XYZ asks with the list', {'/main/CTLE_type': 'XYZ'}, base=no_hp)
    ask('EN07', 'f_HP_Z given (CTLE type set by the loader) with RX_CALIBRATION = 1 and no receiver FFE asks',
        {'/main/f_HP_Z': 1, '/main/RX_CALIBRATION': 1, '/main/ffe_pre_tap_len': 0, '/main/ffe_post_tap_len': 0})
    rit = V.rule_keywords('EN08')[0]
    need = [x for x in re.match(r'(.+?) also need', V.schema_row(rit)['note']).group(1).split(' and ')
            if x != V.schema_row(rit)['loader_default'].strip("'")][0]      # the default would change nothing
    ask('EN08', '%s = %s with f_hp not set asks' % (rit, need), {'/main/' + rit: need})
    ask('EN10', 'an S-parameter extrapolation policy that is not listed asks', {'/main/S-parameter magnitude extrapolation policy': 'cubic'})
    stop('EN11', 'M = 0 stops', {'/main/M': 0}, refused=True)

    # NC: not checked by the loader
    ask('NC01', 'TDR = 0 with ERL = 1 asks (IV19)', {'/main/TDR': 0}, options=['also set ERL = 0', 'keep TDR on', 'cancel'])
    ask('NC02', 'z_p select = 5 asks with the case numbers (IV01)', {'/main/z_p select': '[ 5 ]'}, options=['1', '2', '3', '4'])
    r = run({'/main/z_p select': '[ 0 ]'})
    rcheck('NC02', 'z_p select = 0 says case numbers start at 1 (IV02)', has(r, 'NC02', 'ask') and 'start at 1' in r['text'],
           brief(r))
    sel = xlsx_io.selection_lists(fx.configs['Case1'])
    orders = sel.get('ports', [])
    r = V.validate(copy.deepcopy(case1), {'/main/Port Order': '[1 2 3]'}, selections=sel)
    rcheck('NC03', 'Port Order = [1 2 3] asks with the eight orders of the selections_and_tables sheet (IV06)',
           has(r, 'NC03', 'ask') and len(orders) == 8 and r['options'] == orders, (brief(r), orders))
    r = run({'/main/Port Order': '[1 1 2 4]'})
    rcheck('NC03', 'Port Order = [1 1 2 4] says port 1 is used twice (IV07)', has(r, 'NC03', 'ask') and 'port 1 used twice' in r['text'],
           brief(r))
    ask('NC04', 'package_Z_c in a block with 3 rows against 4 line sections asks',
        {'/packages/%s/package_Z_c' % blocks[0]: '[87.5 87.5 ; 95 95 ; 100 100]'})
    stop('NC05', 'c(-1) = [0:.02:-0.34] stops: the range produces no values (IV16)', {'/main/c(-1)': '[0:.02:-0.34]'}, refused=True)
    ask('NC05', 'c(-1) = [-0.35:.02:0] asks: the range does not land on its end (SX25)', {'/main/c(-1)': '[-0.35:.02:0]'},
        options=['change the end to -0.01', 'keep it as typed', 'cancel'])
    announce('NC06', 'SAVE_CONFIG2MAT = 1 without DIAGNOSTICS', {'/main/SAVE_CONFIG2MAT': 1, '/main/DIAGNOSTICS': 0}, status=None)

    # VR: releases
    older = [x for x in engine.supported_releases() if x != engine.default_release()]
    w_old = cm.apply_changes(case1, {'/main/COM Version': older[0]})['config']
    real = engine.reads_keyword
    engine.reads_keyword = lambda name, scope=None: False if name == 'T_dev' else real(name, scope)
    try:
        r = run({'/main/T_dev': 2}, base=w_old)
    finally:
        engine.reads_keyword = real
    rcheck('VR01', 'T_dev with an engine that does not read it (simulated) stops: no effect', r['status'] == 'stop'
           and has(r, 'VR01', 'stop'), brief(r))
    r = run({'/main/COM Version': older[0]})
    rcheck('VR02', 'COM Version = %s is a plan that announces the release before and after (SC14)' % older[0],
           r['status'] == 'ok' and has(r, 'VR02', 'announce') and engine.default_release() in r['announce'][0], brief(r))
    r = run({'/main/COM Version': engine.default_release()})
    rcheck('VR02', 'COM Version = the default release stops: the engine inputs would not change (SC15)',
           r['status'] == 'stop' and has(r, 'VR02', 'stop'), brief(r))
    rcheck('VR02', 'the release a run emulates: COM Version when the config has one, else the default of VERSION.json',
           V.emulated_release(case1) == engine.default_release() and V.emulated_release(w_old) == older[0])
    no_clip = copy.deepcopy(case1)
    no_clip['main'].pop('Clip Method')
    got = [run({'/main/COM Version': rel}, base=no_clip) for rel in older]
    rcheck('VR03', 'with Clip Method absent, a change of COM Version to a release with another default announces it',
           any(has(x, 'VR03', 'announce') for x in got), [brief(x) for x in got])


# ----------------------------------------------------------------------------- G3.2
def g32_rows(rows):
    out = []
    for r in rows:
        if r['group'] in ('invalid', 'schema') and r['priority'] == 'must' and r['json_path'].strip() and r['value_after'].strip():
            out.append(r)
    return out


def check_g32(fx, rows):
    import scoring
    from sicopr_assist import core
    sc = scoring.Scorer(fx, rows, core.handle)
    sel = g32_rows(rows)
    pairs = typed_ok = l3_ok = l3_n = 0
    misses = []
    t0 = time.time()
    for r in sel:
        if not scoring.applies(r)[0]:
            continue
        jp = r['json_path'].strip()
        for label in scoring.labels_of(r):
            pairs += 1
            ctx = sc.context(r, label)
            try:
                handed = [('value_after', table_value(r['value_after']))]
                if r['id'] in TYPED:
                    handed.append(('as typed', TYPED[r['id']]))
                ok = True
                for how, v in handed:
                    res = V.validate(ctx.prior_wc, {jp: v})
                    got = TYPE_OF[res['status']]
                    if got != r['expected_type']:
                        ok = False
                        misses.append('%s %s (%s): expected %s, got %s: %s' % (r['id'], label, how, r['expected_type'], got,
                                                                               res['text'][:120]))
                        continue
                    if 'loader' in r['verified']:
                        l3_n += 1
                        o = core.outcome('PLAN', changes=[{'json_path': jp, 'before': None, 'after': res['values'].get(jp, v),
                                                           'kind': 'set', 'applied': res['status'] == 'ok'}])
                        p3, note = sc.level3(r, ctx, o)
                        l3_ok += p3
                        if not p3:
                            ok = False
                            misses.append('%s %s (%s): L3 %s' % (r['id'], label, how, note))
                typed_ok += ok
            finally:
                fx.remove_project(ctx.root)
    print('G3.2: %d must rows of the groups invalid and schema with a json_path and a value_after (%d apply), %d row and '
          'config pairs; %d pairs give the expected type and pass L3 (%d L3 comparisons, %d pass) (%.0f s)'
          % (len(sel), sum(1 for r in sel if scoring.applies(r)[0]), pairs, typed_ok, l3_n, l3_ok, time.time() - t0))
    check('G3.2: every pair gives the expected type when the change is handed to validate directly, and passes L3',
          pairs and typed_ok == pairs and l3_ok == l3_n, misses[:10])
    return pairs, typed_ok


# ----------------------------------------------------------------------------- more behaviour
def check_more(fx, tmp):
    case1 = cm.import_config(fx.configs['Case1'])[0]
    r = V.validate(case1, {'/main/R_0': 0}, allow=['Q06'])
    check('allow: a value the schema asks about runs when the user chooses it (R_0 = 0, run it anyway)',
          r['status'] == 'ok' and r['announce'] and r['announce'][0].endswith('run as asked'), brief(r))
    r = V.validate(case1, {'/main/DER_0': 0.0002})
    check('a value the config already holds stops and says so (PA016, EN30)', r['status'] == 'stop' and 'already' in r['text']
          and r['rule'] is None, brief(r))
    r = V.validate(case1, {'/packages/PKG_HiR_CLASSB/package_tl_gamma0_a1_a2': '[0 0.0009909 0.0002772]'})
    check('an edit to a package block PKG_NAME does not select asks whether to switch to it (PA121)',
          r['status'] == 'ask' and r['findings'][-1]['code'] == V.UNSELECTED_BLOCK
          and r['options'] == ['also switch TX and RX to PKG_HiR_CLASSB and run',
                               'save the edit and run with the current package', 'cancel'], brief(r))
    r2 = V.validate(case1, {'/packages/PKG_HiR_CLASSB/package_tl_gamma0_a1_a2': '[0 0.0009909 0.0002772]'},
                    allow=[V.UNSELECTED_BLOCK])
    check('... and saving the edit with the current package runs when chosen', r2['status'] == 'ok', brief(r2))
    r = V.validate(case1, {'/main/PKG_NAME': 'pkg_hir_classb pkg_hir_classb'})
    check('a block name typed in another case is written in the sheet spelling and announced (IV04)',
          r['status'] == 'ok' and r['values'] == {'/main/PKG_NAME': 'PKG_HiR_CLASSB PKG_HiR_CLASSB'} and has(r, 'LS01', 'announce'),
          brief(r))
    r = V.validate(case1, {'/main/package_Z_c': '[1 1 ; 2 2 ; 3 3]'})
    check('a config the loader refuses with no rule to explain it stops with the loader message',
          r['status'] == 'stop' and r['rule'] is None and 'loader refuses' in r['text'], brief(r))
    r = V.validate(case1, {'/main/f_b': 53.125})
    check('f_b = 53.125 is a plan, its seven linked values move with it, and the result is plain data (JSON)',
          r['status'] == 'ok' and len([c for c in r['changes'] if c['kind'] == 'linked']) == 7 and json.dumps(r), brief(r))
    bad = []
    for label in fixtures.CASES:
        wc, res = V.validate_import(fx.configs[label])
        if res['status'] != 'ok':
            bad.append((label, brief(res)))
    for p in engine.shipped_workbooks():
        q = os.path.join(tmp, 'shipped_' + os.path.basename(p))
        shutil.copyfile(p, q)
        wc, res = V.validate_import(q)
        if res['status'] != 'ok':
            bad.append((os.path.basename(p), brief(res)))
    check('validate_import: the four starting workbooks and the %d SiCoPR ships are ok as they stand'
          % len(engine.shipped_workbooks()), not bad, bad)
    check('the selections sheet lists the eight port orders under ports', len(xlsx_io.selection_lists(fx.configs['Case1'])
                                                                            .get('ports', [])) == 8)


def check_g31():
    names = set(V.rules())
    done = set(EXERCISED)
    missing = sorted(names - done - set(NOT_EXERCISED))
    both = sorted(done & set(NOT_EXERCISED))
    print('G3.1: %d of %d rules exercised by a check here; not exercised, with the reason: %s'
          % (len(done & names), len(names), ', '.join('%s (%s)' % (k, v) for k, v in NOT_EXERCISED.items())))
    check('G3.1: every rule is exercised by a check or listed with the reason it cannot be',
          not missing and not both and set(NOT_EXERCISED) <= names, {'missing': missing, 'exercised but listed': both})


PARTS = ('tables', 'values', 'static', 'rules', 'g32', 'more')


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated parts to run, of: %s (default: all)' % ', '.join(PARTS))
    args = ap.parse_args(argv)
    parts = set(args.only.split(',')) if args.only else set(PARTS)
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix='sicopr_assist_test_validate_')
    try:
        if 'tables' in parts:
            check_tables()
        if 'values' in parts:
            check_values()
        if 'static' in parts:
            check_static()
        if parts & {'rules', 'g32', 'more'}:
            with fixtures.Fixtures() as fx:
                if not fx.available:
                    print('SKIP: the rule checks, G3.1 and G3.2 need the four starting workbooks (Case1 to Case4), '
                          'found by SHA-256 in tests\\configs or SICOPR_ASSIST_CONFIGS')
                else:
                    rows = list(csv.DictReader(open(os.path.join(fixtures.HERE, 'sicopr_use_cases.csv'),
                                                    newline='', encoding='utf-8')))
                    if 'rules' in parts:
                        check_rules(fx, tmp)
                        if 'values' in parts:
                            check_g31()
                    if 'g32' in parts:
                        check_g32(fx, rows)
                    if 'more' in parts:
                        check_more(fx, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('test_validate.py: %.0f s' % (time.time() - t0))
    finish()


if __name__ == '__main__':
    sys.exit(main())

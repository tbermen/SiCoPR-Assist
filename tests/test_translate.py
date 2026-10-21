"""Translator mode (Decision 26, Phase V2-10): the setting and its override, the history and feedback fields, the
provenance of the preset values, the overlay, the miss gate and the shipped template.

V10.5  every command in translator mode records the user's wording, whether the strict core missed it, the rule,
       synonym or preset that fired, the phrase handed to the core, any proposal, and whether the user confirmed,
       changed or declined it, with the translator's name, version and rules SHA-256; Export feedback carries them
V10.6  no value whose only source is a document marked redistribute NO is in the repository: the preset file's source
       column says where each value comes from, the redistribute-NO ones are markers (overlay), and with the local
       overlay at hand none of its values is in any text file of the repository; the overlay loads from the path the
       setting preset_overlay names, and without it the presets that need it stop and say what is missing

The use-case rows of groups PS, PP, CF and SY score the outcomes themselves (tests\\test_use_cases.py, gate V10.2).

    python tests\\test_translate.py
    $env:SICOPR_ASSIST_OVERLAY = "<the local overlay.csv>"     the checks that need the overlay (else SKIP)
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

PKG = os.path.join(ROOT, 'sicopr_assist')
PRESETS = os.path.join(PKG, 'data', 'presets.csv')
TEMPLATE = os.path.join(PKG, 'data', 'templates', 'config_com-4p13p0_802p3dj_d2p3_200G_C2M_TP0_TP2_Egress_26_01_27.xlsx')
TEMPLATE_SHA256 = '57e9da3f17dee495f386622f2bab30895a55b2ed40f2df997636d1a73af62e6e'   # 802-COM com_code 4.17.0
# documents marked redistribute NO (interface_presets.csv, receiver_eq_options.csv): a value cited to one of these
# alone may not be in the repository
NO_SOURCES = re.compile(r'802\.3ck-2022|P802\.3dj/D2\.4|\bD2\.4\b|COM 3\.70|OIF|oif20', re.I)
ENV = 'SICOPR_ASSIST_TRANSLATOR'
OVERLAY_ENV = 'SICOPR_ASSIST_OVERLAY'
TRANSLATION_FIELDS = ('translator', 'version', 'rules_sha256', 'wording', 'strict', 'fired', 'preset', 'phrase',
                      'proposal', 'used', 'response')


def overlay_file():
    p = os.environ.get(OVERLAY_ENV, '').strip()
    return p if p and os.path.isfile(p) else None


# ----------------------------------------------------------------------------- V10.6 provenance
def provenance(fx=None):
    with open(PRESETS, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    check('V10.6: the preset file has the columns preset, keyword, value, when, source',
          rows and list(rows[0]) == ['preset', 'keyword', 'value', 'when', 'source'], list(rows[0]) if rows else None)
    check('V10.6: every preset value names its source', all(r['source'].strip() for r in rows),
          [r['preset'] + ' ' + r['keyword'] for r in rows if not r['source'].strip()])
    bad = [(r['preset'], r['keyword'], r['value']) for r in rows if NO_SOURCES.search(r['source'])
           and r['value'] != 'overlay']
    check('V10.6: a value whose source is a redistribute NO document is never written in the preset file, only the '
          'marker overlay', not bad, bad)
    marked = [r for r in rows if r['value'] == 'overlay']
    check('V10.6: every overlay marker says which redistribute NO document holds the value',
          marked and all(r['source'].startswith('overlay:') and NO_SOURCES.search(r['source']) for r in marked),
          [r['preset'] + ' ' + r['keyword'] for r in marked if not NO_SOURCES.search(r['source'])])
    path = overlay_file()
    if path is None:
        print('SKIP: V10.6 overlay search needs the local overlay (%s): no repository file is compared with it' % OVERLAY_ENV)
        return
    with open(path, newline='', encoding='utf-8') as f:
        ov = list(csv.DictReader(f))
    # pairs that the repository may hold for another reason: a value a shipped workbook or a repository preset holds
    shipped = {(r['keyword'].lower(), _norm(r['value'])) for r in rows if r['value'] != 'overlay'}
    wc = fx.working_config('Case1') if fx is not None else None
    if wc is not None:
        for k, v in wc['main'].items():
            shipped.add((k.lower(), _norm(v)))
        for b in wc['packages'].values():
            for k, v in b.items():
                shipped.add((k.lower(), _norm(v)))
    # a value of the overlay that no shipped workbook or repository preset holds, and that is a vector or a number
    # with three or more digits (a single 0, 1 or 1e-4 says nothing about where it came from)
    only_no = [(r['preset'], r['keyword'], r['value']) for r in ov
               if (r['keyword'].lower(), _norm(r['value'])) not in shipped
               and ('[' in r['value'] or len(re.sub(r'[^0-9]', '', r['value'])) >= 3)]
    texts = {n: t for n, t in _repository_texts().items() if not n.replace('\\', '/').startswith('tests/')}
    found = []
    for name, text in texts.items():
        for preset in sorted({p for p, _, _ in only_no}):
            hits = [(k, v) for p, k, v in only_no if p == preset and
                    re.search(r'%s\s*=\s*%s(?![\d.])' % (re.escape(k), re.escape(v)), text, re.I)]
            if len(hits) >= 3:
                found.append('%s: %d values of %s (%s)' % (name, len(hits), preset, '; '.join('%s = %s' % h for h in hits[:4])))
    check('V10.6: no file of the product or its documents holds the overlay values of a preset (%d distinctive values '
          'of %d presets, %d files searched; three values of one preset in one file would reproduce it)'
          % (len(only_no), len({p for p, _, _ in only_no}), len(texts)), only_no and texts and not found, found[:10])
    in_presets = [(r['preset'], r['keyword']) for r in ov for p in rows
                  if p['preset'] == r['preset'] and p['keyword'] == r['keyword'] and _norm(p['value']) == _norm(r['value'])]
    check('V10.6: the preset file holds no overlay value under its own preset', not in_presets, in_presets[:5])


def _norm(v):
    return re.sub(r'\s+', ' ', str(v)).strip().lower()


def _repository_texts():
    """{path: text} of every text file git tracks or would track in the repository (not the workbooks)."""
    try:
        names = subprocess.run(['git', '-C', ROOT, 'ls-files', '--cached', '--others', '--exclude-standard'],
                               capture_output=True, text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        names = []
        for d, _, files in os.walk(ROOT):
            if '.git' in d.split(os.sep):
                continue
            names += [os.path.relpath(os.path.join(d, f), ROOT) for f in files]
    out = {}
    for n in names:
        if n.lower().endswith(('.xlsx', '.xls', '.png', '.s4p', '.zip', '.pyc')):
            continue
        try:
            with open(os.path.join(ROOT, n), encoding='utf-8') as f:
                out[n] = f.read()
        except (OSError, UnicodeDecodeError):
            continue
    return out


def template_ships():
    with open(TEMPLATE, 'rb') as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    check('V10.6: the 802-COM C2M egress template ships byte for byte (SHA-256 of com_code 4.17.0)', sha == TEMPLATE_SHA256,
          sha)
    import openpyxl
    wb = openpyxl.load_workbook(TEMPLATE, read_only=True)
    notice = wb['License Notice'] if 'License Notice' in wb.sheetnames else None
    text = ' '.join(str(c.value) for r in notice.iter_rows(max_row=40) for c in r if c.value) if notice else ''
    check('V10.6: the template keeps its License Notice sheet (BSD-3-Clause, 802-COM Authors)',
          'Copyright 2025 802-COM Authors' in text and 'Redistribution and use' in text, text[:120])
    with open(os.path.join(ROOT, 'NOTICE'), encoding='utf-8') as f:
        notice_file = f.read()
    check('V10.6: NOTICE names the shipped template', os.path.basename(TEMPLATE) in notice_file)


# ----------------------------------------------------------------------------- the setting, the overlay
def settings_and_overlay(fx):
    import prior_states
    from sicopr_assist import core
    from sicopr_assist.project import Project, read_settings
    old = os.environ.pop(ENV, None)
    try:
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.seed_run(ctx)
        s = read_settings(ctx.project)['values']
        check('V10.6: the settings translator (on) and preset_overlay (empty) are shipped with their defaults',
              s['translator'] is True and s['preset_overlay'] == '', (s['translator'], s['preset_overlay']))
        o = core.handle('Re-run with baud rate 53.125.', Project(ctx.root))
        check('translator on (the default): baud rate is f_b', o['type'] == 'PLAN' and
              any(c['json_path'] == '/main/f_b' and c.get('kind') == 'set' for c in o['changes']), _brief(o))
        prior_states.project_settings(ctx, 'translator = off')
        o = core.handle('Re-run with baud rate 53.125.', Project(ctx.root))
        check('translator = off in the project settings: strict mode, the phrase asks', o['type'] == 'QUESTION'
              and not o.get('translation'), _brief(o))
        core.handle('cancel', Project(ctx.root))                # the strict question above is answered first
        os.environ[ENV] = 'on'
        o = core.handle('Re-run with baud rate 53.125.', Project(ctx.root))
        check('the environment override %s = on wins over the setting' % ENV, o['type'] == 'PLAN', _brief(o))
        fx.remove_project(ctx.root)
        os.environ.pop(ENV, None)
        # the overlay: from the settings path; without it the 802.3ck presets stop and name the setting
        ctx = prior_states.Ctx(fx, 'Case1')
        o = core.handle('Setup a 802.3ck config for KR and run my channels.', Project(ctx.root))
        check('V10.6: with no overlay named, an 802.3ck preset stops and names the setting preset_overlay',
              o['type'] == 'STOP' and 'preset_overlay' in o['reason'] and 'redistribute NO' in o['reason'], _brief(o))
        prior_states.write_settings(ctx.project.settings_path, ['[translator]', 'preset_overlay = %s'
                                                                 % os.path.join(ctx.root, 'no_such_overlay.csv')])
        o = core.handle('Setup a 802.3ck config for KR and run my channels.', Project(ctx.root))
        check('V10.6: an overlay path that does not exist stops and says so', o['type'] == 'STOP' and
              'does not exist' in o['reason'], _brief(o))
        path = overlay_file()
        if path is None:
            print('SKIP: V10.6 the overlay loads from the settings path: needs the local overlay (%s)' % OVERLAY_ENV)
        else:
            prior_states.write_settings(ctx.project.settings_path, ['[translator]', 'preset_overlay = %s' % path])
            o = core.handle('Setup a 802.3ck config for KR and run my channels.', Project(ctx.root))
            check('V10.6: with the overlay named in the settings, the 802.3ck KR preset is read and Q14 asks once',
                  o['type'] == 'QUESTION' and [x.lower() for x in o['question']['options']] == ['run it anyway', 'cancel']
                  and (o.get('translation') or {}).get('preset') == '802.3ck KR', _brief(o))
        fx.remove_project(ctx.root)
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old


def _brief(o):
    return (o['type'], o.get('reason') or (o.get('question') or {}).get('text') or [s['op'] for s in o['steps']])


# ----------------------------------------------------------------------------- V10.5 history and feedback
def history_fields(fx):
    import prior_states
    from sicopr_assist import core, feedback
    from sicopr_assist.project import Project
    old = os.environ.pop(ENV, None)
    os.environ[ENV] = 'on'
    try:
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.seed_run(ctx)
        p = Project(ctx.root)
        said = ['Re-run with baud rate 53.125.', 'Give me more Rx FFE and re-run my setup.', 'yes',
                'Give me more Rx FFE and re-run my setup.', 'cancel',
                'Restrict the receiver equalization to low power.', 'short fixed FFE', 'Show settings.']
        outs = [core.handle(ph, p) for ph in said]
        hist = [r for r in p.read_history() if r.get('phrase') in said]
        recs = dict(zip(range(len(said)), hist[-len(said):]))
        t0 = recs[0].get('translation') or {}
        check('V10.5: a command in translator mode records every translation field (%s)' % ', '.join(TRANSLATION_FIELDS),
              all(k in t0 for k in TRANSLATION_FIELDS), sorted(set(TRANSLATION_FIELDS) - set(t0)))
        check("V10.5: the user's wording", t0.get('wording') == said[0], t0.get('wording'))
        check('V10.5: whether the strict core missed it', (t0.get('strict') or {}).get('missed') is True, t0.get('strict'))
        check('V10.5: the rule, synonym or preset that fired', 'synonym: baud rate is f_b' in (t0.get('fired') or []),
              t0.get('fired'))
        check('V10.5: the phrase handed to the core', t0.get('phrase') == 'Re-run with f_b 53.125.' and
              t0.get('used') is True, t0.get('phrase'))
        check("V10.5: the translator's name, version and rules SHA-256",
              t0.get('translator') == 'rules and presets' and t0.get('version') and
              re.fullmatch(r'[0-9a-f]{64}', t0.get('rules_sha256') or ''), (t0.get('translator'), t0.get('version')))
        t1 = recs[1].get('translation') or {}
        check('V10.5: a proposal is recorded with its values', 'ffe_pre_tap_len 6 -> 7' in (t1.get('proposal') or ''),
              t1.get('proposal'))
        check('V10.5: the proposal confirmed (its first option chosen)',
              (recs[2].get('translation') or {}).get('response') == 'confirmed', recs[2].get('translation'))
        check('V10.5: the proposal declined (cancel)',
              (recs[4].get('translation') or {}).get('response') == 'declined', recs[4].get('translation'))
        check('V10.5: the proposal changed (another option than the proposal)',
              (recs[6].get('translation') or {}).get('response') == 'changed', recs[6].get('translation'))
        t7 = recs[7].get('translation') or {}
        check('V10.5: a phrase the strict core reads is recorded too, with nothing fired and not used',
              t7.get('wording') == said[7] and t7.get('used') is False and (t7.get('strict') or {}).get('missed') is False,
              t7)
        lines = feedback.export_lines(p)
        text = '\n'.join(lines)
        sec = text[text.find('translator mode ('):]
        check('V10.5: Export feedback has a translator-mode section with every command made in translator mode',
              'translator mode (%d commands)' % len([r for r in p.read_history() if r.get('translation')]) in text,
              text[text.find('translator mode'):][:200])
        for what, needle in (('the wording', 'wording: Re-run with baud rate'), ('strict missed', 'strict missed: yes'),
                             ('what fired', 'fired: synonym: baud rate is f_b'),
                             ('the phrase handed to the core', 'handed to the core: Re-run with f_b 53.125.'),
                             ('the proposal', 'proposal: ffe_pre_tap_len 6 -> 7'), ('the response', 'response: confirmed'),
                             ('declined', 'response: declined'), ('changed', 'response: changed'),
                             ('the translator', 'translator: rules and presets')):
            check('V10.5: Export feedback carries %s' % what, needle in sec, sec[:300])
        fx.remove_project(ctx.root)
        # strict mode records no translation
        os.environ[ENV] = 'off'
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.seed_run(ctx)
        p = Project(ctx.root)
        core.handle('Re-run with baud rate 53.125.', p)
        last = p.read_history()[-1]
        check('V10.5: in strict mode a command records no translation', last.get('translation') is None,
              last.get('translation'))
        fx.remove_project(ctx.root)
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old


# ----------------------------------------------------------------------------- the miss gate and the layer's reach
def miss_gate(fx):
    import prior_states
    from sicopr_assist import core
    from sicopr_assist.project import Project
    old = os.environ.get(ENV)
    os.environ[ENV] = 'on'
    try:
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.seed_run(ctx)
        p = Project(ctx.root)
        o = core.handle('set DER_0 to 2 and rerun', p)
        check('miss gate: an illegal value on a request the core understood is a STOP, not reinterpreted',
              o['type'] == 'STOP' and not (o.get('translation') or {}).get('used'), _brief(o))
        o = core.handle('email the results to the team', p)
        check('miss gate: an out-of-scope request (email) is never handed to the layer',
              o['type'] == 'STOP' and not (o.get('translation') or {}).get('fired'), _brief(o))
        o = core.handle('explain the baud rate', p)
        check('miss gate: an out-of-scope request the strict core misses (explain, with a word the layer knows) is '
              'never handed to the layer', o['type'] == 'STOP' and not (o.get('translation') or {}).get('fired'),
              (_brief(o), (o.get('translation') or {}).get('fired')))
        q = core.handle('Sweep DER_0', p)
        o = core.handle('set the baud rate to 53.125 and rerun', p)
        check('miss gate: while a question is pending, a reply that is not one of its answers never goes to the layer',
              q['type'] == 'QUESTION' and o['type'] == 'QUESTION' and not (o.get('translation') or {}).get('fired'),
              (q['type'], _brief(o), (o.get('translation') or {}).get('fired')))
        fx.remove_project(ctx.root)
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old
    with open(os.path.join(PKG, 'translate.py'), encoding='utf-8') as f:
        src = f.read()
    imports = re.findall(r'^\s*(?:from\s+(\S+)\s+import\s+([^\n]+)|import\s+([^\n]+))', src, re.M)
    names = ' '.join(' '.join(x) for x in imports)
    check('the layer never runs the engine or writes the run CSV: translate.py imports neither run, run_case, '
          'subprocess nor engine, and opens no file for writing',
          not re.search(r'\brun\b|run_case|subprocess|\bengine\b', names) and not re.search(r"open\([^)]*'[wa]", src),
          names)


# ----------------------------------------------------------------------------- the core fixes, beyond their rows
def core_fixes(fx):
    """What rows CF01, CF10 and CF12 do not compare by machine: Q14's text for a b_min limit above 0 (core fix 1), the
    run CSV holding a MATLAB vector expression written out (core fix 3), and the verdict of a run in eye height and
    VEC mode (core fix 5)."""
    import prior_states
    from sicopr_assist import config_model, core, summary, validate
    from sicopr_assist.project import Project
    wc = fx.working_config('Case1')
    r = validate.validate(wc, [('/main/b_min(1)', '0.3')])
    check('core fix 1: Q14 says that b_min(1) = 0.3 is a minimum above 0 that forces the first DFE tap up, not a '
          'weight outside -1 to 1', r['status'] == 'ask' and 'minimum above 0' in r['text'] and 'first DFE tap' in
          r['text'] and 'outside -1 to 1' not in r['text'], r['text'])
    r = validate.validate(wc, [('/main/b_max(1)', '0.5')])
    check('core fix 1: a b_max(1) of 0.5 is not asked about (the sign rule is for b_min above 0 and b_max below 0)',
          r['status'] == 'ok', r['text'])
    old = os.environ.get(ENV)
    os.environ[ENV] = 'off'
    try:
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.seed_run(ctx)
        o = core.handle('Re-run with N_b = 12 and b_max(2..N_b) = [0.25 0.15*ones(1,3) 0.05*ones(1,7)].', Project(ctx.root))
        after = next((c['after'] for c in o['changes'] if c['json_path'] == '/main/b_max(2..N_b)'), None)
        check('core fix 3: a MATLAB vector expression is written out as the values MATLAB reads',
              o['type'] == 'PLAN' and after == '[0.25 0.15 0.15 0.15 0.05 0.05 0.05 0.05 0.05 0.05 0.05]', after)
        new = config_model.apply_changes(ctx.prior_wc, [(c['json_path'], c['after']) for c in o['changes']
                                                         if c['kind'] in ('set', 'add')])['config']
        fields, err = config_model.loaded_fields(new)
        check("core fix 3: SiCoPR's loader reads the run CSV of that change", err is None and fields is not None, err)
        fx.remove_project(ctx.root)
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.c2m_eye_run(ctx)
        p = Project(ctx.root)
        s = summary.run_summary(p, p.read_history()[-1]['run_ids'][0])
        text = '\n'.join(s['lines'])
        check('core fix 5: a run in eye height and VEC mode is judged by VEC Pass threshold and EH_min, not COM: fail, '
              'the eye height below EH_min', 'fail: VEC_dB 8.6 is within VEC Pass threshold (10); the eye height '
              '(VEO_mV 9.1) is below EH_min (12)' in text and 'COM Pass threshold' not in text and 'not judged' in text,
              text)
        fx.remove_project(ctx.root)
        ctx = prior_states.Ctx(fx, 'Case1')
        prior_states.strict_ooxml(ctx)
        o = core.handle('Run COM on data\\thru.s4p with data\\config.xlsx.', Project(ctx.root))
        check('core fix 4: a strict OOXML workbook is a STOP that names it and says how to save it',
              o['type'] == 'STOP' and 'strict OOXML workbook' in o.get('reason', '') and
              'ordinary Excel Workbook' in o.get('reason', ''), _brief(o))
        fx.remove_project(ctx.root)
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks are absent or hidden; the translator checks need a working config')
        provenance()
        template_ships()
        finish()
    template_ships()
    with fixtures.Fixtures(variants=False) as fx:
        provenance(fx)
        settings_and_overlay(fx)
        history_fields(fx)
        miss_gate(fx)
        core_fixes(fx)
    finish()


if __name__ == '__main__':
    main()

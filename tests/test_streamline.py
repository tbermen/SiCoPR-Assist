"""Streamlining the panel (Decision 25, gate V9.1): the panel shows only what SiCoPR's GUI does not.

    python tests\\test_streamline.py

The owner's request of 19 October 2026, five items, each checked on the panel's page part (panel.js, panel.css) and,
where the panel's server decides, through its API:

1. no selection line and no Run selection button (the Run tab shows its files and options); a reply that used the
   GUI's setup says so in a few words
2. the project folder, Browse and the version are inside the Settings fold; the top line is the title and, with a
   working config, its short state
3. a plan is one line that says where its effect can be seen (changes in Config, a run or a batch in the Run tab),
   with its steps and announcements under details
4. the examples under the box show only while it is empty and the history holds fewer successful commands than
   tutor_until_commands; What can I say? always shows them
5. the last three exchanges stay in view; older ones go to the History fold, newest first, one line each that opens
   to the full reply

When node is installed, planLine and showExamples are run in it on sample outcomes and states; without node those two
checks print SKIP with the reason (the text checks still run). The real page is driven in the walk-through of gate
V9.3. Nothing here needs SiCoPR or the starting workbooks.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402

STATIC = os.path.join(ROOT, 'sicopr_assist', 'panel', 'static')
src = io.open(os.path.join(STATIC, 'panel.js'), encoding='utf-8').read()
css = io.open(os.path.join(STATIC, 'panel.css'), encoding='utf-8').read()
m = re.search(r'ROOT\.innerHTML = `(.*?)`;', src, re.S)
tpl = m.group(1) if m else ''


def fn(name):
    """The text of a function of the panel: from its header to the closing brace at its own indent."""
    got = re.search(r'^  (?:async )?function %s\(.*?^  \}' % re.escape(name), src, re.S | re.M)
    return got.group(0) if got else ''


def const(name):
    got = re.search(r'^  const %s = [^;]*;' % re.escape(name), src, re.M)
    return got.group(0) if got else ''


def block(elid):
    """The template text of the element with this id, up to its closing tag (nested details counted)."""
    start = re.search(r'<(\w+) id="%s"' % re.escape(elid), tpl)
    if not start:
        return ''
    tag, depth, i = start.group(1), 0, start.start()
    for t in re.finditer(r'<(/?)%s\b' % tag, tpl[i:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return tpl[i:i + t.end()]
    return tpl[i:]


def rule(selector):
    got = re.search(r'#panel-assist ' + re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return got.group(1) if got else ''


NODE = shutil.which('node')


def in_node(code):
    """Run a script in node and return what it prints as JSON, or None without node."""
    if not NODE:
        return None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'probe.js')
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write(code)
        got = subprocess.run([NODE, p], capture_output=True, text=True, encoding='utf-8')
    if got.returncode != 0:
        return {'error': got.stderr[-800:]}
    return json.loads(got.stdout)


# ---- 1. no selection line, no Run selection button
check('1: no selection line and no Run selection button: the template and the script name neither',
      tpl and 'aSelLine' not in src and 'aRunSel' not in src and 'Run selection' not in tpl
      and 'syncSelection' not in src and "call('selection'" not in src and 'RUN_PHRASE' not in src,
      [w for w in ('aSelLine', 'aRunSel', 'syncSelection', "call('selection'", 'RUN_PHRASE') if w in src])
check('1: the selection is still kept from the tabs and posted with every phrase, for the core',
      'SELECTION.thru = d.thru' in src and "call('handle', { phrase, selection: SELECTION })" in fn('send'),
      fn('send')[:300])
pl = fn('planLine')
check("1: a plan that used the GUI's setup (the core's pattern names the selection or the Run tab) says so: using "
      "the Run tab's setup",
      "const GUI_SETUP = ['selection', 'run tab'];" in src
      and "(out.pattern || '').split('; ').some((p) => GUI_SETUP.includes(p))" in pl
      and "\"using the Run tab's setup; \"" in pl, pl)

# ---- 2. project, Browse and version in Settings; the top line
settings = block('aSettings')
outside = tpl.replace(settings, '') if settings else tpl
check('2: the project folder, Browse and the version are inside the Settings fold, and nowhere else',
      settings.startswith('<details id="aSettings"') and all(('id="%s"' % i) in settings
                                                             for i in ('aProject', 'aBrowse', 'aVersion'))
      and not any(('id="%s"' % i) in outside for i in ('aProject', 'aBrowse', 'aVersion')), settings[:400])
top = re.search(r'<div id="aTop" class="atop" hidden>(.*?)</div>', tpl, re.S)
check('2: the top line holds only the working config (the title is the slot\'s own header); it comes first and starts '
      'hidden, and its class has its own [hidden] rule',
      top and 'id="aWorking"' in top.group(1) and len(re.findall(r'<(?:span|button|div)\b', top.group(1))) == 1
      and tpl.find('id="aTop"') < tpl.find('id="aConv"')
      and re.search(r'\.atop\[hidden\]\s*\{\s*display:\s*none', css), top.group(1) if top else 'no #aTop line')
rf = fn('refresh')
check('2: the top line shows the working config only when the project has one, and is hidden otherwise; the version '
      'goes to Settings',
      "$a('#aWorking').textContent = STATE.project && /^working config /.test(STATE.line || '') ? STATE.line : '';"
      in rf and "$a('#aTop').hidden = !$a('#aWorking').textContent;" in rf
      and "$a('#aVersion').textContent = 'SiCoPR-Assist ' + STATE.version;" in rf
      and "STATE.version + ' - '" not in src, rf)
check('2: with no project folder the Settings fold is opened, so Browse is in sight',
      "$a('#aSettings').open = true;" in fn('init') and 'in Settings' in fn('init'), fn('init'))

# ---- 3. the plan as one line
cd = fn('card')
check('3: a PLAN is one line (planLine), with no list of steps; its steps and announcements are under details',
      "box.appendChild(el('div', 'aoneline', planLine(out)));" in cd and "el('ol'" not in cd and 'asteps' not in src
      and "details(box, steps.concat(out.announce || []));" in cd
      and "(out.steps || []).map((s, i) => (i + 1) + '. ' + (s.op || s))" in cd, cd)
check('3: a QUESTION keeps its text and buttons, a STOP its reason',
      "el('div', 'aq', 'QUESTION: ' + (q.text || ''))" in cd and "b.addEventListener('click', () => send(o));" in cd
      and "el('div', 'astop', 'STOP: ' + (out.reason || ''))" in cd, cd)
check('3: the result lines stay as in V2-8: the headline and the Results buttons',
      "box.appendChild(el('div', 'aheadline', r.headline));" in fn('resultCard')
      and "['results', 'Results, static'], ['dynamic', 'Results, dynamic']" in fn('resultCard'), fn('resultCard')[:300])
probe = in_node('''
const RUN_OPS = %s; const SET_OPS = %s; const GUI_SETUP = %s;
%s
const st = (ops) => ops.map((op) => ({ op }));
console.log(JSON.stringify([
  planLine({ steps: st(['set_param', 'set_param']), changes: [{}, {}] }),
  planLine({ steps: st(['set_channel', 'validate_inputs', 'validate_config', 'run_com', 'summarize']), changes: [] }),
  planLine({ steps: st(['build_matrix', 'validate_config', 'run_batch', 'batch_summary']), changes: [], points: [1, 2, 3] }),
  planLine({ steps: st(['set_param', 'validate_config', 'run_com', 'summarize']), changes: [{}] }),
  planLine({ steps: st(['validate_inputs', 'validate_config', 'run_com', 'summarize']), changes: [], pattern: 'run tab; run' }),
  planLine({ steps: st(['show_tutor']), changes: [] }),
  planLine({ steps: st(['show_config']), changes: [] }),
  planLine({ steps: st(['show_config', 'show_tutor']), changes: [] }),
  planLine({ steps: st(['set_param', 'validate_config', 'run_com', 'summarize', 'show_tutor']), changes: [{}] }),
  planLine({ steps: st(['set_param', 'validate_config', 'run_com', 'summarize']) }),
]));''' % (re.search(r"const RUN_OPS = (\[.*?\]);", src).group(1) if 'const RUN_OPS' in src else '[]',
          re.search(r"const SET_OPS = (\[.*?\]);", src).group(1) if 'const SET_OPS' in src else '[]',
          re.search(r"const GUI_SETUP = (\[.*?\]);", src).group(1) if 'const GUI_SETUP' in src else '[]', pl))
want = ['2 changes, highlighted in Config', 'running in the Run tab', '3 points: output in the Run tab',
        '1 change, highlighted in Config; running in the Run tab',
        "using the Run tab's setup; running in the Run tab", 'examples under the command box',
        'show_config: its lines below', 'show_config: its lines below',
        '1 change, highlighted in Config; running in the Run tab',
        '1 change, highlighted in Config; running in the Run tab']    # the last: a plan from the history, no changes
if probe is None:
    print('SKIP: node is not installed, so planLine is not run on sample plans (its text is checked above)')
else:
    check('3: planLine says where the effect can be seen: changes in Config, a run or a batch in the Run tab',
          probe == want, 'got %s' % (probe,))

# ---- 4. examples only when they help
se = fn('showExamples')
check('4: the examples show only while the box is empty and the tutor is due, or after What can I say?, never '
      'while a plan runs',
      "const asked = !!(TUTOR && TUTOR.why === 'asked');" in se
      and "const due = !!(STATE && STATE.tutor_due) && !$a('#aCmd').value;" in se
      and "host.hidden = $a('#aCmd').disabled || !host.childElementCount || !(asked || due);" in se, se)
check('4: they are looked at again as the box is typed in, filled or emptied, and when the state or the run changes',
      "$a('#aCmd').addEventListener('input', () => { fitBox(); showExamples(); });" in src
      and 'showExamples();' in fn('fillBox') and 'showExamples();' in fn('refresh') and 'showExamples();' in fn('busyUi')
      and "$a('#aExamples').hidden = on;" not in src, fn('busyUi'))
check('4: the examples area starts hidden, and its class has its own [hidden] rule',
      '<div id="aExamples" class="aexamples" hidden></div>' in tpl
      and re.search(r'\.aexamples\[hidden\]\s*\{\s*display:\s*none', css), 'template or [hidden] rule')
le = fn('loadExamples')
check("4: a PLAN's tutor (a new user's, or What can I say?) is shown under the box, not in the card; the tutor after a "
      "miss or on trouble stays in its reply",
      "TUTOR = r.outcome.type === 'PLAN' && tu && tu.why !== 'trouble' && (tu.lines || []).length ? tu : null;"
      in fn('send') and "if (out.type !== 'PLAN' || !out.tutor || out.tutor.why === 'trouble') tutorLines(box, out.tutor);"
      in cd and 'tutorLines(host, TUTOR);' in le and 'if (!STATE.tutor_due) {' in le, le)
fin = fn('finished')
check("4: the lines the plan's show_tutor step gives when carried out are left out of its reply, since they are under "
      "the box (the first walk-through showed them twice)",
      "const taught = new Set((((TUTOR || {}).lines) || []).map((x) => x.trim()));" in fin
      and "done.lines = (done.lines || []).filter((x) => !taught.has(String(x).trim()));" in fin
      and fin.find('done.lines = (done.lines') < fin.find('const runs = '), fin[:700])
probe = in_node('''
let STATE = null, TUTOR = null; const els = {};
const $a = (s) => els[s];
%s
function at(tutorDue, typed, busy, asked, items) {
  STATE = { tutor_due: tutorDue }; TUTOR = asked ? { why: 'asked' } : null;
  els['#aCmd'] = { value: typed, disabled: busy };
  els['#aExamples'] = { hidden: null, childElementCount: items };
  showExamples(); return els['#aExamples'].hidden;
}
console.log(JSON.stringify([at(true, '', false, false, 4), at(true, 'Re-run', false, false, 4),
  at(false, '', false, false, 4), at(false, 'x', false, true, 4), at(true, '', true, false, 4),
  at(true, '', false, false, 0)]));''' % se)
if probe is None:
    print('SKIP: node is not installed, so showExamples is not run on sample states (its text is checked above)')
else:
    check('4: shown when due and the box is empty; hidden once typed in, once no longer due, while a plan runs, or '
          'when there is nothing to show; What can I say? shows them whatever the count',
          probe == [False, True, True, False, True, True], 'hidden for the six states: %s' % (probe,))

# the server's half: tutor_due is tutor.after's rule (fewer successful commands than tutor_until_commands)
from sicopr_assist.panel import api  # noqa: E402
from sicopr_assist.project import Project, history_record  # noqa: E402

home = tempfile.mkdtemp(prefix='streamline_home_')
proj = tempfile.mkdtemp(prefix='streamline_proj_')
old_home = os.environ.get('SICOPR_ASSIST_HOME')
os.environ['SICOPR_ASSIST_HOME'] = home
try:
    p = Project(proj)
    os.makedirs(p.dir, exist_ok=True)
    seen = [api.state(p)['tutor_due']]
    for i in range(5):
        p.append_history(history_record(phrase='Show the config.', outcome='PLAN', status='ok', origin='gui',
                                        kind='phrase'))
        if i == 0:
            p.append_history(history_record(phrase='Re-run with DER_0 = 1e-4', outcome='STOP', status='stopped',
                                            origin='gui', kind='phrase'))
            p.append_history(history_record(phrase='Set DER_0 = 1e-4', outcome='PLAN', status='ok', origin='gui',
                                            kind='edit'))
        seen.append(api.state(p)['tutor_due'])
    with io.open(p.settings_path, 'w', encoding='utf-8') as f:
        f.write('[tutor]\ntutor_until_commands = 9\n')
    seen.append(api.state(p)['tutor_due'])
    with io.open(p.settings_path, 'w', encoding='utf-8') as f:
        f.write('[tutor]\ntutor_until_commands = 0\n')
    seen.append(api.state(p)['tutor_due'])
    check('4: the state says the examples are due while the history holds fewer successful commands than '
          'tutor_until_commands (5): a stop and a Config-view edit do not count; 9 in the project file extends it, '
          '0 ends it; no project, not due',
          seen == [True, True, True, True, True, False, True, False] and api.state(None)['tutor_due'] is False, seen)
finally:
    if old_home is None:
        os.environ.pop('SICOPR_ASSIST_HOME', None)
    else:
        os.environ['SICOPR_ASSIST_HOME'] = old_home
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(proj, ignore_errors=True)

# ---- 5. three exchanges in view, the rest in History
kt = fn('keepThree')
check('5: three exchanges stay in view: each new one calls keepThree, which moves the oldest beyond three to History',
      re.match(r'  const IN_VIEW = 3;', const('IN_VIEW')) is not None and 'keepThree();' in fn('entry') and 'while (shown.length > IN_VIEW) {' in kt, kt)
history_fold = block('aHistory')
check('5: older exchanges go to the History fold, newest first, each one line (a summary) that opens to the full '
      'reply', 'id="aOlder"' in history_fold and "const d = el('details', 'aolditem');" in kt
      and "d.appendChild(el('summary', '', e.dataset.line || ''));" in kt and 'd.appendChild(e);' in kt
      and 'older.insertBefore(d, older.firstChild);' in kt
      and re.search(r'\.aolditem > summary\s*\{[^}]*white-space:\s*nowrap', css), kt)
check('5: the replies to a command (its result, a note) go into its exchange, so they move to History with it',
      "$a('#aConv').appendChild(box)" not in src and 'reply(box);' in fn('resultCard') and 'reply(box);' in fn('finished')
      and "reply(el('div', 'anote ' + (cls || ''), text));" in fn('note')
      and "e.dataset.line = h.textContent + (out ? ': ' + outLine(out) : '');" in fn('entry'), fn('reply'))
check('5: the History fold keeps every record of the project history too, folded, as before',
      'id="aHistLines"' in history_fold and "call('history?limit=500')" in src and "viewed('history');" in src,
      history_fold[:300])

finish()

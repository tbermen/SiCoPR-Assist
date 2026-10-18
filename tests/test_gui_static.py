"""The Assist panel's page part (GUI_DESIGN.md section 11, "The page"), checked without a browser or a server.

    python tests\\test_gui_static.py

- panel.js parses: with node --check when node is installed, else with esprima (pip install esprima), as SiCoPR's
  tests/test_gui_static.py does; with neither it fails, because a syntax error there leaves the panel blank while
  every server-side check passes
- every element id it looks up exists in the template it writes
- every class that sets display has its own [hidden] rule (a class that sets display defeats the hidden attribute)
- every event name it sends or hears is one of the panel contract's (SiCoPR gui/README.md, "Panels"), and when the
  SiCoPR in use documents the contract, it is that list
- it calls only endpoints the panel's api.py answers
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from check import check, finish  # noqa: E402

STATIC = os.path.join(ROOT, 'sicopr_assist', 'panel', 'static')
JS = os.path.join(STATIC, 'panel.js')
CSS = os.path.join(STATIC, 'panel.css')
# the panel contract, API 1 (GUI_DESIGN.md section 4.1): the page sends the first seven and hears the last six
# (run-request and set-run were added in Phase V2-7, Decision 23)
CONTRACT = {'config', 'edit', 'view', 'run', 'browsed', 'channels', 'run-request', 'open-config', 'overlay',
            'clear-edits', 'show', 'browse', 'set-run'}

src = io.open(JS, encoding='utf-8').read()
css = io.open(CSS, encoding='utf-8').read()

# ---- it parses
node = shutil.which('node')
try:
    import esprima
except ImportError:
    esprima = None
if node:
    p = subprocess.run([node, '--check', JS], capture_output=True, text=True)
    check('panel.js parses (node --check)', p.returncode == 0, p.stderr or p.stdout)
elif esprima is not None:
    err = ''
    try:
        esprima.parseScript(src)
    except Exception as e:                                    # noqa: BLE001
        err = str(e)
    check('panel.js parses (esprima)', not err, err)
else:
    check('panel.js is parsed by node or esprima', False,
          'neither node nor esprima is installed: pip install esprima. A syntax error in panel.js would leave the '
          'panel blank while every server-side check passes')

# ---- strict mode, and no em dash or emoji in what the user reads
check('panel.js is strict mode', re.search(r"^'use strict';", src, re.M) is not None, 'no use strict line')

# ---- ids: every lookup has an element in the template
template = re.search(r'ROOT\.innerHTML = `(.*?)`;', src, re.S)
defined = set(re.findall(r'id="([^"]+)"', template.group(1))) if template else set()
used = set(re.findall(r"\$a\('#([A-Za-z0-9_-]+)'\)", src))
check('every element id panel.js looks up is in its template', used and defined and not (used - defined),
      'looked up but not defined: %s' % sorted(used - defined))
check('panel.js mounts in the element SiCoPR gives it (#panel-assist)', "getElementById('panel-assist')" in src,
      'no lookup of panel-assist')

# ---- [hidden] rules
hidden_classes = set()
for attrs in re.findall(r'<\w+([^>]*\bhidden\b[^>]*)>', template.group(1) if template else ''):
    m = re.search(r'class="([^"]+)"', attrs)
    if m:
        hidden_classes.update(m.group(1).split())
broken = []
for c in sorted(hidden_classes):
    sets = re.search(r'\.' + re.escape(c) + r'\s*(?:,[^{]*)?\{[^}]*?display:\s*[a-z-]+', css)
    has = re.search(r'\.' + re.escape(c) + r'\[hidden\]\s*\{[^}]*display:\s*none', css)
    if sets and not has:
        broken.append(c)
check('every class used with the hidden attribute that sets display has its own [hidden] rule',
      hidden_classes and not broken, 'no [hidden] rule for: %s (classes with hidden: %s)' % (broken, hidden_classes))
# a class the script hides by property (el.hidden = ...) counts too
by_prop = set(re.findall(r"\$a\('#([A-Za-z0-9_-]+)'\)\.hidden\s*=", src))
classes_of = dict(re.findall(r'id="([^"]+)" class="([^"]+)"', template.group(1) if template else ''))
broken = [classes_of[i] for i in by_prop if i in classes_of and
          re.search(r'\.' + re.escape(classes_of[i]) + r'\s*\{[^}]*?display:', css) and
          not re.search(r'\.' + re.escape(classes_of[i]) + r'\[hidden\]', css)]
check('every element panel.js hides by property can be hidden', not broken, broken)

# ---- events
sent = set(re.findall(r"emit\('([a-z-]+)'", src))
heard = set(re.findall(r"addEventListener\('sicopr:([a-z-]+)'", src))
named = set(re.findall(r"sicopr:([a-z-]+)", src))
check('every event panel.js sends or hears is one of the panel contract\'s', (sent | heard | named) <= CONTRACT
      and sent and heard, 'not in the contract: %s' % sorted((sent | heard | named) - CONTRACT))
check('panel.js sends only events the page hears, and hears only events the page sends',
      sent <= {'open-config', 'overlay', 'clear-edits', 'show', 'browse', 'set-run'}
      and heard <= {'config', 'edit', 'view', 'run', 'browsed', 'channels', 'run-request'},
      'sent %s, heard %s' % (sorted(sent), sorted(heard)))
try:
    from sicopr_assist import engine
    readme = os.path.join(engine.folder(), 'gui', 'README.md')
    text = io.open(readme, encoding='utf-8').read() if os.path.isfile(readme) else ''
except Exception:                                             # noqa: BLE001 - no SiCoPR: the contract above stands
    text = ''
documented = set(re.findall(r'`sicopr:([a-z-]+)`', text))
if documented:
    check('the contract here is the one the SiCoPR in use documents (gui/README.md, Panels)', documented == CONTRACT,
          'SiCoPR documents %s' % sorted(documented))
else:
    print('SKIP: the SiCoPR in use documents no panel events (its GUI has no panel slot); the events were checked '
          'against GUI_DESIGN.md section 4.1 only')

# ---- endpoints
api_src = io.open(os.path.join(ROOT, 'sicopr_assist', 'panel', 'api.py'), encoding='utf-8').read()
answered = set(re.findall(r"path == '([a-z]+)'", api_src))
called = {re.match(r'[a-z]+', c).group(0) for c in re.findall(r"call\('([a-z]+[^']*)'", src)}
called |= {'log'} if "API + 'log'" in src else set()
check('panel.js calls only endpoints api.py answers', called and called <= answered,
      'called %s, answered %s' % (sorted(called), sorted(answered)))


# ---- the command box and the selection (Decisions 20 and 21; gate V6.3)
#
# The maintainer's first session: the one-line box was easy to miss, and nothing told the panel which channel files
# were picked in the tabs. These read the template, the handlers and the stylesheet; the real page is driven in the
# walk-through of gate V6.5.
def fn(name):
    """The text of a function of the panel: from its header to the closing brace at its own indent."""
    m = re.search(r'^  (?:async )?function %s\(.*?^  \}' % re.escape(name), src, re.S | re.M)
    return m.group(0) if m else ''


def heard_body(event):
    m = re.search(r"^  window\.addEventListener\('sicopr:%s', \(e\) => \{.*?^  \}\);" % re.escape(event), src,
                  re.S | re.M)
    return m.group(0) if m else ''


def wired(el_id, event):
    """The handler text of $a('#id').addEventListener('event', ...), up to the end of the statement."""
    m = re.search(r"^  \$a\('#%s'\)\.addEventListener\('%s', (.*?)^(?=  \S)(?!  \})" % (re.escape(el_id), event), src,
                  re.S | re.M)
    if not m:
        return ''
    text = m.group(1)
    end = re.search(r'^  \}\);', text, re.M)
    return text[:end.end()] if end else text.split(';\n')[0]


def rule(selector):
    m = re.search(r'#panel-assist ' + re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return m.group(1) if m else ''


tpl = template.group(1) if template else ''
box = re.search(r'<textarea id="aCmd"([^>]*)>', tpl)
rows = re.search(r'\brows="(\d+)"', box.group(1)) if box else None
check('the command box is a text area of three lines or more', box and rows and int(rows.group(1)) >= 3
      and '<input id="aCmd"' not in tpl, 'the template holds %r' % (box.group(0) if box else 'no textarea #aCmd'))
check('the command box has its visible label, Type a command',
      re.search(r'<label for="aCmd"[^>]*>Type a command</label>', tpl) is not None
      and 'font-weight' in rule('.alabel'), 'no label for aCmd with that text, or the label has no weight')
keys = wired('aCmd', 'keydown')
enter = re.search(r"if \(e\.key === 'Enter' && !e\.shiftKey\) \{(.*?)\}", keys, re.S)
check('Enter sends the box, and Shift+Enter does not (it is a new line)',
      enter and 'e.preventDefault()' in enter.group(1) and "send($a('#aCmd').value)" in enter.group(1)
      and len(re.findall(r"e\.key === 'Enter'", src)) == 1, 'the keydown handler of the box: %r' % keys[:200])
check('a phrase of several lines is sent as one line',
      re.search(r"phrase = String\(phrase \|\| ''\)\.replace\(/\\s\*\\n\\s\*/g, ' '\)\.trim\(\)", fn('send')),
      'send() does not join the lines of the box')
area = rule('.abox textarea')
check('the command box is set apart from the conversation: its own border in the accent colour and a height of '
      'several lines', re.search(r'border:\s*2px solid var\(--accent\)', area) and re.search(r'min-height:\s*[4-9]', area),
      area)
cmd = re.search(r'<div id="aCommand" class="acommand">(.*?)\n    </div>\n', tpl, re.S)
block = rule('.acommand')
conv = rule('.aconv')
check('the command box stays in view: its block sticks to the bottom of the panel, and the conversation scrolls',
      cmd and 'id="aCmd"' in cmd.group(1) and re.search(r'position:\s*sticky', block)
      and re.search(r'bottom:\s*0', block) and re.search(r'background:\s*var\(--panel\)', block)
      and re.search(r'overflow-y:\s*auto', conv) and 'max-height' in conv
      and tpl.find('id="aConv"') < tpl.find('id="aCommand"'), (block, conv))
check('the command box takes the focus on load, once it is on screen, and never from a field in use',
      re.search(r"async function init\(\) \{\s*focusBox\(\d+\);", src) is not None
      and 'box.offsetParent !== null' in fn('focusBox') and 'if (free) box.focus();' in fn('focusBox')
      and 'document.activeElement === document.body' in fn('focusBox'), fn('focusBox'))
fit = fn('fitBox')
check('the command box grows with its content', 'box.scrollHeight + 4' in fit and "box.style.height = 'auto'" in fit
      and "addEventListener('input', fitBox)" in src and 'fitBox();' in fn('fillBox'), fit)

sync = fn('syncSelection')
cfg_ev, ch_ev = heard_body('config'), heard_body('channels')
check('the selection line follows sicopr:config and sicopr:channels',
      'SELECTION.config = d.path' in cfg_ev and 'await syncSelection()' in cfg_ev
      and 'SELECTION.thru = d.thru' in ch_ev and 'SELECTION.fext = (d.fext' in ch_ev
      and 'SELECTION.next = (d.next' in ch_ev and 'await syncSelection()' in ch_ev
      and "call('selection', { selection: SELECTION })" in sync and "$a('#aSelLine').textContent = r.line" in sync,
      'config handler %r\nchannels handler %r' % (cfg_ev[:160], ch_ev[:300]))
check('the selection line and the Run selection button sit above the command box',
      cmd and 0 <= cmd.group(1).find('id="aSelLine"') < cmd.group(1).find('id="aRunSel"') < cmd.group(1).find('id="aCmd"')
      and '>Run selection</button>' in cmd.group(1), 'the order in the template')
from sicopr_assist import core as _core  # noqa: E402
from sicopr_assist.panel import api as _api  # noqa: E402
first_phrase = re.search(r"let RUN_PHRASE = '([^']*)';", src)
check('Run selection sends the phrase Run the selected config and channels.',
      'send(RUN_PHRASE)' in wired('aRunSel', 'click') and first_phrase
      and first_phrase.group(1) == _core.RUN_SELECTION == 'Run the selected config and channels.'
      and 'RUN_PHRASE = r.phrase || RUN_PHRASE' in sync, (wired('aRunSel', 'click')[:120], first_phrase and first_phrase.group(1)))
check('every phrase is posted with the selection, so the core is handed it as data',
      "call('handle', { phrase, selection: SELECTION })" in fn('send'), 'send() posts the phrase without the selection')
ex = fn('loadExamples')
check('an example phrase fills the command box: up to four are asked from the panel, and a click puts one in the box',
      "call('examples', { selection: SELECTION })" in ex and "b.addEventListener('click', () => fillBox(p))" in ex
      and 'box.value = text' in fn('fillBox') and 'box.focus()' in fn('fillBox') and _api.MAX_EXAMPLES == 4
      and 'id="aExamples"' in (cmd.group(1) if cmd else ''), ex[:300])
check('the examples are asked again when the config in view changes and when a command ends',
      'loadExamples()' in cfg_ev and 'loadExamples()' in fn('send') and 'loadExamples()' in fn('finished')
      and 'await loadExamples()' in fn('init'), 'a call of loadExamples is missing')
check('while a plan runs, the box, Send and Run selection are off together',
      all(("$a('#%s').disabled = on" % i) in fn('busyUi') for i in ('aCmd', 'aSend', 'aRunSel')), fn('busyUi'))


# ---- the Run tab and the panel as one (Decision 23; gate V7.4)
#
# The maintainer's second session: he wanted the Run tab to show the command Assist assembles, and what he sets there
# (Output dynamic results, the files) to be part of what "run the command" runs. These read the handlers; the real
# page is driven in the walk-through of gate V7.5.
send_fn, fin, rcard = fn('send'), fn('finished'), fn('resultCard')
rr_ev = heard_body('run-request')
check('a PLAN with one COM run fills the Run tab: the panel sends sicopr:set-run with the run_tab the server made',
      'if (r.run_tab) assemble(r.run_tab);' in send_fn and "emit('set-run', tab);" in fn('assemble')
      and 'ASSEMBLED = tab;' in fn('assemble') and 'return dict(res, job=True, run_tab=tab)' in
      io.open(os.path.join(ROOT, 'sicopr_assist', 'panel', 'api.py'), encoding='utf-8').read(),
      send_fn[:400])
check('the options of the Run tab come with sicopr:channels into the selection, on only when the page says true',
      'SELECTION.options = { export_mat: o.export_mat === true, eye_under_mlse: o.eye_under_mlse === true };' in ch_ev,
      ch_ev[:500])
check('a change made in the Run tab while it is assembled updates its command; a change the panel made does not',
      "if (ASSEMBLED && d.cause !== 'panel' && STATE.project) await reassemble();" in ch_ev
      and "call('runtab', { selection: SELECTION })" in fn('reassemble') and 'assemble(r);' in fn('reassemble'),
      ch_ev[:600])
check('the Run button is taken only while the panel has the Run tab assembled, with the files and options it was '
      'pressed with, and is the phrase Run the command.',
      0 <= rr_ev.find('if (!ASSEMBLED || !STATE || !STATE.project) return;') < rr_ev.find('e.preventDefault();')
      and rr_ev.find('e.preventDefault();') >= 0
      and 'SELECTION.thru = d.thru' in rr_ev and 'SELECTION.options = {' in rr_ev
      and "send(RUN_COMMAND, 'Run button')" in rr_ev
      and re.search(r"const RUN_COMMAND = '([^']*)';", src).group(1) == _core.RUN_COMMAND == 'Run the command.',
      rr_ev[:600])
check('a run made with Output dynamic results ticked opens in Results, dynamic, which builds its dashboard',
      "emit('show', { view: 'dynamic', run: r.folder, build: true });" in fin
      and 'r.export_mat && JOB_TAB && JOB_TAB.options && JOB_TAB.options.export_mat' in fin
      and 'JOB_TAB = r.job ? (r.run_tab || null) : null;' in send_fn, fin[:900])
check('Results, dynamic opened on a run with no .mat export says so and offers the phrase that makes one',
      "if (view === 'dynamic' && !r.export_mat) noDynamic(rid, r.dynamic_phrase);" in rcard
      and 'fillBox(phrase)' in fn('noDynamic') and 'nothing' in fn('noDynamic'), rcard[:600])

finish()

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
# the panel contract, API 1 (GUI_DESIGN.md section 4.1): the page sends the first five and hears the last five
CONTRACT = {'config', 'edit', 'view', 'run', 'browsed', 'open-config', 'overlay', 'clear-edits', 'show', 'browse'}

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
      sent <= {'open-config', 'overlay', 'clear-edits', 'show', 'browse'}
      and heard <= {'config', 'edit', 'view', 'run', 'browsed'}, 'sent %s, heard %s' % (sorted(sent), sorted(heard)))
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

finish()

/* Copyright 2026 Todd Bermensolo
 * SPDX-License-Identifier: BSD-3-Clause */
'use strict';
/* The SiCoPR-Assist panel, in SiCoPR's GUI (panel API 1: SiCoPR gui/README.md, "Panels"; GUI_DESIGN.md).
 *
 * A phrase typed here goes to the core through /panel/assist/api/handle, exactly as on the command line; a PLAN is
 * carried out on the server and its progress polled from /job. The Config view shows the working config laid over
 * its workbook (sicopr:overlay), an edit committed there is taken into the working config (sicopr:edit to /edit), and
 * a workbook opened there is followed (sicopr:config to /open). Every action is in the project's history.
 *
 * The page also tells the panel what is selected in its tabs: the workbook of the Config tab (sicopr:config) and the
 * THRU, FEXT and NEXT files of the Run tab (sicopr:channels). The panel keeps that selection, shows it in a line
 * above the command box, and hands it to the core with every phrase, so "the selected config and channels" means
 * those files.
 *
 * The Run tab and the panel work as one (Decision 23). A PLAN that runs COM fills the Run tab (sicopr:set-run): its
 * files, its two options, and in its command box the command the panel will run, which is the working config's run
 * CSV and not the workbook. A change made in the Run tab comes back with sicopr:channels (files and options), is part
 * of the selection, and updates that command. "Run the command." runs exactly that setup; while the panel has the Run
 * tab assembled, the Run tab's own Run button is handed here (sicopr:run-request) and is that phrase.
 *
 * GUI first (Decision 24). SiCoPR's GUI is the tool, used as without the panel; the panel drives it by typing. A run
 * the panel carries out streams its lines to the Run tab's Output (sicopr:output), with its status line and Stop
 * there (sicopr:stop-request), and the page shows the Run tab when it starts, unless the user is in the middle of an
 * edit in Config. The panel keeps short replies: the plan as a short list with the long text folded behind details,
 * a question with its buttons, one line while a plan runs, then the headline result (or a batch's short table) with
 * the buttons that open it in Results. */
(function () {
  const API = '/panel/assist/api/';
  const ROOT = document.getElementById('panel-assist');
  if (!ROOT) return;

  ROOT.innerHTML = `
    <div class="aline">
      <span id="aProject" class="apath">no project folder</span>
      <button id="aBrowse" class="ghost asmall">Browse&hellip;</button>
    </div>
    <div id="aWorking" class="amuted"></div>
    <div id="aConv" class="aconv"></div>
    <div id="aRunning" class="arunning" hidden>
      <span id="aRunLine"></span>
      <button id="aToRun" class="ghost asmall">Run tab</button>
    </div>
    <div id="aPending" class="apending" hidden></div>
    <div id="aCommand" class="acommand">
      <div class="aselrow">
        <span id="aSelLine" class="aselline">Selected: nothing yet</span>
        <button id="aRunSel" class="ghost asmall">Run selection</button>
      </div>
      <label for="aCmd" class="alabel">Type a command</label>
      <div class="abox">
        <textarea id="aCmd" rows="3" spellcheck="false" autocomplete="off"
                  placeholder="for example: Re-run with DER_0 = 1e-4"></textarea>
        <button id="aSend">Send</button>
      </div>
      <div class="ahint">Enter sends. Shift+Enter starts a new line. Up and Down recall earlier commands.</div>
      <div id="aExamples" class="aexamples"></div>
    </div>
    <details id="aSettings" class="afold"><summary>Settings</summary><pre id="aSetLines" class="aset"></pre></details>
    <details id="aHistory" class="afold"><summary>History</summary><div id="aHistLines" class="aset"></div></details>
    <details id="aLlm" class="afold"><summary>Language model</summary>
      <p class="amuted">none: this version is rules-based. A language model, when one is added, is configured here; it
      may turn loose wording into a phrase, and the core checks that phrase as it checks typed input.</p></details>`;

  const $a = (s) => ROOT.querySelector(s);
  const norm = (p) => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  let STATE = null;
  let KEYS = [];            // the field keys the Config view shows (sicopr:config)
  let VIEW_PATH = null;     // the workbook the Config view shows
  let PHRASES = [];         // earlier phrases, newest first, for Up and Down
  let RECALL = -1;
  let SINCE = 0;
  let POLL = null;
  let FAILS = 0;
  let SHOWN_RUN = false;    // the Run tab was asked for once for the plan being carried out
  let EDITS = Promise.resolve();   // edits being taken in; a phrase waits for them
  // a workbook the user opened in the Config view is being followed, or its keep-or-start question is open: the
  // view stays on it, and nothing here pulls it back to the source of the working config meanwhile
  let FOLLOWING = false;
  // what is selected in the tabs: the workbook of the Config tab and the channel files of the Run tab (Decision 20)
  const SELECTION = { config: null, thru: null, fext: [], next: [],
    options: { export_mat: false, eye_under_mlse: false } };
  let RUN_PHRASE = 'Run the selected config and channels.';
  const RUN_COMMAND = 'Run the command.';   // what the Run tab's Run button is, while the panel has it assembled
  let ASSEMBLED = null;     // the setup this panel last put in the Run tab (sicopr:set-run), or null
  let JOB_TAB = null;       // the Run tab setup of the plan being carried out, if it has one
  const BOX_MAX_PX = 220;   // the command box grows with its content up to here, then scrolls

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent('sicopr:' + name, { detail }));
  }

  async function call(path, body) {
    const opts = body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    };
    let r;
    try {
      r = await fetch(API + path, opts);
    } catch (e) {
      report('call ' + path, String(e.message || e));
      throw e;
    }
    const j = await r.json().catch(() => ({ error: 'bad response from the Assist panel' }));
    if (!r.ok) report('call ' + path, j.error || ('HTTP ' + r.status));
    return j;
  }

  /* Page errors go to the history as error records (GUI_DESIGN.md section 7a). */
  function report(where, message, trace) {
    fetch(API + 'log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'error', where, message, trace: trace || '' }),
    }).catch(() => {});
  }
  window.addEventListener('error', (e) => {
    report('script', String(e.message), (e.filename || '') + ':' + (e.lineno || ''));
  });
  window.addEventListener('unhandledrejection', (e) => {
    report('promise', String((e.reason && e.reason.message) || e.reason));
  });

  function viewed(what, extra) {
    call('log', Object.assign({ kind: 'view', what }, extra || {})).catch(() => {});
  }

  /* ------------------------------------------------------------ rendering */
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function scrollDown() {
    const c = $a('#aConv');
    c.scrollTop = c.scrollHeight;
  }

  /* Long text (the announcements, a run's summary lines) folded behind a details toggle (Decision 24). */
  function details(box, lines) {
    if (!(lines || []).length) return;
    const d = el('details', 'adetails');
    d.appendChild(el('summary', '', 'details (' + lines.length + ' line' + (lines.length === 1 ? '' : 's') + ')'));
    for (const line of lines) d.appendChild(el('div', 'aann', line));
    box.appendChild(d);
  }

  /* A card for an outcome: the plan as a short list of its steps, the question with a button per option, or the stop;
   * what the outcome announces is under details. */
  function card(out, opts) {
    const box = el('div', 'acard t' + out.type.toLowerCase());
    if (out.type === 'STOP') {
      box.appendChild(el('div', 'astop', 'STOP: ' + (out.reason || '')));
    } else if (out.type === 'QUESTION') {
      const q = out.question || {};
      box.appendChild(el('div', 'aq', 'QUESTION: ' + (q.text || '')));
      const row = el('div', 'aopts');
      (q.options || []).forEach((o, i) => {
        const b = el('button', 'ghost asmall', (i + 1) + '. ' + o);
        b.disabled = !(opts && opts.live);
        b.addEventListener('click', () => send(o));
        row.appendChild(b);
      });
      box.appendChild(row);
    } else {
      box.appendChild(el('div', 'aplan', 'PLAN:'));
      const ol = el('ol', 'asteps');
      for (const s of out.steps || []) ol.appendChild(el('li', '', s.op || s));
      box.appendChild(ol);
    }
    details(box, out.announce);
    tutorLines(box, out.tutor);       // for a PLAN too: its run's lines are in the Run tab, not here
    return box;
  }

  /* The tutor's lines (Decision 11); an example phrase is a link that puts it in the command box. */
  function tutorLines(box, tutor) {
    if (!tutor || !(tutor.lines || []).length) return;
    const t = el('div', 'atutor');
    for (const line of tutor.lines) {
      const d = el('div', '', line);
      const p = (tutor.phrases || []).find((x) => line.includes(x));
      if (p) {
        d.textContent = '';
        const i = line.indexOf(p);
        d.appendChild(document.createTextNode(line.slice(0, i)));
        const a = el('a', 'alink', p);
        a.href = '#';
        a.addEventListener('click', (e) => { e.preventDefault(); fillBox(p); });
        d.appendChild(a);
        d.appendChild(document.createTextNode(line.slice(i + p.length)));
      }
      t.appendChild(d);
    }
    box.appendChild(t);
  }

  function entry(said, out, how) {
    const e = el('div', 'aentry');
    const h = el('div', 'asaid' + (how ? ' aview' : ''), (how ? how + ': ' : '> ') + said);
    e.appendChild(h);
    if (out) e.appendChild(card(out));
    $a('#aConv').appendChild(e);
    scrollDown();
    return e;
  }

  function note(text, cls) {
    $a('#aConv').appendChild(el('div', 'anote ' + (cls || ''), text));
    scrollDown();
  }

  function pinned(pending) {
    const p = $a('#aPending');
    p.textContent = '';
    p.hidden = !pending;
    $a('#aCmd').placeholder = pending ? 'answer the question, or type a new command'
      : 'for example: Re-run with DER_0 = 1e-4';
    if (!pending) return;
    p.appendChild(card({ type: 'QUESTION', question: pending.question, announce: [] }, { live: true }));
  }

  /* --------------------------------------------------------------- state */
  async function refresh() {
    STATE = await call('state');
    $a('#aProject').textContent = STATE.project || 'no project folder: use Browse';
    $a('#aProject').title = STATE.project || '';
    $a('#aWorking').textContent = 'SiCoPR-Assist ' + STATE.version + ' - ' + STATE.line;
    pinned(STATE.pending);
    return STATE;
  }

  async function syncOverlay(changed) {
    if (!STATE || !STATE.project) return;
    const o = await call('overlay', { keys: KEYS, changed: changed || [] });
    if (o.error) return;
    if (o.source_kind === 'other') {
      emit('overlay', null);
      note('The working config comes from ' + o.source + ', which is not a workbook, so the Config view cannot show '
        + 'it. Show me the config. lists it here.', 'amuted');
      return;
    }
    if (!o.source) { emit('overlay', null); return; }
    if (VIEW_PATH && norm(VIEW_PATH) !== norm(o.source)) {
      if (FOLLOWING) return;
      // the view is on another workbook: show the one the working config comes from (its config event then
      // asks for the overlay again)
      emit('open-config', { path: o.source });
      return;
    }
    emit('overlay', { source: 'assist', title: o.title, cells: o.cells, save_hint: o.save_hint,
      run_note: o.run_note, focus: o.focus });
  }

  function showSource() {
    if (FOLLOWING) return;
    if (STATE && STATE.source && STATE.source_kind === 'workbook') emit('open-config', { path: STATE.source });
  }

  /* ------------------------------------------- the command box and the selection */
  /* The box grows with what is typed in it, from its three lines up to BOX_MAX_PX. */
  function fitBox() {
    const box = $a('#aCmd');
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight + 4, BOX_MAX_PX) + 'px';   // 4: its two borders
  }

  /* The command box takes the focus when the panel comes up: SiCoPR shows the slot only after this script has
   * loaded, so it is tried until the box is on screen, and never taken from a field the user is already in. */
  function focusBox(tries) {
    const box = $a('#aCmd');
    const free = !document.activeElement || document.activeElement === document.body;
    if (box.offsetParent !== null && !box.disabled) {
      if (free) box.focus();
      return;
    }
    if (tries > 0) setTimeout(() => focusBox(tries - 1), 50);
  }

  function fillBox(text) {
    const box = $a('#aCmd');
    box.value = text;
    fitBox();
    box.focus();
  }

  /* The selection line follows the tabs. It is asked from the server, which says what the core will be handed. */
  async function syncSelection() {
    if (!STATE || !STATE.project) return;
    const r = await call('selection', { selection: SELECTION });
    if (r.error) return;
    $a('#aSelLine').textContent = r.line;
    $a('#aSelLine').title = [r.selection.config, r.selection.thru].concat(r.selection.fext, r.selection.next)
      .filter(Boolean).join('\n');
    RUN_PHRASE = r.phrase || RUN_PHRASE;
  }

  /* Up to four phrases that work now, under the command box; clicking one puts it in the box (Decision 21). */
  async function loadExamples() {
    if (!STATE || !STATE.project) return;
    const r = await call('examples', { selection: SELECTION });
    const host = $a('#aExamples');
    host.textContent = '';
    if (r.error || !(r.phrases || []).length) return;
    host.appendChild(el('span', 'amuted', 'Examples (click one to put it in the box):'));
    for (const p of r.phrases) {
      const b = el('button', 'aexample', p);
      b.type = 'button';
      b.addEventListener('click', () => fillBox(p));
      host.appendChild(b);
    }
  }

  /* --------------------------------------------------------- the Run tab */
  /* The Run tab shows the setup the panel runs: a plan's files, options and command, or, after a change in the Run
   * tab, the command for what it holds now (Decision 23). */
  function assemble(tab) {
    ASSEMBLED = tab;
    emit('set-run', tab);
  }

  async function reassemble() {
    const r = await call('runtab', { selection: SELECTION });
    if (r.error || !r.command) return;
    assemble(r);
  }

  /* ------------------------------------------------------------ commands */
  async function send(phrase, how) {
    phrase = String(phrase || '').replace(/\s*\n\s*/g, ' ').trim();
    if (!phrase) return;
    // a half-typed edit in the Config view is committed, and taken in, before the phrase is read
    if (document.activeElement && document.activeElement !== $a('#aCmd')
        && document.activeElement.blur) document.activeElement.blur();
    await EDITS;
    FOLLOWING = false;                 // a phrase answers the keep-or-start question, or sets it aside
    $a('#aCmd').value = '';
    fitBox();
    RECALL = -1;
    if (!PHRASES.length || PHRASES[0] !== phrase) PHRASES.unshift(phrase);
    const r = await call('handle', { phrase, selection: SELECTION });
    if (r.error) { note(r.error, 'abad'); return; }
    entry(phrase, r.outcome, how);
    if (r.refused) note(r.refused, 'abad');
    JOB_TAB = r.job ? (r.run_tab || null) : null;
    if (r.run_tab) assemble(r.run_tab);           // the Run tab shows what this plan runs
    await refresh();
    await syncOverlay((r.outcome.changes || []).map((c) => c.json_path));
    if (r.job) startJob();
    else loadExamples().catch(() => {});
  }

  function busyUi(on) {
    $a('#aCmd').disabled = on;
    $a('#aSend').disabled = on;
    $a('#aRunSel').disabled = on;
    $a('#aExamples').hidden = on;       // no phrase can be sent while a plan runs
    $a('#aRunning').hidden = !on;       // the one line the panel shows while it runs; its output is in the Run tab
  }

  function startJob() {
    SINCE = 0;
    FAILS = 0;
    SHOWN_RUN = false;
    $a('#aRunLine').textContent = 'starting';
    busyUi(true);
    poll();
  }

  /* The Run tab's status line for the panel's run, in the form SiCoPR gives its own. */
  function runState(st) {
    const quiet = st.running && st.quiet > 20 ? ', no output for ' + Math.round(st.quiet) + ' s' : '';
    if (st.running) return 'SiCoPR-Assist #' + st.seq + ' running, ' + Math.round(st.elapsed) + ' s' + quiet;
    return 'SiCoPR-Assist #' + st.seq + ' finished ('
      + (st.stopped ? 'stopped' : (st.done || {}).status || (st.error ? 'failed' : 'ok')) + ') in '
      + Math.round(st.elapsed) + ' s';
  }

  /* The lines of a plan that runs go to the Run tab's Output (Decision 24), as a run of the Run tab's own; when it
   * starts the page shows the Run tab, unless the user is in the middle of an edit in Config. */
  function toRunTab(st) {
    if (!st.runs) return;
    if (!SHOWN_RUN) {
      SHOWN_RUN = true;
      emit('show', { view: 'run', unless_editing: true });
    }
    const lines = st.lines.map((x) => x[1]);
    if (st.resync) lines.unshift('[SiCoPR-Assist] earlier lines were dropped; the whole output is in run.log');
    emit('output', { job: 'SiCoPR-Assist #' + st.seq, lines, status: runState(st), done: !st.running });
  }

  async function poll() {
    clearTimeout(POLL);
    let st;
    try {
      st = await call('job?since=' + SINCE);
      FAILS = 0;
    } catch (e) {
      // a failed poll retries with backoff and never ends the loop, as SiCoPR's run poller does
      FAILS += 1;
      const wait = Math.min(30000, 900 * Math.pow(2, FAILS));
      $a('#aRunLine').textContent = 'status unavailable (' + FAILS + 'x), retrying in ' + Math.round(wait / 1000) + ' s';
      POLL = setTimeout(poll, wait);
      return;
    }
    if (st.idle) { busyUi(false); return; }
    toRunTab(st);
    SINCE = st.next;
    $a('#aRunLine').textContent = st.runs ? st.running_line : 'carrying out the plan of #' + st.seq;
    if (st.running) { POLL = setTimeout(poll, 900); return; }
    busyUi(false);
    await finished(st);
  }

  /* A batch's reply: its short table, one row per point (Decision 24). */
  function batchTable(b) {
    const t = el('table', 'atable');
    const head = el('tr');
    for (const h of ['#', 'case', 'status', 'run', 'COM dB']) head.appendChild(el('th', '', h));
    t.appendChild(head);
    for (const r of b.rows || []) {
      const tr = el('tr');
      for (const v of [r.point, r.values, r.status, r.run_id, r.com]) tr.appendChild(el('td', '', String(v)));
      t.appendChild(tr);
    }
    return t;
  }

  async function finished(st) {
    for (const o of st.outcomes || []) entry('(the plan made from the download)', o, 'next');
    if (st.error) note('the plan could not be carried out: ' + st.error, 'abad');
    const done = st.done || {};
    if (st.stopped) note('stopped: the run under way was terminated and nothing after it started', 'abad');
    const runs = [...new Set(done.run_ids || [])];
    const batchSeq = (done.points || []).length ? st.seq : null;
    if (!runs.length && !batchSeq) {
      const box = el('div', 'acard aresult');
      for (const line of (done.lines || []).slice(0, 3)) box.appendChild(el('div', 'aann', line));
      details(box, (done.lines || []).slice(3));
      if ((done.lines || []).length) $a('#aConv').appendChild(box);
    }
    if (batchSeq) {
      const b = await call('batch?seq=' + batchSeq);
      if (!b.error) {
        const box = el('div', 'acard aresult');
        box.appendChild(el('div', 'aplan', 'batch of ' + (done.points || []).length + ' points'));
        box.appendChild(batchTable(b));
        details(box, (done.lines || []).concat([b.csv]));
        $a('#aConv').appendChild(box);
      }
    } else {
      for (const rid of runs) {
        const r = await resultCard(rid, done.lines);
        // a run made with Output dynamic results ticked opens in Results, dynamic, which builds its dashboard there,
        // as a run started from the Run tab with that box ticked does (Decision 23)
        if (r && r.export_mat && JOB_TAB && JOB_TAB.options && JOB_TAB.options.export_mat
            && !(st.pages || []).length) {
          emit('show', { view: 'dynamic', run: r.folder, build: true });
          viewed('run in Results, dynamic', { run: rid });
        }
      }
    }
    JOB_TAB = null;
    for (const page of st.pages || []) {           // a dashboard: shown in Results, dynamic, not in a new tab
      const folder = page.replace(/[\\/][^\\/]*$/, '');
      emit('show', { view: 'dynamic', run: folder });
      viewed('dashboard', { path: page });
    }
    await refresh();
    await syncOverlay([]);
    scrollDown();
    loadExamples().catch(() => {});
    focusBox(0);
  }

  /* A run's reply: the headline result (COM, pass or fail), the buttons that open it in Results, and the summary
   * under details. */
  async function resultCard(rid, more) {
    const r = await call('result?run=' + encodeURIComponent(rid));
    if (r.error) return null;
    const box = el('div', 'acard aresult');
    box.appendChild(el('div', 'aheadline', r.headline));
    const row = el('div', 'aopts');
    for (const [view, label] of [['results', 'Results, static'], ['dynamic', 'Results, dynamic']]) {
      const b = el('button', 'ghost asmall', label);
      b.addEventListener('click', () => {
        emit('show', { view, run: r.folder });
        viewed('run in ' + label, { run: rid });
        if (view === 'dynamic' && !r.export_mat) noDynamic(rid, r.dynamic_phrase);
      });
      row.appendChild(b);
    }
    box.appendChild(row);
    details(box, (more || r.lines || []));
    $a('#aConv').appendChild(box);
    return r;
  }

  /* Results, dynamic opened on a run with no .mat export has nothing to show: said here, with the phrase that makes
   * one (Decision 23, the vocabulary). */
  function noDynamic(rid, phrase) {
    const box = el('div', 'anote amuted');
    box.appendChild(document.createTextNode(rid + ' was run without the .mat export, so Results, dynamic has nothing '
      + 'to show for it. This runs it again with the export and builds its dashboard: '));
    const b = el('button', 'aexample', phrase);
    b.type = 'button';
    b.addEventListener('click', () => fillBox(phrase));
    box.appendChild(b);
    $a('#aConv').appendChild(box);
    scrollDown();
  }

  /* --------------------------------------------------- the Config view */
  window.addEventListener('sicopr:config', (e) => {
    const d = e.detail || {};
    KEYS = d.keys || [];
    VIEW_PATH = d.path;
    SELECTION.config = d.path || null;
    (async () => {
      if (!STATE) await refresh();
      if (!STATE.project) return;
      await syncSelection();
      const same = STATE.source && norm(STATE.source) === norm(d.path);
      if (d.cause === 'user' && !same) {
        // another workbook opened in the Config view: Assist follows (GUI_DESIGN.md section 6)
        FOLLOWING = true;
        const r = await call('open', { path: d.path });
        FOLLOWING = !!(r.outcome && r.outcome.type === 'QUESTION');   // held until the question is answered
        if (r.error) { note(r.error, 'abad'); return; }
        if (r.outcome) entry(r.outcome.type === 'PLAN' ? 'opened ' + d.name : 'open ' + d.name, r.outcome,
          'config view');
        await refresh();
        if (r.outcome && r.outcome.type === 'PLAN') {
          await syncOverlay((r.outcome.changes || []).map((c) => c.json_path));
          if (ASSEMBLED) await reassemble();      // the Run tab's command names the workbook followed
        } else if (r.outcome && r.outcome.type === 'STOP') {
          showSource();
        }
        // a QUESTION (keep the overrides, or start as saved) leaves the view on the new workbook until it is answered
        return;
      }
      if (d.cause === 'boot' && STATE.source && !same && STATE.source_kind === 'workbook') {
        showSource();
        return;
      }
      await syncOverlay([]);
    })().catch((x) => report('config event', String(x.message || x)))
      .then(() => loadExamples())                  // the examples are written with the names of the config in view
      .catch(() => {});
  });

  /* The channel files picked in the Run tab (Decision 20): kept, shown in the selection line, and handed to the
   * core with the next phrase. */
  window.addEventListener('sicopr:channels', (e) => {
    const d = e.detail || {};
    SELECTION.thru = d.thru || null;
    SELECTION.fext = (d.fext || []).slice();
    SELECTION.next = (d.next || []).slice();
    const o = d.options || {};
    SELECTION.options = { export_mat: o.export_mat === true, eye_under_mlse: o.eye_under_mlse === true };
    (async () => {
      if (!STATE) await refresh();
      await syncSelection();
      // a change the user made in the Run tab while it holds this panel's setup: its command follows (Decision 23);
      // a change the panel made itself (cause panel) needs nothing more
      if (ASSEMBLED && d.cause !== 'panel' && STATE.project) await reassemble();
    })().catch((x) => report('channels event', String(x.message || x)));
  });

  /* The Run tab's Run button, while this panel has the Run tab assembled (Decision 23): taken here and carried out as
   * Run the command., with the files and options it was pressed with; one history record, the same plan, the same
   * progress. Without an assembled Run tab the button is left to SiCoPR. */
  window.addEventListener('sicopr:run-request', (e) => {
    if (!ASSEMBLED || !STATE || !STATE.project) return;
    e.preventDefault();
    const d = e.detail || {};
    SELECTION.thru = d.thru || null;
    SELECTION.fext = (d.fext || []).slice();
    SELECTION.next = (d.next || []).slice();
    const o = d.options || {};
    SELECTION.options = { export_mat: o.export_mat === true, eye_under_mlse: o.eye_under_mlse === true };
    if ($a('#aCmd').disabled) {
      note('a plan is being carried out; the Run button runs when it ends, or press Stop here', 'abad');
      return;
    }
    send(RUN_COMMAND, 'Run button').catch((x) => note(x.message, 'abad'));
  });

  /* Stop in the Run tab while its Output shows this panel's run (Decision 24): the plan is stopped here. */
  window.addEventListener('sicopr:stop-request', (e) => {
    const d = e.detail || {};
    if (!String(d.job || '').startsWith('SiCoPR-Assist #')) return;
    call('stop', {}).then((r) => {
      if (!r.stopped) note('nothing was running', 'amuted');
    }).catch(() => {});
  });

  window.addEventListener('sicopr:edit', (e) => {
    const d = e.detail || {};
    EDITS = EDITS.then(async () => {
      if (!STATE || !STATE.project) return;
      const r = await call('edit', { edits: [{ key: d.key, value: d.value, before: d.before }], source: VIEW_PATH });
      if (r.error) { note(r.error, 'abad'); return; }
      entry('Set ' + d.key + ' = ' + d.value, r.outcome, 'config view');
      if ((r.clear || []).length) emit('clear-edits', { keys: r.clear });
      await refresh();
      await syncOverlay((r.outcome.changes || []).map((c) => c.json_path));
    }).catch((x) => report('edit event', String(x.message || x)));
  });

  window.addEventListener('sicopr:run', (e) => {
    const d = e.detail || {};
    const words = (String(d.command || '').match(/"[^"]*"|\S+/g) || []).map((w) => w.replace(/^"|"$/g, ''));
    const at = words.findIndex((w) => /sicopr\.py$/i.test(w));
    const cfg = at >= 0 ? words[at + 1] : null;
    const thru = at >= 0 ? words[at + 2] : null;
    const phrase = cfg && thru ? 'Run COM on ' + thru + ' with ' + cfg + '.' : '';
    note('a run from the Run tab finished; SiCoPR-Assist does not track it.'
      + (phrase ? ' To build on it here: ' + phrase : ''), 'amuted');
    if (phrase && !$a('#aCmd').value) fillBox(phrase);
  });

  window.addEventListener('sicopr:browsed', (e) => {
    const d = e.detail || {};
    if (d.purpose !== 'assist-project') return;
    call('project', { path: d.path }).then(async (r) => {
      if (r.error) { note(r.error, 'abad'); return; }
      $a('#aConv').textContent = '';
      await refresh();
      await loadHistory();
      showSource();
      await syncSelection();
      await loadExamples();
    }).catch(() => {});
  });

  /* ---------------------------------------------------------------- wiring */
  $a('#aBrowse').addEventListener('click', () => {
    emit('browse', { purpose: 'assist-project', title: 'Choose the SiCoPR-Assist project folder (where .sicopr is)' });
  });
  $a('#aSend').addEventListener('click', () => send($a('#aCmd').value).catch((x) => note(x.message, 'abad')));
  $a('#aToRun').addEventListener('click', () => emit('show', { view: 'run' }));
  $a('#aRunSel').addEventListener('click', () => send(RUN_PHRASE).catch((x) => note(x.message, 'abad')));
  $a('#aCmd').addEventListener('input', fitBox);
  $a('#aCmd').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {             // Enter sends; Shift+Enter is a new line in the box
      e.preventDefault();
      send($a('#aCmd').value).catch((x) => note(x.message, 'abad'));
    } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !$a('#aCmd').value.includes('\n')) {
      // recall, while the box holds one line; in a text of several lines the arrows move the caret
      if (!PHRASES.length) return;
      e.preventDefault();
      RECALL = Math.max(-1, Math.min(PHRASES.length - 1, RECALL + (e.key === 'ArrowUp' ? 1 : -1)));
      $a('#aCmd').value = RECALL < 0 ? '' : PHRASES[RECALL];
      fitBox();
    }
  });
  $a('#aSettings').addEventListener('toggle', () => {
    if (!$a('#aSettings').open) return;
    call('settings').then((r) => { $a('#aSetLines').textContent = (r.lines || []).join('\n'); viewed('settings'); });
  });
  $a('#aHistory').addEventListener('toggle', () => {
    if (!$a('#aHistory').open) return;
    call('history?limit=500').then((h) => {
      const host = $a('#aHistLines');
      host.textContent = '';
      for (const r of h.records || []) {
        const what = r.phrase || (r.detail ? JSON.stringify(r.detail).slice(0, 160) : '');
        host.appendChild(el('div', 'ahrec', '#' + r.seq + ' ' + (r.origin || 'cli') + ' ' + (r.kind || 'phrase')
          + (r.outcome ? ' ' + r.outcome : '') + ': ' + what));
      }
      viewed('history');
    });
  });

  /* The conversation again after a reload: the commands and Config-view records of the history. */
  async function loadHistory() {
    const h = await call('history?limit=40');
    PHRASES = h.phrases || [];
    for (const r of h.records || []) {
      if (['run', 'stop', 'view', 'error'].includes(r.kind)) continue;
      const p = r.plan || {};
      const out = { type: p.type || r.outcome || 'STOP', announce: p.announce || [],
        steps: (p.steps || []).map((op) => ({ op })), question: p.question, reason: p.reason || r.reason };
      const e = entry(r.phrase || '', out, ['edit', 'open'].includes(r.kind) ? 'config view' : '');
      e.classList.add('aold');
    }
  }

  async function init() {
    focusBox(100);                       // the command box is where a new user starts (Decision 21)
    await refresh();
    if (!STATE.project) {
      note('Choose the project folder with Browse: the folder that holds (or will hold) .sicopr.', 'amuted');
      return;
    }
    await loadHistory();
    showSource();
    if (STATE.running) startJob();
    await syncSelection();
    await loadExamples();
  }
  init().catch((x) => report('init', String(x.message || x)));
}());

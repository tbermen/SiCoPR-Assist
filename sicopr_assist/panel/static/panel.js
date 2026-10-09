/* Copyright 2026 Todd Bermensolo
 * SPDX-License-Identifier: BSD-3-Clause */
'use strict';
/* The SiCoPR-Assist panel, in SiCoPR's GUI (panel API 1: SiCoPR gui/README.md, "Panels"; GUI_DESIGN.md).
 *
 * A phrase typed here goes to the core through /panel/assist/api/handle, exactly as on the command line; a PLAN is
 * carried out on the server and its progress polled from /job. The Config view shows the working config laid over
 * its workbook (sicopr:overlay), an edit committed there is taken into the working config (sicopr:edit to /edit), and
 * a workbook opened there is followed (sicopr:config to /open). Every action is in the project's history. */
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
    <div id="aProgress" class="aprogress" hidden>
      <div class="arow"><span id="aProgState" class="amuted"></span>
        <button id="aStop" class="ghost asmall">Stop</button></div>
      <pre id="aLines" class="alines"></pre>
    </div>
    <div id="aPending" class="apending" hidden></div>
    <div class="abox">
      <input id="aCmd" type="text" spellcheck="false" autocomplete="off"
             placeholder="type a command, for example: Re-run with DER_0 = 1e-4">
      <button id="aSend">Send</button>
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
  let EDITS = Promise.resolve();   // edits being taken in; a phrase waits for them
  // a workbook the user opened in the Config view is being followed, or its keep-or-start question is open: the
  // view stays on it, and nothing here pulls it back to the source of the working config meanwhile
  let FOLLOWING = false;

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

  /* A card for an outcome: the plan with its steps, the question with a button per option, or the stop. */
  function card(out, opts) {
    const box = el('div', 'acard t' + out.type.toLowerCase());
    for (const line of out.announce || []) box.appendChild(el('div', 'aann', line));
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
    if (out.type !== 'PLAN') tutorLines(box, out.tutor);
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
        a.addEventListener('click', (e) => { e.preventDefault(); $a('#aCmd').value = p; $a('#aCmd').focus(); });
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
      : 'type a command, for example: Re-run with DER_0 = 1e-4';
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

  /* ------------------------------------------------------------ commands */
  async function send(phrase) {
    phrase = String(phrase || '').trim();
    if (!phrase) return;
    // a half-typed edit in the Config view is committed, and taken in, before the phrase is read
    if (document.activeElement && document.activeElement !== $a('#aCmd')
        && document.activeElement.blur) document.activeElement.blur();
    await EDITS;
    FOLLOWING = false;                 // a phrase answers the keep-or-start question, or sets it aside
    $a('#aCmd').value = '';
    RECALL = -1;
    if (!PHRASES.length || PHRASES[0] !== phrase) PHRASES.unshift(phrase);
    const r = await call('handle', { phrase });
    if (r.error) { note(r.error, 'abad'); return; }
    entry(phrase, r.outcome);
    if (r.refused) note(r.refused, 'abad');
    await refresh();
    await syncOverlay((r.outcome.changes || []).map((c) => c.json_path));
    if (r.job) startJob();
  }

  function busyUi(on) {
    $a('#aCmd').disabled = on;
    $a('#aSend').disabled = on;
    $a('#aProgress').hidden = !on && !$a('#aLines').textContent;
    $a('#aStop').disabled = !on;
  }

  function startJob() {
    SINCE = 0;
    FAILS = 0;
    $a('#aLines').textContent = '';
    busyUi(true);
    $a('#aProgress').hidden = false;
    poll();
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
      $a('#aProgState').textContent = 'status unavailable (' + FAILS + 'x), retrying in ' + Math.round(wait / 1000) + ' s';
      POLL = setTimeout(poll, wait);
      return;
    }
    if (st.idle) { busyUi(false); return; }
    const pre = $a('#aLines');
    if (st.resync) pre.textContent = '';
    if (st.lines.length) {
      const keep = (pre.textContent ? pre.textContent.split('\n') : []).concat(st.lines.map((x) => x[1]));
      pre.textContent = keep.slice(-2000).join('\n');
      pre.scrollTop = pre.scrollHeight;
    }
    SINCE = st.next;
    const quiet = st.running && st.quiet > 20 ? ', no output for ' + Math.round(st.quiet) + ' s' : '';
    $a('#aProgState').textContent = st.running ? 'running, ' + Math.round(st.elapsed) + ' s' + quiet
      : 'finished in ' + Math.round(st.elapsed) + ' s';
    if (st.running) { POLL = setTimeout(poll, 900); return; }
    busyUi(false);
    await finished(st);
  }

  async function finished(st) {
    for (const o of st.outcomes || []) entry('(the plan made from the download)', o, 'next');
    if (st.error) note('the plan could not be carried out: ' + st.error, 'abad');
    const done = st.done || {};
    for (const line of done.lines || []) note(line, 'aout');
    const runs = [...new Set(done.run_ids || [])];
    const batchSeq = (done.points || []).length ? st.seq : null;
    if (batchSeq) {
      const b = await call('batch?seq=' + batchSeq);
      if (!b.error) {
        const box = el('div', 'acard aresult');
        box.appendChild(el('div', 'aplan', 'batch of ' + (done.points || []).length + ' points'));
        for (const line of b.lines) box.appendChild(el('div', 'aann', line));
        box.appendChild(el('div', 'amuted', b.csv));
        $a('#aConv').appendChild(box);
      }
    } else {
      for (const rid of runs) await resultCard(rid);
    }
    for (const page of st.pages || []) {           // a dashboard: shown in Results, dynamic, not in a new tab
      const folder = page.replace(/[\\/][^\\/]*$/, '');
      emit('show', { view: 'dynamic', run: folder });
      viewed('dashboard', { path: page });
    }
    await refresh();
    await syncOverlay([]);
    scrollDown();
  }

  async function resultCard(rid) {
    const r = await call('result?run=' + encodeURIComponent(rid));
    if (r.error) return;
    const box = el('div', 'acard aresult');
    for (const line of r.lines) box.appendChild(el('div', 'aann', line));
    const row = el('div', 'aopts');
    for (const [view, label] of [['results', 'Results, static'], ['dynamic', 'Results, dynamic']]) {
      const b = el('button', 'ghost asmall', label);
      b.addEventListener('click', () => {
        emit('show', { view, run: r.folder });
        viewed('run in ' + label, { run: rid });
      });
      row.appendChild(b);
    }
    box.appendChild(row);
    $a('#aConv').appendChild(box);
  }

  /* --------------------------------------------------- the Config view */
  window.addEventListener('sicopr:config', (e) => {
    const d = e.detail || {};
    KEYS = d.keys || [];
    VIEW_PATH = d.path;
    (async () => {
      if (!STATE) await refresh();
      if (!STATE.project) return;
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
    })().catch((x) => report('config event', String(x.message || x)));
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
    if (phrase && !$a('#aCmd').value) $a('#aCmd').value = phrase;
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
    }).catch(() => {});
  });

  /* ---------------------------------------------------------------- wiring */
  $a('#aBrowse').addEventListener('click', () => {
    emit('browse', { purpose: 'assist-project', title: 'Choose the SiCoPR-Assist project folder (where .sicopr is)' });
  });
  $a('#aSend').addEventListener('click', () => send($a('#aCmd').value).catch((x) => note(x.message, 'abad')));
  $a('#aStop').addEventListener('click', () => call('stop', {}).then((r) => {
    note(r.stopped ? 'stop requested: the run under way is terminated and nothing after it starts'
      : 'nothing was running', 'amuted');
  }));
  $a('#aCmd').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      send($a('#aCmd').value).catch((x) => note(x.message, 'abad'));
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      if (!PHRASES.length) return;
      e.preventDefault();
      RECALL = Math.max(-1, Math.min(PHRASES.length - 1, RECALL + (e.key === 'ArrowUp' ? 1 : -1)));
      $a('#aCmd').value = RECALL < 0 ? '' : PHRASES[RECALL];
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
    await refresh();
    if (!STATE.project) {
      note('Choose the project folder with Browse: the folder that holds (or will hold) .sicopr.', 'amuted');
      return;
    }
    await loadHistory();
    showSource();
    if (STATE.running) startJob();
  }
  init().catch((x) => report('init', String(x.message || x)));
}());

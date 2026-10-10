# SiCoPR-Assist GUI: design

Phase V2-4, 9 October 2026; approved the same day with the maintainer's two changes (sections 6 and 7a), and
built in Phase V2-5 (SiCoPR-Assist 0.7.0, and the slot of section 4 on SiCoPR's branch `gui-panel-slot`).
Where the build differs from the text below, the text was changed to match and section 13 lists it. The
static mock-up is `docs\gui_mockup.html` (open it from the file system; it needs no server and no network).

Changed in Phase V2-6 (10 October 2026, SiCoPR-Assist 0.8.0) after the maintainer's first session with the
GUI: the selection in the tabs (section 5a, and the event `sicopr:channels` in section 4.1), the command box
(section 5, item 5), and the example that runs from an empty folder (section 7). Section 14 lists what was
built and where it differs from what was written. The mock-up still shows the 0.7.0 panel.

Written against SiCoPR-Assist 0.6.0 (`f884c1f`) and SiCoPR `55c3f71` (1.1.1), whose GUI was read in full
(`gui\app.py`, `config_io.py`, `runner.py`, `schematic.py`, `static\`, `README.md`) and run once from a
temporary folder (`--no-browser --dir <temp> --run-dir <temp>`, port 8799) to see its layout, views and
endpoints. SiCoPR was left untouched (`git status --porcelain` empty afterwards).

## 1. What the maintainer asked for

The GUI looks like SiCoPR's existing GUI, with a persistent Assist panel on the right where SiCoPR-Assist
commands are typed. As a command is carried out, its changes show in the standard SiCoPR views, so the user
can review them or change something there, then go back to the panel. Both ways must work: an Assist command
shows up in the SiCoPR views, and an edit made in the SiCoPR views is what the next Assist command builds on.
Earlier decisions still hold: the GUI is public, stands alone (folders are browsed, never assumed), calls the
same functions as `cli.py` (Decision 13) and never reaches past the core, and keeps its pieces separable so
that si-gui can later combine the GUIs of SiCoPR, SiCoPR-Assist and BeSS.

## 2. SiCoPR's GUI as it is

A stdlib HTTP server bound to 127.0.0.1 (`gui\app.py`, port 8765 or `SICOPR_GUI_PORT`) and one page
(`static\index.html`, `app.js`, `style.css`). Five tabs, one operation each:

| tab | what it does | endpoints |
|---|---|---|
| Config | pick a workbook, edit it on the channel schematic (16 blocks in 4 lanes), Save as a new workbook | `/api/config_dirs`, `/api/configs`, `/api/config`, `/api/save`, `/api/new_config` |
| S-parameters | plot SDD21, SDD11, SDD22 of Touchstone files through the engine's own reader | `/api/channel_dirs`, `/api/channels`, `/api/sparam` |
| Run | choose THRU, FEXT, NEXT; show the exact argv; run `sicopr.py`; stream its output | `/api/netlist`, `/api/exec/start`, `/api/exec/status`, `/api/exec/stop` |
| Results, static | per run folder: per `case_NN`, the headline numbers from `results.csv` and the PNG figures by stage | `/api/results`, `/api/run`, `/figure` |
| Results, dynamic | the R dashboard of a `.mat` export, built on demand | `/api/dynamic`, `/api/render`, `/rpt/...` |

What matters for this design:

- **Trust model.** Paths are accepted only under roots the user opened: the repository, `--dir`, `--run-dir`,
  and directories chosen in the Browse dialog (`/api/open`). Browsing grants nothing.
- **Edits.** `app.js` keeps `EDITS` (key to typed value) in the page. A `[TX RX]` cell is shown under both ends
  of the link with keys `name#tx` and `name#rx`, recombined on save. Save as writes a copy of the workbook
  with only the changed cells rewritten (`config_io.write_config`, sheet XML edited in place so formulas and
  cached values survive), and warns `STALE:` when a formula's precedent changes.
- **Runs.** `runner.py` runs one job per slot (`com`, `render`), argv only, no shell, unbuffered, bounded
  buffer, polled by `since`. The Run tab always runs the workbook file as saved.
- **Results are found by content.** A run folder is one with `case_NN` folders or an engine `results.csv`,
  up to 3 levels under a root. SiCoPR-Assist's run folders (`.sicopr\runs\run_NNNN\case_01\...`) are exactly
  3 levels under the project folder, so opening the project folder makes every Assist run appear in both
  Results tabs with no change. Assist's dashboard files (`run_NNNN_case01.mat` and
  `run_NNNN_case01_report.html` in the run folder) also match what Results, dynamic looks for.
- **Package blocks** are counted but not shown as editable fields; the Config tab edits the main area only.
- **It is a supporting tool**, outside the maintainer's commitment (`docs\MAINTAINING.md`, section 1): it never
  changes a COM result and is provided as it is. Its tests: `tests\test_gui_server.py` (71 checks),
  `tests\test_gui_static.py` (parses `app.js`; every class that sets `display` has a `[hidden]` rule),
  `tests\test_config_roundtrip.py`.

## 3. Architecture options

| | (A) a panel slot in SiCoPR's GUI | (B) Assist serves SiCoPR's GUI and patches in its panel | (C) a copy of SiCoPR's GUI in Assist |
|---|---|---|---|
| what it is | SiCoPR's GUI gains a small, documented extension point: installed packages register a panel; the page shows it on the right and exchanges a few named events with it | Assist imports `gui.app` from the SiCoPR install, subclasses its `Handler`, rewrites `index.html` on the fly to add the panel, and wraps `app.js` functions at run time | Assist copies `app.py`, `app.js`, `style.css`, `config_io.py`, `runner.py`, `schematic.py` (about 4,300 lines) and edits them |
| change in SiCoPR | yes, about 300 lines in `gui\` and its tests, written by the maintainer (section 4) | none | none |
| cost now | the SiCoPR change, then the panel in Assist | the panel, plus run-time patching of names that are not an interface (`Handler`, `EXTRA_ROOTS`, `CFG`, `EDITS`, `renderPanel`, element ids) | the copy, its licence notes, and edits throughout it |
| cost later | a versioned contract to keep stable (one endpoint, two route prefixes, eleven event names since Phase V2-6); every SiCoPR GUI fix reaches Assist users at once | any SiCoPR GUI change can break Assist with no test in SiCoPR to say so; Assist would have to pin the hashes of SiCoPR's GUI files and fail on every SiCoPR release | drift: SiCoPR's fixes (the poll that died, the unbounded terminal, the Windows path split of 1 October) never reach the copy; two config editors for one file format; si-gui would have to merge two forks |
| SiCoPR with no Assist installed | unchanged: no panel registered, the slot stays hidden | unchanged | unchanged |
| for si-gui and BeSS | the same slot takes a BeSS panel or an si-gui composition | nothing reusable | nothing reusable |

**Recommendation: (A).** It is the only option where both GUIs keep working on their own and keep working
together after either one changes. It puts the cost where it belongs: SiCoPR owns a small, tested,
documented surface; Assist owns everything Assist-specific. The change sits in `gui\`, a supporting tool
outside the engine commitment, and never touches a COM result, so it needs no reference rerun. (B) is cheap
for one week and expensive for every release after it. (C) is the drift the earlier decision warned
against.

A fourth shape, two servers with the SiCoPR GUI in an iframe beside an Assist page, was set aside: the two
pages would live on different origins and could not exchange the events that make the views follow the
commands, which is the point of the maintainer's direction.

**If SiCoPR does not take the change**, the fallback is a panel-only page served by Assist itself (the same
panel bundle, mounted at `/` by a small Assist server), without the SiCoPR views and so without the two-way
sync; the user keeps SiCoPR's GUI open in another tab. (B) is not recommended even then.

## 4. The SiCoPR change (for the maintainer to decide)

Written as a description, because SiCoPR takes no pull requests: the maintainer writes it in a SiCoPR
session, from this section, if he takes it. Nothing in SiCoPR-Assist depends on its exact code, only on the
contract below.

### 4.1 The contract (panel API 1)

A panel is registered by an installed package through the Python entry-point group `sicopr.gui_panels`.
The entry point names an object (a module is fine) with:

| attribute | meaning |
|---|---|
| `API` | `1`; a panel with another value is skipped with a console line |
| `NAME` | a slug, `[a-z0-9_]+`, used in URLs (`assist`) |
| `TITLE` | the heading shown above the panel (`SiCoPR-Assist`) |
| `STATIC` | a folder holding `panel.js` and optionally `panel.css` |
| `handle(method, path, query, body, host)` | answers `/panel/<NAME>/api/<path>`; returns a JSON-able object, or `(status, content_type, bytes)` |
| `busy()` (optional) | `None`, or a short text when the panel has a COM run in progress |

`host` is the only view a panel gets of SiCoPR's server: `host.roots()` (the opened directories, a copy),
`host.run_dir()` (the Run tab's working directory) and `host.com_running()` (whether the Run tab's `com` slot
is live). A panel checks its own paths against `host.roots()`, so it follows SiCoPR's trust model.

On the page, SiCoPR and a panel talk through `CustomEvent`s on `window`. SiCoPR sends:

| event | detail | when |
|---|---|---|
| `sicopr:config` | `{path, name, cause, keys}` | a workbook was loaded in the Config tab; `cause` is `user`, `boot` (the first load) or `panel` (an `sicopr:open-config`), and `keys` are the field keys the view shows (as built, section 13) |
| `sicopr:edit` | `{key, name, half, value, before}` | a field's edit is committed (the input's `change` event: Enter or leaving the field) |
| `sicopr:view` | `{view}` | the tab changed |
| `sicopr:run` | `{returncode, command, cwd}` | a run started from the Run tab finished (once per run, under the existing `RUN_DONE` guard) |
| `sicopr:browsed` | `{purpose, path}` | the Browse dialog was used for a panel (see `sicopr:browse`) |
| `sicopr:channels` | `{thru, fext, next, cause}` | the channel files chosen in the Run tab changed (added in Phase V2-6, section 5a): `thru` a path, empty when none, `fext` and `next` lists of paths, as the page holds them. Sent once at start (`cause` `boot`; the lists are empty until the Run tab is first opened), on a pick in THRU, FEXT or NEXT (`user`), and when the lists are filled again and the selection differs (`list`: a directory, the filter, the first THRU taken by default) |

The panel API number stays 1: an event was added and none changed, so a panel written for the ten events of
0.7.0 works as before.

and listens for:

| event | detail | what SiCoPR does |
|---|---|---|
| `sicopr:open-config` | `{path}` | selects and loads that workbook (with the usual discard-edits confirm) |
| `sicopr:overlay` | `{source, title, cells: {key: {value, tag, note}}, save_hint, run_note, focus}` or `null` | shows each listed key with the overlay value in place of the workbook value, a tag (`tag` text), and the workbook value in the field's info line; marks the blocks that hold overlaid keys; shows `title` in the header; while an overlay is set, Save as is disabled with `save_hint` as its tooltip and the Run tab shows `run_note` under its config line. `focus` (a list of keys) selects their block when they all sit in one. `null` removes it |
| `sicopr:clear-edits` | `{keys}` | drops those keys from `EDITS` (the panel took them) |
| `sicopr:show` | `{view, run}` | switches tab; with `run`, selects that run folder in the Results tabs |
| `sicopr:browse` | `{purpose, title}` | opens the Browse dialog; "Use this directory" opens the directory (`/api/open`, as today) and answers with `sicopr:browsed` |

Keys are SiCoPR's own: `name` for a main keyword, `name#tx` and `name#rx` for the halves of a `[TX RX]` cell,
`BLOCK/name` for a package-block keyword.

### 4.2 Files and size

| file | change | about |
|---|---|---|
| `gui\app.py` | load panels from the entry points at start (and `--no-panels`); `GET /api/panels` (`{api: 1, panels: [{name, title, script, style}]}`); `/panel/<name>/static/<file>` served by base name only, as `/static/` is; `/panel/<name>/api/...` routed to `handle` with a `host`; `/api/exec/start` refuses while a panel reports `busy()`; a panel that fails to import or raises is reported and skipped | 80 lines |
| `gui\static\index.html` | the views and a right-hand `<aside id="panelSlot" hidden>` in one grid | 6 lines |
| `gui\static\style.css` | the grid with the slot (400 px, sticky, own scroll; one column under 1200 px), `.panelslot[hidden]`, the overlay tag and field highlight, the dashed outline of a block with overlaid keys | 30 lines |
| `gui\static\app.js` | `loadPanels()` in `boot()`; the five events sent and five handled (six sent since Phase V2-6: `sicopr:channels`, about 25 lines); `OVERLAY` beside `EDITS` (a field compares with the overlay value when there is one, so editing back to it is not a change); Browse for a panel | 110 lines |
| `gui\README.md` | a section "Panels": the contract above, and that no panel means no change | 40 lines |
| `tests\test_gui_server.py` | no panel: `/api/panels` gives `[]`, the page and every existing check unchanged; a stand-in panel (a module injected in place of the entry points): its static and api routes answer, `../` and absolute paths under `/panel/` are refused, a raising panel is skipped and the server still serves, `busy()` makes `/api/exec/start` refuse with its text | about 15 checks, 90 lines |
| `tests\test_gui_static.py` | the slot is hidden by default; every event name `app.js` sends or handles is in the README's table; `.panelslot[hidden]` exists (the existing hidden-class check covers it) | 20 lines |

In all, about 300 lines, none in the engine. Every new check would be shown to fail on the defect it targets
before it is kept, as the existing GUI suites were.

**Why SiCoPR's GUI keeps working with no Assist installed.** With no entry point registered, `/api/panels`
returns an empty list, the slot stays hidden and the grid is one column as today; `OVERLAY` stays `null`, so
`renderPanel` takes exactly today's path; events dispatched with no listener do nothing; the busy check loops
over an empty list. The existing 71 server checks and the static checks run unchanged, and the new "no
panel" checks pin it. A broken panel is skipped rather than taking the GUI down with it.

## 5. The Assist panel

Mounted as panel `assist` by SiCoPR-Assist's own package (`sicopr_assist\panel\`: `__init__.py` with the
contract attributes, `api.py` with the endpoint functions, `static\panel.js`, `static\panel.css`), registered
in `pyproject.toml` under `[project.entry-points."sicopr.gui_panels"]`. Launched with
`sicopr-assist gui [folder]`, which starts SiCoPR's `gui\app.py` (found through `engine.folder()`) from an
argument list with `--dir` and `--run-dir` set to the project folder; or by starting SiCoPR's GUI directly,
when the panel asks for a project folder through Browse.

From top to bottom:

1. **Project line.** The project folder (Decision 3: where `.sicopr\` lives), Browse to change it, the
   SiCoPR-Assist version, and the working config in one line: `working config run_0003, 2 overrides, 1 edit
   from the config view`.
2. **The conversation.** Each command as typed, then its outcome as a card:
   - PLAN: the announced lines, then the numbered steps (as `cli.show` prints them);
   - QUESTION: the question text and one button per option. A button sends the option text as the next
     phrase, which the core reads as the answer to the pending question, exactly as typing it would. The
     question card stays pinned at the bottom until it is answered or set aside, and the command box says
     `answer the question, or type a new command`; it survives a page reload (`pending.json`);
   - STOP: the reason, in the problem style SiCoPR uses.
   The tutor's lines (Decision 11) follow the card as on the command line; each example phrase is a link that
   puts it in the command box.
3. **Live progress** while a plan is carried out (section 7).
4. **The result** of each run: the run summary lines (`summary.run_summary`), COM first with pass or fail
   against COM Pass threshold, and buttons that show the run in Results, static or Results, dynamic.
5. **The command box** (Decision 21, Phase V2-6: the first thing a new user sees in the panel). Its own
   block at the bottom of the panel, set apart from the conversation by a rule and a border in the accent
   colour, and kept in view: the conversation scrolls above it, the block does not (it sticks to the bottom
   of the panel). From top to bottom:
   - the selection line and the **Run selection** button (section 5a);
   - the label `Type a command`;
   - a text area of three lines that grows with its content (up to about twelve lines, then it scrolls), with
     Send beside it. Enter sends; Shift+Enter starts a new line (a phrase typed on several lines is sent as
     one line); Up and Down recall earlier phrases from the project's history (`history.jsonl`, newest first,
     the same list the CLI keeps) while the box holds one line. The box has the focus when the panel comes
     up, and is never given the focus while the user is in another field;
   - one line that says so (`Enter sends. Shift+Enter starts a new line. ...`);
   - up to four example phrases, each a button that puts its phrase in the box and sends nothing. They are
     phrases that give a PLAN right now, checked by the core against the project as it is (the tutor's rule,
     row TU04): with no run yet, the phrase that runs the one config and the one channel file of the folder
     (when there is exactly one of each) and `Run the example.`; once there is a working config, the tutor's
     examples, written with the names of that config, which is the one the Config view shows. They are asked
     again when the config in view changes and when a command ends, and hidden while a plan runs.
   While a plan runs, the box, Send and Run selection are off, and Stop (in the progress block) is live.
6. **Settings** (folded): the settings in force with where each came from (`core.settings_lines`); they are
   changed by phrase (`Tutor off`) as on the command line.
7. **Language model** (folded, reserved): shows `none: this version is rules-based`. When the layer is added
   it is configured here. It works upstream of the core and never past it (version 1 prompt, section 1): it
   may turn loose wording into a phrase or propose `changes`, and the core validates them exactly as typed
   input; the conversation then shows the user's own wording and the phrase the core resolved, both kept in
   the history. The panel never gives it a way to write the run CSV, start a run or skip validation.

## 5a. The selection in the tabs (Decision 20, Phase V2-6)

The maintainer picked a config in the Config tab and a channel in the Run tab and typed `Run on the config and
channels specified in the tabs.` The panel had followed the config, but nothing told it which channel files
were picked, and strict mode had no meaning for "the selected", so it asked about `b_min(1)`.

**Where SiCoPR's GUI holds the selection.** The config is the workbook the Config tab shows (`CFG.path`, already
sent as `sicopr:config`). The channel files of a run are held by the Run tab alone, in its three lists: THRU
(`#nlThru`, one file), FEXT aggressors (`#nlFext`) and NEXT aggressors (`#nlNext`), each a list of paths the
user may fill against the file names (the filter can be switched off). They are what the Run tab's command is
built from. The S-parameters tab has a list of its own (`#spFiles`), which picks files to plot, with no roles and
no tie to a run, so it is not part of the selection. SiCoPR therefore sends `sicopr:channels` from the Run tab:
once at start, on every pick in the three lists, and whenever the lists are filled again and the selection
differs (section 4.1). The Run tab fills its lists when it is first opened, so until then the selection has a
config and no channel file.

**What the panel does with it.** It keeps the selection (`config` from `sicopr:config`, `thru`, `fext` and
`next` from `sicopr:channels`), shows it in a line above the command box, and posts it with every phrase:

    Selected: config.xlsx; THRU thru.s4p; 3 FEXT, 4 NEXT
    Selected: config.xlsx; no channel file (pick a THRU in the Run tab)

The line is asked from the panel's server (`POST selection`), which answers what the core will be handed: each
path is checked against the project folder and the opened directories, and one from anywhere else is left out
and never reaches the core. The **Run selection** button sends `Run the selected config and channels.`

**What the core does with it** (`core.handle(phrase, project, selection=...)`, one more optional input like
`origin`; the outcome is data as before). "the selected", "the specified" or "the chosen" config, channel,
channels or files, "in the tabs", "the selection" and "what is selected" mean the selection, in those forms
only: a selection word outside them is left unplaced and asked about (Rule 4).

| state | outcome | row |
|---|---|---|
| no working config yet, or the phrase names the selected config and it is another file than the source of the working config | the selected config is imported and run on the selected channels, as `Run COM on <channels> with <config>` would be: `import_config > validate_inputs > run_com > summarize`, the files and their roles announced | SL01, SL02 |
| a working config whose source is the selected config, or a phrase that names only the channel | the working config is kept, with its overrides and what was done in the Config view, and only the channel files change: `set_channel > validate_inputs > validate_config > run_com > summarize` (Decision 18's swap; one `set_channel` step for the THRU when it changes, one for the aggressors when they change) | SL05 |
| the same, and nothing changed since a completed run | STOP: the results would equal the last run (as row CH07) | |
| no channel file selected | QUESTION: select one in the Run tab, name a file, cancel | SL03 |
| no selection at all (the command line, or a phrase posted without one) | QUESTION: provide files, cancel | SL04 |
| `Re-run with the selected channel.` and no run yet | the question of row CH05 (there is no config of a last run to keep) | |
| a selected file that is not on disk, or is not a Touchstone file | STOP that names it | |
| the selection beside a sweep, named files, the example or another request | QUESTION: the selection is run on its own | |

The files run in the roles they have in the Run tab (`run_com` carries `roles`), not the roles their names
suggest: a file the user put under NEXT is a NEXT aggressor whatever it is called. An answer to a question is
posted with the selection too, so a question asked about a selection phrase is resolved against the selection of
the moment it is answered.

## 6. The config round trip

The rule: **SiCoPR-Assist's working config is the one current config while Assist is in use.** The source
workbook is never written (Decision 2). The SiCoPR Config view shows that working config laid over its
source workbook.

**What the Config view shows.** When the panel starts, or after any command, it sends `sicopr:open-config`
with the source workbook of the working config (`Context.source_path`) and then `sicopr:overlay` with every
key whose working value differs from the workbook's stored value. So the schematic, the blocks, units, notes,
cell addresses and descriptions are SiCoPR's, read from the workbook as today, and the values are Assist's.
Each overlaid field carries a tag that says where its value came from:

| tag | meaning |
|---|---|
| `Assist #12` | set by command 12 of the history |
| `edited here #13` | an edit made in the Config view, taken into the working config as record 13 |
| `linked` | recomputed by a link (Decision 15) after a change to what it depends on |
| `proposed` | a change a pending QUESTION would make (the outcome's `changes` with `applied` false); not yet in the working config |
| `option n` | a keyword offered as option n of a pending QUESTION (row RS02: `ERL Pass threshold`, `COM Pass threshold`), so the user can read both fields before choosing |

and the info line keeps the workbook value (`workbook 0.0002`). A field whose link was removed by an
explicit value says so (`link {f_b}/2.5 removed`). The header shows the working config line from section 5.
For a key the working config holds that the workbook does not (row RS26, `add_param`), the overlay entry
goes to SiCoPR's Other settings block with tag `Assist #n, not in the workbook`.

**How an Assist change appears there.** After every PLAN (before its runs start, so the user can watch
while it runs), QUESTION or STOP, the panel asks its own `overlay` endpoint and sends the result. The block
that holds a changed key is outlined on the schematic, and the panel switches the Config view to that block
when the command changed exactly one block.

**How an edit there becomes part of the working config.** When a field's edit is committed (`sicopr:edit`),
the panel sends it to its `edit` endpoint. The endpoint turns the SiCoPR key into a working-config path
(`name` to `/main/name`; `BLOCK/name` to `/packages/BLOCK/name`; a `#tx` or `#rx` half recombined with the
other half of the current working value, in the shape that value has, as SiCoPR's `join_tx_rx` does), then
calls a new core function, `core.edit(project, changes)`. That function is the structured-input path the
version 1 prompt reserves for a language-model layer (it "may propose `changes` against the working config,
and the core validates them and builds the plan exactly as it does for typed input"): it validates the
changes against the working config with `validate.validate`, applies links with `config_model.apply_changes`
(an explicit value removes that key's link; a change to `f_b` recomputes `f_z` and the rest), and returns an
outcome:

- PLAN with `set_param` or `add_param`, `recompute_linked` when links moved, and `validate_config`, and no
  run. It is recorded in the history as one record (pattern `config view: set`, phrase the canonical
  sentence `Set DER_0 = 0.0001.`), with its own working config `configs\edit_NNNN.json` and the override list
  of the last record plus this change. Then the panel sends `sicopr:clear-edits` for the key and a new
  overlay: the field now shows `edited here #13`.
- QUESTION (a rule's `ask_if`, Decision 7 style asks; a `[TX RX]` pair edited as one number goes to both sides, as
  row RS28 does for a typed number, section 13): shown in the
  panel with its buttons; the field keeps SiCoPR's green "changed" state and a `proposed` tag until the
  answer.
- STOP (a value the loader or a `stop_if` refuses): shown in the panel and under the field; the edit stays in
  SiCoPR's `EDITS` (green, unsaved) and never reaches the working config; Revert all in SiCoPR's bar drops it.

Because the next command starts from the last record that names a working config (`Context.base`), the
edit is what the next command builds on, with no other change to how the base is found.

**Both change the same keyword.** The history orders everything, and the latest record wins. A command that
changes a keyword last edited in the view announces it: `DER_0: 0.0001 -> 5e-05 (it was edited in the config
view, #13)`. An edit in the view of a keyword a command set earlier is announced in the panel the same way.
Because an edit is taken when it is committed, there is no window in which a view edit and a command race:
before a phrase is sent, the panel blurs the focused field, so a half-typed edit is committed (and checked)
first.

**How the user can tell which one is current.** One working config, one history: the header line names it,
every field that differs from the workbook carries its origin and record number, and the conversation lists
commands and view edits in one sequence. The CLI sees the same state: `What did you change?` lists the
overrides, view edits included.

**Save as.** While the overlay is set, SiCoPR's Save as is disabled, with the hint `Save the working config
from the Assist panel: Save that config as data\config_new.xlsx.`, because Save as would write the workbook
plus the unsaved edits and leave out every Assist override. Assist's own export (row CP06, `export_xlsx`)
writes the whole working config into a copy of the source workbook; the source is never the target.

**Another workbook in the Config view** (maintainer, 9 October 2026: Assist follows). If the user opens a
different workbook in the Config tab (`sicopr:config` with another path), Assist follows: it imports that
workbook as the new source through `core.edit`'s import path, keeps the channel files of the last run, and
the overlay is laid over the new workbook. The panel announces it: `SiCoPR-Assist now works on <file>
(it was <source>); the channel files of the last run are kept`. Nothing runs until a command is sent.
- If the previous working config had overrides, the panel asks once, with buttons: `keep my N overrides on
  <file>` or `start from <file> as saved`. An override whose keyword the new workbook does not hold, or whose
  value it refuses, is named and left out, as a typed change would be.
- The previous working config and its overrides stay in the history, so `Undo that change.` (row C7) or
  re-opening the earlier workbook brings them back; nothing is lost.
- A file that does not import (ST14, ST15, IV21 and the like) gives the same STOP or QUESTION as the import
  phrase would, and Assist stays on the previous source.
- The switch is one history record (pattern `config view: open`), so the history shows exactly when the
  source changed and why.

**A source that is not a workbook** (a `.csv` or `.json` config, rows CP14 and CP16): the Config view has no
workbook to show, so the panel says so and offers `Show me the config.` (row CP13). No spreadsheet is
written to make one (Decision 2).

## 7. Runs and results

**A run started from the panel.** A PLAN is carried out at once, as on the command line (Decision 13; the
use-case table scores it that way). The panel's `handle` endpoint returns the outcome, records it (the core
does), and starts `run.carry_out(project, outcome, progress=...)` in a worker thread. The progress callback
of Decision 17 appends `(kind, text)` to a bounded buffer, which the panel polls by `since`, the same pattern
as SiCoPR's runner (a failed poll retries with backoff and never ends the loop; the panel keeps the last 2000
lines; a quiet run says how long it has been silent). Status lines are shown as they are, engine lines
indented and dimmed, exactly as `run.line_text` forms them and `run.log` holds them. A two-part channel
download (rows F1 to F12) is followed the way `cli.handle_and_run` follows `next`. The command box is
disabled while a plan runs; Stop terminates the child. When a run finishes, the result card appears and the
panel sends `sicopr:show` with the run folder only if the user clicks the button (it does not pull the user
away from what they are reading), except after a dashboard phrase, where the page is shown in Results,
dynamic in place of opening a browser tab (`carry_out(open_page=...)` already takes a stand-in).

**The example in an empty project** (Decision 22, Phase V2-6). `Run the example.` in a project folder with no
channel file gives a PLAN on a synthetic THRU: the 400 mm lossy line of `sicopr_assist\example_channel.py`,
written to `data\example_thru.s4p` when the plan is carried out (the first progress line says so) and never at
plan time. The plan says that the channel is synthetic and not a measured one. A channel file already in the
folder is used instead, as row R1 does. It is the phrase under the command box in a new project.

**It lands in the results views** with no further work: the project folder is an opened root, and each run's
folder is a run directory by SiCoPR's own rule (section 2). A batch is several run folders, one per point;
the panel shows the batch summary table and the path of `batch_summary.csv`.

**One COM run at a time, across both.** The panel's `busy()` makes SiCoPR refuse to start a Run-tab run
while an Assist plan runs (`a run started from SiCoPR-Assist is in progress`), and the panel checks
`host.com_running()` before carrying out a plan with runs and answers with a STOP-styled line if the Run tab
is busy.

**A run started from the Run tab** is not in Assist's history, so Assist neither shows it in its history nor
reuses it: reuse (Decision 6) needs a recorded working config, channel hashes and engine hash, and the Run
tab runs a workbook file, not a working config. When the panel hears `sicopr:run`, it says one line: `a run
from the Run tab finished; SiCoPR-Assist does not track it. To build on it here: Run COM on <thru> with
<config>.` with that phrase ready in the command box (filled from the run's command). Sending it imports the
config and runs through the core like any other command; if the inputs are equal to a run Assist already
holds, Decision 6 reuses that one.

**The Run tab while Assist is in use** keeps its meaning: it runs the workbook file as saved. The overlay
makes the Config view show the working config, so the Run tab shows one more line under its config line:
`this runs the workbook file as saved, without the working config of SiCoPR-Assist; run from the panel to
include it`. The text is the panel's, sent as the overlay's `run_note` (section 4.1); SiCoPR only shows it.

## 7a. Everything the GUI does is in the history

Maintainer, 9 October 2026: every interaction in the GUI is captured in the history, so that anything that
does not work can be reviewed later. The history (`history.jsonl`) is the one log; the GUI adds no second
log of its own. Each record the GUI writes carries `origin: "gui"` and a `kind` (as built: `source` already names
the source config of a record, section 13):

| kind | written when | holds |
|---|---|---|
| `phrase` | a phrase is sent from the command box | as the CLI's record: phrase, pattern, unplaced words, outcome |
| `answer` | an option button is clicked | the question's record number, the option chosen, the outcome |
| `edit` | a Config-view field is committed | keyword, block, value before and after, accepted or refused with the rule |
| `open` | the Config view opens another workbook | old and new source with SHA-256, the overrides kept or left out |
| `run` | a plan starts, and again when it ends | the plan, run ids, status, elapsed time, the stop reason if stopped |
| `stop` | the user presses Stop | what was running and what was left |
| `view` | a run is shown in Results, a dashboard is opened, settings or history are shown | what was shown |
| `error` | the panel's server raises, an API call fails, or the page reports a script error | the endpoint or the page, the message, the traceback or the script line |

- The page reports its own errors: a `window.onerror` and `unhandledrejection` handler posts them to
  `POST /panel/assist/api/log`, which records them (at most one record per distinct message per minute, so a
  loop cannot fill the file).
- Records written by the CLI carry `origin: "cli"` (records written before 0.7.0 have none and are phrases), so
  one history shows both, in order.
- The feedback export (Decision 10) includes every record, with the masks applied to the new fields as to
  the old ones; `What did I run last?` and the tutor read only the kinds they read today.
- `GET history` returns every kind, so the panel can show the whole session again after a reload.

## 8. Endpoints of the panel and the core functions they call

All under `/panel/assist/api/`. None of them reaches past the core: they call the functions `cli.py` calls,
plus the read-only project and summary functions. Paths given by the page are checked against the project
folder and `host.roots()`.

| endpoint | does | calls |
|---|---|---|
| `GET state` | the project line, the pending question, whether a plan is running | `Project`, `Project.read_pending`, `core.history_lines`, `core.Context(...).base` |
| `POST project {path}` | change the project folder (a directory under `host.roots()`) | `Project` |
| `POST handle {phrase, selection}` | resolve a phrase, with the selection in the tabs handed over as data (section 5a); carry out a PLAN in the worker | `core.handle`, then `run.carry_out` (and `core.fetch_followup` through `next`) |
| `POST selection {selection}` | the selection as the core will be handed it (paths outside the project folder and `host.roots()` left out), the line that shows it, and the phrase of the Run selection button | none of the core: `api.clean_selection`, `api.selection_line` |
| `POST examples {selection}` | up to four phrases for under the command box, each one giving a PLAN now | `tutor.first_run`, `tutor.examples`, `core._resolve` through the tutor's own check |
| `GET job?since=` | progress lines, running or done, the carry-out result | the worker's buffer, `run.line_text` |
| `POST stop` | stop the plan in progress | the worker (new cancel hook, section 10) |
| `POST overlay {keys, changed}` | the source workbook path and the overlay cells, keyed as the view shows them (`keys` from `sicopr:config`), with `focus` for the keys of the last outcome | `core.Context`, `config_model.import_config` of the source (cached by SHA-256), `config_model.same_value`, history for the origin of each override |
| `POST edit {edits}` | take committed Config-view edits into the working config | `core.edit` (new) |
| `POST open {path}` | follow another workbook opened in the Config view | `core.edit` with a source |
| `POST log {kind}` | a view shown (`view`) or a page error (`error`), recorded | `Project.append_history` |
| `GET history?limit=` | phrases for recall, and the conversation on reload | `Project.read_history` |
| `GET result?run=` | one run's summary card | `summary.run_summary` |
| `GET batch?seq=` | a batch's table | `summary.batch_rows`, `summary.batch_lines` |
| `GET settings` | the settings in force | `project.read_settings`, `core.settings_lines` |

## 9. What is separable for si-gui

- The panel is one bundle: `panel.js`, `panel.css` and the `api.py` functions. It knows SiCoPR only through
  the contract of section 4.1, so si-gui can host the same bundle beside a SiCoPR view and a BeSS panel by
  implementing the same contract (one route prefix, the `host` object, the events).
- `api.py` is plain functions over `core`, `run`, `summary` and `Project`; si-gui can call them without HTTP.
- Nothing in it names a workspace path or a folder layout: the project folder is browsed or given on the
  command line, and SiCoPR is found as the rest of the package finds it (`engine.folder()`).
- No new dependency: stdlib on the server, plain JavaScript in the page, no external scripts or fonts.

## 10. Changes in SiCoPR-Assist when the GUI is built

For the build phase that follows approval; listed here so that their reach is known now.

| change | why | checked by |
|---|---|---|
| `sicopr_assist\panel\` (contract module, `api.py`, `static\`) and the entry point | the panel | new `tests\test_gui_api.py`, `tests\test_gui_static.py` |
| `core.edit(project, changes)` | the structured-change path (section 6); also the path a language-model layer will use | `test_gui_api.py`: an edit is validated as the same value typed in a phrase is (same ok, ask or stop on the four starting configs) |
| `Context.base` unchanged; `_replay` takes the steps of the last record with runs and runs the current working config, announcing the view edits it includes | `Re-run.` after a view edit must run the edited config, not re-apply the old command's `set_param` over it | a test: edit `DER_0` in the view, then `Re-run.`: the run CSV holds the edited value (checked with the engine's loader, as L3 does) |
| `run.carry_out(..., cancel=None)` | Stop in the panel: a `threading.Event` checked between points, and the child terminated | a test with the stand-in child |
| the loop of `cli.handle_and_run` moved into a function in `run.py` that both use | the CLI and the panel follow a channel download's `next` the same way (Decision 13) | the existing CLI tests, unchanged |
| `tutor.successes` and `trouble` leave out view-edit records; the feedback export marks them `config view` | an edit in a field is not a typed command | `test_tutor.py`, `test_feedback.py` additions |

No format changes: a view edit is an ordinary history record (`sicopr-assist-history/1`) told apart by its
pattern, and its working config is a `configs\edit_NNNN.json` read through the record's `working_config`
path like any other.

## 11. Tests of the GUI (when it is built)

- **The same answers as the command line.** For the frozen L4 list, `POST handle` on a fresh copy of each
  prior state returns the outcome `core.handle` returns, key for key; carried out with the stand-in child,
  the progress lines equal what `cli.handle_and_run` prints for the same plan.
- **The round trip.** On the four starting configs: a Config-view edit becomes one history record and the
  next command's run CSV holds it (loader check); an edit of `f_b` moves the linked keys and the overlay tags
  them `linked`; an edit of `f_z` removes its link; a `[TX RX]` half keeps the other half and the shape; a
  refused edit never reaches the working config; the last writer wins and the announce names the earlier one;
  the source workbook's SHA-256 is unchanged after every test (Decision 2).
- **Overlay keys** match SiCoPR's `config_payload` keys for every overlaid value (run against SiCoPR's real
  `gui.app.config_payload` in a temp folder, read only).
- **Runs and results.** Busy refusal both ways; Stop leaves the record failed and no half-written result;
  every Assist run folder is listed by SiCoPR's `/api/results` when the project folder is opened.
- **Paths.** Anything outside the project folder and `host.roots()` is refused, including `..\` and absolute
  paths.
- **The history (section 7a).** Each kind of interaction, driven through the API with a stand-in child and
  stand-in page errors, writes exactly one record of its kind with `source: "gui"` and the fields listed; a
  failing endpoint and a page script error each leave an `error` record; a repeated error is recorded once a
  minute; the feedback export masks the new fields.
- **Following another workbook.** Opening another of the four starting configs in the Config view imports it,
  keeps the channel files, records one `open` record, and the next run's CSV loads to that workbook's fields
  (loader check); with overrides present, both answers (keep, start as saved) give the right working config;
  a workbook that does not import leaves Assist on the previous source.
- **The page.** `panel.js` parses (node or esprima, as SiCoPR's static test does), every element id it uses
  exists, every class that sets `display` has a `[hidden]` rule, and every event name it uses is one of the
  contract's.
- Every new check shown to fail on the defect it targets (Rule 7), GX after each phase, and
  `tests\test_text_style.py`.
- **The selection and the command box (Phase V2-6).** SiCoPR's `tests\test_gui_static.py`: the event is sent at
  start, when the lists are filled and on every pick, carries the three lists and the cause, is not sent again
  for an unchanged selection, and makes no request and changes nothing (so the page with no panel is as it
  was). Here: `tests\test_selection.py` (the forms read and the near-forms left unplaced; the plans; the roles
  the engine is given, with a stand-in child that records its arguments; the example in an empty folder);
  `tests\test_gui_api.py` (the selection line; the phrase posted with a selection gives what the core gives; a
  path outside the opened directories never reaches the core; the examples all give a PLAN);
  `tests\test_gui_static.py` (the box is a text area of three lines with its label, Enter sends and Shift+Enter
  does not, the block stays in view, the line follows both events, Run selection sends its phrase, an example
  fills the box). The real page is driven in the walk-through of gate V6.5, where the same behaviours are
  checked with real key presses.

## 12. Open questions for the maintainer

*Decided 9 October 2026:* questions 1 to 5 and 7 to 10 as recommended; question 6 changed to "Assist
follows" (below and section 6); and every GUI interaction is recorded in the history (section 7a).

1. **Does SiCoPR take the panel slot of section 4?** About 300 lines in `gui\` and its tests, no engine
   change, written by you in a SiCoPR session. *Recommendation: yes.* Without it the GUI falls back to a
   panel-only page with no two-way sync.
2. **Does a PLAN run at once in the panel, as on the command line, or wait for a Run button?**
   *Recommendation: at once, as the CLI does.* The plan is announced before anything runs, large batches
   already ask (`max_new_runs`), and Stop is there. A confirm step would make the GUI behave differently from
   the table that specifies it.
3. **Is a Config-view edit taken into the working config when it is committed, or held until the next
   command?** *Recommendation: when committed*, one history record per edit. It is checked at once, the user
   sees `edited here #n` at once, the CLI sees it too, and there is no conflict window.
4. **Should Assist track runs started from the Run tab?** *Recommendation: no, not in the first build.* Offer
   the phrase that brings the same inputs into Assist; reuse then works through Decision 6 as usual.
5. **Save as in the Config view while Assist is in use: disabled with a pointer to Assist's export?**
   *Recommendation: yes.* Enabled, it would write a workbook that silently leaves out every Assist override.
6. **When the Config view is switched to another workbook, does Assist follow?** *Decided by the
   maintainer, 9 October 2026: yes.* Assist imports it as the new source, keeps the channel files, announces
   the switch, and asks once whether to keep any overrides (section 6).
7. **Launch.** *Recommendation:* `sicopr-assist gui [folder]` starts SiCoPR's GUI with the project folder as
   `--dir` and `--run-dir`; starting SiCoPR's GUI directly also shows the panel, which then asks for a
   project folder.
8. **Do view edits count as commands for the tutor (Decision 11)?** *Recommendation: no*; they are listed in
   the feedback export, marked `config view`.
9. **The command box during a run.** *Recommendation: disabled until the plan ends* (Stop stays live), as
   the CLI is. Read-only questions during a run (`What's my COM summary...`) can come later.
10. **Gates for the build.** The use-case table has no GUI rows. *Recommendation:* gate the build on section
    11's tests, the frozen L4 list through the panel's API with the same outcomes as the core, and GX; the
    version after the build is 0.7.0.

## 13. As built (Phase V2-5, 9 October 2026)

Where the design was silent, or wrong once built, the least surprising reading was taken and the text above
changed to match:

1. **`origin`, not `source`, in the history (section 7a).** A history record already has `source`, the source
   config of a run. The GUI's records carry `origin: "gui"` (the CLI's `origin: "cli"`), a `kind`, and a
   `detail` with what each kind holds. Records written before 0.7.0 have none of the three and read as phrases.
   The log kinds (`run`, `stop`, `view`, `error`) are left out of `Project.read_history()` unless asked for,
   so no reader of the history other than the history view and the feedback export ever sees them; `edit`
   and `open` are records with a working config, which the next command builds on.
2. **`sicopr:config` carries `cause` and `keys` (section 4.1).** The panel follows a workbook the *user*
   opened, not SiCoPR's first load or the panel's own `sicopr:open-config`, so the page says which it was. The
   field keys the view shows let the overlay send exactly SiCoPR's keys (a `[TX RX]` value as its `#tx` and
   `#rx` halves where the view shows halves) without the panel copying SiCoPR's schematic.
3. **`sicopr:overlay` carries `focus`**, a list of keys: the page selects their block when they all sit in one
   (section 6, "switches the Config view to that block when the command changed exactly one block").
4. **`POST overlay {keys, changed}`** in place of `GET overlay`, because it takes the view's keys; **`POST
   open {path}`** follows another workbook; **`POST log {kind}`** records a view shown or a page error.
5. **A `[TX RX]` pair edited as one number** goes to both sides, as row RS28 does for a typed number (the edit
   is validated exactly as the same value typed, section 10), rather than asking.
6. **An edit made before Assist has a working config**: the workbook the view shows is imported as the source
   first, and the edit applies to it (one `edit` record).
7. **A refused edit** is shown in the panel only; under the field the value stays green and unsaved, as SiCoPR
   shows any unsaved edit.
8. **Package-block values** (`BLOCK/name`) are counted in the overlay title; SiCoPR's Config tab does not show
   package fields, so they are not shown there.
9. **`sicopr-assist gui`** with a SiCoPR whose GUI has no panel slot says so and stops (exit code 2); the
   panel-only fallback page of section 3 is not built.
10. **Following another workbook keeping the overrides** validates them together first, then one at a time for
    those left: one override can need another beside it (`N_b = 0` needs `MLSE = 0`), which the walk-through
    showed. **A plan's changes show in the overlay while its runs are under way** (section 6 says "before its runs
    start"; the working config of a run is recorded only when the run ends, so the overlay reads the plan).
    **`run` records** are written for a plan that runs something (COM, a batch, a download), not for every PLAN.
11. **`core.edit(project, changes, source=None, origin='gui')`** is the entry point of section 6; `core.handle`
    gains `origin` for the record only (the outcome does not depend on it), so the frozen L4 list gives the same
    outcomes through the panel as through the core.

## 14. As built (Phase V2-6, 10 October 2026)

Decisions 20, 21 and 22 of the build prompt, after the maintainer's first session with the GUI. Rows SL01 to SL05
and EX01 of the use-case table specify the selection and the example; the command box has no rows and is specified
by Decision 21 and section 5. Where a decision was silent, the least surprising reading was taken:

1. **`sicopr:channels` is sent from the Run tab only**, with the causes `boot`, `user` and `list` (section 4.1).
   The S-parameters tab picks files to plot, not files for a run, so it is not the selection (section 5a). The
   event is not sent again for an unchanged selection, so the filter checkbox and a refilled list are not a change.
   At start the Run tab's lists are still empty, so the first event carries no channel: the selection line then
   says `no channel file (pick a THRU in the Run tab)`, and `Run selection` gives the question of row SL03.
   SiCoPR's lists are not filled earlier for the panel's sake, because that would add requests to a page that
   makes none of them today.
2. **The selection is posted with every phrase** (`POST handle {phrase, selection}`) and not kept on the
   server, so two browser tabs cannot hand each other's selection to the core, and a phrase sent right after a
   pick carries that pick. `POST selection` only answers the line to show. The history record of a phrase that
   spoke of the selection keeps what was selected then (`detail.selection`), so a session can be reviewed
   later (section 7a); no other record holds it.
3. **With a working config, the selection keeps it.** Decision 20 gives the plan of row SL01 for a project with
   no history and the swap of row SL05 after a run. In between is the state the maintainer was in: a workbook
   opened in the Config view (Assist followed it, an `open` record) and no run since. There the working config
   is the selected config with whatever was done to it in the Config view, so it is kept and run on the selected
   channel files; importing the workbook again would drop the edits. The plan says so.
4. **`Run the selected config and channels.` after a completed run with the same files and nothing changed** is
   a STOP (the results would equal the last run), as row CH07 is for a channel named in a phrase. After a run
   that failed or was stopped, the same selection runs again.
5. **`Re-run with the selected channel.` with no run yet** asks as row CH05 does, although the selection holds a
   config: a re-run has nothing to re-run, and Decision 18 says so for a channel named in a phrase.
   `Run the selected config and channel.` is the phrase that runs it.
6. **"the selected file" (one file, no kind named) is not one of the forms**: it could be the config or a
   channel, so it is asked about. "the selected files" is the whole selection.
7. **The selection beside any other request** (a sweep, files named, the example, crosstalk, a question about
   the config) asks, with `cancel` as its only option, and says which two phrases run a selection. A change of
   a parameter in the same phrase is planned as a re-run would plan it (`Run the selected config and channels
   with DER_0 = 1e-4`).
8. **The examples under the box** are checked against the project as it is, not as if a run had just been made
   (the tutor's examples are checked that way, and are shown after a PLAN). So a new project shows only what
   runs now; the tutor's phrases appear once there is a working config.
9. **Focus.** SiCoPR shows the panel slot only after the panel's script has loaded, so the box cannot take the
   focus at once: it is tried until the box is on screen, and only when no other field has the focus.
10. **`Run the example.` writes `data\example_thru.s4p` only when the plan is carried out**, creating `data` if
    it is not there; planning writes nothing in the project folder but the history. The step that carries it is
    `import_config(example)` with one more argument, so the chain of row EX01 is the chain of row R1.

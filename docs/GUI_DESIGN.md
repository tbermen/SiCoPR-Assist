# SiCoPR-Assist GUI: design

This document describes the GUI panel of SiCoPR-Assist as the code now behaves: what it is, how it is started,
the contract it keeps with SiCoPR's GUI, what it shows, how it carries out runs and edits, what it records, and how
it is tested. How it came to be this way is in `CHANGELOG.md`. A static mock-up of the panel as first designed is
`docs\gui_mockup.html` (open it from the file system; it needs no server and no network); the panel has been
simplified since, so where the two differ, this document and the code are right.

## 1. What the panel is

SiCoPR-Assist adds a panel on the right of SiCoPR's own GUI, where the same phrases as on the command line are
typed. SiCoPR's GUI stays the tool: its Config, S-parameters, Run and Results tabs are used as they are without
SiCoPR-Assist. The panel is a way to drive them by typing. A phrase goes to the same core as on the command line,
and its effect shows in SiCoPR's views: a changed value in the Config view, a run's files and command in the Run
tab, its output in the Run tab's Output, its results in the Results tabs. It works both ways: what the user does in
SiCoPR's views (an edit in Config, files picked in Run, another workbook opened) is what the next command builds on.

The panel shows only what the GUI does not: short replies, questions with buttons, one line while a plan runs, and
the headline result. It never reaches past the core: it calls the functions the command line calls, so a phrase
gives the same outcome in the panel as in a terminal, and every action is recorded in the project's history.

## 2. SiCoPR's GUI, as the panel sees it

SiCoPR's GUI is a small standard-library HTTP server bound to 127.0.0.1 (`gui\app.py`, port 8765 or
`SICOPR_GUI_PORT`) and one page. What matters to the panel:

- **Opened directories.** SiCoPR serves paths only under directories the user opened: the repository, `--dir`,
  `--run-dir`, and directories chosen in its Browse dialog. The panel follows the same rule (section 9).
- **Config tab.** Shows a workbook on a channel schematic and keeps the user's unsaved edits in the page. Save as
  writes a copy with only the changed cells rewritten. A `[TX RX]` cell is shown as two fields, with keys
  `name#tx` and `name#rx`. Package blocks are not shown as fields.
- **Run tab.** Picks the THRU, FEXT and NEXT files and two options (Output dynamic results and `--eye-under-mlse`),
  shows the command, runs it, and streams its output with a status line and Stop. On its own it runs the workbook
  file as saved.
- **Results tabs.** Find run folders by their content (a folder of `case_NN` folders, or an engine `results.csv`)
  under the opened directories. SiCoPR-Assist's run folders (`.sicopr\runs\run_NNNN`) match that rule, so every
  run made from the panel appears in Results, static and Results, dynamic with no extra work once the project folder
  is opened.

## 3. How the pieces fit

The panel is the package `sicopr_assist\panel\`: `__init__.py` holds the contract attributes (section 4.1), `api.py`
the endpoints as plain functions over the core (they take a `Project` and return plain data, so another front end can
call them without HTTP) plus a small class that routes HTTP to them, and `static\panel.js` and `static\panel.css` the
page part. It is registered in `pyproject.toml` under `[project.entry-points."sicopr.gui_panels"]`. Nothing in it
names a folder layout: the project folder is given or browsed, and SiCoPR is found as the rest of the package finds
it (`engine.folder()`). It adds no dependency: the standard library on the server, plain JavaScript in the page, no
external scripts or fonts, and colours from SiCoPR's own style variables.

**SiCoPR versions.** The panel needs a SiCoPR whose GUI has the panel slot. No released SiCoPR has it yet; a later
SiCoPR release will. Until then `sicopr-assist gui` says so and stops, and SiCoPR-Assist is used from the command line.

## 4. The contract with SiCoPR's GUI

The contract is documented on SiCoPR's side in its `gui\README.md`, section *Panels*. What follows is the part this
panel uses.

### 4.1 The contract (panel API 1)

A panel is registered through the Python entry-point group `sicopr.gui_panels`. The entry point names an object (a
module is fine) with:

| attribute | this panel |
|---|---|
| `API` | `1` (a panel with another value is skipped by SiCoPR) |
| `NAME` | `assist`, used in URLs |
| `TITLE` | `SiCoPR-Assist`, shown by SiCoPR as the slot's header |
| `STATIC` | the folder holding `panel.js` and `panel.css` |
| `handle(method, path, query, body, host)` | answers `/panel/assist/api/<path>` (section 8) |
| `busy()` | `None`, or `a run started from SiCoPR-Assist is in progress` while a plan with runs is carried out |

`host` is all the panel sees of SiCoPR's server: `host.roots()` (the opened directories), `host.run_dir()` (the Run
tab's working directory) and `host.com_running()` (whether the Run tab's own run is live). SiCoPR serves the
panel's `panel.js` and `panel.css` by base name only from `STATIC`, and gives the panel a mount element with id
`panel-assist` in the slot.

On the page, SiCoPR and the panel talk through `CustomEvent`s on `window`. The page sends, and the panel listens to:

| event | detail | what the panel does with it |
|---|---|---|
| `sicopr:config` | `{path, name, cause, keys}` | a workbook was loaded in Config (`cause` is `user`, `boot` or `panel`). The panel keeps the field keys, sends the overlay, and when the user opened another workbook, follows it (section 6) |
| `sicopr:edit` | `{key, name, half, value, before}` | a field's edit was committed (Enter, or leaving the field): taken into the working config (section 6) |
| `sicopr:view` | `{view}` | the tab changed (not used by this panel) |
| `sicopr:run` | `{returncode, command, cwd}` | a run started from the Run tab on its own finished: the panel says it does not track it and offers the phrase that brings it in (section 7) |
| `sicopr:browsed` | `{purpose, path}` | the Browse dialog the panel opened was used: the chosen folder becomes the project folder |
| `sicopr:channels` | `{thru, fext, next, options, cause}` | the Run tab's files or its two options changed (`cause` is `boot`, `user`, `list` or `panel`): kept as the selection (section 5a) |
| `sicopr:run-request` | `{thru, fext, next, options}` | Run was pressed while the panel has the Run tab assembled; sent cancelable, and the panel takes it with `preventDefault()` (section 7) |
| `sicopr:stop-request` | `{job}` | Stop was pressed while the Run tab's Output shows the panel's run: the panel stops its run |

The panel sends, and the page acts on:

| event | detail | what SiCoPR's page does |
|---|---|---|
| `sicopr:open-config` | `{path}` | loads that workbook in Config (asking first if there are unsaved edits) |
| `sicopr:overlay` | `{title, cells: {key: {value, tag, note}}, save_hint, run_note, focus}` or `null` | shows each listed key with the panel's value and its tag, the workbook value in the field's info line, outlines the blocks that hold one, shows `title` in the header, disables Save as with `save_hint` as its tooltip, shows `run_note` in the Run tab, and selects the block of the `focus` keys when they all sit in one. `null` removes it |
| `sicopr:clear-edits` | `{keys}` | drops those keys from the page's unsaved edits (the panel took them) |
| `sicopr:show` | `{view, run, build, unless_editing}` | switches tab; with `run`, selects that run folder in the Results tabs; with `build`, Results, dynamic builds the run's dashboard; with `unless_editing`, the tab is left alone while the user is editing in Config |
| `sicopr:output` | `{job, lines, status, done}` | shows the panel's run in the Run tab's Output as a run of its own: a new `job` clears the Output, `lines` are appended, `status` goes in the status line, and Stop is live until `done` |
| `sicopr:set-run` | `{config, thru, fext, next, options, command, note}` or `null` | assembles the Run tab: selects the files, sets the two options, shows `command` and `note`; its controls stay live, and Run then sends `sicopr:run-request` |
| `sicopr:browse` | `{purpose, title}` | opens the Browse dialog; using it opens the directory and answers with `sicopr:browsed` |

Keys are SiCoPR's own: `name` for a main keyword, `name#tx` and `name#rx` for the halves of a `[TX RX]` cell.

### 4.2 With no panel installed

With no entry point registered, SiCoPR's `/api/panels` lists nothing, the slot stays hidden, and the page is as it
always was. Nothing sends `sicopr:set-run` or `sicopr:output`, so the Run tab and its Output behave as before. A
panel that fails to load is skipped with a console line, and a `handle()` that raises gives a JSON error while the
server carries on. SiCoPR's GUI can also be started with `--no-panels`.

## 5. The panel

### Starting it

```powershell
sicopr-assist gui                    # this folder; opens a browser on http://127.0.0.1:8765
sicopr-assist gui D:\other\project --port 8790 --no-browser
```

`sicopr-assist gui [folder] [--port N] [--no-browser]` (`cli.gui`) checks that the folder exists and that the
SiCoPR in use has a GUI with the panel slot; if it has none, it says so and exits with code 2. Otherwise
`run.start_gui` starts SiCoPR's `gui\app.py` from an argument list (no shell) with the project folder as both `--dir`
and `--run-dir`, names the project to the panel through the environment variable `SICOPR_ASSIST_PROJECT`, and turns
bytecode writing off so nothing is written in SiCoPR's folder.

SiCoPR's GUI can also be started directly. The panel then has no project folder: it opens its Settings fold and
asks for one with Browse. The folder chosen must be inside a directory opened in the GUI.

### Layout, from top to bottom

1. **Top line.** Once the project has a working config, its short state: `working config run_0003, 2 overrides,
   1 edit from the config view`. Hidden otherwise. The title is the slot's header, which SiCoPR gives every panel.
2. **The conversation.** Each exchange is what was said (`> phrase`, or `config view: Set DER_0 = 1e-4`, or
   `Run button: Run the command.`) and its outcome as a card:
   - a PLAN is one line that says where its effect can be seen: `2 changes, highlighted in Config`, `running in
     the Run tab`, `3 points: output in the Run tab`, or for a plan that only shows or writes something its steps
     and `its lines below`. It begins `using the Run tab's setup` when the phrase used the GUI's setup (the core's
     pattern names the selection or the Run tab);
   - a QUESTION shows its text and one numbered button per option;
   - a STOP shows its reason.

   The plan's numbered steps and the announcements are behind a **details** toggle. The tutor's lines after a miss
   or on trouble stay in the card they explain; each example phrase in them is a link that puts it in the command
   box. Replies that come later (a result, a note) go into the same exchange. The last three exchanges stay in view;
   an older one moves to the History fold.
3. **A pending question**, pinned above the command box with live buttons until it is answered or set aside. A
   button sends the option text as the next phrase, which the core reads as the answer, exactly as typing it would.
   The box then says `answer the question, or type a new command`. The question survives a page reload (the core
   keeps it in `pending.json`).
4. **One running line** while a plan is carried out: `run_0006 running: output in the Run tab` (for a batch, with
   its point), and a button that shows the Run tab. For a plan that runs nothing it reads `carrying out the plan of
   #12`.
5. **The result** of each run, as a reply in its exchange: the headline (`run_0006: COM 8.80571 dB, pass (COM
   Pass threshold 3 dB)`; with several package cases, each COM and how many pass; in eye height and VEC mode, the
   verdict on VEC Pass threshold and EH_min), buttons that show the run in Results, static or Results, dynamic,
   and the run summary under details. A batch gives a short table, one row per point (point, case, status, run,
   COM), with its lines and the path of `batch_summary.csv` under details.
6. **The command box**, its own block at the bottom of the panel, kept in view while the conversation scrolls above
   it. Under the label `Type a command`, a text area of three lines that grows with its content and then scrolls,
   with Send beside it. Enter sends; Shift+Enter starts a new line (a phrase on several lines is sent as one line);
   Up and Down recall earlier phrases from the project's history while the box holds one line. The box takes the
   focus when the panel comes up, but never from a field the user is already in. While a plan runs, the box and
   Send are off.

   **Examples** show under the box only while it is empty and the user is new: the history holds fewer successful
   commands than the setting `tutor_until_commands` (5 by default; the server reports it as `tutor_due`, by the
   tutor's own count). Up to four phrases, each checked by the core to give a PLAN now: in a new project, the phrase
   that runs the folder's one config and one channel file (when there is exactly one of each) and `Run the
   example.`; once there is a working config, the tutor's examples written with that config's names. A click puts a
   phrase in the box and sends nothing. After a plan, the tutor's lines for a new user show here in place of the
   examples, and after `What can I say?` they show whatever the count. Typing hides them; emptying the box shows
   them again.
7. **Settings** (folded): the project folder with Browse, the SiCoPR-Assist version, and the settings in force with
   where each came from (`core.settings_lines`). Settings are changed by phrase (`Tutor off`), as on the command line.
   The fold opens by itself when the panel has no project folder.
8. **History** (folded): the exchanges older than the last three, newest first, one line each (what was said, its
   one-line reply and, after a run, its headline) that opens to the full exchange. Below them, folded, every record
   of the project history.
9. **Language model** (folded): reserved. It says the panel is rules-based. A language model, when one is added, is
   configured here; it may turn loose wording into a phrase, and the core checks that phrase as it checks typed
   input.

`Run the example.` in a project folder with no channel file plans a run on a synthetic THRU (the lossy line of
`sicopr_assist\example_channel.py`), written to `data\example_thru.s4p` when the plan is carried out and never when
it is planned. The plan says the channel is synthetic. A channel file already in the folder is used instead.

## 5a. The selection in the tabs

The page tells the panel what is selected in its tabs: the workbook of the Config tab (`sicopr:config`) and the
THRU, FEXT and NEXT files of the Run tab with its two options (`sicopr:channels`). The S-parameters tab picks files
to plot, not files for a run, so it is not part of the selection. The Run tab fills its lists when it is first
opened, so until then the selection has a config and no channel file.

The panel keeps the selection in the page and posts it with every phrase (`POST handle {phrase, selection}`). It is
not kept on the server, so two browser tabs cannot hand each other's selection to the core. The server checks every
path against the project folder and the opened directories, and leaves out one from anywhere else before the core
sees it. The panel does not show the selection: the Run tab already does.

The core reads "the selected", "the specified" or "the chosen" config, channel, channels or files, "in the tabs",
"the selection" and "what is selected" as the selection, in those forms only. Roughly:

- With no working config yet, or a phrase naming a selected config other than the working config's source, the
  selected workbook is imported and run on the selected channel files.
- With a working config whose source is the selected config, it is kept with its overrides and Config-view edits,
  and only the channel files change.
- Nothing changed since a completed run: a STOP, since the results would equal the last run.
- No channel file selected, or no selection at all (as on the command line): a QUESTION.
- A selected file that is not on disk, or not a Touchstone file: a STOP that names it.

The files run in the roles they have in the Run tab, not the roles their names suggest. The history record of a
phrase that used the selection keeps what was selected then.

## 6. The config round trip

The rule: **SiCoPR-Assist's working config is the one current config while the panel is in use.** The source
workbook is never written. The Config view shows that working config laid over its source workbook.

**What the Config view shows.** When the panel starts, and after every command, the panel sends `sicopr:open-config`
with the source workbook of the working config, then `sicopr:overlay` with every key whose working value differs
from the workbook's. The schematic, blocks, units and notes are SiCoPR's, read from the workbook; the values are the
working config's. Each overlaid field carries a tag:

| tag | meaning |
|---|---|
| `Assist #12` | set by command 12 of the history |
| `edited here #13` | an edit made in the Config view, taken into the working config as record 13 |
| `linked` | recomputed by a link after a change to what it depends on |
| `proposed` | a change a pending QUESTION would make; not yet in the working config |
| `option n` | a keyword offered as option n of a pending QUESTION, so both fields can be read before choosing |

The field's info line keeps the workbook value (`workbook 0.0002`), and says so when an explicit value removed a
link (`link {f_b}/2.5 removed`). A keyword the workbook does not hold goes to SiCoPR's Other settings block, tagged
`not in the workbook`. Package-block values are counted in the overlay's title, since the Config view shows no
package fields. While a plan is being carried out, its changes are already in the overlay, so the user can watch the
view while it runs. The block that holds a changed key is outlined, and when the command changed keys in one block
only, the view selects that block.

**An edit in the Config view.** When a field's edit is committed, the panel posts it to its `edit` endpoint. The
SiCoPR key is turned into a working-config path (`name` to `/main/name`; a `#tx` or `#rx` half is put back with the
other half of the working value, in the shape that value has), and `core.edit(project, changes)` checks it exactly
as the same value typed in a phrase is checked, applying links (an explicit value removes that key's link; a change
to `f_b` recomputes what depends on it). The outcome is:

- a PLAN with no run: one history record with its own working config (`configs\edit_NNNN.json`). The panel sends
  `sicopr:clear-edits` for the key and a new overlay, and the field shows `edited here #13`;
- a QUESTION: shown in the panel with its buttons; the field keeps SiCoPR's unsaved state and a `proposed` tag until
  the answer;
- a STOP: shown in the panel; the value stays unsaved in SiCoPR's view and never reaches the working config.
  SiCoPR's Revert all drops it.

A `[TX RX]` pair edited as one number goes to both sides, as a typed number does. An edit made before there is a
working config first imports the workbook in view as the source. An edit made while a plan is running is refused
and stays unsaved in the view.

**The next command builds on it.** The next command starts from the last record that names a working config, so an
edit is what it builds on, and `Re-run.` after an edit runs the edited config. Before a phrase is sent, the panel
blurs the focused field so a half-typed edit is committed and checked first; there is no window in which an edit
and a command race. When both change the same keyword the latest record wins, and the command announces what it
replaced (`DER_0: 0.0001 -> 5e-05 (it was edited in the config view, #13)`).

**Another workbook in the Config view.** When the user opens a different workbook in Config (`sicopr:config` with
cause `user`), the panel follows it: the workbook is imported as the new source through `core.edit`, the channel
files of the last run are kept, and the overlay is laid over the new workbook. Nothing runs. If the previous working
config had overrides, the panel asks once: keep them on the new workbook, or start from it as saved. Overrides are
checked together first, then one at a time; one the new workbook does not hold or refuses is named and left out. A
workbook that does not import gives the same STOP or QUESTION as the import phrase would, and the panel stays on the
previous source. The switch is one history record, and the earlier working config stays in the history, so `Undo
that change.` brings it back.

**A source that is not a workbook** (a `.csv` or `.json` config): the Config view has nothing to show, so the panel
says so and points to `Show me the config.`. No spreadsheet is written to make one.

**Save as.** While the overlay is set, SiCoPR's Save as is disabled, with the hint `Save the working config from the
Assist panel: Save that config as data\config_new.xlsx.`. Save as would write the workbook plus the unsaved edits and
leave out every override. SiCoPR-Assist's own export writes the whole working config into a copy of the source
workbook; the source is never the target.

## 7. Runs and results

**A plan is carried out at once,** as on the command line. `POST handle` returns the outcome, the core records it,
and the server carries the plan out in a worker thread with `run.follow`, the same function the command line uses
(it also follows a channel download into the plan made from it). Progress lines go to a bounded buffer (the last 2000
lines) that the page polls by position; a failed poll retries with backoff and never ends the loop.

**Its output is in the Run tab.** The page hands every new line to SiCoPR as `sicopr:output`, and the Run tab's Output
shows it as a run of its own: the same terminal, follow output, and its status line (`SiCoPR-Assist #12 running, 40
s`, `..., no output for 25 s` when quiet, then `SiCoPR-Assist #12 finished (ok) in 63 s`, or `failed` or `stopped`).
When a plan that runs something starts, the page is asked to show the Run tab, unless the user is in the middle of an
edit in Config. A batch streams every point in order, each headed by its status line. A plan that runs nothing (a
setting, a workbook export) sends no output; its few lines are in the panel's reply. After a page reload during a run, the
whole buffer is sent again under the same job.

**The Run tab is the setup the panel runs.** A PLAN with one COM run also returns `run_tab`, made by
`run.run_tab_setup` before the run starts, which the page sends as `sicopr:set-run`: the THRU, FEXT and NEXT files
are selected, the two options set, and the command box shows the command the panel runs. That command runs the
working config's run CSV (`.sicopr\configs\run_NNNN.csv`), not the workbook, and a line in the Run tab says so. A
batch, a plan that runs nothing, and the dashboard of an earlier run send no setup.

While the Run tab is assembled:

- its controls stay live. A change there comes back in `sicopr:channels`; the panel asks `POST runtab` for the
  command for the files and options now, and sends it as `sicopr:set-run`. What the panel set itself comes back with
  cause `panel` and is not sent again, so the two cannot chase each other;
- `Run the command.` (also `Run it.`, `Run what is in the Run tab`, `Run the Run tab`, `Run with current settings.`)
  runs exactly that setup through the panel, with history and reuse;
- the Run tab's **Run sicopr.py** button does the same: the page sends `sicopr:run-request`, the panel takes it and
  sends `Run the command.` with the files and options of the request, shown as `Run button` in the conversation;
- Output dynamic results makes the run an export run (`--export-mat`); when it ends, the page shows Results, dynamic
  and builds the dashboard. `--eye-under-mlse` is passed to the run. Both options are part of what decides reuse.

**Stop.** The Run tab's Stop, while its Output shows the panel's run, sends `sicopr:stop-request`; the panel calls its
`stop` endpoint, which sets a cancel flag checked between points and terminates the run under way. The history
records the stop, and the run record ends `stopped`.

**When the run ends** the page stays on the Run tab, as after a run of SiCoPR's own, and the panel shows the headline
result with buttons for the Results tabs. A dashboard phrase shows its page in Results, dynamic rather than in a new
browser tab. Opening Results, dynamic on a run with no `.mat` export says so in the panel and offers the phrase that
runs it again with the export.

**One COM run at a time, across both.** While the panel carries out a plan with runs, its `busy()` makes SiCoPR
refuse Run sicopr.py. Before carrying out such a plan, the panel checks `host.com_running()`; if the Run tab's own
run is live, nothing runs and the panel says so (the record is marked failed).

**A run started from the Run tab on its own** (before the panel has assembled it) runs the workbook as saved and is
not in SiCoPR-Assist's history: reuse needs a recorded working config, channel hashes and engine hash. When it
finishes, the panel says it does not track it and puts the phrase that brings the same inputs in (`Run COM on <thru>
with <config>.`) in the command box. Sending it imports the config and runs through the core; if the inputs equal a
run SiCoPR-Assist already holds, that run is reused.

## 7a. Everything the GUI does is in the history

The project history (`.sicopr\history.jsonl`) is the one log; the GUI adds none of its own. Each record the GUI
writes carries `origin: "gui"`, a `kind`, and a `detail` with what that kind holds. Records written by the command
line carry `origin: "cli"`; records older than the GUI have neither and read as phrases.

| kind | written when | holds |
|---|---|---|
| `phrase` | a phrase is sent from the command box | as a command-line record: phrase, pattern, outcome; and the selection, when the phrase used it |
| `answer` | an option button is clicked | the option chosen and the outcome |
| `edit` | a Config-view field is committed | the keyword, the value before and after, accepted or refused |
| `open` | the Config view opens another workbook | old and new source, the overrides kept or left out |
| `run` | a plan that runs something (COM, a batch, the export, a download) starts, and again when it ends | the command's record number and steps; at the end, run ids, status, elapsed time, the reason if it did not complete, and the plan's status lines (at most 400; the engine's own lines are in each run's `run.log`) |
| `stop` | Stop is pressed | the command, what was running and what was left |
| `view` | a run is shown in Results, a dashboard is shown, Settings or History is opened | what was shown |
| `error` | an endpoint raises, an API call fails, or the page reports a script error | where, the message, the trace or script line |

`edit` and `open` records carry a working config, which the next command builds on. The log kinds (`run`, `stop`,
`view`, `error`) are left out of `Project.read_history()` unless asked for, so only the History fold and the feedback
export see them. The page reports its own errors through `window.onerror` and `unhandledrejection` to `POST log`,
and an error is recorded at most once a minute per distinct message, so a loop cannot fill the file. The feedback
export includes every record, with its masks applied to the new fields. The tutor does not count an edit or an open
as a command.

## 8. Endpoints of the panel and the core functions they call

All are under `/panel/assist/api/`. Every path the page gives is checked against the project folder and
`host.roots()`.

| endpoint | does | calls |
|---|---|---|
| `GET state` | the version, project folder, working-config line, source workbook, pending question, whether a plan is running, and `tutor_due` | `Project.read_pending`, `api.working_line`, `core.Context`, `tutor.successes`, `read_settings` |
| `POST project {path}` | change the project folder (a folder under `host.roots()`; refused while a plan runs) | `Project` |
| `POST handle {phrase, selection}` | resolve a phrase with the selection handed over as data; carry out a PLAN in the worker; with a PLAN of one COM run, also `run_tab` | `core.handle`, `run.run_tab_setup`, `run.follow` |
| `POST runtab {selection}` | the Run tab's setup and command for its files and options now, the working config kept; `{command: null}` with no THRU | `run.run_tab_preview` |
| `POST examples {selection}` | up to four phrases for under the command box, each giving a PLAN now | `tutor.first_run`, `tutor.examples`, `tutor._resolve` |
| `POST selection {selection}` | the selection as the core would be handed it, and a line that shows it; kept for other front ends, not called by the page | `api.clean_selection`, `api.selection_line` |
| `GET job?since=` | progress lines since a position, running or done, the outcome, whether the plan runs anything (`runs`), and the running line | the worker's buffer, `run.line_text` |
| `POST stop` | stop the plan in progress | the worker's cancel flag |
| `POST overlay {keys, changed}` | the source workbook and the overlay cells, keyed as the view shows them, with `focus` for the keys of the last outcome | `core.Context`, `config_model.import_config` (cached by SHA-256), `config_model.apply_changes`, `config_model.same_value` |
| `POST edit {edits, source}` | take committed Config-view edits into the working config | `core.edit` |
| `POST open {path}` | follow another workbook opened in the Config view | `core.edit` with a source |
| `POST log {kind}` | a view shown or a page error, recorded | `Project.append_history` |
| `GET history?limit=` | the records for the conversation after a reload and the History fold, and the phrases for recall | `Project.read_history` |
| `GET result?run=` | one run's summary, its headline, whether it has the `.mat` export, and the phrase that shows its dynamic results | `summary.run_summary`, `api.headline`, `core.dynamic_phrase` |
| `GET batch?seq=` | a batch's lines and rows (point, values, status, run, COM) and the path of `batch_summary.csv` | `summary.batch_rows`, `summary.batch_lines` |
| `GET settings` | the settings in force | `read_settings`, `core.settings_lines` |

A response that holds a number that is not finite (ERL is `inf` when not computed) writes it as text, since a browser
reads only strict JSON. An endpoint that raises is recorded as an `error` record and answered with a JSON error.

## 9. Security

- **A local server.** SiCoPR's GUI binds to 127.0.0.1 only. The panel has no server of its own; its routes are
  served by SiCoPR's.
- **Cross-site and DNS-rebinding requests are refused.** SiCoPR's request guard (`Handler._refused`) runs before any
  route, panel routes included: the Host must be this server, an Origin must be this server, `Sec-Fetch-Site` must be
  same-origin or none, and a POST body must be `application/json`. So a page on another site cannot reach the
  panel's `handle()` or the core.
- **Paths.** The panel accepts a path only when it is inside the project folder or a directory opened in the GUI
  (`host.roots()`); a relative path is read against the project folder, so `..\` that leaves it is refused like an
  absolute path elsewhere. This holds for the selection, a workbook to follow, the source of an edit, and the project
  folder itself (which must be under an opened directory). SiCoPR serves the panel's static files by base name only.
- **Nothing past the core.** Every change goes through `core.handle` or `core.edit` and is checked as typed input is.

## 10. What the core provides for the GUI

- `core.edit(project, changes, source=None, origin='gui')`: the structured-change path of section 6. It validates
  changes against the working config, applies links, records one history record, and returns an outcome like
  `core.handle`. With `source` it imports another workbook (following, section 6).
- `core.handle(phrase, project, selection=..., origin=...)`: `selection` is the selection in the tabs and the Run
  tab's options (section 5a); `origin` goes only into the record, so the outcome does not depend on it.
- `run.follow`: carrying out a plan and following a channel download into the plan made from it, shared by the
  command line and the panel. It takes a `cancel` event (Stop) and a progress callback.
- `run.run_tab_setup`, `run.run_tab_preview` and `run.child_argv`: the Run tab's setup and the command it shows, made
  by the same function that makes the run's own argument list, so the command shown is the command that runs.
- `Re-run.` after a Config-view edit runs the current working config, edit included, rather than re-applying the
  earlier command's changes over it.
- The tutor's count of successful commands leaves out edits and opens; the feedback export marks them `config view`.
- A view edit is an ordinary history record, told apart by its pattern (`config view: set`, `config view: open`).

## 11. Tests of the GUI

They run without a browser and without COM: a stand-in host plays SiCoPR's server and a stand-in child plays the
engine. Checks that need SiCoPR's real server with the panel slot print SKIP when the SiCoPR in use has no slot.

- `tests\test_gui_api.py`: the panel's API driven as SiCoPR's GUI drives it. The same answers as the core for the
  frozen list of use-case rows scored on the steps of a plan or the options of a question (README, levels), and the
  same progress lines as the command line; the Config-view round trip on the four starting workbooks (an edit is one
  record and the next run's CSV loads to it, links move and are removed, a `[TX RX]` half keeps the other half, a
  refused edit never reaches the working config, the latest record wins, the source workbook's SHA-256 never
  changes); overlay keys are SiCoPR's own; busy both ways and Stop; every run folder listed by SiCoPR's Results; paths
  outside the opened directories refused; each kind of history record; following another workbook; a cross-site
  request refused before `handle()`.
- `tests\test_gui_static.py` ("The page"): `panel.js` parses (with node, else esprima); every element id it uses
  exists; every class that sets `display` has a `[hidden]` rule; every event it sends or hears is in the contract,
  and is SiCoPR's list when the SiCoPR in use documents it; it calls only endpoints `api.py` answers; the command
  box's keys and layout.
- `tests\test_selection.py`: the forms read as the selection and the near-forms left unplaced; the plans; the roles
  the engine is given; the example in an empty folder (with `SICOPR_ASSIST_E2E = 1`, through the real engine).
- `tests\test_run_tab.py`: the phrases for the Run tab and the dynamic results; the options as part of the run and of
  reuse; the command the Run tab shows is the command that runs; `POST handle` gives the Run tab's setup and `POST
  runtab` its command after a change.
- `tests\test_gui_first.py`: the running line, the headline result, a batch's lines and table, and the status lines
  in the run record.
- `tests\test_streamline.py`: what the panel no longer shows; the project folder, Browse and the version in Settings;
  a plan as one line with its steps under details; when the examples show (run in node when it is installed);
  three exchanges in view and older ones in History, newest first.

Every new check is shown to fail on the defect it targets before it is kept, and `tests\test_text_style.py` covers
this document as it covers every file.

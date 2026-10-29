# Changelog

## 0.12.3 (29 October 2026): first public release

- **Security: SiCoPR 1.1.4 or later is required.** SiCoPR 1.1.3 and earlier evaluated some config cell text
  as Python, so a crafted workbook could run code when SiCoPR-Assist loaded it. SiCoPR 1.1.4 reads every
  cell with a MATLAB-subset evaluator. `engine.folder()` now refuses a SiCoPR without it, with a message that
  says why (`tests\test_engine_minimum.py`, shown failing without the check). `SICOPR_REF` is SiCoPR v1.1.4.
- **Contributions are issues only.** Pull requests are not accepted (`CONTRIBUTING.md`). `SECURITY.md`
  describes private vulnerability reporting. An issue template asks for the phrase, what was meant and the
  answer.
- **A named-standard preset in a folder with no config.** "Setup a 802.3dj config for C2C and run my channels."
  in a folder holding only channel files stopped inside the translator, and the user saw the strict "could not be
  placed" question. 802.3dj now gets the no-config proposal; 802.3ck gets a STOP that says to put a config in the
  folder (`tests\test_preset_no_config.py`, shown failing without the fix).
- The README's install steps clone both repositories and pin SiCoPR v1.1.4, and say how long a run takes.
- A plan's announcement gives the source of a preset value that rule Q14 does not ask about.
- CI runs with a read-only token.
- The GUI section says plainly that no released SiCoPR has the panel slot yet; the command line is the way
  to use SiCoPR-Assist until it does.

## 0.12.2 (21 October 2026)

Tested with SiCoPR commit `e1651c4` (config value cells read as MATLAB evaluates them, SiCoPR finding F19), recorded
in `SICOPR_REF`.

- **`b_max(2..N_b)` and `b_min(2..N_b)` are read again.** SiCoPR `e1651c4` reads them through a helper,
  `_dfe_limits(key, default)`, and the loader scan (`schema_check.loader_keywords`) knew only helpers of one argument.
  The two keywords dropped out of the import, so the run CSV left out the workbook's cells and the engine took the
  reference defaults (0.2 and -0.2): "Change DFE taps to 2" on the 802.3dj KR workbooks (C4, PA073) loaded
  `bmax [0.85 0.2]`, `bmin [0 -0.2]` where the workbook holds 0 for both. A helper now passes on its keyword from
  its first argument and its default from the argument the call gives it. COM Octave 4p17p0 (`read_ParamConfigFile`)
  on the run CSV with the two cells gives `bmax [0.85 0]`, `bmin [0 0]` for N_b = 2 and `[0.85 0 0]`, `[0 0 0]` for
  N_b = 3 on Case1 to Case4, as the table expects; without them it gives the defaults, as SiCoPR does. The table is
  unchanged.
- The test oracle (`tests\cases\gen_use_cases.py`) reads the two keywords through the same helper.
- Tests: the schema self-check covers a helper of two arguments; G2.3 and G2.5 of `tests\test_config.py` failed on
  `e1651c4` before the fix.

## 0.12.1 (21 October 2026)

The maintainer's rulings at the Phase V2-10 checkpoint (21 October 2026). The use-case table grows to 1050 rows (46
rows of groups PS, PP and SY changed, 9 SY rows added; every other row byte for byte as in 0.12.0), the frozen L4 list
to 802 rows (the 660 of V2-9 unchanged) and the review list to 248.

- **Preset values skip the validation question.** A value a preset takes from the standard (802.3ck `b_min(1) = 0.3`
  and the rest) does not trigger rule Q14: the 802.3ck KR, CR and C2C presets, "100G per lane backplane", and both
  802.3ck C2M runs plan in one step. The plan carries a pass for rule Q14 on the preset's own keywords only
  (`validate.py` reads `Q14:<keyword>`), so the same value typed by hand still asks, in strict mode and in translator
  mode. The plan says that Q14 did not ask and why.
- **Standard values ship.** COM parameter values taken from IEEE Std 802.3ck-2022, IEEE P802.3dj/D2.4, the IEEE COM
  3.70 workbooks and the public OIF-CEI-05.3 are in `sicopr_assist\data\presets.csv` under the same terms as the COM
  configuration workbooks (BSD-3-Clause, Copyright 2025 802-COM Authors). Every value names its source and carries a
  licence tag (new column `license`); `NOTICE` carries the workbooks' License Notice. Nothing whose only source is an
  OIF member working text is shipped (low-power option 1 takes the 802.3dj C2C values of the 802-COM C2C template).
- **No overlay.** Every preset works on a fresh install: 802.3ck KR, CR, C2C and C2M, the 802.3dj C2M `eta_0`, and
  all five low-power receivers (CTLE only now takes the XSR ranges, and the long DFE is always offered). The setting
  `preset_overlay` is gone; a settings file that still has it warns and changes nothing.
- **802.3ck C2M eye height and VEC** takes `TDR_W_TXPKG = 1`, the value of its COM 3.70 workbook, now that SiCoPR 1.1.3
  runs it (0.12.0 held 0, the workaround for the make_full_pkg failure).
- **Translator-mode rows for strict rows the translator reads**: SY67 (PH15), SY68 (TU02, which still asks with no
  run) and SY69 to SY74 (TU14 to TU19); the strict rows keep their expectations.
- Tests: `tests\test_translate.py` replaces gate V10.6's overlay checks with the source and licence checks, the License
  Notice in NOTICE and README, and the presets on a fresh install (ruling 1, 4 and 5 checks); `tests\test_settings.py`
  covers the removed setting; the overlay conditions of the harness are gone.

## 0.12.0 (21 October 2026)

Version 2, Phase V2-10: rules and presets. The owner: "I want the user to be able to request KR, CR, C2M or C2C, or
802.3ck or 802.3dj, and have it adjust the analysis appropriately." Decision 26: translator mode, a layer of rules and
interface presets in front of the strict core, with no model. The use-case table grows to 1041 rows (groups PS, PP,
CF and SY, 165 rows, scored in translator mode; CF in both modes) and the frozen L4 list to 801 rows (the 660 of V2-9
unchanged, then 141 new); with `translator = off` every earlier row scores as in 0.11.0.

- **Translator mode** (`sicopr_assist\translate.py`; setting `translator`, default on, and its environment override
  `SICOPR_ASSIST_TRANSLATOR`). When the strict core misses a phrase, the layer reads it again and hands the core a
  phrase it resolves, or asks its own question, or stops. It never writes the run CSV, runs the engine or skips
  validation. The miss gate: a reply to a pending question, an out-of-scope request (email, slides, diagnose,
  convert, optimise) and a value the core refused never reach it. Typos are forgiven in command words only.
- **Words to keywords**: the owner's rulings (baud rate, pass threshold, SNDR, DFE taps, Rx FFE taps, package A and B,
  the high-loss package, both package tests) and the study's list; references from the project (the 500mm thru, the
  original thru, the other package, the channel I selected); number words; a word with several readings (`Z_c`,
  `SNR`, trace impedance) is a question with the candidates; a name one look-alike character from a keyword
  (`DER_O`) is asked about, never corrected.
- **Interface presets** (`sicopr_assist\data\presets.csv`, each value with its source): KR, CR, C2C and C2M in
  802.3dj and 802.3ck. 802.3dj CR proposes the host classes (HL to HL) with the valid pairs as options; 802.3dj C2M
  starts from the 802-COM C2M egress template, shipped unchanged with its License Notice sheet, with the adaptive
  search keywords; 802.3ck C2M offers the eye height and VEC run or a C2C-parameter COM. A named interface takes the
  standard of the config in view, a named standard keeps the interface in view.
- **The overlay**: values whose only source may not be redistributed (IEEE Std 802.3ck-2022, P802.3dj drafts, the COM
  3.70 workbooks, OIF texts) are not in the repository; they load from a local CSV named by the setting
  `preset_overlay`, and without it those presets stop and say what is missing.
- **Proposals**: about 10% more Rx FFE taps with the counts; the low-power receivers (four without the overlay, five
  with it); the XSR-like receiver. Each option is a phrase the core resolves.
- **History and feedback**: every command in translator mode records the wording, whether the strict core missed it,
  the rules or preset that fired, the phrase handed to the core, any proposal, whether the user confirmed, changed or
  declined it, and the translator's name, version and rules SHA-256 (history key `translation`); Export feedback
  carries them.
- **Core fixes** (both modes): the answer to a validation question on a first-run phrase is kept, and Q14's text is
  right for a `b_min` limit above 0 (rows CF01 to CF03); `in <block>` binds per item, a main keyword is never written
  into a package block, a first-run phrase reads block qualifiers, an unqualified package keyword follows the
  `PKG_NAME` set in the same phrase (CF04 to CF09); a MATLAB vector expression with `ones` or `zeros` is written out
  as the values MATLAB reads (CF10); a strict OOXML workbook is a STOP, not a traceback (CF11); a run in eye height
  and VEC mode is judged by `VEC Pass threshold` and `EH_min` (CF12). A value glued to letters (`53.l25`) is read as
  one word, so it stops as not a number.
- **Also**: `Use the selected channels.` takes the channel files selected in the GUI into the working config without a
  run; several keywords in one `Show`; `Show the package block <block>.`; a batch summary says whether COM passes at
  every point; the panel's result line for an eye height and VEC run.
- Tests: `tests\test_translate.py` (new: gates V10.5 and V10.6, the miss gate, the core fixes' texts); gates V10.1
  and V10.2 in `tests\test_use_cases.py`; 17 new prior-state builders; the settings test covers the two new settings.
  The test scripts written before this phase run in strict mode (`tests\check.py`).

## 0.11.0 (19 October 2026)

Version 2, Phase V2-9: streamlining the panel. The owner liked GUI first ("the Assist command prompt area was getting
too busy") and chose five of eight items offered on 18 October: the panel shows only what SiCoPR's GUI does not
(Decision 25). Only the panel's page changes, and the panel's `GET state` gains one field; the core, its outcomes, the
use-case table (876 rows) and the frozen L4 list (660 rows) are unchanged, and the same session writes the same history
records. SiCoPR's branch `gui-panel-slot` is unchanged.

- **No selection line.** The line above the command box and its Run selection button are gone: the Run tab shows the
  files and options. The selection is still handed to the core with every phrase, and a plan that used it says so
  (`using the Run tab's setup`). The Run tab's Run button and `Run the command.` run it.
- **Project and version in Settings.** The project folder, Browse and the version line are in the Settings fold (opened
  by itself when the panel has no project folder). The panel's own top line is only the working config's short
  state (`working config run_0005, 2 overrides`), hidden while there is none; the title is the slot's header, which
  SiCoPR's GUI gives every panel.
- **A plan is one line** that says where its effect can be seen: `2 changes, highlighted in Config`, `running in the Run
  tab`, `3 points: output in the Run tab`. The steps and the announcements are under details. A question keeps its text
  and buttons, a stop its reason; the result lines are as in 0.10.0.
- **Examples only when they help.** The example phrases under the box show while it is empty and the history holds fewer
  successful commands than `tutor_until_commands`; a plan's tutor text (a new user's) is shown there the same way,
  and no longer also in the plan's reply.
  `What can I say?` always shows them. `GET state` gives `tutor_due` (the tutor's own rule).
- **Short conversation.** The last three exchanges stay in view; older ones are in the History fold, newest first, each
  one line (what was said, its one-line reply, its run's headline) that opens to the full reply. Every record of the
  project history is still there, folded below them.
- Tests: `tests\test_streamline.py` (new, gate V9.1); the checks of `tests\test_gui_static.py` that described the
  selection line, the Run selection button and the plan's list of steps now describe what replaced them.

## 0.10.0 (18 October 2026)

Version 2, Phase V2-8: GUI first, after the maintainer's third GUI session. "For displaying the run command output, I'd
prefer it to use the GUI Output area that has more screen space rather than forcing output to Assist window. I really
want the GUI to be used just like non-Assist SiCoPR, but with Assist you can type commands to get what you want." The
same session found three phrasings that missed; the language-model layer is deferred (decisions of 18 October), so
they are rules. Rows GF01 to GF05 (on existing prior states) specify them; the table has 876 rows. It needs SiCoPR's
branch `gui-panel-slot` with `sicopr:output`.

- **A run's output is in the Run tab (Decision 24).** A run the panel carries out streams its lines to the Run tab's
  Output (the page event `sicopr:output`), shown as a run of the Run tab is: its status line, follow output, and Stop,
  which stops the panel's run (`sicopr:stop-request`). When a run starts the page shows the Run tab
  (`sicopr:show` with `unless_editing`), unless the user is in the middle of an edit in Config; when it ends the page
  stays there and the run is in the Results tabs, as after a run of SiCoPR's own. A batch streams every point in
  order, each headed with its point.
- **The panel keeps short replies.** The plan's steps as a short list, questions with buttons, one line while a plan
  runs (`run_0006 running: output in the Run tab`), then the headline result (COM, pass or fail against COM Pass
  threshold) with the Results buttons, or a batch's short table; long text (announcements, a run's summary) folds
  behind a details toggle. The panel has no progress area of its own any more. `GET job` gives `runs` and
  `running_line`, `GET result` the `headline`, `GET batch` its `rows`; the `run` end record keeps the status lines.
- **"the current settings"**, "settings captured", "what I have set up" and "as it is set up" mean the setup in the GUI,
  as "the command" does (row GF01; the maintainer's `Run with current settings.`).
- **The thru-only and the crosstalk case together.** "thru-only and xtalk", "with and without crosstalk" (and
  `Compare thru-only with xtalk`) are a batch of two points on the same config and THRU, without and with the
  crosstalk that belongs to the THRU (Decision 19), with `diff_results` against the thru-only case when "compare" is
  said (rows GF02 to GF04). Points already run are reused, so a last run with crosstalk no longer stops it (the
  maintainer's `Run config thru-only and xtalk and compare results.`). No crosstalk to find asks (row GF05).
- **Several sentences are one request** when they describe one run or batch (row GF03): "two cases" (or both cases)
  is placed beside the two cases of a THRU, and the maintainer's `Run with settings captured.  Run thru-only and with
  xtalk.  Compare results of two cases.` gives the plan of GF02.
- Tests: `tests\test_gui_first.py` (new), gate V8.2 in `tests\test_use_cases.py`, and new checks in
  `tests\test_crosstalk.py` and `tests\test_gui_static.py`. The frozen L4 list has 660 rows (GF01 to GF05 added), the
  review list 216, unchanged.

## 0.9.0 (17 October 2026)

Version 2, Phase V2-7: what the maintainer's second GUI session asked for. "The Run Tab will have the command
assembled as the Assist prompt gets user feedback. So if I notice that dynamic results is not selected, I can select it
in the GUI and then tell Assist prompt to 'run the command' and all the information from the GUI is part of the Assist
prompt." The same session found that `Re-run last config and channel.` asked about "channel", and that
`I'd like results, dynamic for the last run.` was read as a result name. Rows RT01 to RT06 (four new prior states)
specify it; the table has 871 rows. It needs SiCoPR's branch `gui-panel-slot`, now based on SiCoPR 1.1.2.

- **The Run tab is the setup Assist runs (Decision 23).** A PLAN that runs COM fills SiCoPR's Run tab (the page event
  `sicopr:set-run`): its files, Output dynamic results and `--eye-under-mlse` as the plan runs them, and in its command
  box the command the panel runs, the working config's run CSV and not the workbook, with a note that says so. The
  command is made by the same function as the run itself (`run.child_argv`), so what is shown is what runs.
- **The Run tab to Assist.** `sicopr:channels` now carries the two options and is sent on every change of a file or an
  option; the selection holds them, and the selection line names those that are on. A change in the Run tab while
  the panel has it assembled updates its command (`POST runtab`).
- **"Run the command."**, "Run it." (where there is a Run tab; on the command line it keeps its meaning), "Run what is in
  the Run tab" and "Run the Run tab" run exactly the Run tab: the working config (with what was done in the Config
  view), its files and its options; with no working config yet, the workbook of the Config tab. A setup equal to the
  last run, options too, is a STOP. With no Run tab (the command line) it asks: re-run the last run, or cancel.
- **The Run button runs through Assist** while the panel has assembled the Run tab (`sicopr:run-request`, which the
  panel takes): the same phrase, one history record, the same plan and progress.
- **The options are part of the run and of reuse.** Output dynamic results is `--export-mat` (an export run: its
  `.mat` and dashboard are then available, and when it ends the run opens in Results, dynamic, which builds its
  dashboard); `--eye-under-mlse` goes to the run child, which sets the engine's `EYE_PLOT_UNDER_MLSE` as
  `sicopr.py --eye-under-mlse` does (it changes eye plots, no reported value), and is recorded in `result.json`. A run
  is reused only by a run with the same `--eye-under-mlse`; a run with the export still serves one without it.
- **Vocabulary.** "dynamic results", "results, dynamic" and "the dynamic results of the last run" are the dashboard
  (rows D1, RT05); "I'd like" is placed. A run named by its id (`Show the dynamic results of run_0004.`) gives that
  run's dashboard, on its own config and channel files; a run id anywhere else is asked about. "the last config and
  channel(s)" are the config and channel files of the last run (row RT06). Opening Results, dynamic from the panel on a
  run with no `.mat` export says so and offers the phrase that makes one.
- Found by the new tests and fixed: the dashboard of an earlier run named by its id re-ran the last run's channel files;
  it now runs that run's own config and channels, and its history record names them.
- Tests: `tests\test_run_tab.py` (new), gate V7.3 in `tests\test_use_cases.py`, and new checks in
  `tests\test_gui_api.py` (a cross-site POST to the panel is refused by SiCoPR's request guard before the core sees it)
  and `tests\test_gui_static.py`. The frozen L4 list has 655 rows (RT01, RT03, RT04, RT05 added), the review list 216
  (RT02, RT06).

## 0.8.0 (10 October 2026)

Version 2, Phase V2-6: what the maintainer's first GUI session found. He picked a config and a channel in the
GUI's tabs and typed `Run on the config and channels specified in the tabs.`; the panel had no way to know which
channel files were picked, strict mode had no meaning for "the selected", and it asked about `b_min(1)`. The
one-line command box was easy to miss. `Run the example` asked for a channel file. Rows SL01 to SL05 and EX01
(six new prior states) specify the first and the third; the table has 865 rows.

- **The selection in the tabs (Decision 20).** `core.handle(phrase, project, selection=...)` takes what is
  selected in a GUI's tabs as data, one more optional input like `origin`: the config, the THRU, and the FEXT
  and NEXT files. "the selected", "the specified" or "the chosen" config, channel, channels or files, "in the
  tabs", "the selection" and "what is selected" mean that selection, in those forms only (a selection word
  outside them is still asked about). With no working config the selected config is imported and run on the
  selected channels, as the same files named in a phrase would be; with one, it is kept, with its overrides and
  what was done in the Config view, and only the channel files change (Decision 18's swap with the files from
  the selection). The files run in the roles they were given in the Run tab, whatever their names say. No
  channel selected asks; no selection at all, as on the command line, asks; a selected file that is not on disk
  stops. The history record of a phrase that spoke of the selection keeps what was selected then.
- **The role of a channel file is part of what decides reuse.** Until now a file's role followed from its name,
  so the same files always meant the same run. With roles given by the selection, the same file as a FEXT and as
  a NEXT aggressor is another run, and is never served by the result of the first.
- **The panel keeps the selection** (the config from `sicopr:config`, the channels from the new page event
  `sicopr:channels` of SiCoPR's GUI), shows it in a line above the command box
  (`Selected: <config>; THRU <file>; 3 FEXT, 4 NEXT`), and posts it with every phrase. A path outside the project
  folder and the opened directories is left out before it reaches the core. A **Run selection** button sends
  `Run the selected config and channels.`
- **The command box (Decision 21)** is a text area of three lines that grows with its content, in its own block
  with the label `Type a command` and a border in the accent colour. Enter sends, Shift+Enter starts a new
  line, and it has the focus when the panel comes up. Under it are up to four phrases that give a PLAN right
  now; a click puts one in the box. The block stays in view at the bottom of the panel while the conversation
  scrolls.
- **`Run the example.` works from an empty folder (Decision 22).** With no channel file in the project folder,
  the plan runs the example setup on a synthetic THRU, the 400 mm lossy line, written to `data\example_thru.s4p`
  when the plan is carried out, and says that it is synthetic and not a measured channel. A channel file already
  in the folder is used instead. The line model moved into the package as `sicopr_assist\example_channel.py`;
  `tests\cases\make_s4p.py` hands the tests that one implementation and writes the same bytes as before.
- Found in the walk-through on the real page and fixed: the box could not take the focus while SiCoPR still had
  the panel slot hidden (it is now tried until the box is on screen, and never taken from a field in use); a
  run that was stopped counted as "the last run" with nothing changed, so the same selection could not be run
  again (only a completed run does now); the examples under the box are hidden while a plan runs, so the
  progress lines have the room.
- Tests: `tests\test_selection.py` (30 checks, and gate V6.4 end to end with `SICOPR_ASSIST_E2E = 1`), the
  selection and the examples through the panel in `tests\test_gui_api.py`, the command box and the selection
  line in `tests\test_gui_static.py`, and `tests\test_use_cases.py --gate V6.2`. The frozen L4 list has 651
  rows: the 645 it had, unchanged, then the six new rows.

## 0.7.0 (9 October 2026)

Version 2, Phase V2-5: the GUI, built to `docs\GUI_DESIGN.md` as approved on 9 October 2026 with the
maintainer's two changes (Assist follows a workbook opened in the Config view; every GUI interaction is in the
history). It needs SiCoPR's GUI with the panel slot (SiCoPR branch `gui-panel-slot`, for the maintainer to take
or not); the version 1 gates still run against SiCoPR 1.1.1 (`55c3f71`), whose engine is the same.

- **The Assist panel** in SiCoPR's GUI (`sicopr_assist\panel\`, registered under the entry-point group
  `sicopr.gui_panels`): the project line, the conversation with each PLAN, QUESTION or STOP as on the command
  line, option buttons, the tutor's example phrases as links, live progress with Stop, run summaries with
  buttons to SiCoPR's Results tabs, recall of earlier phrases, the settings, and a reserved place for a
  language model. `sicopr-assist gui [folder]` starts it.
- **The round trip.** SiCoPR's Config view shows the working config laid over its workbook, each changed value
  tagged with where it came from; a plan's changes show before its runs end. An edit committed in the view goes
  through the new `core.edit`, which validates it as the same value typed in a phrase, and becomes one history
  record with its own working config (`configs\edit_NNNN.json`); `Re-run.` after an edit runs the edited
  config; the latest record wins, and says which one it replaced. Another workbook opened in the view is
  followed, with the channel files kept and the overrides kept or not as the user answers.
- **The history records every GUI interaction**, with `origin` (`gui` or `cli`), `kind` and `detail`: phrases,
  answers, edits, opens, runs (start and end), Stop, views and errors (the panel's and the page's, at most one
  a minute for one message). The log kinds are left out of every reader of the history but the history view
  and the feedback export, which lists them masked.
- `run.carry_out` takes a `cancel` event (Stop: no further point starts, the child is terminated, the record
  and the result end failed); the CLI and the panel follow a channel download through one function,
  `run.follow`.
- Found in the walk-through on the real page and fixed, each with a check: a run's results hold `inf` and `nan`
  (ERL when it is not computed), which a browser's JSON reader refuses, so the panel answers strict JSON; when a
  workbook is followed, overrides that need each other (`N_b = 0` with `MLSE = 0`) are validated together before
  one at a time; the view is not pulled back to the old workbook while a follow, or its question, is under way;
  an edit finished by an answer button is tagged `edited here`.
- Tests: `tests\test_gui_api.py` and `tests\test_gui_static.py` (new), `tests\test_tutor.py` (Config-view
  records are not commands). The stand-in child writes `case_01\results.csv`, as the engine's report does.


Version 2, Phase V2-3: channel download (rows F1 to F12). Tested with SiCoPR 1.1.1 (commit `55c3f71`).

- **Channel download.** `Download the latest 802.3dj channels posted and analyze with SiCoPR, both
  thru-only and xtalk.` reads the IEEE P802.3dj tools page, takes the newest zip for the interface of the
  project, downloads it into `.sicopr\cache\<interface>\`, unpacks it, writes its inventory, pairs each
  FEXT and NEXT file with its THRU by Decision 19, and runs every channel thru-only and with its crosstalk
  as one batch (`batch_summary.csv`, reuse by fingerprint, `max_new_runs`).
- **The page as it is** (read on 7 October 2026). The interface is the folder of the zip link
  (`tools/KR/`, `tools/CR/`, `c2c/`, `c2m/`); the date of a zip is the line under its link, in every form
  the page uses, never a date in a note; a superseded note covers every zip of its entry, "do not use"
  only the zip whose link says it; a row with no link is skipped; a relative link is resolved; the page
  is read as Windows-1252. An entry with several zips under its date asks which one (F11), and so do
  two entries that share the newest date (F12). The skipped entries are named in the plan, with why (F5).
- **The interface** is asked once per project, KR first when the config file name or `RUNTAG` says KR,
  with that evidence, and the answer is kept (F2).
- **Two parts.** The core plans and never downloads: it reads the page, and asks the server for the
  size (Content-Length) when the page gives none. `run.py` downloads and unpacks the zip; the core then
  plans the run matrix from the cache (`core.fetch_followup`), and the command line shows it and carries
  it out. A zip already in the cache is not downloaded again (F4), and one already unpacked is not
  unpacked again.
- **Safe download.** A zip larger than `max_download_mb` asks first. A download arrives through a
  partial file outside the cache; an interrupted one is tried again `download_retries` times, then stops
  with nothing in the cache (F9). With the site unreachable it stops, or offers the zips already cached
  (F3).
- **Safe unpacking.** Every path in a zip is checked to stay inside the cache before anything is
  written: `..\`, `../`, an absolute path and a drive are refused, with nothing written, and the zip is
  removed. A zip inside the zip is unpacked in place. A path longer than the 260 characters Windows
  allows is warned about.
- **Inventory and pairing.** `<zip>.inventory.csv` lists every file with its role, its THRU, the rule
  that paired it, whether it reads as Touchstone, its SHA-256, and the role SiCoPR's
  `benchmark\208_case_4p15p0\channels.csv` gives a file with the same SHA-256; a download that is one of
  those six contributions is checked against it. A FEXT or NEXT file Decision 19 cannot pair asks:
  correct the inventory and say `continue`, or run thru-only only (F6). A file that does not read as
  Touchstone skips the runs that need it, with the reason in `batch_summary.csv` (F7). A zip with no
  Touchstone file offers the next zips for the interface (F8); one with THRU files only runs thru-only
  and says so (F10).
- **Network.** Only `sicopr_assist\fetch.py` touches the network, from the standard library, and only
  when a download is asked for (Rule 5 relaxed for that module alone; gate G5.3 narrowed, gate V3.4).
  `SICOPR_ASSIST_FETCH_INDEX` names another index URL.
- **IEEE public-area files** are kept in the project's `.sicopr\cache` and are never committed or
  redistributed; `.gitignore` now also leaves out `*.zip` and `*.s2p`.
- **Decision 16 is gone**: no phrase is answered with "not in this version" any more. `grab` is a
  download word.
- **Tests.** New: `tests\test_fetch.py` (the page reader, V3.2, V3.3, pairing and the known channels,
  the answers to F2, F3, F6, F8 and F11, and the F1 and F7 plans carried out with the stand-in child),
  and `tests\cases\standin_ieee.py`, a stand-in of the tools page in its recorded markup with small zips,
  served from 127.0.0.1. No test touches the network; with `SICOPR_ASSIST_LIVE_FETCH=1`, `test_fetch.py`
  reads the real page and the size of its newest KR zip, and with `SICOPR_ASSIST_LIVE_FETCH_ZIP=1` also
  downloads that zip into a temporary folder and checks it against `channels.csv`. The harness reads
  `same as F1` as F1's phrase, gives every fetch row its stand-in site, scores the outcome met before
  any run (after the download part, for a download plan), and gates the group fetch (`--gate V3.1`).
  Every group is now gated.
- **Scores** (full harness, `SICOPR_ASSIST_FULL=1`): 2435 applicable pairs; must pairs 2340: L1 2340/2340, L2 1582/1582, L3 1623/1623, L4 1740/1744 (the miss is RS07, as before); the 11 fetch must pairs pass L1, and L4 on F1 and F2; paraphrases 3669: 3518 understood, 151 asked, 0 wrong.

## 0.5.0 (8 October 2026)

Version 2, Phase V2-2: the dashboard (rows D1 to D4, CB17 and C2). Tested with SiCoPR 1.1.1 (commit
`55c3f71`).

- **The dashboard.** `Now give me the results in a dynamic dashboard.` plans `export_mat >
  render_dashboard > open_report`. `export_mat` runs the working config of the last run again with the
  engine's `.mat` export on (`run_case.py --export-mat`), announced as a full COM run; a run that had
  the export, with the same inputs, is reused instead. Whether a run had the export is now part of the
  fingerprint that decides reuse: a run with it serves a plain run, and a run without it never serves an
  export. `render_dashboard` runs Rscript on SiCoPR's `R\com_analysis.R` with the run's own folder as
  its working folder, so the page and its `lib\` folder land beside the `.mat`. `open_report` opens the
  page and prints its path. Each step has its status lines, and Rscript's own lines are passed on
  indented, as the engine's are (Decision 17).
- **With a run.** `Re-run with DER_0 = 1e-4 and show the dashboard.` (row CB17) runs once, with the
  export on, and builds the dashboard of that run; a re-run right after a dashboard builds it again
  (row C2). These two rows have their dashboard chains back.
- **Finding Rscript** (`engine.find_rscript`): on PATH, else the newest R under Program Files, compared
  as version numbers, so R-4.10 is newer than R-4.9. With no Rscript the dashboard is a STOP that names
  the CSV summary of the last run (row D3); with no run yet it asks (row D2). `report` is now a word for
  the dashboard (`open the report`).
- **The tutor** shows the dashboard phrase among its examples (row TU01) when Rscript is found; it is
  resolved like every other example first.
- **Tests.** The group report is gated (`--gate V2.1`). New: `tests\test_dashboard.py` (gate V2.2: the
  finder; the plans of D1 to D3, CB17 and C2; a dashboard plan carried out with the stand-in child and
  the new stand-in Rscript, `tests\cases\standin_rscript.py`; gate V2.3 end to end with
  `SICOPR_ASSIST_E2E=1`). The harness finds a stand-in Rscript for every pair and hides it, from PATH
  and from Program Files, for row D3, so the scores are the same on a machine with or without R. The
  table copy has CB17 and C2 with their dashboard chains; the frozen L4 list moved for those two rows
  only.

## 0.4.0 (7 October 2026)

Version 2, Phase V2-1: the tutor, trouble detection and feedback export (Decisions 10 and 11). Tested with
SiCoPR 1.1.1 (commit `55c3f71`).

- **The tutor** (`sicopr_assist\tutor.py`). `What can I say?` (or `help`) lists phrases that work on the
  config in front of the tool, with its own names: a re-run with one change, a re-run with another
  package block, a sweep over a range, a sweep over a choice, what changed, and the original config
  again. Each phrase is resolved by the core before it is shown, as if that config had just been run,
  and a phrase that would not work is left out. The dashboard phrase waits for the dashboard.
- **On its own**: after each command while the history holds fewer than `tutor_until_commands` (5)
  successful commands, as a `show_tutor` step at the end of a plan; after a phrase that was not
  understood, the nearest phrase that works (`Re-run with f_b = <value>` for `halve the baud rate and
  rerun`). With no run yet, a name that is not a COM keyword is now asked about against the one config
  in the folder, as it is after a run.
- **Trouble detection**: 3 misses in the last 5 commands (a word that could not be placed, a phrase
  that matched nothing, a cancelled question) bring up the nearest phrase that works for each one, and
  at most once in 20 commands a line about Export feedback. Misses counted for one showing are not
  counted again. These thresholds are still an assumption (open decision TU14).
- `Tutor off.` and `Tutor on.` write and remove `tutor_until_commands = 0` in the project settings file.
- **Feedback export** (`sicopr_assist\feedback.py`). `Export feedback.` writes
  `.sicopr\feedback_<date>.txt` from the history: counts by outcome and pattern, questions with their
  options and answers, rephrase pairs, words that could not be placed, settings that differ, and every
  phrase. Names are masked by default (`<file1>.s4p`, `<block1>`, `<name1>`), numbers with
  `mask_numbers = on` (`<num>`, units kept), and the first lines say which. Option remarks that show
  current config values are left out. `Send feedback.` also prints the address and subject and opens
  the folder. Nothing is ever sent. A phrase that works right after a cancelled or missed one is
  recorded as its rephrase.
- **Tests.** The table is 859 rows (F1 and F5 rewritten from the IEEE page, F11 and F12 added), with
  two more prior states; the frozen L4 list is unchanged and F11 and F12 go to the review list. The
  groups tutor and feedback are gated (`--gate V1.1`). New: `tests\test_tutor.py` (gate V1.3: every
  phrase the tutor prints resolves, on the four starting configs and the twelve variants, before and
  after a run; and the tutor text of rows TU01 to TU19) and `tests\test_feedback.py` (gate V1.2:
  masking; and rows FB02 to FB07, FB15 to FB17). The prior states "history holds N successful commands"
  now include a seeded run, so the re-runs of rows TU14 to TU19 have one to start from. A `show_tutor`
  step that the tutor adds on its own is left out when the harness compares the chain of a row outside
  the tutor group, since those rows were written while the tutor was deferred.

## 0.3.1 (7 October 2026)

- **A path written with `/` is read as a path.** `Run COM on ch/a_thru1.s4p with data/config.xlsx` kept only the
  file names, so the files were looked for at the top of the project and the tool asked for them. It
  broke on Linux (CI) and for anyone who types `/` on Windows. A path with `/`, `\` or both is now one
  path when it ends in a file extension the tool reads, so `w/` and `dB/GHz` are unchanged.
  `tests/test_paths.py` guards it.

## 0.3.0 (7 October 2026)

After the maintainer's second session. Tested with SiCoPR 1.1.1 (commit `55c3f71`).

- **Adding crosstalk** (Decision 19). After a thru-only run, `Re-run with crosstalk.`,
  `Add xtalk files and re-run.` and the like keep the config, the overrides and the THRU of the last
  run, and take the FEXT and NEXT files that belong to the THRU: every FEXT and NEXT file in its
  folder when it is the only THRU there, otherwise the ones whose names equal the THRU's once the role
  words are removed. One `set_channel` step carries them; the engine gets FEXT then NEXT, each sorted
  by name, with their counts. The plan lists every file and the rule that took it. Nothing found, or
  no name that matches, asks for the files; the crosstalk already in use is a STOP.
- **No word is dropped.** A known word that means something only inside a clause (crosstalk,
  package, tx, three, back and the like) was placed silently when no clause took it, so
  `Add xtalk files and re-run.` replayed the last command, a wrong PLAN. Such a word is now unplaced
  and asked about. `Add widget files and re-run.` asks too, and nothing runs.
- **The summary of the last run summarises.** `the last run` and `the previous run` are a run already
  made, not a request to run, so `Give me the results summary of the last run.` shows the summary and
  runs nothing.
- **Thru only after a crosstalk run** replays the last run with its THRU alone. Before, it asked a
  question that said the last run had no crosstalk files, and the replay ignored the choice.
- **Tests.** The table gains rows XT01 to XT06 and SM16 (857 rows) and four prior states. The frozen L4
  list gains XT01, XT02, XT03, XT05, XT06 and SM16 and nothing else; XT04 (STOP) goes to the review
  list. New: `tests\test_crosstalk.py` (the matching rule on five naming styles, the arguments the
  runner gives the engine, and a check that no word vanishes in any of several phrase shapes, on the
  reader and on the core), and `--gate N1`, `--gate N2` in the harness.

## 0.2.0 (6 October 2026, not yet released)

After the maintainer's first real use. Tested with SiCoPR 1.1.1 (commit `55c3f71`).

- **A re-run with another channel file keeps the last run's config** (Decision 18). After a run,
  `Re-run with data\thru_500mm.s4p`, `Re-run COM on <file> with the previous config` (or the same
  config, or the last config) keep the working config of the last run with its overrides, and change
  only that channel (new step `set_channel`). A parameter change in the same phrase is made as well.
  `FEXT <file>` or `NEXT <file>` adds or replaces an aggressor. A bare file name that is not in the
  project folder is looked for by its exact name in `data\` and beside the last run's THRU. A file
  that does not exist stops and keeps the last setup; the file already in use is a STOP; with no run
  yet the tool asks for a config. Before, every phrase naming a file went to the first-run path and
  asked for a config in the folder. The channel's SHA-256 decides reuse as before: a new THRU is a
  new run, and an earlier THRU with the same config is reused.
- **A run shows what is happening** (Decision 17). While a plan is carried out the command line
  prints a status line as each step starts (with the run id, and the point n of N in a batch), the
  engine's own progress lines as they arrive, indented and unchanged, and each run's elapsed time and
  headline COM. The same lines go to `run.log`. `--quiet` leaves out the engine's lines on the
  screen. The lines come through a callback (`run.carry_out(..., progress=...)`) that a GUI can use.
  The child now writes UTF-8, so characters such as the engine's multiplication sign reach the log
  intact.
- **Tests.** The table gains rows CH01 to CH08 (850 rows) and three prior states. The frozen L4 list
  gains the six CH rows the normaliser reads and nothing else; CH04 and CH07 (STOP) go to the review
  list. New checks: the CH gates (`--gate M1`, `--gate M2`), what the command line shows and logs
  while a run goes (stand-in child), the runner's channel swap and reuse, and an end-to-end run and
  re-run on a 300 mm THRU (`SICOPR_ASSIST_E2E=1`).

Scoreboard (`SICOPR_ASSIST_FULL=1`), must rows outside the deferred groups: 2281 row and config
pairs; L1 2281/2281, L2 1582/1582, L3 1617/1617, L4 1703/1707 pairs (579 of 580 rows; the miss is
RS07, as in 0.1.0). The 14 must CH pairs pass every level that applies. Paraphrases: 3632, of which
3480 understood, 152 asked, 0 wrong.

## 0.1.0 (6 October 2026, not yet released)

The first version. Tested with SiCoPR 1.1.1 (commit `55c3f71`, recorded in `SICOPR_REF`).

- **The core.** `core.handle(phrase, project)` turns a phrase and the project state into one PLAN,
  QUESTION or STOP, as a plain dictionary. It never runs COM. Strict mode: parameters are named by
  their COM keyword; a word that cannot be placed asks, and nothing is guessed.
- **The config model.** A COM workbook (`.xlsx`, or `.csv`, or a working config `.json`) is
  imported to a working config. Formula cells become links by keyword name, evaluated without
  `eval`. Changes recompute the links downstream. Each run writes the config SiCoPR reads as a CSV in
  the Reference Code's own format. `Save that config as ...` writes a copy of the source workbook with
  only the changed cells rewritten.
- **Validation** against the parameter schema (269 rows) and 84 rules. The legal releases come from
  SiCoPR's `VERSION.json` when the tool runs.
- **Sweeps and batches.** Counts and step sizes as MATLAB reads them, grids, reuse of earlier runs by
  fingerprint, one question for a batch with points a rule asks about, and `max_new_runs`.
- **Running.** One child process per run, each with its own results folder and `result.json` at full
  precision; `batch_summary.csv` for every sweep.
- **Summaries.** The run summary (with the release emulated), statistics over the last set of runs,
  and a parameter or result against a result (Pearson and slope). Not-a-number results are shown and
  left out of statistics, with the count stated.
- **Project state.** History of every phrase, replay of a stored plan, a pending question, and
  settings from built-in defaults, a user file and a project file.
- **Command line.** `sicopr-assist "phrase"`, or an interactive prompt.
- **Tests.** Standalone scripts run by `tests\run_all.ps1`, including the use-case harness over 842
  rows and the four committed starting workbooks.

Final scoreboard (`SICOPR_ASSIST_FULL=1`), must rows outside the deferred groups: 2267 row and config
pairs; L1 2267/2267, L2 1580/1580, L3 1607/1607, L4 1693/1697 pairs (574 of 575 rows; the miss is
RS07). Paraphrases: 3616, of which 3464 understood, 152 asked, 0 wrong.

Not in this version (STOP with what to do instead): the GUI, the tutor, feedback export, the
dashboard and channel download. See `README.md`.

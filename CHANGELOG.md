# Changelog

Each version starts with a short summary of what a user sees. The details below it say how.

## 0.13.0 (29 October 2026)

Safer channel downloads, a `--json` that a program can read, a tutor that offers only what works now,
plan announcements that match what the plan runs, and the usual files of a public project. The GUI
panel works with a released SiCoPR: 1.2.0 and later have its slot.

- **Channel download is held to the IEEE site.** Only `https://www.ieee802.org` is read, for the tools
  page, every zip and after every redirect (or the one site `SICOPR_ASSIST_FETCH_INDEX` names). A zip
  whose file name is not plain is skipped. A download stops once it passes `max_download_mb` (or the size
  you agreed to), whether or not the server gives a size, and is not retried. A zip that would unpack to
  more than 20 times its size (at least 100 MB, at most 20 GB) or to more than 20000 files, nested zips
  counted, is refused with nothing written.
- **Programs by full path.** Rscript is the newest R under Program Files first, then PATH; the current
  folder is never searched. The file manager (Send feedback) and git (the schema tool) are started by
  their full path. `.sicopr\` gets a `.gitignore` of `*`.
- **`--json` prints one JSON document**, also when a plan runs: the last outcome, with `carried_out`
  (status, run ids, the result lines). The plan and the progress lines go to standard error.
- **Output into a pipe is UTF-8**, so the engine's multiplication sign is no longer mojibake on Windows.
- **`--help` names the `gui` subcommand.**
- **The tutor offers phrases that work now.** With no run yet, `What can I say?` (and the tutor after a
  plan that makes no run) offers only the run itself: the config and channel in the folder, or
  `Run the example.` in an empty folder. A change already in effect is never offered.
- **Plan announcements follow the config the plan runs.** A value already in effect is no step and no
  change line (`COM Pass threshold: 3 -> 3` is gone); it is named once. An override the plan sets again,
  or a config imported again, is no longer announced as kept. A note the import made on the config as it
  was (`MLSE = 1 turns COM_CONTRIBUTION off`) is dropped when the plan's own change makes it untrue.
- **A config JSON named in a phrase runs.** `Run data\thru.s4p with data\config.json.` planned a run but,
  carried out in a new folder, stopped with "no run in this project yet"; after other runs it ran the
  last run's config instead of the JSON. The plan now names the JSON, and the run uses it. This was also
  why an 802.3ck preset after an earlier run announced changes against one config and ran another.
- **Project files.** `CITATION.cff`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), package metadata
  (SPDX licence, classifiers, project links), a `test` extra (`pip install -e ".[test]"` installs
  esprima for the panel's script check), and a source distribution that carries the whole test suite.
  CI runs Python 3.10, 3.12 and 3.14 on Windows and Linux.
- **Documents.** The README, this changelog, `CONTRIBUTING.md` and `docs\GUI_DESIGN.md` (now the current
  design, not its history) are written for a reader outside the project; internal labels are gone from the
  tool's messages and the package's comments.
- Tests: new checks in `tests\test_fetch.py` (with a stand-in server that can redirect and leave out
  Content-Length), `tests\test_dashboard.py`, `tests\test_cli.py`, `tests\test_tutor.py`,
  `tests\test_run.py`, and the new `tests\test_programs.py`; each was shown to fail without its fix. The
  use-case table is unchanged.

## 0.12.3 (29 October 2026): first public release

SiCoPR 1.1.4 or later is required, contributions come as issues, and a preset in a folder with no config
says what to do.

- **Security: SiCoPR 1.1.4 or later is required.** SiCoPR 1.1.3 and earlier evaluated some config cell text
  as Python, so a crafted workbook could run code when SiCoPR-Assist loaded it. SiCoPR 1.1.4 reads every cell
  with a MATLAB-subset evaluator, and SiCoPR-Assist refuses an older SiCoPR with a message that says why.
- **Contributions are issues only.** Pull requests are not accepted (`CONTRIBUTING.md`). `SECURITY.md`
  describes private vulnerability reporting. An issue template asks for the phrase, what was meant and the
  answer.
- **A named-standard preset in a folder with no config.** "Setup a 802.3dj config for C2C and run my
  channels." in a folder holding only channel files gave the strict "could not be placed" question. 802.3dj
  now gets the no-config proposal; 802.3ck gets a STOP that says to put a config in the folder.
- The README's install steps clone both repositories, pin SiCoPR v1.1.4, and say how long a run takes.
- A plan's announcement gives the source of a preset value that is not asked about.
- CI runs with a read-only token.

## 0.12.2 (21 October 2026)

`b_max(2..N_b)` and `b_min(2..N_b)` from the workbook reach the engine again.

- SiCoPR commit `e1651c4` reads these two keywords through a helper with two arguments, which the tool's
  scan of the loader did not know. They dropped out of the import, so the engine took the reference
  defaults (0.2 and -0.2) where the workbook holds 0. The scan now reads such a helper; COM Octave on the
  run CSV gives the values the workbook holds.

## 0.12.1 (21 October 2026)

The 802.3ck presets run in one step, and every preset works on a fresh install.

- **Preset values are not asked about.** A value a preset takes from the standard (802.3ck `b_min(1) = 0.3`
  and the rest) does not trigger rule Q14, so the 802.3ck KR, CR and C2C presets and both 802.3ck C2M runs
  plan in one step. The same value typed by hand is still asked about. The plan says so.
- **The standard's values ship.** COM parameter values from IEEE Std 802.3ck-2022, IEEE P802.3dj/D2.4, the
  IEEE COM 3.70 workbooks and OIF-CEI-05.3 are in `sicopr_assist\data\presets.csv` under the terms of the
  COM configuration workbooks (BSD-3-Clause, Copyright 2025 802-COM Authors), each with its source and
  licence. Nothing whose only source is an OIF member working text ships.
- **No overlay file.** The setting `preset_overlay` is gone; a settings file that still has it warns and
  changes nothing.
- 802.3ck C2M eye height and VEC takes `TDR_W_TXPKG = 1`, the workbook's value, now that SiCoPR 1.1.3 runs it.

## 0.12.0 (21 October 2026)

Translator mode: ask for KR, CR, C2C or C2M, or 802.3ck or 802.3dj, in the words engineers use.

- **Translator mode** (`sicopr_assist\translate.py`; setting `translator`, on by default, and the
  environment override `SICOPR_ASSIST_TRANSLATOR`). When the strict core misses a phrase, a layer of rules
  and presets reads it again and hands the core a phrase it resolves, or asks its own question, or stops. It
  never writes the run CSV, runs the engine or skips validation. A reply to a pending question, an
  out-of-scope request and a value the core refused never reach it. Typos are forgiven in command words only.
- **Words to keywords**: baud rate, pass threshold, SNDR, DFE taps, Rx FFE taps, package A and B, the
  high-loss package, both package tests; references from the project (the 500mm thru, the original thru,
  the other package, the channel I selected); number words. A word with several readings is a question;
  a name one character off a keyword (`DER_O`) is asked about, never corrected.
- **Interface presets** for KR, CR, C2C and C2M in 802.3dj and 802.3ck, each value with its source.
- **Proposals**: about 10% more Rx FFE taps with the counts; the low-power receivers.
- **History and feedback** record what the layer did for every command.
- **Fixes in both modes**: the answer to a validation question on a first run is kept; `in <block>`
  binds per item and a main keyword is never written into a package block; a MATLAB vector written with
  `ones` or `zeros` is written out as the values MATLAB reads; a strict OOXML workbook is a STOP, not a
  traceback; a run in eye height and VEC mode is judged by `VEC Pass threshold` and `EH_min`.
- Also: `Use the selected channels.`, several keywords in one `Show`, `Show the package block <block>.`, and
  a batch summary that says whether COM passes at every point.

## 0.11.0 (19 October 2026)

The GUI panel shows only what SiCoPR's GUI does not.

- The selection line and its button are gone: the Run tab shows the files and options.
- The project folder, Browse and the version are in the Settings fold; the panel's top line is the
  working config's short state.
- A plan is one line that says where its effect can be seen, with its steps behind a details toggle.
- Example phrases show under the command box only while you are new; `What can I say?` always shows them.
- The last three exchanges stay in view; older ones are in the History fold.

## 0.10.0 (18 October 2026)

In the GUI, a run's output goes to SiCoPR's Run tab, and three more phrasings are understood.

- A run the panel carries out streams its lines to the Run tab's Output, with its status line and Stop.
  The panel keeps short replies: the headline result with buttons to the Results tabs, or a batch's table.
- "the current settings", "settings captured", "what I have set up" and "as it is set up" mean the setup
  in the GUI.
- "thru-only and xtalk", "with and without crosstalk" and `Compare thru-only with xtalk` run both cases on
  the same config and THRU, reusing a case already run, and compare them when asked.
- Several sentences that describe one run or batch are one request.

## 0.9.0 (17 October 2026)

The Run tab and the panel work as one.

- A plan that runs COM fills SiCoPR's Run tab: its files, its two options, and the command the panel runs
  (the working config's run CSV). What you change in the Run tab comes back to the panel.
- `Run the command.` (or `Run it.`, `Run what is in the Run tab`) runs exactly that setup, and the Run
  tab's own Run button does the same while the panel has assembled it.
- Output dynamic results makes the run an export run, so its dashboard can be built; `--eye-under-mlse`
  is passed to the engine. Both are part of what decides reuse.
- "dynamic results" means the dashboard; a run named by its id gives that run's dashboard on its own
  config and channels (it used to re-run the last run's channels). "the last config and channels" are
  those of the last run.

## 0.8.0 (10 October 2026)

The selection in SiCoPR's tabs, a clearer command box, and an example that runs from an empty folder.

- The config and the THRU, FEXT and NEXT files picked in SiCoPR's tabs are handed to the core with every
  phrase. "the selected", "the specified" or "the chosen" files, "in the tabs" and "the selection" mean
  them. They run in the roles given in the Run tab, and the role of a file is part of what decides reuse.
- The command box is a three-line text area in its own block, with up to four phrases under it that work
  right now.
- `Run the example.` works from an empty folder: it runs the example setup on a synthetic 400 mm THRU,
  written to `data\example_thru.s4p`, and says that it is not a measured channel.
- Fixed: the command box could not take the focus while SiCoPR still hid the panel; a stopped run counted
  as the last run.

## 0.7.0 (9 October 2026)

The GUI: an Assist panel inside SiCoPR's own GUI (it needs a SiCoPR whose GUI has the panel slot).

- `sicopr-assist gui [folder]` starts SiCoPR's GUI with the panel: the conversation, option buttons, live
  progress with Stop, run summaries with buttons to SiCoPR's Results tabs, and the settings.
- The Config view shows the working config, each changed value tagged with where it came from. An edit
  there is checked as the same value typed in a phrase, and the next command builds on it. Another
  workbook opened there is followed.
- The history records every GUI interaction with its origin.
- Fixed: a run's `inf` and `nan` results broke the page's JSON reader; overrides that need each other are
  validated together when a workbook is followed.

## 0.6.0 (8 October 2026)

Channel download: the newest IEEE P802.3dj channels, downloaded, unpacked and run.

- `Download the latest 802.3dj channels posted and analyze with SiCoPR, both thru-only and xtalk.` reads
  the IEEE P802.3dj tools page, takes the newest zip for the project's interface, downloads and unpacks it
  into `.sicopr\cache\`, pairs each FEXT and NEXT file with its THRU, and runs every channel thru-only and
  with its crosstalk as one batch.
- The page is read as it is written: the interface is the folder of the zip link, the date is the line
  under the link, superseded and "do not use" notes are honoured, and a choice between zips is asked.
- The interface is asked once per project and kept.
- A zip larger than `max_download_mb` asks first; an interrupted download is retried, then stops with
  nothing in the cache; with the site unreachable, cached zips are offered.
- Every path in a zip is checked to stay inside the cache before anything is written.
- `<zip>.inventory.csv` lists every file with its role, its THRU and its SHA-256; a file that cannot be
  paired is asked about; a file that is not Touchstone skips the runs that need it.
- Only `sicopr_assist\fetch.py` touches the network, and only when a download is asked for.

## 0.5.0 (8 October 2026)

The dashboard: SiCoPR's interactive R report on the last run.

- `Now give me the results in a dynamic dashboard.` runs the last run again with the engine's `.mat`
  export (announced as a full COM run, or reused when an export run with the same inputs exists), runs
  Rscript on SiCoPR's `R\com_analysis.R`, and opens the page.
- `Re-run with DER_0 = 1e-4 and show the dashboard.` runs once, with the export, and builds its dashboard.
- With no Rscript the dashboard is a STOP that names the CSV summary of the last run.

## 0.4.0 (7 October 2026)

The tutor, and feedback you can export.

- `What can I say?` lists phrases that work on the config in front of the tool, each checked first.
- The tutor also comes up on its own for a new user, and when several recent phrases were not
  understood, with the nearest phrase that works.
- `Tutor off.` and `Tutor on.` switch it in the project settings.
- `Export feedback.` writes a text file from the history with names masked by default; `Send feedback.`
  also gives the address and opens the folder. Nothing is ever sent by the tool.

## 0.3.1 (7 October 2026)

A path written with `/` is read as a path.

- `Run COM on ch/a_thru1.s4p with data/config.xlsx` kept only the file names. A path with `/`, `\` or
  both is now one path when it ends in a file extension the tool reads.

## 0.3.0 (7 October 2026)

Add crosstalk to a run, and no word is ever dropped.

- `Re-run with crosstalk.` keeps the config, overrides and THRU of the last run and takes the FEXT and
  NEXT files that belong to the THRU: every one in its folder when it is the only THRU there, otherwise
  those whose names match the THRU's.
- A word that means something only inside a clause is asked about when no clause takes it, so
  `Add xtalk files and re-run.` no longer replays the last command.
- `Give me the results summary of the last run.` shows the summary and runs nothing.
- `Re-run thru only` after a crosstalk run runs the THRU alone.

## 0.2.0 (6 October 2026, not released)

Re-run with another channel file, and see what a run is doing.

- `Re-run with data\thru_500mm.s4p` keeps the last run's config and overrides and changes only that
  channel; `FEXT <file>` or `NEXT <file>` adds or replaces an aggressor.
- While a plan runs, the command line prints a status line per step, the engine's own lines and each
  run's time and headline COM; `run.log` keeps them all; `--quiet` hides the engine's lines.

## 0.1.0 (6 October 2026, not released)

The first version: phrases to plans, validated changes, sweeps, runs and summaries.

- `core.handle(phrase, project)` turns a phrase into one PLAN, QUESTION or STOP. Parameters are named by
  their COM keyword; a word that cannot be placed is asked about, and nothing is guessed.
- A COM workbook is imported to a working config, with formula cells kept as links. Each run writes the
  config SiCoPR reads as a CSV in the Reference Code's format. `Save that config as ...` writes a copy of
  the source workbook with only the changed cells rewritten.
- Every value is checked against the parameter schema and 84 rules.
- Sweeps and batches with MATLAB's counts and steps, reuse of earlier runs, and `max_new_runs`.
- One child process per run, with its own results folder; summaries, statistics and correlation.
- History of every phrase, replay, a pending question, and settings files.

# Changelog

## 0.3.0 (7 October 2026, not yet released)

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

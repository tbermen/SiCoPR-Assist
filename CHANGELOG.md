# Changelog

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

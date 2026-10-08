# SiCoPR-Assist

SiCoPR-Assist is a command-line front end for [SiCoPR](https://github.com/tbermen/SiCoPR), the
Python port of the IEEE 802.3 COM Reference Code. You type a phrase such as

```text
Re-run with DER_0 = 1e-4
Re-run the setup, but sweep C_b from 0.1e-4 to 0.5e-4 in 0.5e-5 steps
How does C_b correlate to COM?
```

and the tool answers with exactly one of three outcomes:

| outcome | meaning |
|---|---|
| PLAN | the steps it will carry out, shown before anything runs |
| QUESTION | one question with a short list of options, when the phrase cannot be resolved exactly |
| STOP | a refusal with the reason, when the request is outside what the tool does or would be wrong |

The rule is: resolve exactly, or ask. A parameter is named by its COM keyword, as the config spells
it (case and spaces do not matter). There is no alias table, and nothing is guessed. A mistyped
parameter name is offered back to you as an option, never corrected silently. The tool is
rules-based: there is no language model in this version.

## What it is not

- **It never changes a COM result.** It edits a working copy of your config, hands it to SiCoPR,
  and reports what SiCoPR returns. All of the numbers come from SiCoPR.
- **It is not the authority.** For compliance and anything normative, the IEEE 802.3 COM Reference
  Code is the authority. SiCoPR is a behavioural equivalent of it, and this tool sits on top of
  SiCoPR.
- **It does not diagnose.** It reports run summaries, statistics over a set of runs, and how a
  parameter relates to a result. It does not say why a channel fails.
- It is an independent project. It is not affiliated with IEEE or the 802-COM Authors.

## Every run can be repeated on COM MATLAB

Each run writes the config SiCoPR actually read as `.sicopr\configs\run_NNNN.csv`. That file is in the
Reference Code's own config format: one `keyword,value` row per entry, then each package block
between a `.START,<block>` row and a `.END` row. The Reference Code reads it with `xlsread`, so you can
give the same file to COM MATLAB and repeat the run there. The working config beside it
(`run_NNNN.json`) is this tool's own format and never reaches the engine. Your source workbook is
never written to.

## Install

You need Python 3.10 or later and SiCoPR 1.1.1 or later. SiCoPR is not on PyPI. It is public at
`github.com/tbermen/SiCoPR`; install it from a checkout first, then this package:

```powershell
git clone https://github.com/tbermen/SiCoPR
pip install -e .\SiCoPR
pip install -e .\sicopr_assist          # this repository
```

SiCoPR has to be installed from a checkout, because SiCoPR-Assist reads `VERSION.json` and the
shipped workbooks from SiCoPR's folder. It finds that folder through the environment variable
`SICOPR_REPO` when it is set, and otherwise through the installed `sicopr` module. It only reads
SiCoPR; it never writes there.

The dependencies are numpy, scipy and openpyxl. The only network access in the tool is a channel
download you ask for (see "Channel download"), from the standard library.

## Run it

The project is the folder you run the tool from. Put a COM config workbook and your channel files
there, then:

```powershell
cd C:\work\my_channel
sicopr-assist "Run COM on data\thru.s4p with data\config.xlsx"
sicopr-assist "Re-run with DER_0 = 1e-4"
sicopr-assist "Re-run with data\thru_500mm.s4p"
sicopr-assist "Sweep C_b from 0.1e-4 to 0.5e-4 in 2e-5 steps and run DER_0 at 1e-4 and 2e-4"
sicopr-assist "What's my COM summary statistics for the last set of runs?"
sicopr-assist                            # an interactive prompt; type quit to leave
```

`python -m sicopr_assist "..."` does the same if the `sicopr-assist` script is not on your `PATH`.
`--json` prints the outcome as JSON. `--quiet` is described below. When the answer is a QUESTION, the
next phrase is read as the answer: an option number, the option's text, or `cancel`.

Some things to know:

- A PLAN is shown before it is carried out. Each change is announced with its old and new value,
  and so is every value a formula link moves with it (for example, changing `f_b` moves `f_z`,
  `f_p1`, `f_p2` and others).
- Each value is checked against the parameter schema and 84 rules taken from the Reference Code and
  SiCoPR's loader. A value that would be wrong stops. A value that is legal but unusual asks first.
- A sweep in `X steps` with a whole X of 2 or more is a count of points, both ends included. Any
  other step size follows MATLAB `start:step:end`, so it can stop short of the end; the points are
  announced.
- A point whose loaded parameters, channel files and SiCoPR version equal an earlier run is reused,
  not run again. More new runs than `max_new_runs` asks first.
- Runs go one at a time, each in a child process. `Re-run the last one` replays the stored plan.

### A re-run with another channel file

After a run, a phrase that names a channel file and no config re-runs the last run with that file:
the config of the last run is kept, with every override you made, and only that channel changes
(step `set_channel`). These all mean the same:

```powershell
sicopr-assist "Re-run with data\thru_500mm.s4p"
sicopr-assist "Re-run COM on data\thru_500mm.s4p with the previous config"
sicopr-assist "Re-run with data\thru_500mm.s4p and DER_0 = 1e-4"      # the channel and one change
sicopr-assist "Re-run with FEXT data\fext1.s4p"                        # adds or replaces a FEXT aggressor
```

- The file is taken as written, relative to the project folder. A file name with no folder that is
  not in the project folder is looked for by that exact name in `data\` and in the folder of the
  last run's THRU, and the plan says where it was found.
- A file that does not exist stops, and the last setup is kept.
- The file already in use, unchanged, is a STOP: the results would equal the last run.
- With no run in the project yet there is no config to keep, so the tool asks for one. Name both
  files instead: `Run COM on data\thru.s4p with data\config.xlsx`.
- The channel file's SHA-256 is part of what decides reuse, so a new THRU is a new run, and going
  back to an earlier THRU with the same config reuses that earlier run.

### Adding crosstalk

After a thru-only run, ask for its crosstalk and the tool finds the FEXT and NEXT files that belong to
the THRU in use. The config of the last run, its overrides and its THRU are kept. These all mean the
same:

```powershell
sicopr-assist "Re-run with crosstalk."
sicopr-assist "Add xtalk files and re-run."
sicopr-assist "Re-run last config, but include the matching xtalk files in the simulation."
sicopr-assist "Re-run with the matching FEXT and NEXT files"
```

How the files are chosen:

- Only the folder of the THRU is looked at, and only Touchstone files (`.s4p` and the like).
- A file name is split into words on `_`, `-`, `.` and spaces. A role word is `thru`, `through`,
  `fext`, `next`, `xtalk`, `crosstalk` or `xt`, each with an optional number and an optional letter
  (`FEXT1a`). A file is a FEXT if one of its words is `fext` in that form, a NEXT likewise, and
  otherwise a THRU. Case does not matter.
- If the THRU is the only THRU in its folder, every FEXT and NEXT file there is taken.
- Otherwise the FEXT and NEXT files whose names equal the THRU's name, once the role words are
  removed, are taken. So `..._BPK_1200mm_..._thru1.s4p` takes `..._BPK_1200mm_..._xtalk1_Fext.s4p` to
  `..._xtalk3_Fext.s4p` and `..._xtalk4_Next.s4p` to `..._xtalk7_Next.s4p`, and nothing of the 100 mm or
  1400 mm channels beside it.
- The engine is given the THRU, then the FEXT files, then the NEXT files, each sorted by name, with
  their counts.
- The plan lists every file it took and which of the two rules took it, before anything runs.
- If nothing is found, or the folder holds more than one THRU and no name matches, the tool asks you
  to name the files: `Re-run with FEXT <file> and NEXT <file>`.
- If the last run already had exactly those files, it is a STOP: the results would equal the last run.
- `Re-run thru only` after a crosstalk run runs the THRU alone with the same config.

A word the tool cannot place is never dropped. `Add widget files and re-run.` asks, and nothing runs.

### While a run is going

COM can take several minutes per run. While a plan is carried out, the command line prints:

- one status line as each step starts, such as `step 1 of 5: set_channel: THRU ... -> ...` or
  `step 4 of 5: run_com: run_0002 started` (for a batch, `point 3 of 9` and the values);
- the engine's own progress lines as they arrive, unchanged and indented by four spaces;
- at the end of each run, its elapsed time and headline result, such as
  `run_0002 finished in 4 min 12 s: COM 5.0123 dB`; then the run summary.

The same lines go to `run.log` in the run's folder. `--quiet` leaves out the engine's lines on the
screen and keeps the status lines; `run.log` still holds everything. The lines come from a callback
of `run.carry_out(..., progress=...)`, so a GUI can show them the same way.

### What it writes

Everything goes into `.sicopr\` in the project folder:

| path | what it is |
|---|---|
| `history.jsonl` | one record per phrase: how it was read, the options offered and chosen, and the plan |
| `configs\run_NNNN.json` | the working config of run NNNN |
| `configs\run_NNNN.csv` | the config SiCoPR read for run NNNN (the Reference Code's format) |
| `runs\run_NNNN\` | that run's own results folder: SiCoPR's report, `run.log` (the lines shown while it ran), and `result.json` with every result field at full precision |
| `runs\run_NNNN\run_NNNN_caseNN.mat` | the engine's `.mat` export of a run made for the dashboard, and beside it `run_NNNN_caseNN_report.html` and its `lib\` folder |
| `runs\batch_summary.csv` | one row per point of every sweep or batch |
| `assist.ini` | settings for this project (optional) |

A config is written to a spreadsheet only when you ask, for example
`Save that config as data\config_pkgB.xlsx`. That writes a copy of the source workbook with only the
changed cells rewritten, and it refuses to write over the source.

## Settings

Settings are read from the built-in defaults, then `%USERPROFILE%\.sicopr\assist.ini`, then
`<project>\.sicopr\assist.ini`; a later file wins. A mistyped name, a bad value or an unreadable file
gives a warning and keeps the default, and never stops a run. `Show settings` lists the values in
force and where each one came from. The example file
`sicopr_assist\data\sicopr_assist_settings_example.ini` explains each one.

| setting | default | what it does |
|---|---|---|
| `max_new_runs` | 30 | a sweep or batch with more new runs than this asks first |
| `name_match_cutoff` | 0.8 | how close a mistyped name must be to a keyword to be offered |
| `max_options` | 8 | the most options in one question |
| `min_correlation_points` | 3 | fewer results than this give the pairs and the difference, not a coefficient |
| `tutor_until_commands` | 5 | the tutor shows on its own while the history holds fewer successful commands than this; 0 = never on its own |
| `trouble_misses`, `trouble_window` | 3, 5 | that many misses in the last commands bring the tutor up; `trouble_misses = 0` turns this off |
| `feedback_notice_gap`, `feedback_notice` | 20, on | the line about Export feedback that comes with trouble: at most once in this many commands; off = never |
| `mask_names`, `mask_numbers` | on, off | what Export feedback masks |
| `max_download_mb` | 500 | a channel download larger than this many megabytes asks first |
| `download_retries` | 1 | how many more times an interrupted download is tried before the tool stops |

## The dashboard

`Now give me the results in a dynamic dashboard.` (or `Show the dashboard.`, `plot the results`) builds
SiCoPR's interactive R report on the last run, in three steps:

1. `export_mat` runs the working config of the last run again with the engine's `.mat` export on (the
   command line's `--export-mat`). That is a full COM run, as long as the run it repeats, and the plan
   says so before anything runs. A run that already had the export, with the same inputs, is reused
   instead; a run without it never is.
2. `render_dashboard` runs Rscript on SiCoPR's `R\com_analysis.R` with the `.mat`, from the run's own
   folder. The page `run_NNNN_case01_report.html` and its `lib\` folder are written beside the `.mat`.
3. `open_report` opens the page in the browser, and its path is printed.

`Re-run with DER_0 = 1e-4 and show the dashboard.` runs the change once, with the export on, and builds
the dashboard of that run. A re-run right after a dashboard builds it again.

Rscript is found as SiCoPR's GUI finds it: on PATH, else the newest R in `C:\Program Files\R` (by
version number). R needs the packages R.matlab, plotly and htmltools. With no Rscript the dashboard is a
STOP that names the CSV summary of the last run, so the results can still be read.

## Channel download

```powershell
sicopr-assist "Here's my config spreadsheet at data\config.xls. Download the latest 802.3dj channels posted and analyze with SiCoPR, both thru-only and xtalk."
```

The tool reads the IEEE P802.3dj tools page
(`https://www.ieee802.org/3/dj/public/tools/index.html`), takes the newest zip for the interface of
your project, downloads it, unpacks it, pairs each FEXT and NEXT file with its THRU, and runs every
channel thru-only and with its crosstalk:

1. **The interface** (KR, CR, C2C or C2M) is asked once per project, with what the config file name
   and `RUNTAG` say, and the answer is kept. On the page the interface is the folder of the zip link
   (`tools/KR/`, `tools/CR/`, `c2c/`, `c2m/`).
2. **The zip** is the newest for that interface by the date written under its link. An entry whose
   cell says its files have been superseded is skipped, with every zip in it; a zip whose own link says
   "do not use" is skipped alone. The plan names what was skipped and why. When the newest entry holds
   several zips, or two entries share the newest date, it asks which one.
3. **The size** is the page's where it gives one, else the server's (Content-Length). A zip larger
   than `max_download_mb` asks before it is downloaded.
4. **The download** goes through a partial file in `.sicopr\` and reaches the cache only when it
   arrived whole. An interrupted download is tried again `download_retries` times; if it still fails,
   the tool stops and the cache holds nothing of it.
5. **Unpacking.** Every path in the zip is checked to stay inside the cache before anything is
   written (no `..`, no absolute path); a zip that breaks this is refused and removed. A zip inside
   the zip is unpacked in place. A path longer than the 260 characters Windows allows is warned about.
6. **The inventory** (`<zip>.inventory.csv` beside the unpacked folder) lists every file: THRU, FEXT,
   NEXT or other, the THRU each FEXT and NEXT file belongs to (Decision 19, as for
   `Re-run with crosstalk`), whether it reads as Touchstone, its SHA-256, and the role SiCoPR's
   `benchmark\208_case_4p15p0\channels.csv` gives a file with the same SHA-256. When a FEXT or NEXT
   file cannot be paired with confidence, the tool asks: correct the `thru` column and say
   `continue`, or run thru-only only.
7. **The run matrix** is each THRU thru-only, and with its FEXT and NEXT files. The plan says how
   many runs, how many are new and how many are reused (Decision 6, and `max_new_runs` applies). A
   file that does not read as Touchstone skips the runs that need it, and `batch_summary.csv` says
   why. A zip with no FEXT or NEXT file runs thru-only and says so.

The plan is shown in two parts: first the zip, before anything is downloaded, then, once it is
unpacked, the run matrix, before any run starts. Asked again, a zip that is in the cache is not
downloaded or unpacked again. With the site unreachable, the zips already in the cache for that
interface are offered.

Only the download touches the network (`sicopr_assist\fetch.py`), and only when you ask for one.
`SICOPR_ASSIST_FETCH_INDEX` names another index URL, such as a mirror.

**The channel files are IEEE public-area files.** They are kept in `.sicopr\cache` of your project
for your own use. Do not commit them or redistribute them; this repository holds none of them, and
its tests use small synthetic files written by the tests themselves.

## The tutor

`What can I say?` (or `help`) lists phrases that work on the config in front of the tool, filled with
its own names: a re-run with one change, a re-run with another package block, a sweep over a range, a
sweep over a choice, the dashboard (when Rscript is found), what changed, and the original config
again. Every phrase is first resolved by the
tool itself, as if that config had just been run, and a phrase that would not work is never shown. With
no run yet, the first phrase is the run of the config and the channel file in the folder.

The tutor also comes up on its own:

- after each command while the project history holds fewer than `tutor_until_commands` (5) successful
  commands; a phrase that was not understood then gets the nearest phrase that works, such as
  `Re-run with f_b = <value>` for `halve the baud rate and rerun`;
- when 3 of the last 5 commands were misses (`trouble_misses`, `trouble_window`): a word that could not
  be placed, a phrase that matched nothing, or a question that was cancelled. It shows the nearest
  phrase that works for each one, and at most once in 20 commands a line about Export feedback.
  Misses counted for one showing are not counted again.

`Tutor off.` writes `tutor_until_commands = 0` to the project settings file, and `Tutor on.` removes
that line. Put the line in the user file to keep the tutor away in every new project folder.

## Feedback

`Export feedback.` writes `.sicopr\feedback_<date>.txt`: plain text for you to read and then email
yourself, if you choose. It holds the tool version, counts by outcome and by pattern, every question
with its options and the answer chosen, the phrases that rephrased one that did not work, the words
that could not be placed, the settings that differ from the defaults, and every phrase. It holds no
results, no config values beyond what you typed, and no channel data. Its first lines say what was
masked:

- `mask_names = on` (the default): paths and file names read `<file1>.s4p`, package block names
  `<block1>`, and other names that are not COM keywords `<name1>`. COM keywords and the words the tool
  could not place are kept, because they are what the file is for; read it before sending, since one of
  those words could be a product name.
- `mask_numbers = on`: every number reads `<num>`, with its unit kept.

`Send feedback.` does the same, then prints the address `sicopr_assist.showman405@simplelogin.com`
and the subject `SiCoPR-Assist feedback`, and opens the folder with the file selected. The tool sends
nothing itself and makes no network connection for feedback. You can also open an issue (see
`CONTRIBUTING.md`).

## How it is tested

The behaviour is specified by a table of 859 use cases (`tests\cases\sicopr_use_cases.csv`), written
and checked against SiCoPR before any code; rows were added after the maintainer's first use (CH01 to
CH08, 6 October 2026), his second session (XT01 to XT06 and SM16) and the reading of the IEEE tools
page (F11 and F12, 7 October). Each row gives a phrase, the state of the project before it, and the
expected outcome. The harness runs every row on each starting workbook it applies to (2447 row and
config pairs) and scores four levels:

| level | what is compared |
|---|---|
| L1 | the outcome type |
| L2 | the parameter, block, old and new value of each change, or the points of a sweep |
| L3 | the change written as the run CSV and loaded by SiCoPR's real loader: the loaded fields that moved |
| L4 | the steps of a plan in order, or the options of a question |

The harness never runs COM. The four starting workbooks are committed in `tests\configs\`, so the
whole harness runs from a fresh clone.

```powershell
powershell -ExecutionPolicy Bypass -File tests\run_all.ps1
```

Each `tests\test_*.py` is a standalone script that exits 0 or 1; `run_all.ps1` runs them all and stops
at the first failure. It takes 15 minutes or more, most of it in `test_use_cases.py`.

| variable | effect |
|---|---|
| `SICOPR_REPO` | the SiCoPR checkout to use |
| `SICOPR_ASSIST_FULL=1` | L3 on every pair (default: Case1 and the twelve variants only) |
| `SICOPR_ASSIST_HIDE_CONFIGS=1` | hide the four workbooks: tests that need them print `SKIP:` and exit 0 |
| `SICOPR_ASSIST_E2E=1` | also run real COM end to end on synthetic THRU files: one case with eight changes, then a run and a re-run with a THRU of another length (three runs, about 4 minutes each); and in `test_dashboard.py` a run, then the dashboard phrase with the real Rscript (about 10 minutes) |
| `SICOPR_ASSIST_INPUTS` | where the harness writes `score_use_cases.csv` (default: the temporary folder) |
| `SICOPR_ASSIST_LIVE_FETCH=1` | `test_fetch.py` also reads the real IEEE tools page once: the index and the size of the newest KR zip, not the zip |
| `SICOPR_ASSIST_LIVE_FETCH_ZIP=1` | with the one above, it also downloads that zip into a temporary folder, unpacks it, checks it against SiCoPR's `channels.csv`, and removes it |

No other test touches the network: `tests\test_fetch.py` and the fetch rows of the harness use a
stand-in of the tools page in its own markup, served from 127.0.0.1 (`tests\cases\standin_ieee.py`),
with small zips the tests write.

`python tests\test_use_cases.py --gate G7` prints the scoreboard by group and level, `--gate V1.1`
the tutor and feedback rows, `--gate V2.1` the dashboard rows, and `--gate V3.1` the download rows. The tutor text and the feedback
file, which the four levels do not read, are checked by `tests\test_tutor.py` and
`tests\test_feedback.py`. `tests\test_dashboard.py` carries out dashboard plans with a stand-in COM
child and a stand-in Rscript, so it needs no R. The build scores are in
`CHANGELOG.md`.

## What version 2 adds

Version 2 is being built in phases. The tutor and feedback export (above) are in 0.4.0, the dashboard
in 0.5.0, and channel download in 0.6.0. Still to come:

- **A GUI**, in this repository: a command box that takes the same phrases, with views of the project
  folder, the history, run results and summaries, the pending question as buttons, and the settings.
  It calls the same functions as the command line. Its design comes first, for the maintainer to
  approve.

## What is known to be incomplete

- The use-case table was written against four 802.3dj KR workbooks and twelve variants of one of
  them. Other sheet families are untested.
- A re-run with another channel file replaces one THRU, or one FEXT or NEXT file. When the last run
  had several FEXT (or NEXT) files, naming one of them stops and asks for the whole set with its
  config.
- 214 of the 859 rows (the review list) have an expected detail that is a sentence, not a list of steps or options.
  They are scored at L1 (and L2 and L3 where those apply) and listed for a person to review.
- Four behaviours are assumptions not yet confirmed by the maintainer: matching a typo in an action
  or filler word (`agian` read as `again`, never for a parameter name); the trouble thresholds of
  the tutor (3 misses in the last 5 commands, the feedback line at most once in 20); what a summary prints (count, minimum, maximum, mean, median, standard
  deviation, pass count); and Pearson as the coefficient.
- A THRU whose highest frequency is below `f_b` is run with a warning, as the Reference Code and
  SiCoPR run it (zero-padded with `ZERO_PAD = 1`, else extrapolated).
- A workbook held open in Excel can be read: the tool reads the last saved version. It does not yet
  say that unsaved edits in Excel are left out.
- Whether COM MATLAB's `xlsread` reads a quoted CSV field (a value holding a comma) the way Python's
  `csv` module writes it has not been checked. None of the four workbooks has such a value.
- Full-precision results come from `sicopr._run_com`, whose name marks it as internal to SiCoPR. A
  change to it in SiCoPR would show up in the tests.
- The CI workflow (`.github\workflows\ci.yml`) is untested until the first push.
- The dashboard re-runs COM to get the `.mat` export, because a run made without it has none. Whether
  R has the packages `com_analysis.R` needs is found out only when it runs; a failure is reported and
  the run's results stay.

The build also found:

- A control run of a plain 2-port THRU (`TDR_W_TXPKG = 0`), started while checking rule EN09, did not
  finish within 15 minutes. It was not investigated.
- The channel-download rows of the table were written from a description of the IEEE tools page.
  The page was read on 7 October 2026, and rows F1 and F5 were rewritten and F11 and F12 added from it.
  The page is hand-made HTML: its reader follows the markup of that day (the date line under each
  link, the link folder as the interface, the superseded and do-not-use notes). A change in how the
  page is written may need a change in the reader; the live test (`SICOPR_ASSIST_LIVE_FETCH=1`) shows
  it.
- Channel download pairs FEXT and NEXT files with their THRU only inside one folder of the zip, by
  Decision 19. Files that the rule does not pair get a best guess and a question, not a silent run.
- When a FEXT or NEXT file cannot be paired, the tool asks before anything runs, the thru-only runs
  included; the table says those could go ahead at once.
- Feedback masking recognises a package block name by the package clause it is typed in, by the
  working configs of the project, or by a name written like an identifier. A block name typed where
  the tool cannot place it, and never named anywhere else, is kept as an unplaced word.

## Licence

BSD-3-Clause. See `LICENSE`, and `NOTICE` for the parts that come from elsewhere (parameter
descriptions from the COM Reference Code and workbooks, the four test workbooks, and the spreadsheet
reader and writer).

SiCoPR-Assist was developed with AI coding assistance.

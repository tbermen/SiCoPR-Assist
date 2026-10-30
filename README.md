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

That is strict mode. Translator mode (on by default since 0.12.0) adds a layer of rules and interface
presets in front of it: when the strict reading misses, the layer reads the phrase again with the words
engineers use (baud rate is `f_b`, DFE taps is `N_b`, SNDR is `SNR_TX`, the 500mm thru, the other
package), the interfaces of 802.3dj and 802.3ck (KR, CR, C2C, C2M), and proposals where an amount is
missing (about 10% more Rx FFE taps, the CR host classes, the low-power receivers), and hands the core a
phrase it resolves. The core still validates and plans everything. See *Translator mode* below.

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

You need Python 3.10 or later and SiCoPR 1.1.4 or later. SiCoPR-Assist refuses an older SiCoPR,
because before 1.1.4 SiCoPR evaluated some config cell text as Python (see `SECURITY.md`). The GUI
panel needs SiCoPR 1.2.0 or later. Install SiCoPR from a checkout of `github.com/tbermen/SiCoPR` first,
then this package:

```powershell
git clone --branch v1.2.1 https://github.com/tbermen/SiCoPR
git clone https://github.com/tbermen/SiCoPR-Assist
pip install -e .\SiCoPR
pip install -e .\SiCoPR-Assist
```

A COM run takes a few minutes: about 5 to 10 minutes for an 802.3dj configuration and 1 to 2 minutes for
an 802.3ck one on a current laptop. `sicopr-assist "Run the example."` in an empty folder is a good first
test.

SiCoPR has to be installed from a checkout, because SiCoPR-Assist reads `VERSION.json`, the
shipped workbooks and the GUI from SiCoPR's folder. `pip install sicopr` from PyPI gives the engine
alone, without them, and is not enough for SiCoPR-Assist. It finds that folder through the environment variable
`SICOPR_REPO` when it is set, and otherwise through the installed `sicopr` module. It only reads
SiCoPR; it never writes there.

The dependencies are numpy, scipy and openpyxl. The only network access in the tool is a channel
download you ask for (see "Channel download"), from the standard library.

SiCoPR-Assist is developed and tested on Windows, and the examples here are written for PowerShell. It
also passes its tests in CI on Linux (Python 3.10, 3.12 and 3.14). On Linux or macOS the same steps
read:

```bash
git clone --branch v1.2.1 https://github.com/tbermen/SiCoPR
git clone https://github.com/tbermen/SiCoPR-Assist
pip install -e ./SiCoPR
pip install -e ./SiCoPR-Assist
cd ~/work/my_channel
sicopr-assist "Run COM on data/thru.s4p with data/config.xlsx"
```

A path in a phrase may be written with `/` or `\` on either system.

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

With nothing of your own at hand, `sicopr-assist "Run the example."` works from an empty folder: it runs
the example setup (the working config of the Case1 workbook, shipped with the tool) on a synthetic THRU,
a 400 mm lossy line that it writes to `data\example_thru.s4p` when the plan is carried out. The plan says
that the channel is synthetic and not a measured one. A channel file already in the folder is used
instead. The line model is `sicopr_assist\example_channel.py`; the file is ours, and no IEEE file is
involved.

`python -m sicopr_assist "..."` does the same if the `sicopr-assist` script is not on your `PATH`.
`--json` prints one JSON document on standard output: the outcome, and when a plan was carried out,
what it gave (`carried_out`: status, run ids and the result lines). Everything meant for a person (the
plan, the progress lines) then goes to standard error, so the output can be piped to a JSON reader.
Output into a pipe or a file is written as UTF-8. `--quiet` is described below.
`sicopr-assist --help` lists the options and the `gui` subcommand. When the answer is a QUESTION, the
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
- A point whose loaded parameters, channel files (each in its role: THRU, FEXT or NEXT) and SiCoPR
  version equal an earlier run is reused, not run again. More new runs than `max_new_runs` asks first.
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
- Both cases at once: `Run thru-only and with xtalk and compare results.` (also "with and without
  crosstalk", `Compare thru-only with xtalk`) is a batch of two points on the same config and THRU,
  without and with its crosstalk files. A case already run is reused, so after a crosstalk run only the
  thru-only case runs, and the other way round. "compare" adds the comparison: COM of each case against
  the thru-only one. With no crosstalk file for the THRU, the tool asks you to name the files.

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
| `max_download_mb` | 500 | a channel download larger than this many megabytes asks first, and a download stops once it passes it (or the size you agreed to) |
| `download_retries` | 1 | how many more times an interrupted download is tried before the tool stops |
| `translator` | on | translator mode: the rules-and-presets layer reads a phrase the strict core misses; off = strict mode only |

## Translator mode

With `translator = on` (the default), a phrase the strict core misses is read again by a layer of
rules and presets (`sicopr_assist\translate.py`), which hands the core a phrase it resolves, or asks
its own question, or stops. It never writes the run CSV, runs the engine or skips validation, and it
never reads a reply to a pending question, an out-of-scope request (email, slides, diagnose, convert,
optimise) or a value the core refused. A typo is forgiven in command words only (`Re-reun`, `rn it
agian`), never in a keyword name or a value: `DER_O` is asked about.

- **Words to keywords**: baud rate (`f_b`), pass threshold (`COM Pass threshold`), SNDR (`SNR_TX`),
  DFE taps (`N_b`), Rx FFE pre and post taps, local search off or a full grid (`Local Search = 0`),
  ERL on, package A or B (the class blocks), the class B or high-loss package and both package tests
  (`z_p select`), with vs without xtalk, the interactive R report, what was the COM, did it pass,
  stats on the sweep, sensitive to X. A word with several readings (`Z_c`, `SNR`, trace impedance)
  becomes a question with the candidates.
- **References from the project**: the 500mm thru (a THRU beside the last one with that length in
  its name), the original thru (the first run's), the other package, the channel I selected.
- **Interfaces and standards**: `Setup a 802.3dj config for C2C and run my channels.`,
  `Make it an 802.3ck KR config and re-run.`, `make it a cable config` (the standard of the config in
  view, by `f_b`), `Switch to 802.3ck.` (the interface in view). 802.3dj KR and C2C start from the
  shipped KR workbook; 802.3dj CR asks for the host classes with HL to HL proposed; 802.3dj C2M starts
  from the 802-COM C2M egress template, shipped in `sicopr_assist\data\templates` with its License
  Notice sheet, and is informative margin, not pass or fail. 802.3ck KR, CR and C2C run in one step
  as a plan: a value a preset takes from the standard (such as `b_min(1) = 0.3`) is not asked about by
  rule Q14, while the same value typed by hand still is. 802.3ck C2M asks which run, eye height and VEC
  (with the workbook's `TDR_W_TXPKG = 1`) or a C2C-parameter COM.
- **Proposals**: `Give me more Rx FFE and re-run my setup.` proposes about 10% more taps with the
  counts; `Restrict the receiver equalization to low power.` offers the low-power receivers. Each
  option is a phrase the core resolves.

Every command in translator mode records in the history the wording, whether the strict core missed
it, the rules or preset that fired, the phrase handed to the core, any proposal, and whether you
confirmed, changed or declined it; Export feedback carries them.

**Preset values and their terms.** Every value in `sicopr_assist\data\presets.csv` names its source
(document and table and page, or workbook and cell) and its licence. COM parameter values taken from IEEE
Std 802.3ck-2022, IEEE P802.3dj/D2.4, the IEEE COM 3.70 workbooks and OIF-CEI-05.3 ship under the same
terms as the COM configuration workbooks: BSD-3-Clause, Copyright 2025 802-COM Authors (the License
Notice is in `NOTICE`). The documents themselves are not shipped, and nothing whose only source is an OIF
member working text is. Every preset works on a fresh install; there is no overlay file to set up.

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

Rscript is the newest R in `C:\Program Files\R` (by version number), else the first on PATH. A
program in the current folder is never used, even where Windows would look there first. R needs the packages R.matlab, plotly and htmltools. With no Rscript the dashboard is a
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
   arrived whole. It is stopped once more than `max_download_mb` (or the size you agreed to) has
   arrived, whether or not the server gave a size. An interrupted download is tried again
   `download_retries` times; if it still fails, the tool stops and the cache holds nothing of it.
   Only `https://www.ieee802.org` is read, for the page, every zip and after every redirect, and a zip
   whose file name is not a plain name (letters, digits, `_`, `.` and `-`) is skipped.
5. **Unpacking.** Every path in the zip is checked to stay inside the cache before anything is
   written (no `..`, no absolute path); a zip that breaks this is refused and removed. So is a zip that
   would unpack to more than 20 times its own size (at least 100 MB, at most 20 GB) or to more than
   20000 files, the files of a zip inside it counted. A zip inside the zip is unpacked in place. A path
   longer than the 260 characters Windows allows is warned about.
6. **The inventory** (`<zip>.inventory.csv` beside the unpacked folder) lists every file: THRU, FEXT,
   NEXT or other, the THRU each FEXT and NEXT file belongs to (by name, as for
   `Re-run with crosstalk`), whether it reads as Touchstone, its SHA-256, and the role SiCoPR's
   `benchmark\208_case_4p15p0\channels.csv` gives a file with the same SHA-256. When a FEXT or NEXT
   file cannot be paired with confidence, the tool asks: correct the `thru` column and say
   `continue`, or run thru-only only.
7. **The run matrix** is each THRU thru-only, and with its FEXT and NEXT files. The plan says how
   many runs, how many are new and how many are reused (`max_new_runs` applies). A
   file that does not read as Touchstone skips the runs that need it, and `batch_summary.csv` says
   why. A zip with no FEXT or NEXT file runs thru-only and says so.

The plan is shown in two parts: first the zip, before anything is downloaded, then, once it is
unpacked, the run matrix, before any run starts. Asked again, a zip that is in the cache is not
downloaded or unpacked again. With the site unreachable, the zips already in the cache for that
interface are offered.

Only the download touches the network (`sicopr_assist\fetch.py`), and only when you ask for one.
`SICOPR_ASSIST_FETCH_INDEX` names another index URL, such as a mirror; the site of that URL is then
read as well.

**The channel files are IEEE public-area files.** They are kept in `.sicopr\cache` of your project
for your own use. Do not commit them or redistribute them; this repository holds none of them, and
its tests use small synthetic files written by the tests themselves.

## The tutor

`What can I say?` (or `help`) lists phrases that work on the config in front of the tool, filled with
its own names: a re-run with one change, a re-run with another package block, a sweep over a range, a
sweep over a choice, the dashboard (when Rscript is found), what changed, and the original config
again. Every phrase is first resolved by the
tool itself, as if that config had just been run, and a phrase that would not work is never shown, nor
a change that is already in effect. With no run yet, it offers only the phrase that runs now: the
config and the channel file in the folder, or `Run the example.` in an empty folder. The re-runs,
sweeps and the dashboard come once there is a run.

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

The behaviour is specified by a table of 1050 use cases (`tests\cases\sicopr_use_cases.csv`), written
and checked against SiCoPR before the code, and extended after each round of use. Each row gives a
phrase, the state of the project before it, and the expected outcome; for the rows about the GUI that
state holds what is selected in the GUI's tabs and the Run tab's options, which the harness hands to the
core as data. The harness runs every row on each starting workbook it applies to and scores four
levels:

| level | what is compared |
|---|---|
| L1 | the outcome type |
| L2 | the parameter, block, old and new value of each change, or the points of a sweep |
| L3 | the change written as the run CSV and loaded by SiCoPR's real loader: the loaded fields that moved |
| L4 | the steps of a plan in order, or the options of a question |

The harness never runs COM. The four starting workbooks are committed in `tests\configs\`, so the
whole harness runs from a fresh clone.

To run the tests you need SiCoPR (as in *Install*) and, for `tests\test_gui_static.py`, either Node.js
on PATH or the Python package esprima, which the test extra installs:

```powershell
pip install -e ".\SiCoPR-Assist[test]"
powershell -ExecutionPolicy Bypass -File tests\run_all.ps1
```

On Linux, run each script in turn: `for t in tests/test_*.py; do python "$t" || break; done`.

Each `tests\test_*.py` is a standalone script that exits 0 or 1; `run_all.ps1` runs them all and stops
at the first failure. A full run takes about an hour on a current laptop, most of it in
`test_use_cases.py`; in CI each job takes 30 to 80 minutes.

| variable | effect |
|---|---|
| `SICOPR_REPO` | the SiCoPR checkout to use |
| `SICOPR_ASSIST_FULL=1` | L3 on every pair (default: Case1 and the twelve variants only) |
| `SICOPR_ASSIST_HIDE_CONFIGS=1` | hide the four workbooks: tests that need them print `SKIP:` and exit 0 |
| `SICOPR_ASSIST_E2E=1` | also run real COM end to end on synthetic THRU files: one case with eight changes, then a run and a re-run with a THRU of another length (three runs, about 4 minutes each); and in `test_dashboard.py` a run, then the dashboard phrase with the real Rscript (about 10 minutes) |
| `SICOPR_ASSIST_INPUTS` | where the harness writes `score_use_cases.csv` (default: the temporary folder) |
| `SICOPR_ASSIST_LIVE_FETCH=1` | `test_fetch.py` also reads the real IEEE tools page once: the index and the size of the newest KR zip, not the zip |
| `SICOPR_ASSIST_LIVE_FETCH_ZIP=1` | with the one above, it also downloads that zip into a temporary folder, unpacks it, checks it against SiCoPR's `channels.csv`, and removes it |

No other test touches the network: `tests\test_fetch.py` and the download rows of the harness use a
stand-in of the tools page in its own markup, served from 127.0.0.1 (`tests\cases\standin_ieee.py`),
with small zips the tests write.

`python tests\test_use_cases.py --gate G7` prints the scoreboard by group and level; the docstring of
`test_use_cases.py` lists the other checks it can run on one group of rows. The tutor text and the
feedback file, which the four levels do not read, are checked by `tests\test_tutor.py` and
`tests\test_feedback.py`. `tests\test_dashboard.py` carries out dashboard plans with a stand-in COM
child and a stand-in Rscript, so it needs no R. `tests\test_gui_api.py` drives the GUI panel's API as
SiCoPR's GUI does, with a stand-in child, and `tests\test_gui_static.py` parses the panel's script and
checks its ids, its `[hidden]` rules, its events and the command box; the checks of SiCoPR's real
server routing to the panel print SKIP when the SiCoPR in use has no panel slot.
`tests\test_streamline.py` checks what the panel shows and when. `tests\test_selection.py` checks how
the selection in the GUI's tabs is read and planned, and the example in an empty folder.
`tests\test_programs.py` checks that the programs the tool starts are started by their full path.

## The GUI

SiCoPR-Assist adds a panel on the right of SiCoPR's own GUI, where the same phrases are typed. SiCoPR's
GUI stays the tool, used as without SiCoPR-Assist; the panel is a way to drive it by typing. Its
design is `docs\GUI_DESIGN.md`. It needs a SiCoPR whose GUI has the panel slot (`gui\README.md` of
SiCoPR, *Panels*), which SiCoPR has from 1.2.0. With an older SiCoPR, `sicopr-assist gui` says so and
stops, and SiCoPR-Assist is used from the command line as described above.

```powershell
cd C:\my\project
sicopr-assist gui                    # this folder; opens a browser on http://127.0.0.1:8765
sicopr-assist gui D:\other\project --port 8790 --no-browser
```

It starts SiCoPR's `gui\app.py` with the project folder opened and made the run folder. Starting
SiCoPR's GUI directly also shows the panel, which then opens its Settings and asks for the project folder
(Browse).

- **The panel shows only what the GUI does not.** Under its title (the slot's header) its top line,
  once the project has a working config, is that config's short state (`working config run_0005, 2 overrides`); the project folder, Browse
  and the version are in **Settings**. The conversation shows each phrase with its PLAN, QUESTION or
  STOP, in short: a plan is one line that says where its effect can be seen (`2 changes, highlighted in
  Config`, `running in the Run tab`, `3 points: output in the Run tab`, and `using the Run tab's setup`
  when it ran what the Run tab holds), with its steps and what it announces behind a **details** toggle;
  a question keeps its text and its options as buttons; a stop keeps its reason. The last three
  exchanges stay in view; older ones are in **History**, newest first, one line each that opens to the
  full reply (with every record of the project history folded below them). While a plan runs the panel shows one
  line (`run_0006 running: output in the Run tab`); at the end, the headline result (COM, pass or fail
  against COM Pass threshold) with buttons that show the run in SiCoPR's Results tabs, or for a batch a
  short table, one row per point.
- **A run's output is in the Run tab.** A run the panel carries out streams its lines to the Run tab's
  Output, as a run of the Run tab does: its status line, follow output, and Stop, which stops the
  panel's run. The page shows the Run tab when the run starts, unless you are in the middle of an edit
  in Config, and stays there when it ends; the run is then in the Results tabs. A batch streams every
  point in order, each headed with its point.
- **The command box** is the block at the bottom of the panel, under the label `Type a command`: a text
  area of three lines that grows with what you type. Enter sends, Shift+Enter starts a new line, Up and
  Down recall earlier phrases. While you are new (fewer successful commands than `tutor_until_commands`,
  5) and the box is empty, up to four phrases that work right now are shown under it (`Run the example.`
  in a new project; phrases written with the names of your config after that), and the tutor's examples
  after a plan go there too; a click puts one in the box. After that they show only when you ask:
  `What can I say?`. The block stays in view while the conversation scrolls.
- **The selection in the tabs.** The workbook of the Config tab and the THRU, FEXT and NEXT files
  picked in the Run tab are handed to the core with every phrase; the Run tab shows them, so the panel
  does not. `Run the selected config and channels.` runs exactly those files, in the roles you gave them
  in the Run tab. "the selected", "the specified" or "the chosen" config, channel, channels or files, "in the tabs",
  "the selection" and "what is selected" all mean that selection. After a run,
  `Re-run with the selected channel.` keeps the config and changes only the channel files. With no
  channel picked, the tool asks. On the command line there is no selection, so those phrases ask for
  files.
- **The Run tab is the setup the panel runs.** A plan that runs COM fills SiCoPR's Run tab: its THRU,
  FEXT and NEXT files are selected, Output dynamic results and `--eye-under-mlse` are set as the plan
  runs them, and the command box shows the command the panel runs, which is the working config's run
  CSV (`.sicopr\configs\run_NNNN.csv`) and not the workbook, with a line saying so. The Run tab's own
  controls stay live: what you change there (a file, Output dynamic results, `--eye-under-mlse`) comes
  back into the command and what the panel hands the core, and `Run the command.` (or `Run it.`,
  `Run what is in the Run tab`, `Run the Run tab`) runs exactly that setup through the panel, with
  history and reuse. While the Run tab is assembled this way, its **Run sicopr.py** button does the same
  as `Run the command.`: one history record, the same plan, its output in the Run tab. Output dynamic results
  makes the run an export run (`--export-mat`), and when it ends the run opens in Results, dynamic,
  where its dashboard is built. The two options are part of what decides reuse. On the command line
  there is no Run tab, so `Run the command.` asks (re-run the last run, or cancel). "the current
  settings", "settings captured", "what I have set up" and "as it is set up" mean the same as "the
  command": `Run with current settings.`
- **Results, dynamic.** "dynamic results", "results, dynamic" and "the dynamic results of the last run"
  mean the dashboard (`Show the dynamic results of the last run.`, or of `run_0004` by its id). Opening
  Results, dynamic on a run that has no `.mat` export says so in the panel and offers that phrase.
  "the last config and channels" are the last run's config and channel files: `Re-run last config and
  channel.` with nothing changed since says so and runs nothing.
- **The Config view shows the working config.** Every value that differs from the workbook is shown in
  place with where it came from (`Assist #12`, `edited here #13`, `linked`, `proposed`, `option 2`) and
  the workbook value beside it. SiCoPR's Save as is off while the panel is in use: save the working
  config with `Save that config as data\config_new.xlsx.`
- **An edit in the Config view is taken in** when it is committed (Enter or leaving the field): it is
  checked as the same value typed in a phrase is (`core.edit`), recorded in the history, and the next
  command builds on it. A refused edit stays unsaved in SiCoPR's view and never reaches the working
  config. `Re-run.` after an edit runs the edited config.
- **Another workbook opened in the Config view is followed:** SiCoPR-Assist imports it as the new
  source, keeps the channel files of the last run, and asks once whether to keep your overrides.
- **One COM run at a time** across both: SiCoPR's Run tab is refused while a plan from the panel runs,
  and the panel waits for a Run-tab run. A run started from the Run tab before the panel has assembled it
  (no plan yet) runs the workbook as saved and is not tracked by SiCoPR-Assist; the panel offers the phrase
  that brings it in.
- **Everything the GUI does is in the history** (`.sicopr\history.jsonl`), each record marked
  `origin: gui` with its kind: phrases, answers, edits, workbooks opened, runs started and ended, Stop,
  what was shown, and errors of the panel and the page. The feedback export lists them, masked.

## Changes

What changed in each version is in `CHANGELOG.md`.

## What is known to be incomplete

- The use-case table was written against four 802.3dj KR workbooks and twelve variants of one of
  them. Other sheet families are untested.
- A re-run with another channel file replaces one THRU, or one FEXT or NEXT file. When the last run
  had several FEXT (or NEXT) files, naming one of them stops and asks for the whole set with its
  config.
- 248 of the 1050 rows (the review list) have an expected detail that is a sentence, not a list of steps or options.
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
- The dashboard re-runs COM to get the `.mat` export, because a run made without it has none. Whether
  R has the packages `com_analysis.R` needs is found out only when it runs; a failure is reported and
  the run's results stay.

The build also found:

- A control run of a plain 2-port THRU (`TDR_W_TXPKG = 0`), started while checking rule EN09, did not
  finish within 15 minutes. It was not investigated.
- The channel-download rows of the table were written from a description of the IEEE tools page.
  The page was read on 7 October 2026, and the download rows were rewritten from it.
  The page is hand-made HTML: its reader follows the markup of that day (the date line under each
  link, the link folder as the interface, the superseded and do-not-use notes). A change in how the
  page is written may need a change in the reader; the live test (`SICOPR_ASSIST_LIVE_FETCH=1`) shows
  it.
- Channel download pairs FEXT and NEXT files with their THRU only inside one folder of the zip, by
  name. Files that the rule does not pair get a best guess and a question, not a silent run.
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

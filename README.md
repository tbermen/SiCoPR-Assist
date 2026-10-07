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

The dependencies are numpy, scipy and openpyxl. There is no network access anywhere in the tool.

## Run it

The project is the folder you run the tool from. Put a COM config workbook and your channel files
there, then:

```powershell
cd C:\work\my_channel
sicopr-assist "Run COM on data\thru.s4p with data\config.xlsx"
sicopr-assist "Re-run with DER_0 = 1e-4"
sicopr-assist "Sweep C_b from 0.1e-4 to 0.5e-4 in 2e-5 steps and run DER_0 at 1e-4 and 2e-4"
sicopr-assist "What's my COM summary statistics for the last set of runs?"
sicopr-assist                            # an interactive prompt; type quit to leave
```

`python -m sicopr_assist "..."` does the same if the `sicopr-assist` script is not on your `PATH`.
`--json` prints the outcome as JSON. When the answer is a QUESTION, the next phrase is read as the
answer: an option number, the option's text, or `cancel`.

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

### What it writes

Everything goes into `.sicopr\` in the project folder:

| path | what it is |
|---|---|
| `history.jsonl` | one record per phrase: how it was read, the options offered and chosen, and the plan |
| `configs\run_NNNN.json` | the working config of run NNNN |
| `configs\run_NNNN.csv` | the config SiCoPR read for run NNNN (the Reference Code's format) |
| `runs\run_NNNN\` | that run's own results folder: SiCoPR's report, `run.log`, and `result.json` with every result field at full precision |
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
| `tutor_until_commands`, `trouble_misses`, `trouble_window`, `feedback_notice_gap`, `feedback_notice` | 5, 3, 5, 20, on | version 2 (tutor and trouble detection); read and kept, no effect yet |
| `max_download_mb`, `download_retries` | 500, 1 | version 2 (channel download); read and kept, no effect yet |
| `mask_names`, `mask_numbers` | on, off | version 2 (feedback export); read and kept, no effect yet |

## Feedback

`Send feedback` prints the address and the subject line. Nothing is ever sent by the tool. To tell us
about a phrase it did not understand, email `sicopr_assist.showman405@simplelogin.com` with the subject
`SiCoPR-Assist feedback`, or open an issue (see `CONTRIBUTING.md`).

## How it is tested

The behaviour is specified by a table of 842 use cases (`tests\cases\sicopr_use_cases.csv`), written
and checked against SiCoPR before any code. Each row gives a phrase, the state of the project before
it, and the expected outcome. The harness runs every row on each starting workbook it applies to
(2403 row and config pairs) and scores four levels:

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
| `SICOPR_ASSIST_E2E=1` | also run one real COM case end to end on a synthetic THRU (about 4 minutes) |
| `SICOPR_ASSIST_INPUTS` | where the harness writes `score_use_cases.csv` (default: the temporary folder) |

`python tests\test_use_cases.py --gate G7` prints the scoreboard by group and level. The final build
scores are in `CHANGELOG.md`.

## What version 2 adds

Version 1 answers each of these with a STOP that says it is not in this version and what to do
instead.

- **A GUI**, in this repository: a command box that takes the same phrases, with views of the project
  folder, the history, run results and summaries, the pending question as buttons, and the settings.
  It calls the same functions as the command line.
- **A tutor and trouble detection**: shown while a project is new, or after several phrases in a row
  that the tool could not place.
- **Feedback export**: a plain-text file of your phrases for you to read and email yourself, with
  names masked by default. Nothing is uploaded.
- **A dashboard**: SiCoPR's R report on the last run.
- **Channel download** from the IEEE P802.3dj tools page, with the FEXT and NEXT files paired to their
  THRU.

## What is known to be incomplete

- The use-case table was written against four 802.3dj KR workbooks and twelve variants of one of
  them. Other sheet families are untested.
- 216 of the 842 rows have an expected detail that is a sentence, not a list of steps or options.
  They are scored at L1 (and L2 and L3 where those apply) and listed for a person to review.
- Four behaviours are assumptions not yet confirmed by the maintainer: matching a typo in an action
  or filler word (`agian` read as `again`, never for a parameter name); the trouble thresholds of
  the version 2 tutor; what a summary prints (count, minimum, maximum, mean, median, standard
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

The build also found:

- A control run of a plain 2-port THRU (`TDR_W_TXPKG = 0`), started while checking rule EN09, did not
  finish within 15 minutes. It was not investigated.
- The channel-download rows of the table were written from a description of the IEEE tools page;
  its markup has not been looked at.

## Licence

BSD-3-Clause. See `LICENSE`, and `NOTICE` for the parts that come from elsewhere (parameter
descriptions from the COM Reference Code and workbooks, the four test workbooks, and the spreadsheet
reader and writer).

SiCoPR-Assist was developed with AI coding assistance.

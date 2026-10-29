# Security policy

## What this software is, in security terms

SiCoPR-Assist is a local front end for SiCoPR, the Python port of the IEEE 802.3 COM Reference Code. It
reads COM config workbooks and Touchstone files, writes a run CSV, and starts SiCoPR as a subprocess.
It stores no credentials and sends nothing anywhere.

Three parts are worth knowing about:

- **Config workbooks.** SiCoPR-Assist loads workbooks through SiCoPR's own reader. SiCoPR 1.1.3 and
  earlier evaluated some config cell text as Python, so a crafted workbook could run code when it was
  loaded. SiCoPR 1.1.4 reads every cell with a MATLAB-subset evaluator, and SiCoPR-Assist refuses to run
  with a SiCoPR older than 1.1.4.
- **Channel download.** The one network access is a download you ask for, from the IEEE 802.3 public
  tools page (`fetch.py`, standard library, TLS verified). Every path in a downloaded zip is checked to
  stay inside the cache folder before anything is written.
- **The GUI panel.** It runs inside SiCoPR's GUI, a local HTTP server bound to `127.0.0.1` that refuses
  cross-site and DNS-rebinding requests. It is built for a single local user and should not be exposed to
  a network.

Commands are built as argument lists, never through a shell. The tool never writes into your source
workbook or into SiCoPR's folder.

## Reporting a vulnerability

Open a GitHub issue at https://github.com/tbermen/SiCoPR-Assist/issues.

If you would rather not describe the problem in public, report it privately instead: **Security** tab,
then **Report a vulnerability**
(https://github.com/tbermen/SiCoPR-Assist/security/advisories/new). The report is not public.

There is no bug bounty and no service-level commitment on response time: this is a single-maintainer
project. Reports are read and acted on.

## What is in scope

- Code execution reachable by opening a crafted workbook, Touchstone file, settings file or downloaded zip.
- Anything that reads, writes or executes outside the project folder, the cache, or the folders you named.
- A way for another website to make the GUI panel act.
- A dependency vulnerability that this project's use actually exposes.

## What is not

- A COM result that differs from the Reference Code. That is SiCoPR's correctness, reported to
  https://github.com/tbermen/SiCoPR.
- A phrase the tool did not understand. That is a normal issue (see `CONTRIBUTING.md`).
- Exposing SiCoPR's GUI server to a network and finding it reachable.

## Supported versions

`main` is the release; there are no maintained release branches. Fixes land on `main`.

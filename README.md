# SiCoPR-Assist

SiCoPR-Assist is a front end for [SiCoPR](https://github.com/tbermen/SiCoPR), the Python port of the
IEEE 802.3 COM Reference Code. You type a phrase such as `Re-run with DER_0 = 1e-4`, and the tool
answers with exactly one of three outcomes: a PLAN it will carry out, a QUESTION when the phrase
cannot be resolved exactly, or a STOP with the reason. It is rules-based. It resolves exactly, or it
asks.

It drives SiCoPR and never changes a COM result. For compliance and anything normative, the IEEE
802.3 COM Reference Code is the authority.

**Status: Phase 1 of the build.** The repository, the test fixtures and the scoring harness exist.
The core answers every phrase with a STOP. This README is completed in Phase 7.

## Install

SiCoPR is not on PyPI. Install it from its checkout first, then this package:

```powershell
pip install -e G:\path\to\SiCoPR
pip install -e .
sicopr-assist "anything"
```

SiCoPR is found through the environment variable `SICOPR_REPO` when it is set, otherwise through the
installed `sicopr` module. SiCoPR-Assist only reads it.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File tests\run_all.ps1
```

Each `tests\test_*.py` is a standalone script that exits 0 or 1. The use-case harness
(`tests\test_use_cases.py`) scores the core against the table in `tests\cases\sicopr_use_cases.csv`.
It needs the four starting workbooks in `tests\configs\`; with them absent (or hidden with
`$env:SICOPR_ASSIST_HIDE_CONFIGS = "1"`) it prints `SKIP:` and exits 0.

## Licence

BSD-3-Clause. See `LICENSE`, and `NOTICE` for the parts that come from elsewhere.

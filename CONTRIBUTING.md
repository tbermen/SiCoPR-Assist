# Contributing

## Issues: the phrases it did not understand

The contribution that helps most is an issue that lists the phrases SiCoPR-Assist did not
understand. For each one, please give:

- the phrase exactly as you typed it;
- what you meant by it;
- what the tool answered (the PLAN, QUESTION or STOP it printed; `--json` prints all of it);
- the SiCoPR-Assist and SiCoPR versions (`sicopr-assist --version`, and SiCoPR's `VERSION.json`).

A QUESTION is not a defect in itself: the tool asks whenever a phrase cannot be resolved exactly.
It is worth reporting when the question was not needed, when the right option was missing, or when a
PLAN did something other than what you meant. A wrong PLAN is the most important kind of report.

Leave out anything you may not share, such as file names or values from a proprietary design. If you
would rather not post in public, email the same details to `sicopr_assist.showman405@simplelogin.com` with the subject
`SiCoPR-Assist feedback`.

A difference in a COM result is a matter for SiCoPR, not for this tool: SiCoPR-Assist never computes
or changes a result. Report it to SiCoPR (`github.com/tbermen/SiCoPR`).

## Pull requests

**Pull requests are not accepted.** Contributions come in as issues: a phrase that was not understood,
a wrong plan, a defect, or an idea. If an idea in an issue is right, the maintainer writes the change
from the description and credits the reporter in the commit message. Every line in the repository then
comes from the maintainer, which keeps the licence record simple.

Security reports: see `SECURITY.md`.

For reference, the rules the maintainer follows for a change:

- Follow the use-case table (`tests\cases\sicopr_use_cases.csv`). It is the specification. A row
  that looks wrong is raised in an issue, not edited to make a score pass.
- Every new check must be shown to fail once: break what it guards, watch it fail, then restore it.
- `powershell -ExecutionPolicy Bypass -File tests\run_all.ps1` must end with `All tests passed`.
- New source files carry the two lines `# Copyright 2026 Todd Bermensolo` and
  `# SPDX-License-Identifier: BSD-3-Clause` after the module docstring.
- Plain words and short sentences in messages and documents. No em dashes and no emoji.

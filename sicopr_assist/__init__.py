"""SiCoPR-Assist: a rules-based front end that turns a phrase into a SiCoPR run.

The core is one function, core.handle(phrase, project), which returns a PLAN, a
QUESTION or a STOP as a plain dictionary and never runs COM.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause

__version__ = '0.12.1'

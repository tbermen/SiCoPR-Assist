"""The SiCoPR-Assist panel for SiCoPR's GUI (panel API 1: SiCoPR's gui/README.md, "Panels"; GUI_DESIGN.md).

Registered in pyproject.toml under the entry-point group sicopr.gui_panels, so a SiCoPR GUI with the panel slot shows
it on the right of its page. api.py holds the endpoints as plain functions over the core; static/ holds the page part.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os

from sicopr_assist.panel import api as _api

API = 1
NAME = 'assist'
TITLE = 'SiCoPR-Assist'
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')


def handle(method, path, query, body, host):
    """Answer /panel/assist/api/<path>."""
    return _api.PANEL.handle(method, path, query, body, host)


def busy():
    """None, or a short text while a plan with runs is being carried out (SiCoPR then refuses a Run-tab run)."""
    return _api.PANEL.busy()

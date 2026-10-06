"""The core: handle(phrase, project) -> outcome. Nothing here runs COM.

The outcome is one plain dictionary that can be written as JSON (prompt section 5):

    type       PLAN, QUESTION or STOP
    steps      [{"op": <a name in STEPS>, "args": {...}}, ...]
    changes    [{"json_path", "before", "after", "kind", "applied"}, ...]
    question   {"text", "options"}            QUESTION only
    reason     text                           STOP only
    announce   every line shown before anything runs
    points, new_runs, reused_runs             batches only
    pattern, unplaced                         how the phrase was read; goes to history

Phase 1: the core answers every phrase with a STOP. The parser and planner come in Phase 4.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause

# The step vocabulary, frozen in Phase 1 from the expected_detail chains of the use-case table
# (tests/cases/l4.py extracts it again and tests/test_l4_normaliser.py checks that the two agree).
STEPS = (
    'add_param', 'batch_summary', 'build_matrix', 'clear_overrides', 'compare_config', 'diff_results',
    'download', 'drop_override', 'export_feedback', 'export_mat', 'export_xlsx', 'extract', 'fetch_index',
    'import_config', 'infer_interface', 'inventory', 'list_parameters', 'open_report', 'recompute_linked',
    'render_dashboard', 'result_stats', 'result_vs_param', 'revert_override', 'run_batch', 'run_com',
    'select_zip', 'set_param', 'set_setting', 'show_config', 'show_history', 'show_overrides', 'show_param',
    'show_settings', 'show_tutor', 'summarize', 'validate_config', 'validate_inputs',
)

OUTCOME_TYPES = ('PLAN', 'QUESTION', 'STOP')
CHANGE_KINDS = ('set', 'add', 'linked', 'revert')


def outcome(kind, **fields):
    """An outcome with every key present, so the scorer and the history never meet a missing key."""
    if kind not in OUTCOME_TYPES:
        raise ValueError('outcome type must be one of %s, not %r' % (', '.join(OUTCOME_TYPES), kind))
    out = {'type': kind, 'steps': [], 'changes': [], 'announce': [], 'points': [], 'new_runs': 0,
           'reused_runs': 0, 'pattern': '', 'unplaced': []}
    if kind == 'QUESTION':
        out['question'] = {'text': '', 'options': []}
    if kind == 'STOP':
        out['reason'] = ''
    out.update(fields)
    return out


def handle(phrase, project):
    """Turn one phrase and the project state into a PLAN, a QUESTION or a STOP. Never runs COM."""
    return outcome('STOP', reason='SiCoPR-Assist does not understand phrases yet: this is the Phase 1 '
                                  'skeleton, which answers every phrase with a STOP.',
                   pattern='stub', unplaced=str(phrase).split())

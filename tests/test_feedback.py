"""Feedback export (Decision 10; rows FB01 to FB08, FB15 to FB17; gate V1.2).

V1.2: a history seeded with paths, file names, block names and numbers exports with none of them in clear under
the masks that cover them: mask_names on hides every path, file name and block name; mask_numbers on hides every
number as well; with both off everything is in clear. The file's first lines say which masks were applied.

Then: what the file holds (counts by outcome and pattern, questions with options and answers, rephrase pairs,
unplaced words, limits that differ) and what it does not (results, config values that were not typed); Send
feedback gives the address and subject and opens the folder through the opener it is given, and sends nothing;
the address is kept in one constant; no history is a STOP; a bad mask setting keeps names masked.

    python tests\\test_feedback.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402

# what a user might type that names their own things (paths, files, blocks) and their values (numbers)
TYPED = [
    'Run COM on D:\\acme\\falcon_rev2\\thru.s4p with D:\\acme\\cfg_falcon.xlsx',
    'Re-run with package PKG_AcmeBGA',
    'Re-run with C_d = [0.4e-4 0.9e-4] in PKG_AcmeBGA',
    'Re-run with data/ch/b300_thru1.s4p',
    'Run COM on thru_lane7.s4p with falcon_cfg.csv',
    'Re-run with PKG_NAME = PKG_LowR_CLASSA PKG_Module',
    'Re-run with DER_0 = 2.5e-4 and SNR_TX = 31.75',
]
PATHS = ['D:\\acme\\falcon_rev2\\thru.s4p', 'falcon_rev2', 'acme', 'cfg_falcon', 'b300_thru1', 'data/ch',
         'thru_lane7', 'falcon_cfg']
BLOCKS = ['PKG_AcmeBGA', 'AcmeBGA', 'PKG_LowR_CLASSA', 'PKG_Module', 'PKG_HiR_CLASSB']
NUMBERS = ['0.4e-4', '0.9e-4', '2.5e-4', '31.75']
RESULT = 7.654321                                   # a made-up COM that must never reach the file
SECRET_RESULT = '7.654321'


def seed(fx, ctx, settings=None):
    """A run (so the blocks of the config are known) and the typed phrases as history records, one of them a
    question whose options name files and a block, answered."""
    import prior_states
    from sicopr_assist.project import history_record
    n = ctx.numbers()
    n['channel_operating_margin_dB'] = RESULT
    prior_states.seed_run(ctx, numbers=n)
    p = ctx.project
    for ph in TYPED:
        p.append_history(history_record(phrase=ph, pattern='seeded', outcome='PLAN', status='ok'))
    q = p.append_history(history_record(phrase='Re-run with the other thru file', pattern='rerun; ask other',
                                        outcome='QUESTION', status='question', unplaced=['other'],
                                        options=['data\\thru_2.s4p', 'data\\thru_3.s4p', 'PKG_AcmeBGA', 'cancel']))
    p.append_history(history_record(phrase='1', pattern='answer: data\\thru_2.s4p', outcome='PLAN', status='ok',
                                    chosen='data\\thru_2.s4p', answers=q['seq']))
    if settings:
        prior_states.project_settings(ctx, *settings)


def export(ctx, phrase='Export feedback.'):
    from sicopr_assist import core, run
    o = core.handle(phrase, ctx.project)
    opened = []
    done = run.carry_out(ctx.project, o, open_folder=lambda path: opened.append(path))
    step = next(s for s in o['steps'] if s['op'] == 'export_feedback')
    with open(os.path.join(ctx.root, *re.split(r'[\\/]', step['args']['path'])), encoding='utf-8') as f:
        text = f.read()
    return o, done, opened, text


def body(text):
    """The file without its first lines, which name the masks and the address."""
    return text.split('\n\n', 1)[1]


def gate_v12(fx):
    import prior_states
    cases = (('names on, numbers off (the default)', None, PATHS + BLOCKS, NUMBERS, 'masks: names masked, numbers not '
              'masked'),
             ('names on, numbers on', ['mask_numbers = on'], PATHS + BLOCKS + NUMBERS, [], 'masks: names and numbers '
              'masked'),
             ('names off, numbers on', ['mask_names = off', 'mask_numbers = on'], NUMBERS, PATHS[:1] + BLOCKS[:1],
              'masks: numbers masked, names not masked'),
             ('names off, numbers off', ['mask_names = off'], [], PATHS[:1] + BLOCKS[:1] + NUMBERS,
              'masks: nothing masked'))
    for name, settings, hidden, clear, head in cases:
        ctx = prior_states.Ctx(fx, 'Case1')
        seed(fx, ctx, settings)
        o, done, opened, text = export(ctx)
        b = body(text)
        leaked = [s for s in hidden if s.lower() in b.lower()]
        missing = [s for s in clear if s not in b]
        check('V1.2 %s: nothing it covers is in clear, the rest is, and the first lines say so' % name,
              not leaked and not missing and text.split('\n')[1] == head,
              'in clear: %s; masked though not covered: %s; line 2: %r' % (leaked, missing, text.split('\n')[1]))
        fx.remove_project(ctx.root)
    # one placeholder per distinct thing, the extension kept, keywords and unplaced words kept (row FB05)
    ctx = prior_states.Ctx(fx, 'Case1')
    seed(fx, ctx, ['mask_numbers = on'])
    _, _, _, text = export(ctx)
    check('FB05/FB16: <file1>.s4p and <file2>.xlsx, <block1> for the same block each time, C_d = [<num> <num>], '
          'keywords and the unplaced word kept',
          'Run COM on <file1>.s4p with <file2>.xlsx' in text and text.count('<block1>') >= 3 and
          'Re-run with C_d = [<num> <num>] in <block1>' in text and 'DER_0 = <num> and SNR_TX = <num>' in text and
          'Re-run with the other thru file' in text, text[-1200:])
    fx.remove_project(ctx.root)


def content_checks(fx):
    import l4
    import prior_states
    from sicopr_assist import core
    rows = l4.load_table()
    by = {}
    for r in rows:
        by.setdefault(r['id'], []).append(r)

    def built(rid):
        row = by[rid][0]
        ctx = prior_states.Ctx(fx, 'Case1', row, by)
        prior_states.build(row['prior_state'], ctx)
        return ctx

    # a history made through the core: a question cancelled, then a phrase that works, a miss, an answered question
    ctx = built('PH12')
    for ph in ('halve the baud rate and rerun', 'cancel', 'Re-run with f_b = 53.125.', 'Re-run with zp select 2',
               'z_p select', 'xyzzy the frobnicator'):
        core.handle(ph, ctx.project)
    prior_states.project_settings(ctx, 'max_new_runs = 12')
    o, done, opened, text = export(ctx)
    hist = ctx.project.read_history()
    q = next(h for h in hist if h['phrase'] == 'halve the baud rate and rerun')
    r = next(h for h in hist if h['phrase'] == 'Re-run with f_b = 53.125.')
    check('FB02: the phrase after a cancelled question is recorded as its rephrase', r['rephrase_of'] == q['seq'],
          [(h['seq'], h['phrase'], h['rephrase_of']) for h in hist])
    want = ['outcomes: PLAN', 'patterns (count, pattern):', 'questions (', 'halve the baud rate and rerun | options: f_b',
            'answer: cancel', 'Re-run with zp select 2 | options: z_p select', 'answer: z_p select',
            'rephrase pairs (', 'halve the baud rate and rerun  ->  Re-run with f_b = 53.125.',
            'words that could not be placed', '  1  halve', '  1  frobnicator',
            'limits that differ from the defaults: max_new_runs = 12', 'SiCoPR-Assist %s' % __import__('sicopr_assist').__version__]
    check('FB04: the file holds the version, counts, questions with options and answers, rephrase pairs, unplaced '
          'words with counts and the limits that differ', all(w in text for w in want),
          [w for w in want if w not in text])
    leak = ('106.25', '(now', 'channel_operating_margin', 'thru.s4p')
    check('FB04: no results and no config value that was not typed (COM, f_b 106.25 and the other current values '
          'the options showed, the THRU path of the run)', not [w for w in leak if w in body(text)],
          [w for w in leak if w in body(text)])
    check('FB04: nothing is opened and nothing sent for Export feedback; the path is shown',
          not opened and any('feedback written to' in ln for ln in done['lines']), done['lines'])
    fx.remove_project(ctx.root)

    ctx = built('FB06')
    n = ctx.numbers()
    n['channel_operating_margin_dB'] = RESULT
    prior_states.seed_run(ctx, numbers=n)
    o, done, opened, text = export(ctx, 'Send feedback.')
    c = core.feedback_contact()
    check('FB06: Send feedback writes the file, gives the address and the subject, opens its folder, sends nothing',
          o['type'] == 'PLAN' and [s['op'] for s in o['steps']] == ['export_feedback'] and
          'email that file to %s' % c['address'] in done['lines'] and 'subject: %s' % c['subject'] in done['lines']
          and len(opened) == 1 and os.path.isfile(opened[0]) and SECRET_RESULT not in text, (done['lines'], opened))
    fx.remove_project(ctx.root)
    for ph in ('email my history to the developer', 'how do I send feedback', 'make a feedback file',
               'export my history for the developer'):
        ctx = built('FB06')
        o = core.handle(ph, ctx.project)
        check('FB04/FB06 paraphrase %r: the export plan' % ph,
              o['type'] == 'PLAN' and [s['op'] for s in o['steps']] == ['export_feedback'] and not o['unplaced'],
              (o['type'], o.get('reason'), o['unplaced']))
        fx.remove_project(ctx.root)

    ctx = built('FB07')
    o = core.handle('Export feedback.', ctx.project)
    check('FB07: no history is a STOP that says there is nothing to export',
          o['type'] == 'STOP' and 'nothing to export' in o['reason'], o.get('reason'))
    fx.remove_project(ctx.root)

    ctx = built('FB17')
    o, done, opened, text = export(ctx)
    check('FB17: mask_names = maybe warns, and names stay masked',
          any('mask_names = maybe is not on or off' in a for a in o['announce']) and
          text.split('\n')[1] == 'masks: names masked, numbers not masked', (o['announce'], text.split('\n')[1]))
    fx.remove_project(ctx.root)

    srcs = {os.path.basename(p): open(p, encoding='utf-8').read() for p in glob.glob(os.path.join(ROOT, 'sicopr_assist',
                                                                                                   '*.py'))}
    holders = sorted(n for n, s in srcs.items() if 'simplelogin' in s)
    check('Decision 10: the address is held in one constant, core.FEEDBACK_ADDRESS', holders == ['core.py'] and
          srcs['core.py'].count('simplelogin') == 1, holders)


def main():
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; the feedback checks need them')
        return 0
    with fixtures.Fixtures() as fx:
        gate_v12(fx)
        content_checks(fx)
    finish()


if __name__ == '__main__':
    sys.exit(main())

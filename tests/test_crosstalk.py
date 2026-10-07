"""After the maintainer's second session (7 October): adding crosstalk, and no word dropped.

    python tests\\test_crosstalk.py

N3     the matching rule of Decision 19 on file lists in the naming styles it covers: the akinwale style
       (<name>_thru1, <name>_xtalkN_Fext, <name>_xtalkN_Next), the lane-named style of row XT02 (x_thru_Tx7_to_Rx7,
       x_FEXT_Tx5_to_Rx7), FEXT1a, through and xt, upper and lower case. Then a run through the runner, with a
       stand-in child that records its arguments: the engine gets the THRU, the FEXT files, then the NEXT files,
       with their counts.
drop   no phrase shape drops a word. A known word that means something only inside a clause (crosstalk, package,
       tx, three, back, ...) and that no clause took is unplaced and asked about. Checked on the reader for every
       such word in several phrase shapes, and on the core: the phrase with the word never gives the same PLAN as
       the phrase without it (the maintainer's "Add xtalk files and re-run." once replayed the last command).
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402
from sicopr_assist import core, parse, run  # noqa: E402
from sicopr_assist.project import Project  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]

# the akinwale folder of the maintainer: seven THRUs, each with three FEXT and four NEXT files named after it
AKINWALE = []
for mm in (100, 300, 500, 700, 1200, 1400, 1600):
    stem = 'Tx_NPC_250mm_32AWG_BPK_%dmm_27AWG_BPK_250mm_32AWG_NPC_Rx' % mm
    AKINWALE += [stem + '_thru1.s4p'] + [stem + '_xtalk%d_Fext.s4p' % k for k in (1, 2, 3)] + \
        [stem + '_xtalk%d_Next.s4p' % k for k in (4, 5, 6, 7)]


def ndrop_words():
    """The known words that carry meaning only inside a clause: not filler, not an action word."""
    return sorted(w for w in parse.KNOWN_WORDS if w not in parse.FILLER and w not in parse.ACTION_WORDS)


def n3_rule():
    m = core.match_crosstalk('Tx_NPC_250mm_32AWG_BPK_1200mm_27AWG_BPK_250mm_32AWG_NPC_Rx_thru1.s4p', AKINWALE)
    s = 'Tx_NPC_250mm_32AWG_BPK_1200mm_27AWG_BPK_250mm_32AWG_NPC_Rx'
    check('N3: akinwale style, seven THRUs: the 1200 mm THRU gets its own 3 FEXT and 4 NEXT files, by name',
          m['rule'] == 'name' and m['fext'] == [s + '_xtalk%d_Fext.s4p' % k for k in (1, 2, 3)]
          and m['next'] == [s + '_xtalk%d_Next.s4p' % k for k in (4, 5, 6, 7)], m)
    m = core.match_crosstalk('Tx_NPC_250mm_32AWG_BPK_100mm_27AWG_BPK_250mm_32AWG_NPC_Rx_thru1.s4p', AKINWALE)
    check('N3: 100 mm is not 1200 mm or 1400 mm: only the files of the 100 mm THRU',
          len(m['fext']) == 3 and len(m['next']) == 4 and all('_BPK_100mm_' in n for n in m['fext'] + m['next']), m)
    lane = ['x_thru_Tx7_to_Rx7.s4p', 'x_FEXT_Tx5_to_Rx7.s4p', 'x_FEXT_Tx8_to_Rx7.s4p', 'x_FEXT_Tx6_to_Rx7.s4p',
            'x_NEXT_Tx8_to_Tx7.s4p', 'x_NEXT_Tx7_to_Rx7.s4p', 'notes.txt']
    m = core.match_crosstalk('x_thru_Tx7_to_Rx7.s4p', lane)
    check('N3: lane-named style (XT02), the only THRU in its folder: every FEXT and NEXT there, sorted by name',
          m['rule'] == 'only_thru' and m['fext'] == ['x_FEXT_Tx5_to_Rx7.s4p', 'x_FEXT_Tx6_to_Rx7.s4p',
                                                     'x_FEXT_Tx8_to_Rx7.s4p']
          and m['next'] == ['x_NEXT_Tx7_to_Rx7.s4p', 'x_NEXT_Tx8_to_Tx7.s4p'], m)
    letters = ['ch5_THRU.s4p', 'ch5_FEXT1a.s4p', 'ch5_FEXT1b.s4p', 'ch5_NEXT2.s4p', 'ch6_THRU.s4p', 'ch6_FEXT1a.s4p',
               'ch6_NEXT2.s4p']
    m = core.match_crosstalk('ch5_THRU.s4p', letters)
    check('N3: FEXT1a and FEXT1b are FEXT files with a number and a letter, matched by name',
          m['fext'] == ['ch5_FEXT1a.s4p', 'ch5_FEXT1b.s4p'] and m['next'] == ['ch5_NEXT2.s4p'], m)
    mixed = ['Lane3_Thru.S4P', 'lane3_xt1_fext.s4p', 'LANE3-XT2-NEXT.s4p', 'lane4_through.s4p', 'lane4_fext.s4p']
    m = core.match_crosstalk('Lane3_Thru.S4P', mixed)
    check('N3: upper and lower case, through, xt and - as a separator',
          m['fext'] == ['lane3_xt1_fext.s4p'] and m['next'] == ['LANE3-XT2-NEXT.s4p'], m)
    check('N3: a file is a FEXT or a NEXT only by a whole word: nextgen_thru is a THRU, next1b_x is a NEXT',
          core.channel_kind('nextgen_thru.s4p') == 'thru' and core.channel_kind('a_next1b_x.s4p') == 'next'
          and core.channel_kind('a_fext12.s4p') == 'fext' and core.channel_kind('a_fextend.s4p') == 'thru')
    m = core.match_crosstalk('b300_thru1.s4p', ['b300_thru1.s4p', 'b500_thru1.s4p', 'c700_xtalk1_Fext.s4p'])
    check('N3: two THRUs and no name that matches: nothing is taken (the core then asks, row XT05)',
          m['rule'] == 'name' and not m['fext'] and not m['next'], m)
    m = core.match_crosstalk('thru.s4p', ['thru.s4p'])
    check('N3: the only THRU and no crosstalk file: nothing is taken (row XT03)',
          m['rule'] == 'only_thru' and not m['fext'] and not m['next'], m)


def n3_run(fx):
    """The runner gives the engine the THRU, the FEXT files and the NEXT files, with their counts."""
    p = Project(fx.project('Case1'))
    names = [n for n in AKINWALE if '_BPK_1200mm_' in n or '_BPK_300mm_' in n]
    for n in names:
        fixtures.link_or_copy(fx.thru, os.path.join(p.root, 'ch', n))
    thru = os.path.join('ch', 'Tx_NPC_250mm_32AWG_BPK_1200mm_27AWG_BPK_250mm_32AWG_NPC_Rx_thru1.s4p')
    out = core.handle(r'Run COM on %s with data\config.xlsx' % thru, p)
    run.carry_out(p, out, child=STANDIN)
    argv = os.path.join(tempfile.mkdtemp(), 'argv.jsonl')
    os.environ['SICOPR_ASSIST_STANDIN_ARGV'] = argv
    try:
        out = core.handle('Add xtalk files and re-run.', p)
        done = run.carry_out(p, out, child=STANDIN) if out['type'] == 'PLAN' else {'run_ids': []}
    finally:
        del os.environ['SICOPR_ASSIST_STANDIN_ARGV']
    got = [json.loads(line) for line in open(argv, encoding='utf-8')] if os.path.exists(argv) else []
    a = got[0] if len(got) == 1 else []
    fx_ = [os.path.join(p.root, 'ch', n) for n in names if '_BPK_1200mm_' in n and n.endswith('_Fext.s4p')]
    nx_ = [os.path.join(p.root, 'ch', n) for n in names if '_BPK_1200mm_' in n and n.endswith('_Next.s4p')]
    i = a.index('--thru') if '--thru' in a else 0
    norm = lambda xs: [os.path.normcase(os.path.abspath(x)) for x in xs]  # noqa: E731
    check('N3: one new run, and the child is given --thru THRU --fext 3 files --next 4 files, in that order',
          len(done['run_ids']) == 1 and len(a) > i + 11 and a[i] == '--thru'
          and norm(a[i + 1:i + 2]) == norm([os.path.join(p.root, thru)])
          and a[i + 2] == '--fext' and norm(a[i + 3:i + 6]) == norm(fx_)
          and a[i + 6] == '--next' and norm(a[i + 7:i + 11]) == norm(nx_) and a[i + 11] == '--fingerprint', a)
    res = p.read_result(done['run_ids'][0]) if done['run_ids'] else {}
    check('N3: the result names the channels in that order with their roles (THRU, 3 FEXT, 4 NEXT)',
          [c['role'] for c in res.get('channels') or []] == ['thru'] + ['fext'] * 3 + ['next'] * 4, res.get('channels'))
    rec = p.read_history()[-1]
    check('N3: the history record holds the eight channels, so a replay runs the same set',
          [c['role'] for c in rec.get('channels') or []] == ['thru'] + ['fext'] * 3 + ['next'] * 4)
    out = core.handle('Re-run with crosstalk.', p)
    check('N3 (XT04): the same request again is a STOP, nothing changed', out['type'] == 'STOP', out.get('steps'))
    out = core.handle('Re-run the last one.', p)
    done = run.carry_out(p, out, child=STANDIN) if out['type'] == 'PLAN' else {'run_ids': []}
    check('N3: a replay of the crosstalk run is reused, not run again (same channels, same config)',
          out['type'] == 'PLAN' and done['run_ids'] == [rec['run_ids'][0]], (out['type'], done['run_ids']))
    out = core.handle('Re-run thru only.', p)
    done = run.carry_out(p, out, child=STANDIN) if out['type'] == 'PLAN' else {'run_ids': []}
    check('N3: thru only after it goes back to the THRU alone (the first run is reused)',
          out['type'] == 'PLAN' and done['run_ids'] == ['run_0001'], (out.get('question'), done['run_ids']))


def n3_questions(fx):
    """Nothing to take: the question says which of the two cases it is (rows XT03 and XT05) and offers the same
    options."""
    p = Project(fx.project('Case1'))
    for n in ('b300_thru1.s4p', 'b500_thru1.s4p', 'c700_xtalk1_Fext.s4p', 'c700_xtalk4_Next.s4p'):
        fixtures.link_or_copy(fx.thru, os.path.join(p.root, 'ch2', n))
    run.carry_out(p, core.handle(r'Run COM on ch2\b300_thru1.s4p with data\config.xlsx', p), child=STANDIN)
    o = core.handle('Re-run with crosstalk.', p)
    check('N3 (XT05): two THRUs and no name that matches asks, and says the folder holds more than one THRU',
          o['type'] == 'QUESTION' and 'more than one THRU' in o['question']['text']
          and o['question']['options'] == ['name the files', 'cancel'], o.get('question'))
    p.clear_pending()
    q = Project(fx.project('Case1'))
    run.carry_out(q, core.handle(r'Run COM on data\thru.s4p with data\config.xlsx', q), child=STANDIN)
    o = core.handle('Re-run with crosstalk.', q)
    check('N3 (XT03): the only THRU and no crosstalk file asks, and says no FEXT or NEXT file belongs to it',
          o['type'] == 'QUESTION' and 'No FEXT or NEXT file belongs to' in o['question']['text']
          and o['question']['options'] == ['name the files', 'cancel'], o.get('question'))


SHAPES = ('{w} and re-run.', 'Add {w} files and re-run.', 'Re-run with {w}.', 'Re-run, but with the {w} files added',
          'Same setup, but with the {w}')


def strip_word(phrase, w):
    return ' '.join(t for t in phrase.replace('{w}', '').split())


def read_fields(o):
    return {k: o[k] for k in ('actions', 'sets', 'sweeps', 'packages', 'files', 'attempts', 'flags', 'edits')}


def no_drop_reader(names, blocks):
    words = ndrop_words() + ['fext', 'next', 'widget']
    bad = []
    for w in words:
        for shape in SHAPES:
            with_w = parse.read(shape.format(w=w), names, blocks)
            without = parse.read(strip_word(shape, w), names, blocks)
            placed = any(u.lower() == w for u in with_w['unplaced'])
            if not placed and read_fields(with_w) == read_fields(without):
                bad.append(shape.format(w=w))
    check('drop: on the reader, %d words in %d shapes: each is unplaced or changes how the phrase is read'
          % (len(words), len(SHAPES)), not bad, bad[:20])
    o = parse.read('Add xtalk files and re-run.', names, blocks)
    check('drop: the maintainer\'s phrase 14 is read as a re-run with crosstalk', 'crosstalk' in o['flags']
          and o['actions'] == ['rerun'] and not o['unplaced'], o)
    o = parse.read('Add widget files and re-run.', names, blocks)
    check('drop: widget is unplaced (row XT06)', 'widget' in o['unplaced'] and 'crosstalk' not in o['flags'], o)
    o = parse.read('Give me the results summary of the last run.', names, blocks)
    check('drop: "the last run" is a run already made, not a request to run (row SM16)',
          'run' not in o['actions'] and 'last_run' in o['flags'], o)


def no_drop_core(fx):
    """On a project with a finished run, a phrase with the word never gives the same PLAN as without it."""
    p = Project(fx.project('Case1'))
    out = core.handle(r'Run COM on data\thru.s4p with data\config.xlsx', p)
    run.carry_out(p, out, child=STANDIN)

    def plan_of(phrase):
        o = core.handle(phrase, p)
        p.clear_pending()
        return o['type'], [(s['op'], json.dumps(s.get('args'), sort_keys=True)) for s in o['steps']]
    bad = []
    words = ndrop_words() + ['fext', 'next', 'widget']
    for w in words:
        for shape in SHAPES:
            a = plan_of(shape.format(w=w))
            if a[0] == 'PLAN' and a == plan_of(strip_word(shape, w)):
                bad.append(shape.format(w=w))
    check('drop: on the core, %d words in %d shapes: none gives the PLAN the phrase gives without it'
          % (len(words), len(SHAPES)), not bad, bad[:20])


def main():
    n3_rule()
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks are absent or hidden; the run and core checks need them')
        finish()
    with fixtures.Fixtures(variants=False) as fx:
        wc = fx.working_config('Case1')
        ctx_names = core.Context(Project(fx.project('Case1'))).names(wc)
        no_drop_reader(ctx_names, list(wc['packages']))
        n3_run(fx)
        n3_questions(fx)
        no_drop_core(fx)
    finish()


if __name__ == '__main__':
    main()

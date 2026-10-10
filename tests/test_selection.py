"""After the maintainer's first GUI session (10 October): the selection in the tabs, and the example in an empty folder.

    python tests\\test_selection.py
    $env:SICOPR_ASSIST_E2E = "1"; python tests\\test_selection.py      also gate V6.4: one real COM run of the example

read       the forms of Decision 20 are read as the selection (the selected, the specified, the chosen config,
           channel, channels or files; in the tabs; the selection; what is selected), and nothing near them is: a
           selection word alone, or beside a word that is not one of the forms, is left unplaced and asked about
           (Rule 4).
core       the selection is data handed to core.handle: paths as the GUI holds them are read as a phrase would name
           them; the maintainer's two phrases give the plan of the row's own phrase; a selected file that is not on
           disk stops; with a working config the config is kept and only the channels change, including what was
           done in the Config view since the last run (the state the maintainer was in).
run        with a stand-in child that records its arguments: the engine is given the files in the roles they were
           selected in, whatever their names say; Re-run with the selected channel keeps the config.
example    Decision 22: Run the example. in a folder with no channel file writes the synthetic THRU when the plan is
           carried out, and not before; a channel file already there is used instead; the line model has one
           implementation, and no .s4p file is in the repository.
V6.4       end to end through the real engine, only when SICOPR_ASSIST_E2E=1 (otherwise SKIP).
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402
from sicopr_assist import core, example_channel, parse, run, summary  # noqa: E402
from sicopr_assist.project import Project  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
SL01 = 'Run the selected config and channel.'
MAINTAINER = ('Run on the config and channels specified in the tabs.', 'Run the config and channel specified.')
BOTH, CHANNEL, CONFIG = ['sel_channel', 'sel_config'], ['sel_channel'], ['sel_config']
FORMS = [
    (SL01, BOTH), ('Run the selected config and channels.', BOTH), (MAINTAINER[0], BOTH), (MAINTAINER[1], BOTH),
    ('Run what is selected', BOTH), ("Run what's selected in the tabs", BOTH), ('Run the selection', BOTH),
    ('Run COM on the selected files', BOTH), ('Run the chosen config and the chosen channels', BOTH),
    ('Run the config and channels in the tabs', BOTH), ('Run the specified config', CONFIG),
    ('Re-run with the selected channel.', CHANNEL), ('Re-run with the channel selected in the tabs', CHANNEL),
    ('Re-run with the chosen channels', CHANNEL),
]
# near the forms and not one of them: every word stays where it was, so strict mode asks
NOT_FORMS = ['Run the selected', 'Run selected', 'Run the selected stuff', 'Run the config and channels',
             'Run the specified widget', 'Run it in the tabs', 'Run the selected file', 'Run the chosen one',
             'Run the channel', 'Run the selection of widgets']


def read_forms():
    bad = []
    for phrase, want in FORMS:
        o = parse.read(phrase)
        if 'selection' not in o['flags'] or sorted(f for f in o['flags'] if f.startswith('sel_')) != want \
                or o['unplaced'] or o['attempts']:
            bad.append((phrase, o['flags'], o['unplaced']))
    check('read: the %d forms of Decision 20 are read as the selection, with what they name, and no word left over'
          % len(FORMS), not bad, bad)
    bad = []
    for phrase in NOT_FORMS[:8]:
        o = parse.read(phrase)
        if 'selection' in o['flags'] or not o['unplaced']:
            bad.append((phrase, o['flags'], o['unplaced']))
    for phrase in NOT_FORMS[8:]:
        o = parse.read(phrase)
        if not o['unplaced']:
            bad.append((phrase, o['flags'], o['unplaced']))
    check('read: a selection word outside those forms is left unplaced, so it is asked about and never guessed',
          not bad, bad)
    a, b = parse.read('Re-run with DER_0 = 1e-4', ['DER_0']), parse.read('Re-run with DER_0 = 1e-4 in the tabs', ['DER_0'])
    check('read: "in the tabs" alone is not the selection', 'selection' not in b['flags'] and b['unplaced'] and
          a['sets'] == b['sets'], (b['flags'], b['unplaced']))


def steps_of(o):
    return [(s['op'], json.dumps(s.get('args') or {}, sort_keys=True)) for s in o.get('steps') or []
            if s['op'] != 'show_tutor']


def fresh(fx, label='Case1'):
    return Project(fx.project(label))


def sel_of(p, thru=None, fext=(), nxt=(), config='config.xlsx'):
    """The selection as SiCoPR's GUI holds it: absolute paths, forward slashes."""
    full = lambda n: os.path.join(p.root, 'data', n).replace(os.sep, '/')      # noqa: E731
    return {'config': full(config) if config else None, 'thru': full(thru) if thru else None,
            'fext': [full(n) for n in fext], 'next': [full(n) for n in nxt]}


def core_checks(fx):
    # the selection is read as a phrase would name the files
    p = fresh(fx)
    typed = core.handle(os.path.join('Run COM on data', 'thru.s4p') + ' with ' + os.path.join('data', 'config.xlsx'), p)
    plans = {}
    for phrase in (SL01,) + MAINTAINER:
        q = fresh(fx)
        plans[phrase] = core.handle(phrase, q, selection=sel_of(q, 'thru.s4p'))
    want = steps_of(plans[SL01])
    check('core: the selected config and channel run as the same files named in a phrase would (the roles given)',
          plans[SL01]['type'] == 'PLAN' and typed['type'] == 'PLAN'
          and [op for op, _ in want] == [op for op, _ in steps_of(typed)]
          and plans[SL01]['steps'][0]['args']['path'] == typed['steps'][0]['args']['path']
          and plans[SL01]['steps'][1]['args'] == typed['steps'][1]['args']
          and plans[SL01]['steps'][2]['args'].get('roles') == ['thru'], (want, steps_of(typed)))
    check('core (V6.2): the maintainer\'s two phrases give the plan of row SL01, step for step with the same arguments',
          all(plans[m]['type'] == 'PLAN' and steps_of(plans[m]) == want for m in MAINTAINER),
          [(m, plans[m]['type'], (plans[m].get('question') or {}).get('text')) for m in MAINTAINER])
    q = fresh(fx)
    handed = sel_of(q, 'thru.s4p')
    core.handle(MAINTAINER[0], q, selection=handed, origin='gui')
    core.handle('What can I say?', q, selection=handed, origin='gui')
    recs = q.read_history()
    kept = (recs[0].get('detail') or {}).get('selection') or {}
    check('core: the record of a phrase that spoke of the selection keeps what was selected then, and no other record '
          'does', kept.get('config') == os.path.join('data', 'config.xlsx')
          and kept.get('thru') == os.path.join('data', 'thru.s4p') and kept.get('fext') == [] and kept.get('next') == []
          and not recs[1].get('detail'), (recs[0].get('detail'), recs[1].get('detail')))
    said = ' '.join(plans[SL01]['announce'])
    check('core: the plan announces the config and the channel file taken from the selection in the tabs',
          'selected in the tabs' in said and os.path.join('data', 'config.xlsx') in said
          and 'THRU: ' + os.path.join('data', 'thru.s4p') in said, plans[SL01]['announce'][:4])

    # nothing is guessed
    q = fresh(fx)
    o = core.handle(SL01, q, selection=sel_of(q, 'gone.s4p'))
    check('core: a selected channel file that is not on disk is a STOP that names it', o['type'] == 'STOP'
          and 'gone.s4p' in o['reason'] and 'does not exist' in o['reason'] and not o['steps'],
          o.get('reason') or o['type'])
    q = fresh(fx)
    o = core.handle(SL01, q, selection=sel_of(q, 'thru.s4p', config=None))
    check('core: a selection with a channel and no config asks, and offers the Config tab', o['type'] == 'QUESTION'
          and o['question']['options'] == [core.SELECT_IN_CONFIG_TAB, core.NAME_A_FILE, core.CANCEL],
          o.get('question') or o['type'])
    q = fresh(fx)
    o = core.handle('Sweep DER_0 from 1e-5 to 1e-4 in 3 steps on the selected channel', q, selection=sel_of(q, 'thru.s4p'))
    check('core: the selection beside another request asks, says that a selection is run on its own, and plans '
          'nothing', o['type'] == 'QUESTION' and o['question']['options'] == [core.CANCEL]
          and 'on its own' in o['question']['text'] and not o['steps'] and not o['points'],
          o.get('question') or o['type'])
    q = fresh(fx)
    o = core.handle('Re-run with the selected channel.', q, selection=sel_of(q, 'thru.s4p'))
    check('core: Re-run with the selected channel with no run yet asks, as a re-run with a file named does (row CH05)',
          o['type'] == 'QUESTION' and o['question']['options'] == ['the example setup', 'provide files'],
          o.get('question') or o['type'])

    # with a working config: the config is kept and only the channels change
    p = fresh(fx)
    first = core.handle(os.path.join('Run COM on data', 'thru.s4p') + ' with ' + os.path.join('data', 'config.xlsx')
                        + ' with DER_0 = 1e-4', p)
    run.carry_out(p, first, child=STANDIN)
    fixtures.link_or_copy(fx.thru_of(300.0), os.path.join(p.root, 'data', 'thru2.s4p'))
    same = core.handle(SL01, p, selection=sel_of(p, 'thru.s4p'))
    check('core: the selection of the last run again, with nothing changed, is a STOP (as row CH07)',
          same['type'] == 'STOP' and 'nothing changed' in same['reason'], same.get('reason') or same['type'])
    o = core.handle(SL01, p, selection=sel_of(p, 'thru2.s4p'))
    ops = [op for op, _ in steps_of(o)]
    check('core: after a run, the selected config and channel keep the working config with its override and change '
          'only the THRU', o['type'] == 'PLAN' and ops == ['set_channel', 'validate_inputs', 'validate_config',
                                                           'run_com', 'summarize']
          and 'import_config' not in ops and any('DER_0' in a for a in o['announce']), (ops, o['announce'][:3]))
    done = run.carry_out(p, o, child=STANDIN)
    rec = p.read_history()[-1]
    wc = p.read_working_config(done['run_ids'][0]) if done['run_ids'] else {'main': {}}
    check('core: carried out, the new run holds the override of the last run and the selected THRU',
          wc['main'].get('DER_0') == 1e-4 and [c['path'] for c in rec.get('channels') or []]
          == [os.path.join('data', 'thru2.s4p')] and [o_['json_path'] for o_ in rec.get('overrides') or []]
          == ['/main/DER_0'], (wc['main'].get('DER_0'), rec.get('channels'), rec.get('overrides')))

    # the state the maintainer was in: a workbook opened in the Config view (an open record), no run since
    p = fresh(fx, 'Case1')
    first = core.handle(os.path.join('Run COM on data', 'thru.s4p') + ' with ' + os.path.join('data', 'config.xlsx'), p)
    run.carry_out(p, first, child=STANDIN)
    other = os.path.join(p.root, 'data', 'case3.xlsx')
    fixtures.link_or_copy(fx.configs['Case3'], other)
    fixtures.link_or_copy(fx.thru_of(300.0), os.path.join(p.root, 'data', 'thru2.s4p'))
    opened = core.edit(p, [], source=other)
    sel = sel_of(p, 'thru2.s4p', config='case3.xlsx')
    outs = [core.handle(m, p, selection=sel) for m in MAINTAINER[:1]]
    p.clear_pending()
    o = outs[0]
    ops = [op for op, _ in steps_of(o)]
    check('core: after a workbook was opened in the Config view, the maintainer\'s phrase runs that working config on '
          'the selected channel', opened['type'] == 'PLAN' and o['type'] == 'PLAN'
          and ops == ['set_channel', 'validate_inputs', 'validate_config', 'run_com', 'summarize']
          and 'config view' in ' '.join(o['announce']), (opened['type'], o['type'], ops, o.get('question')))
    done = run.carry_out(p, o, child=STANDIN) if o['type'] == 'PLAN' else {'run_ids': []}
    rec = p.read_history()[-1]
    check('core: carried out, the run uses the workbook opened in the view and the selected THRU',
          len(done['run_ids']) == 1 and (rec.get('source') or {}).get('path', '').endswith('case3.xlsx')
          and [c['path'] for c in rec.get('channels') or []] == [os.path.join('data', 'thru2.s4p')],
          (done.get('run_ids'), rec.get('source'), rec.get('channels')))


def run_checks(fx):
    """The engine is given the files in the roles they were selected in, whatever their names say."""
    p = fresh(fx)
    # three files of different content, named against the roles they are selected in
    names = {'a_Next.s4p': fx.thru_of(300.0), 'b_Fext.s4p': fx.thru_of(500.0), 'c_plain.s4p': fx.thru_of(600.0)}
    for n, src in names.items():
        fixtures.link_or_copy(src, os.path.join(p.root, 'data', n))
    sel = sel_of(p, 'thru.s4p', fext=['a_Next.s4p'], nxt=['b_Fext.s4p', 'c_plain.s4p'])
    out = core.handle('Run the selected config and channels.', p, selection=sel)
    argv = os.path.join(tempfile.mkdtemp(), 'argv.jsonl')
    os.environ['SICOPR_ASSIST_STANDIN_ARGV'] = argv
    try:
        done = run.carry_out(p, out, child=STANDIN) if out['type'] == 'PLAN' else {'run_ids': []}
    finally:
        del os.environ['SICOPR_ASSIST_STANDIN_ARGV']
    got = [json.loads(line) for line in open(argv, encoding='utf-8')] if os.path.exists(argv) else []
    a = got[0] if len(got) == 1 else []
    i = a.index('--thru') if '--thru' in a else 0
    base = lambda xs: [os.path.basename(x) for x in xs]  # noqa: E731
    check('run: the child is given --thru THRU --fext the selected FEXT --next the selected NEXT files, by the roles '
          'of the selection and not by their names', len(done['run_ids']) == 1 and len(a) > i + 7
          and a[i] == '--thru' and base(a[i + 1:i + 2]) == ['thru.s4p'] and a[i + 2] == '--fext'
          and base(a[i + 3:i + 4]) == ['a_Next.s4p'] and a[i + 4] == '--next'
          and base(a[i + 5:i + 7]) == ['b_Fext.s4p', 'c_plain.s4p'], a)
    rec = p.read_history()[-1]
    check('run: the history record holds the roles as selected, so a replay runs the same set',
          [(os.path.basename(c['path']), c['role']) for c in rec.get('channels') or []]
          == [('thru.s4p', 'thru'), ('a_Next.s4p', 'fext'), ('b_Fext.s4p', 'next'), ('c_plain.s4p', 'next')],
          rec.get('channels'))
    again = core.handle('Re-run.', p)
    done2 = run.carry_out(p, again, child=STANDIN) if again['type'] == 'PLAN' else {'run_ids': []}
    check('run: a replay of that run is reused, not run again', done2['run_ids'] == done['run_ids'],
          (again['type'], done2['run_ids']))
    # the role is part of what decides reuse: the same files with a FEXT and a NEXT changed over are another run
    swapped = sel_of(p, 'thru.s4p', fext=['b_Fext.s4p'], nxt=['a_Next.s4p', 'c_plain.s4p'])
    o = core.handle('Run the selected config and channels.', p, selection=swapped)
    done_s = run.carry_out(p, o, child=STANDIN) if o['type'] == 'PLAN' else {'run_ids': []}
    rec = p.read_history()[-1]
    check('run: the same files selected in other roles are a new run, never the reuse of the run made before',
          o['type'] == 'PLAN' and len(done_s['run_ids']) == 1 and done_s['run_ids'] != done['run_ids']
          and [(os.path.basename(c['path']), c['role']) for c in rec.get('channels') or []]
          == [('thru.s4p', 'thru'), ('b_Fext.s4p', 'fext'), ('a_Next.s4p', 'next'), ('c_plain.s4p', 'next')],
          (o['type'], o.get('reason'), done_s['run_ids'], rec.get('channels')))
    # the aggressors of the selection replace those of the last run (one set_channel step for them)
    sel2 = sel_of(p, 'thru.s4p', fext=['b_Fext.s4p'])
    o = core.handle('Re-run with the selected channels', p, selection=sel2)
    done3 = run.carry_out(p, o, child=STANDIN) if o['type'] == 'PLAN' else {'run_ids': []}
    rec = p.read_history()[-1]
    check('run: Re-run with the selected channels replaces the aggressors of the last run and keeps its config',
          o['type'] == 'PLAN' and [s['op'] for s in o['steps']][:2] == ['set_channel', 'validate_inputs']
          and o['steps'][0]['args'].get('role') == 'crosstalk'
          and [(os.path.basename(c['path']), c['role']) for c in rec.get('channels') or []]
          == [('thru.s4p', 'thru'), ('b_Fext.s4p', 'fext')] and len(done3['run_ids']) == 1,
          (o['type'], rec.get('channels')))


def example_checks(fx):
    root = tempfile.mkdtemp(prefix='sicopr_assist_example_')
    p = Project(root)
    target = os.path.join(root, core.EXAMPLE_THRU)
    out = core.handle('Run the example.', p)
    ops = [s['op'] for s in out['steps'] if s['op'] != 'show_tutor']
    said = ' '.join(out['announce'])
    check('example (EX01): in an empty folder Run the example. is a PLAN on a synthetic THRU, announced as synthetic '
          'and not a measured channel', out['type'] == 'PLAN'
          and ops == ['import_config', 'validate_inputs', 'run_com', 'summarize'] and 'synthetic' in said
          and 'not a measured channel' in said and core.EXAMPLE_THRU in said and 'example setup' in said,
          (out['type'], ops, out['announce'][:2], out.get('question')))
    check('example: planning writes nothing in the project folder but the history (the file is written when the plan '
          'is carried out)', not os.path.exists(target) and sorted(os.listdir(root)) == ['.sicopr'], os.listdir(root))
    lines = []
    done = run.carry_out(p, out, child=STANDIN, progress=lambda k, t: lines.append(t)) if out['type'] == 'PLAN' \
        else {'run_ids': [], 'status': None}
    info = core.touchstone_info(target) if os.path.isfile(target) else {'problem': 'not written'}
    check('example: carried out, data\\example_thru.s4p is written, reads as a 4-port Touchstone file up to 67 GHz, '
          'and the run completes on it', done.get('status') == 'ok' and len(done['run_ids']) == 1
          and info.get('problem') is None and info.get('ports') == 4 and abs(info['fmax'] - 67e9) < 1
          and any('synthetic' in ln and 'example_thru.s4p' in ln for ln in lines), (done, info, lines[:3]))
    rec = p.read_history()[-1]
    check('example: the run is recorded on that file, as its THRU', [(c['path'], c['role']) for c in
                                                                    rec.get('channels') or []]
          == [(core.EXAMPLE_THRU, 'thru')], rec.get('channels'))
    ref = os.path.join(tempfile.mkdtemp(), 'ref.s4p')
    example_channel.write(ref)
    with open(ref, 'rb') as f, open(target, 'rb') as g:
        check('example: the file is the 400 mm line of example_channel.write, byte for byte', f.read() == g.read()
              and example_channel.LENGTH_MM == 400.0)
    before = os.path.getmtime(target)
    again = core.handle('Run the example.', p)
    check('example: with a channel file in the folder the example uses it, as row R1 does, and writes nothing',
          again['type'] == 'PLAN' and 'example_channel' not in again['steps'][0]['args']
          and again['steps'][1]['args']['channels'] == [core.EXAMPLE_THRU] and os.path.getmtime(target) == before,
          (again['type'], again['steps'][:2]))
    p2 = fresh(fx)
    o = core.handle('Run the example.', p2)
    check('example: a folder that holds one channel file runs the example on it (row R1 unchanged)',
          o['type'] == 'PLAN' and o['steps'][1]['args']['channels'] == [os.path.join('data', 'thru.s4p')]
          and 'synthetic' not in ' '.join(o['announce']), o['steps'][:2])

    # one implementation of the line model, and no channel file in the repository
    make = fixtures.make_s4p()
    defs = []
    for folder, _, names in os.walk(ROOT):
        if any(part in folder for part in ('.git', '__pycache__', '.egg-info')):
            continue
        for n in names:
            if n.endswith('.py'):
                text = io.open(os.path.join(folder, n), encoding='utf-8').read()
                if re.search(r'^def tline_s\(', text, re.M):
                    defs.append(os.path.relpath(os.path.join(folder, n), ROOT))
    check('example: the line model has one implementation, in sicopr_assist\\example_channel.py; make_s4p.py hands it on',
          make.write is example_channel.write and make.tline_s is example_channel.tline_s
          and defs == [os.path.join('sicopr_assist', 'example_channel.py')], defs)
    try:
        tracked = subprocess.run(['git', '-C', ROOT, 'ls-files'], capture_output=True, text=True, timeout=60)
        files = tracked.stdout.splitlines() if tracked.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        files = None
    if files is None:
        print('SKIP: no git checkout here, so the tracked files were not searched for channel files')
    else:
        check('example: no channel file is in the repository (Rule 8)',
              not [f for f in files if parse.CHANNEL_EXT.search(f)], [f for f in files if parse.CHANNEL_EXT.search(f)])
    return root


def v64():
    if os.environ.get('SICOPR_ASSIST_E2E', '') != '1':
        print('SKIP: V6.4 end to end runs only with SICOPR_ASSIST_E2E=1 (one real COM run of the example setup, '
              'about 5 to 10 minutes)')
        return
    root = tempfile.mkdtemp(prefix='sicopr_assist_v64_')
    p = Project(root)
    check('V6.4: the temp folder is empty', os.listdir(root) == [], os.listdir(root))
    out = core.handle('Run the example.', p)
    check('V6.4: Run the example. in an empty folder is a PLAN', out['type'] == 'PLAN',
          out.get('reason') or out.get('question'))
    t0 = time.time()
    lines = []
    done = run.carry_out(p, out, progress=lambda kind, text: lines.append(text)) if out['type'] == 'PLAN' else \
        {'run_ids': [], 'status': None}
    took = time.time() - t0
    target = os.path.join(root, core.EXAMPLE_THRU)
    check('V6.4: the synthetic THRU was written to data\\example_thru.s4p', os.path.isfile(target)
          and core.touchstone_problem(target) is None, os.listdir(root))
    rid = done['run_ids'][0] if done['run_ids'] else None
    res = p.read_result(rid) if rid else {}
    com = (res.get('cases') or [{}])[0].get(summary.COM_FIELD)
    check('V6.4: the COM run completes on it (%s, %.0f s, COM %r dB)' % (rid, took, com),
          done.get('status') == 'ok' and res.get('status') == 'complete' and isinstance(com, float),
          res.get('message') or lines[-3:])
    check('V6.4: the result names the synthetic THRU as its only channel',
          [os.path.basename(c['path']) for c in res.get('channels') or []] == ['example_thru.s4p'], res.get('channels'))
    print('V6.4: COM %s dB in %.0f s; %d progress lines; summary: %s' % (com, took, len(lines), done.get('lines', [])[:3]))


def main():
    read_forms()
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks are absent or hidden; the core and run checks need them')
        finish()
    with fixtures.Fixtures(variants=False) as fx:
        os.environ.update(fx.r_env())             # the tutor's examples are then the same on every machine
        core_checks(fx)
        run_checks(fx)
        example_checks(fx)
        v64()
    finish()


if __name__ == '__main__':
    main()

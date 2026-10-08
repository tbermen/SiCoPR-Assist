"""Project state: the history of Decision 9 and replay, Send feedback (Decision 10), and
gate G5.3 (no network import anywhere in the package). No workbook is needed: the working
config of a seeded run is the shipped example.

  - every phrase is recorded with its pattern, unplaced words, options offered, the option chosen, and the
    resolved outcome; an answer names the record it answers, and a new phrase over an open question names the
    question it replaces; a cancel is recorded as cancelled
  - nothing but the history line and a pending question is written at plan time
  - Re-run the last one replays the stored plan of the last run, not a new reading of its phrase (row S1); a
    channel file of that run that is gone asks, with the files there as options; with no history it asks (S3)
  - What did I run last? shows the last command, its inputs, its overrides and its result folders (S2)
  - Send feedback (version 2, Decision 10): with no history a STOP; otherwise the export plan, which writes
    nothing at plan time and gives the address and subject when carried out; the address is one constant
  - no module under sicopr_assist imports urllib, http, socket, smtplib, ftplib or requests

    python tests\\test_session.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
from sicopr_assist import core, project as P  # noqa: E402

PACKAGE = os.path.join(ROOT, 'sicopr_assist')
NETWORK = ('urllib', 'http', 'socket', 'smtplib', 'ftplib', 'requests')
STORED_STEPS = ['set_param', 'validate_config', 'run_com', 'summarize']


def network_imports(folder=PACKAGE):
    """[(file, line, module)] for every import of a network module, or a dynamic import of one by name."""
    out = []
    for dirpath, _, files in os.walk(folder):
        for n in sorted(files):
            if not n.endswith('.py'):
                continue
            path = os.path.join(dirpath, n)
            with open(path, encoding='utf-8') as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    names = [node.module]
                elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str) and (
                            (isinstance(node.func, ast.Name) and node.func.id == '__import__') or
                            (isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')):
                    names = [node.args[0].value]
                for m in names:
                    if m.split('.')[0] in NETWORK:
                        out.append((os.path.relpath(path, ROOT), node.lineno, m))
    return out


def ops(o):
    """The steps of a plan without the show_tutor step the tutor adds on its own at the end (Decision 11)."""
    st = list(o['steps'])
    if st and st[-1]['op'] == 'show_tutor' and (st[-1].get('args') or {}).get('why') in ('new', 'trouble'):
        st = st[:-1]
    return [x['op'] for x in st]


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class Place:
    def __enter__(self):
        self.home = tempfile.mkdtemp(prefix='sicopr_assist_home_')
        self.root = tempfile.mkdtemp(prefix='sicopr_assist_proj_')
        self.old = os.environ.get('SICOPR_ASSIST_HOME')
        os.environ['SICOPR_ASSIST_HOME'] = self.home
        self.project = P.Project(self.root)
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop('SICOPR_ASSIST_HOME', None)
        else:
            os.environ['SICOPR_ASSIST_HOME'] = self.old
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def seed_run(self, phrase='Re-run with DER_0 = 1e-4.', steps=STORED_STEPS):
        """One finished run: the shipped example as its working config, a THRU file, a result and its record."""
        p = self.project
        with open(core.EXAMPLE, encoding='utf-8') as f:
            wc = json.load(f)
        rid = p.next_run_id()
        p.write_working_config(rid, wc)
        os.makedirs(os.path.join(self.root, 'data'), exist_ok=True)
        thru = os.path.join(self.root, 'data', 'thru.s4p')
        with open(thru, 'w', encoding='utf-8') as f:
            f.write('# GHz S MA R 50\n')
        chans = [{'path': os.path.join('data', 'thru.s4p'), 'sha256': sha(thru), 'role': 'thru'}]
        p.write_result(rid, P.result_record(run_id=rid, status='complete', channels=chans, cases=[{'COM': 3.1}]))
        ov = [{'json_path': '/main/DER_0', 'before': 0.0002, 'after': 0.0001, 'kind': 'set'}]
        p.append_history(P.history_record(
            phrase=phrase, pattern='seeded', outcome='PLAN', status='ok', overrides=ov,
            plan={'type': 'PLAN', 'steps': [{'op': s, 'args': {}} for s in steps]}, channels=chans,
            working_config=p.relative(p.working_config_path(rid)), run_ids=[rid]))
        return rid

    def history(self):
        return self.project.read_history()


def main():
    found = network_imports()
    check('G5.3: no module under sicopr_assist imports %s' % ', '.join(NETWORK), not found, found)

    with Place() as pl:
        o = core.handle('Re-run.', pl.project)
        h = pl.history()
        check('S3: with no history, a re-run asks (the example setup, provide files)',
              o['type'] == 'QUESTION' and o['question']['options'] == ['the example setup', 'provide files'], o)
        check('the phrase is recorded with its pattern, the options offered and the outcome (Decision 9)',
              len(h) == 1 and h[0]['phrase'] == 'Re-run.' and h[0]['pattern'] == o['pattern']
              and h[0]['options'] == o['question']['options'] and h[0]['outcome'] == 'QUESTION'
              and h[0]['status'] == 'question' and h[0]['plan'] == o and h[0]['seq'] == 1, h)
        check('at plan time only the history line and the pending question are written',
              sorted(os.listdir(pl.root)) == ['.sicopr'] and sorted(os.listdir(pl.project.dir))
              == ['history.jsonl', 'pending.json'], os.listdir(pl.project.dir))
        o2 = core.handle('2', pl.project)
        h = pl.history()
        check('an answer is recorded with the option chosen and the question it answers',
              len(h) == 2 and h[1]['chosen'] == 'provide files' and h[1]['answers'] == 1 and h[1]['outcome'] == o2['type'],
              h[-1])
        check('the open question is closed by its answer', pl.project.read_pending() is None)
        o3 = core.handle('Re-run with zz_top = 4 pronto.', pl.project)
        h = pl.history()
        check('unplaced words are recorded', h[-1]['unplaced'] == o3['unplaced'] and h[-1]['seq'] == 3, h[-1])

    with Place() as pl:
        pl.seed_run()
        q = core.handle('Re-run the setup, but sweep TDR from 0 to 1 in 2 steps.', pl.project)
        core.handle('Show settings.', pl.project)
        h = pl.history()
        check('a new phrase over an open question names the question it replaces',
              q['type'] == 'QUESTION' and h[-1]['rephrase_of'] == h[-2]['seq'] and pl.project.read_pending() is None,
              (q['type'], h[-1]))
        core.handle('Re-run the setup, but sweep TDR from 0 to 1 in 2 steps.', pl.project)
        core.handle('cancel', pl.project)
        h = pl.history()
        check('a cancelled question is recorded as cancelled', h[-1]['status'] == 'cancelled'
              and h[-1]['chosen'] == 'cancel' and h[-1]['answers'] == h[-2]['seq'], h[-1])

    with Place() as pl:
        rid = pl.seed_run(phrase='Re-run with DER_0 = 1e-4.')
        for ph in ('Re-run the last one.', 'do the last run again', 'repeat my last analysis'):
            o = core.handle(ph, pl.project)
            check('S1 (%s): replays the stored plan of the last run' % ph,
                  o['type'] == 'PLAN' and ops(o) == STORED_STEPS
                  and any('replays the last command: Re-run with DER_0 = 1e-4.' in l for l in o['announce']),
                  (o['type'], ops(o), o['announce']))
        rec = pl.history()[0]
        rec['plan']['steps'] = [{'op': 'validate_config', 'args': {}}, {'op': 'run_com', 'args': {}},
                                {'op': 'summarize', 'args': {}}]
        with open(pl.project.history_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(rec) + '\n')
        o = core.handle('Re-run the last one.', pl.project)
        check('replay uses the stored plan, not a new reading of the stored phrase',
              ops(o) == ['validate_config', 'run_com', 'summarize'], ops(o))
        o = core.handle('What did I run last?', pl.project)
        text = '\n'.join(o['announce'])
        check('S2: What did I run last? shows the last command, its inputs, overrides and result folder',
              o['type'] == 'PLAN' and ops(o) == ['show_history']
              and 'Re-run with DER_0 = 1e-4.' in text and os.path.join('data', 'thru.s4p') in text
              and 'DER_0' in text and os.path.join('.sicopr', 'runs', rid) in text, o['announce'])
        os.rename(os.path.join(pl.root, 'data', 'thru.s4p'), os.path.join(pl.root, 'data', 'thru_v2.s4p'))
        o = core.handle('Re-run the last one.', pl.project)
        check('S1 fallback: a channel file of the last run that is gone asks, with the files there as options',
              o['type'] == 'QUESTION' and os.path.join('data', 'thru.s4p') in o['question']['text']
              and o['question']['options'][:1] == [os.path.join('data', 'thru_v2.s4p')]
              and o['question']['options'][-1] == 'cancel', o.get('question'))

    with Place() as pl:
        o = core.handle('Send feedback.', pl.project)
        check('Send feedback with no history: a STOP, nothing to export (row FB07)',
              o['type'] == 'STOP' and 'nothing to export' in o['reason'], o.get('reason'))
        pl.seed_run()
        for ph in ('Send feedback.', 'how do I send feedback', 'email my history to the developer'):
            o = core.handle(ph, pl.project)
            check('%s: the export plan, sent by nobody (Decision 10, version 2)' % ph,
                  o['type'] == 'PLAN' and ops(o) == ['export_feedback'] and o['steps'][0]['args']['send'] is True
                  and not o['unplaced'], o)
        check('the address and subject are the ones Decision 10 names',
              (core.FEEDBACK_ADDRESS, core.FEEDBACK_SUBJECT) == ('sicopr_assist.showman405@simplelogin.com',
                                                                 'SiCoPR-Assist feedback'))
        check('at plan time, send feedback writes no file but the history line',
              not [n for n in os.listdir(pl.project.dir) if n.startswith('feedback_')], os.listdir(pl.project.dir))
        n = 0
        for dirpath, _, files in os.walk(PACKAGE):
            for f in files:
                if f.endswith('.py'):
                    with open(os.path.join(dirpath, f), encoding='utf-8') as fh:
                        n += fh.read().count('showman405')
        check('the address is written once in the package code', n == 1, n)
    finish()


if __name__ == '__main__':
    sys.exit(main())

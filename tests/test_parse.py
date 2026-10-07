"""The phrase reader (sicopr_assist/parse.py) on its own: no config, no engine call.

  - names are COM keywords, case and spaces ignored, longest name first (z_p (TX) is one name)
  - numbers, units, brackets, ranges, lists, files and the value markers =, to, at and for
  - "package" means PKG_NAME; TX package A and RX package B
  - a word that is not known is reported as unplaced, and a name that is not a keyword as an attempt
  - the typo rule (row PH08): agian is read as again; rn is never matched; a value word is never corrected

    python tests\\test_parse.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
from sicopr_assist import parse  # noqa: E402

NAMES = ['f_b', 'DER_0', 'z_p select', 'z_p (TX)', 'COM Pass threshold', 'ERL Pass threshold', 'C_b', 'c(-1)',
         'b_max(2..N_b)', 'PKG_NAME', 'A_v', 'flim', 'MLSE', 'N_bg', 'TDR', 'ERL', 'Clip Method', 'R_d', 'C_d']
BLOCKS = ['PKG_LowR_CLASSA', 'PKG_HiR_CLASSB']


def read(phrase):
    return parse.read(phrase, NAMES, BLOCKS)


def sets(o):
    return [(s['name'], s['value']) for s in o['sets']]


def main():
    o = read('RE-RUN WITH F_B = 53.125')
    check('case is ignored in a name (PH03)', sets(o) == [('f_b', '53.125')] and o['actions'] == ['rerun'], o)
    check('com pass threshold is COM Pass threshold (RS08)', sets(read('Re-run with com pass threshold = 4.'))
          == [('COM Pass threshold', '4')])
    check('spaces are ignored: z_p(TX) is z_p (TX)', sets(read('Re-run with z_p(TX) = [1 2]'))[0][0] == 'z_p (TX)')
    check('a name of several words is read whole', sets(read('Re-run with z_p select = 2'))[0] == ('z_p select', '2'))
    for ph in ('rerun with f_b=53.125', 'Re-run with f_b 53.125', 'Re-run with 53.125 for f_b.',
               'Run it again with f_b at 53.125.', 'Change f_b to 53.125 and run again.', 'Now try f_b = 53.125.',
               'Same run, but set f_b to 53.125.'):
        got = read(ph)
        check('%s: f_b = 53.125 and nothing left over' % ph, sets(got) == [('f_b', '53.125')] and not got['unplaced'],
              got)
    o = read('set f_b=53.125;DER_0=1e-4 & run')
    check('two changes glued with = and ; (PH09)', sets(o) == [('f_b', '53.125'), ('DER_0', '1e-4')], o)
    o = read('Re-run with flim = 50 GHz.')
    check('a unit stays with its number (RS14)', o['sets'][0]['value'] == '50' and o['sets'][0]['unit'] == 'GHz', o)
    check('a sentence end is not part of a number', sets(read('Re-run with N_bg = 0.')) == [('N_bg', '0')])
    o = read('Re-run with c(-1) = [-0.35:.02:0].')
    check('a bracketed range is one value', sets(o) == [('c(-1)', '[-0.35:.02:0]')], o)
    o = read('Re-run the setup, but sweep C_b from 0.1e-4 to 0.5e-4 in 0.5e-5 steps.')
    sw = o['sweeps'][0]
    check('a range with a count or step after in (SX02)',
          (sw['name'], sw['start'], sw['end'], sw['count'], sw['how']) == ('C_b', '0.1e-4', '0.5e-4', '0.5e-5', 'steps'), sw)
    sw = read('Sweep A_v from 0.36 to 0.42 in steps of 0.02.')['sweeps'][0]
    check('in steps of is a step size (CB09)', (sw['step'], sw['how']) == ('0.02', 'step'), sw)
    sw = read('step A_v from 0.36 up to 0.42 by 0.02')['sweeps'][0]
    check('by is a step size', (sw['step'], sw['how']) == ('0.02', 'step'), sw)
    sw = read('Re-run the setup, but sweep C_b from 10 fF to 50 fF in 5 fF steps.')['sweeps'][0]
    check('a number with a unit is a step size (SX09)', (sw['step'], sw['unit'], sw['how']) == ('5', 'fF', 'step'), sw)
    sw = read('Run C_b at 1e-5, 3e-5 and 5e-5.')['sweeps'][0]
    check('a list of values (SX08)', sw['values'] == ['1e-5', '3e-5', '5e-5'], sw)
    o = read('Re-run the setup, but sweep the TX C_b from 0.1e-4 to 0.5e-4 in 2e-5 steps.')
    check('a side before a swept name (SX13)', o['sweeps'][0]['side'] == 'TX', o)
    o = read('Sweep clip method and give me a summary of the results and differences.')
    check('sweep NAME alone sweeps every value (SX17)', o['sweeps'][0]['name'] == 'Clip Method' and o['sweeps'][0]['every']
          and 'summary' in o['actions'] and not o['unplaced'], o)
    o = read('Re-run with package PKG_HiR_CLASSB.')
    check('package means PKG_NAME', o['packages'] == [{'both': 'PKG_HiR_CLASSB'}], o)
    o = read('Re-run with TX package PKG_LowR_CLASSA and RX package PKG_HiR_CLASSB.')
    check('TX package A and RX package B', o['packages'] == [{'tx': 'PKG_LowR_CLASSA', 'rx': 'PKG_HiR_CLASSB'}], o)
    o = read('Re-run with package case 7.')
    check('package case is a name attempt, not a block (C5)', not o['packages'] and o['attempts']
          and o['attempts'][0]['text'] == 'package case' and o['attempts'][0]['value'] == '7', o)
    o = read('Change z_p (TX) in PKG_HiR_CLASSB to [1 2] and run again.')
    check('NAME in BLOCK to V', o['sets'][0]['block'] == 'PKG_HiR_CLASSB' and o['sets'][0]['value'] == '[1 2]', o)
    o = read('Run it again with PKG_HiR_CLASSB A_v at 0.4.')
    check('BLOCK NAME at V', o['sets'][0]['block'] == 'PKG_HiR_CLASSB' and sets(o) == [('A_v', '0.4')], o)
    o = read('Re-run with A_v = 0.4 for PKG_HiR_CLASSB.')
    check('NAME = V for BLOCK', o['sets'][0]['block'] == 'PKG_HiR_CLASSB', o)
    o = read('run again without TDR and ERL')
    check('without NAME and NAME sets switches to 0', sets(o) == [('TDR', '0'), ('ERL', '0')], o)
    check('turn off NAME', sets(read('Turn off MLSE and re-run.')) == [('MLSE', '0')])
    o = read('Run data\\thru.s4p with data\\config.xlsx')
    check('files and their kind', [(f['text'], f['ext']) for f in o['files']]
          == [('data\\thru.s4p', 'channel'), ('data\\config.xlsx', '.xlsx')], o)
    o = read('How does this config differ from data\\config.xlsx?')
    check('a path before a question mark', [f['text'] for f in o['files']] == ['data\\config.xlsx'] and not o['unplaced'], o)
    o = read('Re-run with fb = 53.125.')
    check('a name that is not a keyword is an attempt with its value (RS06)',
          o['attempts'] == [{'text': 'fb', 'words': ['fb'], 'value': '53.125', 'unit': None}] and not o['sets'], o)
    o = read('Re-run with DER_0 = 1e-4 pronto.')
    check('an unknown word is unplaced (PH22)', o['unplaced'] == ['pronto'] and sets(o) == [('DER_0', '1e-4')], o)
    o = read('rn it agian with DER_0 1e-4')
    check('PH08: agian is read as again, rn is unplaced', o['corrected'] == {'agian': 'again'} and o['unplaced'] == ['rn']
          and sets(o) == [('DER_0', '1e-4')], o)
    check('the typo rule needs four letters', parse.typo_of('rn') is None and parse.typo_of('thn') is None
          and parse.typo_of('wiht') == 'with', (parse.typo_of('rn'), parse.typo_of('thn')))
    check('the typo rule takes one swap or one letter only', parse.typo_of('agian') == 'again' and parse.typo_of('agn') is None
          and parse.typo_of('aagain') == 'again' and parse.typo_of('aaagain') is None)
    o = read('Re-run with Clip Method = Fast.')
    check('a value word is taken as typed, never corrected', sets(o) == [('Clip Method', 'Fast')], o)
    o = read('Set the first C_d value to 0.5e-4 and re-run.')
    check('the first value of a name is an element edit (RS21)', o['sets'][0]['op'] == 'element', o)
    o = read('Change the c(-1) step to 0.01 and re-run.')
    check('the step of a range (RS24)', o['sets'][0]['op'] == 'part' and o['sets'][0]['part'] == 'step', o)
    o = read('Use 16 steps instead.')
    check('an edit of a pending sweep (SX35)', o['edits'] == [{'count': '16'}] and not o['unplaced'], o)
    o = read('Run every package with every z_p select case.')
    check('every z_p select case is all cases in one run (CB12)', o['sets'][0]['op'] == 'all'
          and o['sweeps'][0]['name'] == 'PKG_NAME', o)
    o = read('Now give me the results in a dynamic dashboard.')
    check('a version 2 feature is recognised', 'dashboard' in o['actions'], o)
    # after first use (Decision 18): the config of the last run, and a role word before a channel file
    for ph in (r'Re-run COM .\data\x\thru_b.s4p with previous config.', r'Run data\thru2.s4p with the same config',
               r'Re-run with data\thru2.s4p using the last config'):
        o = read(ph)
        check('%s: the last config, a channel file, nothing left over' % ph, 'last_config' in o['flags']
              and [f['ext'] for f in o['files']] == ['channel'] and not o['unplaced'], o)
    o = read('Re-run with the previous DER_0 = 1e-4.')
    check('previous is placed only before config', 'last_config' not in o['flags'] and 'previous' in
          [a['text'] for a in o['attempts']] + o['unplaced'], o)
    o = read(r'Re-run with FEXT data\fext1.s4p.')
    check('a role word before a channel file (CH08)', [(f['text'], f['role']) for f in o['files']]
          == [(r'data\fext1.s4p', 'fext')] and not o['unplaced'], o)
    o = read('Re-run with Tx_NPC_250mm_32AWG_BPK_500mm_27AWG_BPK_250mm_32AWG_NPC_Rx_thru1.s4p')
    check('a bare channel file name is a file', [f['ext'] for f in o['files']] == ['channel'] and not o['unplaced'], o)
    finish()


if __name__ == '__main__':
    sys.exit(main())

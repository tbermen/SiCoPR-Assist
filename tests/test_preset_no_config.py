"""A named-standard preset in a folder with channels but no config.

"Setup a 802.3dj config for C2C and run my channels." in a folder that held only a channel file crashed
inside the translator (the preset read the config in view, which was None). The crash was caught and the
user saw the strict "could not be placed" question instead (public-release review, 29 October 2026).
Now 802.3dj gets the no-config proposal (the example workbook with the preset's values), and 802.3ck,
whose preset is built on a config, gets a STOP that says to put one in the folder.

    python tests/test_preset_no_config.py
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from check import check, finish  # noqa: E402

os.environ['SICOPR_ASSIST_TRANSLATOR'] = 'on'
from sicopr_assist import core, example_channel  # noqa: E402
from sicopr_assist.project import Project  # noqa: E402


def outcome(phrase):
    root = tempfile.mkdtemp(prefix='assist_noconf_')
    try:
        os.makedirs(os.path.join(root, 'data'))
        example_channel.write(os.path.join(root, 'data', 'thru.s4p'))
        return core.handle(phrase, Project(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    dj = outcome('Setup a 802.3dj config for C2C and run my channels.')
    err = (dj.get('translation') or {}).get('error')
    check('802.3dj C2C, no config: no translator error', not err, repr(err))
    q = (dj.get('question') or {}).get('text', '')
    check('802.3dj C2C, no config: the 802.3dj proposal is asked', dj['type'] == 'QUESTION' and '802.3dj C2C' in q
          and 'Strict mode' not in q, '%s: %s' % (dj['type'], q[:200]))
    ck = outcome('Setup a 802.3ck config for KR and run my channels.')
    err = (ck.get('translation') or {}).get('error')
    check('802.3ck KR, no config: no translator error', not err, repr(err))
    check('802.3ck KR, no config: a STOP that says to put a config in the folder',
          ck['type'] == 'STOP' and 'config' in (ck.get('reason') or '') and '802.3ck' in (ck.get('reason') or ''),
          '%s: %s' % (ck['type'], ck.get('reason') or (ck.get('question') or {}).get('text', '')[:200]))
    finish()


if __name__ == '__main__':
    main()

"""Channel download (rows F1 to F12). No test here touches the network: the IEEE tools page is a stand-in written by the test in the markup recorded on 7 October 2026 and served from 127.0.0.1
(tests\\cases\\standin_ieee.py), with small zips written by the test.

    python tests\\test_fetch.py

page    the reader of the page: an entry's date is the line under its link, in every form the page uses, never a
        date in a note; the interface is the link's folder; a relative link is resolved; a row with no link is
        skipped; superseded covers every zip of its entry, do not use only its own; sizes from the page
V3.2    a download larger than max_download_mb asks first, and nothing is downloaded until the answer; an
        interrupted download is tried 1 + download_retries times and leaves nothing in the cache
V3.3    every member path of a zip is checked to stay inside the cache before anything is written: ..\\, ../, an
        absolute path (/, \\, C:\\, C:) and a nested zip that tries the same are refused with nothing written; a
        nested zip is unpacked in place; a path past the Windows limit is warned about
guards  only https://www.ieee802.org is read (or the site SICOPR_ASSIST_FETCH_INDEX names), also after a redirect;
        a zip name that is not plain is never used; a download stops once it passes its limit, with or without a
        Content-Length; a zip that would unpack to too many files or too many bytes, nested zips counted, is
        refused with nothing written
pair    the inventory pairs FEXT and NEXT files with their THRU by Decision 19 (the akinwale style, one THRU per
        folder, files that match no THRU); a download that is one of SiCoPR's known contributions is checked
        against benchmark\\208_case_4p15p0\\channels.csv
plan    the core never downloads: handle() reads the page and plans; run.py downloads and unpacks; the answers to
        F2, F6, F8 and F11 and a cached zip when the site is unreachable (F3) each lead where they say
run     the F1 plan carried out with the stand-in child: each point gets its own THRU, FEXT and NEXT files, in that
        order, and batch_summary.csv lists every point, a skipped one with its reason (F7); asked again, the zip is
        not downloaded or unpacked again and every point is reused

With SICOPR_ASSIST_LIVE_FETCH=1 it also reads the real IEEE page once: the index and the size (HEAD) of the newest
KR zip, not the zip. With SICOPR_ASSIST_LIVE_FETCH_ZIP=1 as well it downloads that zip into a temporary folder,
unpacks it, and checks its inventory against SiCoPR's channels.csv. Nothing downloaded is kept.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import csv
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cases'))
sys.dont_write_bytecode = True

from check import check, finish  # noqa: E402
import fixtures  # noqa: E402
import standin_ieee  # noqa: E402
from sicopr_assist import cli, core, engine, fetch, run  # noqa: E402
from sicopr_assist.project import Project  # noqa: E402

STANDIN = [sys.executable, os.path.join(HERE, 'cases', 'standin_child.py')]
F1 = ("Here's my config spreadsheet at data\\config.xls. Download the latest 802.3dj channels posted and analyze "
      "with SiCoPR, both thru-only and xtalk.")
F1_CHAIN = ['import_config', 'infer_interface', 'fetch_index', 'select_zip', 'download', 'extract', 'inventory',
            'validate_inputs', 'build_matrix', 'run_batch', 'batch_summary']


def ops(o):
    st = list(o.get('steps') or [])
    if st and st[-1]['op'] == 'show_tutor' and (st[-1].get('args') or {}).get('why') in ('new', 'trouble'):
        st = st[:-1]
    return [s['op'] for s in st]


def tree(root):
    return sorted(os.path.relpath(os.path.join(d, n), root) for d, _, ns in os.walk(root) for n in ns)


# ----------------------------------------------------------------------------- the page
def page_checks():
    for line, want in [('16-May 2023', '2023-05-16'), ('12-Sept 2023', '2023-09-12'), ('25-July 2022 (25.7M)', '2022-07-25'),
                       ('July-2022', '2022-07-01'), ('08-March-2023', '2023-03-08'), ('25-Oct-2023', '2023-10-25'),
                       ('\xa0\xa0 29-Aug 2023', '2023-08-29')]:
        got = fetch.parse_date(line)
        check('a date line in the page form %r reads as %s' % (line.strip(), want), got and got[0] == want, got)
    for line in ('Note - These files have been superseded by 16-May-2023 contribution', 'Supporting Presentation',
                 '212 Gb/s PAM4 per Lane C2M Channels', 'Reference Presentation in zip file'):
        check('%r is not a date line' % line, fetch.parse_date(line) is None, fetch.parse_date(line))
    for text, want in [('(21.7M)', 21.7), ('(Note - 600 MB file)', 600.0), ('(Note 1.1 GB file)', 1100.0),
                       ('(Note 91M file)', 91.0), ('(with managed crosstalk)', None), ('212 Gb/s (TP0 to TP5)', None)]:
        check('the size %r reads as %s MB' % (text, want), fetch.size_mb(text) == want, fetch.size_mb(text))

    site = standin_ieee.Site()
    url = site.url('3/dj/public/tools/index.html')
    sections = [
        ('h2', 'Mated Test Fixture (MTF) Data', [{'zips': [('https://x.org/3/dj/public/tools/MTF/m_01.zip', 'MTF')],
                                                   'date': '05-Oct-2026'}]),
        ('h2', '200Gb/s Per Lane Channel Data', []),
        ('h3', '200 Gb/s CR and KR channel data (TP0 to TP5)', [
            {'zips': [('https://x.org/3/dj/public/tools/CR/cr_01.zip', 'CR set for the \u201cUniversal Port\u201d')],
             'date': '01-Oct 2026', 'link_note': '(Note - 600 MB file)', 'continuation': 'More Authors'},
            {'zips': [('https://x.org/3/dj/public/tools/KR/kr_01.zip', 'KR set')], 'date': '20-Sep-2026',
             'note_after': 'These files have been superseded by 30-Sep-2026 contribution from<br>&nbsp; Doe/Roe'},
            {'note_before': 'Note - These files have been superseded by 16-May-2026 contribution from Doe',
             'zips': [('https://x.org/3/dj/public/tools/KR/kr_02.zip', 'KR set two'),
                      ('https://x.org/3/dj/public/tools/KR/kr_03.zip', 'KR set three')], 'date': '20-Mar-2026'},
            {'zips': [('https://x.org/3/df/public/tools/KR/kr_04a.zip', 'Original (port mapping error, do not use)'),
                      ('https://x.org/3/df/public/tools/KR/kr_04.zip', 'Fixed')], 'date': '25-July 2025 (25.7M)'}]),
        ('h3', 'C2C', [{'zips': [('https://x.org/3/dj/public/tools/c2c/c2c_01.zip', 'C2C')], 'date': 'July-2022'}]),
        ('h3', 'C2M', [{'title_before': 'Two breakouts', 'zips': [('c2m/c2m_01.zip', 'Orthogonal'),
                                                                   ('c2m/c2m_02.zip', 'Parallel')],
                        'date': '12-Sept 2023'}]),
    ]
    data = standin_ieee.page(sections)
    site.add('3/dj/public/tools/index.html', data, ctype='text/html')
    check('the stand-in page is Windows-1252, as the real one is (not valid UTF-8)', b'\x93' in data and _not_utf8(data))
    with _Env(**{fetch.INDEX_ENV: url}):           # the stand-in is the site read, as for a mirror
        entries = fetch.parse_index(fetch.read_index(url), url)
    zips = {z['name']: (e, z) for e in entries for z in e['zips']}
    check('every entry with a zip link is read and the row with no link is skipped (7 entries, 10 zips)',
          len(entries) == 7 and len(zips) == 10, [e['name'] for e in entries])
    check('the interface is the link folder: MTF none, CR, KR, c2c, c2m',
          [zips[n][1]['interface'] for n in ('m_01.zip', 'cr_01.zip', 'kr_01.zip', 'c2c_01.zip', 'c2m_01.zip')]
          == [None, 'CR', 'KR', 'C2C', 'C2M'])
    check('a relative link is resolved against the page URL',
          zips['c2m_01.zip'][1]['url'] == site.url('3/dj/public/tools/c2m/c2m_01.zip'), zips['c2m_01.zip'][1]['url'])
    check('the date is the line under the link, not the newer date in the superseded note (20-Sep-2026)',
          zips['kr_01.zip'][1]['date'] == '2026-09-20', zips['kr_01.zip'][1]['date'])
    check('a superseded note after the links covers its entry', zips['kr_01.zip'][0]['superseded'] is not None)
    check('a superseded note before the links covers every zip of its entry, and dates both by the shared line',
          zips['kr_02.zip'][0]['superseded'] and zips['kr_03.zip'][0]['superseded']
          and zips['kr_02.zip'][1]['date'] == zips['kr_03.zip'][1]['date'] == '2026-03-20')
    check('do not use covers only the zip whose link says it',
          zips['kr_04a.zip'][1]['do_not_use'] and not zips['kr_04.zip'][1]['do_not_use']
          and not zips['kr_04.zip'][0]['superseded'])
    check('sizes come from the page where it gives one: after the link, or on the date line',
          zips['cr_01.zip'][1]['size_mb'] == 600.0 and zips['kr_04.zip'][1]['size_mb'] == 25.7
          and zips['kr_01.zip'][1]['size_mb'] is None)
    check('a date with no day (July-2022) is read', zips['c2c_01.zip'][1]['date'] == '2022-07-01')
    check('the title of a link is decoded from Windows-1252',
          zips['cr_01.zip'][1]['text'] == 'CR set for the \u201cUniversal Port\u201d', zips['cr_01.zip'][1]['text'])

    sel = core.select_zip(entries, 'KR')
    check('F1, F5: the newest KR zip not superseded and not marked do not use is taken (kr_04.zip), and the newer '
          'ones skipped are named with why', sel['zip'] and sel['zip'][1]['name'] == 'kr_04.zip'
          and sorted(z['name'] for z, _ in sel['skipped']) == ['kr_01.zip', 'kr_02.zip', 'kr_03.zip', 'kr_04a.zip'],
          (sel['zip'] and sel['zip'][1]['name'], [z['name'] for z, _ in sel['skipped']]))
    check('the CR zip, newer than every KR zip, is not taken for KR', select_name(entries, 'KR') != 'cr_01.zip')
    sel = core.select_zip(entries, 'C2M')
    check('F11: an entry with several zips under its date asks, with each zip',
          sel['ask'] and sel['ask'][0] == 'zips' and [z['name'] for _, z in sel['ask'][1]] == ['c2m_01.zip', 'c2m_02.zip'])
    check('F11: a zip picked by URL is taken',
          select_name(entries, 'C2M', pick=site.url('3/dj/public/tools/c2m/c2m_02.zip')) == 'c2m_02.zip')
    twin = [dict(e, name='twin') if e['name'] == 'kr_04a' else e for e in entries] + \
        [{'name': 'kr_05', 'title': 'Twin', 'superseded': None, 'zips': [dict(zips['kr_04.zip'][1], name='kr_05.zip',
                                                                                url='https://x.org/kr_05.zip')]}]
    sel = core.select_zip(twin, 'KR')
    check('F12: two entries that share the newest date ask, with each entry',
          sel['ask'] and sel['ask'][0] == 'entries' and [e['name'] for e in sel['ask'][1]] == ['twin', 'kr_05'],
          sel['ask'])
    check('an interface with no zip to use selects nothing', core.select_zip(entries, 'C2X')['zip'] is None)


def select_name(entries, iface, **kw):
    z = core.select_zip(entries, iface, **kw)['zip']
    return z[1]['name'] if z else None


def _not_utf8(data):
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return True
    return False


# ----------------------------------------------------------------------------- V3.3: unpacking
def zip_file(path, files):
    with open(path, 'wb') as f:
        f.write(standin_ieee.zip_bytes(files))
    return path


def unpack_checks():
    base = tempfile.mkdtemp(prefix='fx_')
    try:
        cache = os.path.join(base, 'c')
        good = b'! not a channel\n'
        for evil in ('..\\evil.s4p', '../evil.s4p', '/abs/evil.s4p', '\\abs\\evil.s4p', 'C:\\abs\\evil.s4p',
                     'C:evil.s4p', 'ok/../../evil.s4p'):
            z = zip_file(os.path.join(base, 'z.zip'), {'a_first.s4p': good, evil: b'outside'})
            folder = os.path.join(cache, 'z')
            try:
                fetch.unpack(z, folder)
                refused = False
            except fetch.FetchError as e:
                refused = 'would leave the folder' in str(e)
            written = [p for p in tree(base) if 'evil' in p or p.startswith(os.path.join('c', 'z'))]
            check('V3.3: a member %r is refused before anything is written, and nothing is written' % evil,
                  refused and not written and not os.path.exists(os.path.join(os.path.dirname(base), 'evil.s4p')),
                  written)
        inner = standin_ieee.zip_bytes({'ch_thru.s4p': good, '../evil.s4p': b'outside'})
        z = zip_file(os.path.join(base, 'z.zip'), {'a_first.s4p': good, 'set/inner.zip': inner})
        try:
            fetch.unpack(z, os.path.join(cache, 'n'))
            refused = False
        except fetch.FetchError:
            refused = True
        check('V3.3: a nested zip that tries ../ is refused too, and the unpacked folder is removed',
              refused and not os.path.exists(os.path.join(cache, 'n')) and not any('evil' in p for p in tree(base)),
              tree(base))
        inner = standin_ieee.zip_bytes({'ch_thru1.s4p': good, 'ch_xtalk1_Fext.s4p': good})
        z = zip_file(os.path.join(base, 'z.zip'), {'top/a_thru.s4p': good, 'top/set.zip': inner})
        got = fetch.unpack(z, os.path.join(cache, 'ok'))
        check('a nested zip is unpacked in place, into a folder named after it, and removed',
              got['files'] == ['top/a_thru.s4p', 'top/set/ch_thru1.s4p', 'top/set/ch_xtalk1_Fext.s4p']
              and not os.path.exists(os.path.join(cache, 'ok', 'top', 'set.zip')), got)
        long_name = 'x' * 120 + '/' + 'y' * 120 + '_thru.s4p'
        z = zip_file(os.path.join(base, 'z.zip'), {long_name: good})
        try:
            got = fetch.unpack(z, os.path.join(cache, 'long'))
            said = ' '.join(got['warnings'])
        except fetch.FetchError as e:           # Windows without long paths refuses the write; the warning says why
            said = str(e)
        check('a member path past the Windows limit (260) is warned about', 'Windows allows' in said, said[:200])
        z = os.path.join(base, 'bad.zip')
        with open(z, 'wb') as f:
            f.write(b'PK\x03\x04 not really a zip')
        try:
            fetch.unpack(z, os.path.join(cache, 'bad'))
            ok = False
        except fetch.FetchError:
            ok = not os.path.exists(os.path.join(cache, 'bad'))
        check('a zip that cannot be read stops with a FetchError and leaves no folder', ok)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ----------------------------------------------------------------------------- the guards on what is read and unpacked
class _Env:
    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.values}
        for k, v in self.values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _refused(fn):
    """(refused, message): whether fn raised FetchRefused."""
    try:
        fn()
    except fetch.FetchError as e:
        return isinstance(e, getattr(fetch, 'FetchRefused', ())), str(e)
    return False, 'nothing was raised'


def _bomb_zip(path, name, mb):
    """A zip holding one file of mb MB of zeros: a few hundred kB on disk."""
    import zipfile
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        with z.open(name, 'w') as f:
            block = bytes(1 << 20)
            for _ in range(mb):
                f.write(block)
    return path


def guard_checks():
    with _Env(**{fetch.INDEX_ENV: None}):
        check('only https://www.ieee802.org is read: http, another host, a look-alike host and a user part are not',
              fetch.allowed('https://www.ieee802.org/3/dj/public/tools/KR/a.zip')
              and not any(fetch.allowed(u) for u in ('http://www.ieee802.org/3/dj/public/tools/KR/a.zip',
                                                     'https://example.org/a.zip', 'https://www.ieee802.org.example.org/a.zip',
                                                     'https://x@www.ieee802.org/a.zip', 'file:///C:/a.zip')))
        base = tempfile.mkdtemp(prefix='fg_')
        try:
            ok, said = _refused(lambda: fetch.download('http://www.ieee802.org/3/dj/public/tools/KR/a.zip',
                                                       os.path.join(base, 'c', 'a.zip'), os.path.join(base, 'a.zip.part')))
            check('a zip URL on http is refused before anything is asked, and nothing is written',
                  ok and tree(base) == [], (said, tree(base)))
        finally:
            shutil.rmtree(base, ignore_errors=True)
    site = standin_ieee.Site()
    index = site.add('3/dj/public/tools/index.html', b'<html></html>', ctype='text/html')
    zbytes = standin_ieee.zip_bytes({'a_thru.s4p': b'! a channel\n' * 50})
    good = site.add('3/dj/public/tools/KR/good.zip', zbytes)
    other = good.replace('127.0.0.1', 'localhost')            # the same server, under another host name
    base = tempfile.mkdtemp(prefix='fg_')
    try:
        with _Env(**{fetch.INDEX_ENV: index}):
            cache = os.path.join(base, 'c')
            got = fetch.download(good, os.path.join(cache, 'good.zip'), os.path.join(base, 'good.zip.part'))
            check('the site SICOPR_ASSIST_FETCH_INDEX names is read: a zip there downloads',
                  got['bytes'] == len(zbytes) and os.path.isfile(os.path.join(cache, 'good.zip')))
            shutil.rmtree(cache)
            n0 = site.hits('3/dj/public/tools/KR/good.zip')[0]
            ok, said = _refused(lambda: fetch.download(other, os.path.join(cache, 'good.zip'),
                                                       os.path.join(base, 'good.zip.part'), retries=2))
            check('a zip on another site is refused, at once and not retried, and is never asked for',
                  ok and site.hits('3/dj/public/tools/KR/good.zip')[0] == n0 and tree(base) == [], (said, tree(base)))
            hop = site.redirect('3/dj/public/tools/KR/hop.zip', other)
            ok, said = _refused(lambda: fetch.download(hop, os.path.join(cache, 'hop.zip'),
                                                       os.path.join(base, 'hop.zip.part')))
            check('a redirect to another site is refused, the target is never asked for, and nothing is kept',
                  ok and site.hits('3/dj/public/tools/KR/good.zip')[0] == n0 and tree(base) == [], (said, tree(base)))
            page_hop = site.redirect('3/dj/public/tools/moved.html', other)
            try:
                fetch.read_index(page_hop)
                ok = False
            except fetch.FetchError:
                ok = True
            check('the tools page is not read through a redirect to another site either',
                  ok and site.hits('3/dj/public/tools/KR/good.zip')[0] == n0)
            check('the size of a zip on another site is not asked for (HEAD)',
                  fetch.head_size(other) is None and site.hits('3/dj/public/tools/KR/good.zip')[1] == 0)
            for name in ('a b.zip', '.hidden.zip', 'x.zip.exe', 'evil%2f.zip'):
                ok, said = _refused(lambda: fetch.download(good, os.path.join(cache, name),
                                                           os.path.join(base, 'n.part')))
                check('a zip name that is not plain (%r) is not used for a file in the cache' % name,
                      ok and tree(base) == [], (said, tree(base)))
            z = {'url': good, 'name': 'a%20b.zip', 'text': 'odd', 'interface': 'KR', 'date': '2026-10-01',
                 'day_given': True, 'date_text': '01-Oct 2026', 'size_mb': None, 'size_text': None,
                 'do_not_use': False}
            sel = core.select_zip([{'name': 'odd', 'title': 'odd', 'superseded': None, 'zips': [z]}], 'KR')
            check('the core does not select a zip whose name is not plain, and says why',
                  sel['zip'] is None and sel['skipped'] and 'plain zip name' in sel['skipped'][0][1], sel)
            big = os.urandom(1500000)
            for length in (True, False):
                path = '3/dj/public/tools/KR/big_%d.zip' % length
                url = site.add(path, standin_ieee.zip_bytes({'a_thru.s4p': big}), length=length)
                ok, said = _refused(lambda: fetch.download(url, os.path.join(cache, 'big.zip'),
                                                           os.path.join(base, 'big.zip.part'), retries=2,
                                                           max_bytes=1000000))
                check('a download that passes max_bytes is stopped, not retried, and nothing is kept (%s)'
                      % ('the server gives its size' if length else 'the server gives no size'),
                      ok and 'max_download_mb' in said and site.hits(path)[0] == 1 and tree(base) == [],
                      (said, site.hits(path), tree(base)))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    base = tempfile.mkdtemp(prefix='fb_')
    try:
        bomb = _bomb_zip(os.path.join(base, 'bomb.zip'), 'zeros_thru.s4p', 200)
        ok, said = _refused(lambda: fetch.unpack(bomb, os.path.join(base, 'u')))
        check('a zip that would unpack to far more than 20 times its size (200 MB from %d kB) is refused with nothing '
              'written' % (os.path.getsize(bomb) // 1000), ok and not os.path.exists(os.path.join(base, 'u')), said)
        with open(bomb, 'rb') as f:
            inner = f.read()
        outer = zip_file(os.path.join(base, 'outer.zip'), {'a_thru.s4p': b'! a channel\n', 'set/inner.zip': inner})
        ok, said = _refused(lambda: fetch.unpack(outer, os.path.join(base, 'n')))
        check('a nested zip counts against the same limit: refused, and the folder is removed',
              ok and not os.path.exists(os.path.join(base, 'n')), said)
        few = standin_ieee.zip_bytes({'b_thru.s4p': b'x', 'b_fext.s4p': b'y'})
        many = zip_file(os.path.join(base, 'many.zip'), {'a_thru.s4p': b'x', 'a_fext.s4p': b'y', 'set/few.zip': few})
        keep = fetch.MAX_MEMBERS
        fetch.MAX_MEMBERS = 3
        try:
            ok, said = _refused(lambda: fetch.unpack(many, os.path.join(base, 'm')))
        finally:
            fetch.MAX_MEMBERS = keep
        check('the files of a nested zip count towards the number of files (3 at the top, 2 inside, the limit 3)',
              ok and not os.path.exists(os.path.join(base, 'm')), said)
        got = fetch.unpack(many, os.path.join(base, 'm2'))
        check('the same zip unpacks under the usual limit', len(got['files']) == 4, got)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ----------------------------------------------------------------------------- pairing and the known channels
AKINWALE = []
for _mm in (100, 300, 500, 700, 1200, 1400, 1600):
    _stem = 'Tx_NPC_250mm_32AWG_BPK_%dmm_27AWG_BPK_250mm_32AWG_NPC_Rx' % _mm
    AKINWALE += [_stem + '_thru1.s4p'] + [_stem + '_xtalk%d_Fext.s4p' % k for k in (1, 2, 3)] + \
        [_stem + '_xtalk%d_Next.s4p' % k for k in (4, 5, 6, 7)]


def write_files(folder, names, data=None):
    for i, n in enumerate(names):
        p = os.path.join(folder, *n.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data(i) if data else ('# GHz S RI R 50\n! file %d\n' % i).encode('ascii'))
    return sorted(names)


def pairing_checks():
    base = tempfile.mkdtemp(prefix='fp_')
    try:
        import prior_states
        files = write_files(base, ['ak/' + n for n in AKINWALE], data=lambda i: prior_states.s4p_bytes(50 + i))
        rows = core.fetch_inventory(base, files)
        thrus = [r for r in rows if r['kind'] == 'thru']
        ok = len(thrus) == 7 and all(
            len([r for r in rows if r['thru'] == t['file'] and r['kind'] == 'fext']) == 3 and
            len([r for r in rows if r['thru'] == t['file'] and r['kind'] == 'next']) == 4 for t in thrus)
        check('Decision 19 in the inventory: seven THRUs in one folder, each with its 3 FEXT and 4 NEXT files by name',
              ok and all(r['rule'] == 'name' for r in rows if r['kind'] != 'thru')
              and all(r['touchstone'] == 'ok' for r in rows), [(r['file'][-30:], r['thru'][-30:], r['rule']) for r in rows][:4])
        files = write_files(base, ['one/a_thru.s4p', 'one/agg1_fext.s4p', 'one/agg2_NEXT3.s4p', 'one/notes.txt',
                                   'two/b_thru.s4p', 'two/c_thru.s4p', 'two/zz_fext.s4p', 'xt/q_fext.s4p'])
        rows = {r['file']: r for r in core.fetch_inventory(base, files)}
        check('the only THRU in its folder takes every FEXT and NEXT file there (rule only_thru)',
              rows['one/agg1_fext.s4p']['thru'] == 'one/a_thru.s4p' and rows['one/agg2_NEXT3.s4p']['rule'] == 'only_thru'
              and rows['one/agg2_NEXT3.s4p']['kind'] == 'next')
        check('a file that is not a channel is kept as other', rows['one/notes.txt']['kind'] == 'other')
        check('a FEXT file that matches no THRU by name, and one in a folder with no THRU, get a best guess (rule '
              'guess), which the core asks about (row F6)',
              rows['two/zz_fext.s4p']['rule'] == 'guess' and rows['two/zz_fext.s4p']['thru'] in ('two/b_thru.s4p',
                                                                                                'two/c_thru.s4p')
              and rows['xt/q_fext.s4p']['rule'] == 'guess', [(r['file'], r['thru'], r['rule']) for r in rows.values()])
        # the check against SiCoPR's channels.csv, with a stand-in list made from these files
        known = [{'contribution': 'kn_01', 'ieee_url': 'https://x.org/kn_01.zip', 'role': r['kind'].upper(),
                  'file': 'x/' + f, 'sha256': r['sha256']} for f, r in rows.items() if r['kind'] != 'other']
        known[0]['role'] = 'NEXT' if known[0]['role'] != 'NEXT' else 'FEXT'
        rows2 = core.fetch_inventory(base, files, known)
        check('known_role is the role channels.csv gives the file with the same SHA-256',
              sum(1 for r in rows2 if r['known_role']) == len(known))
        real = engine.known_channels
        engine.known_channels = lambda: known
        try:
            lines = core._known_lines({'url': 'https://x.org/kn_01.zip'}, rows2)
        finally:
            engine.known_channels = real
        check('a download that is a known contribution is checked against channels.csv: the files present by '
              'SHA-256, and a role that differs is a warning',
              any('channels.csv' in x and '%d of the %d files' % (len(known), len(known)) in x for x in lines)
              and any(x.startswith('warning') for x in lines), lines)
        k = engine.known_channels()
        check("SiCoPR's benchmark channels.csv is read: 164 files of six contributions",
              len(k) == 164 and len({x['contribution'] for x in k}) == 6, len(k))
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ----------------------------------------------------------------------------- the plan, the answers, the run
class Env:
    """One stand-in project and site (a fetch prior state), with its environment set while the core is called."""

    def __init__(self, fx, **flags):
        import prior_states
        self.ctx = prior_states.Ctx(fx, 'Case1')
        self.site = prior_states.fetch_env(self.ctx, **flags)
        self.p = Project(self.ctx.root)
        self.fx = fx

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.ctx.env}
        os.environ.update(self.ctx.env)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.fx.remove_project(self.ctx.root)

    def say(self, phrase):
        return core.handle(phrase, self.p)

    def through(self, phrase):
        """The outcome before anything runs: for a download plan, after run.py has fetched the zip."""
        o = core.handle(phrase, self.p)
        if o['type'] == 'PLAN' and run.fetch_pending(o):
            return o, run.carry_out(self.p, o)['next']
        return o, o

    def settings(self, text):
        os.makedirs(self.p.dir, exist_ok=True)
        with open(self.p.settings_path, 'w', encoding='utf-8') as f:
            f.write('[limits]\n' + text + '\n')

    def newest(self):
        import prior_states
        return self.site.hits(prior_states.TOOLS + 'KR/' + prior_states.NEWEST)

    def cache(self):
        d = os.path.join(self.p.dir, 'cache')
        return tree(d) if os.path.isdir(d) else []


def plan_checks(fx):
    import prior_states
    with Env(fx) as e:
        o = e.say(F1)
        check('the core plans the download and never makes it: after handle() the zip has had no GET, only the HEAD '
              'for its size, and nothing is in the cache', o['type'] == 'PLAN' and e.newest() == (0, 1)
              and e.cache() == [], (o['type'], e.newest(), e.cache()))
        check('F1 before the download: the chain of F1, with the run matrix still to be built',
              ops(o) == F1_CHAIN and not o['points'], ops(o))
        check('F1 announces the zip, its size from the server (Content-Length), and that the matrix comes after',
              any('zip: %s' % prior_states.NEWEST in x and "Content-Length" in x for x in o['announce'])
              and any('run matrix' in x for x in o['announce']), o['announce'])
        nxt = run.carry_out(e.p, o)['next'] if o['type'] == 'PLAN' else o
        check('run.py downloads and unpacks the zip, and the core then plans the run matrix (3 channels x thru-only '
              'and xtalk = 6 runs) and announces the run count',
              nxt['type'] == 'PLAN' and ops(nxt) == F1_CHAIN and len(nxt['points']) == 6 and nxt['new_runs'] == 6
              and any('6 runs' in x for x in nxt['announce']) and e.newest()[0] == 1, (nxt['type'], ops(nxt)))
        check('the zip, its unpacked files and the inventory are in .sicopr\\cache\\KR, and no partial file is left',
              os.path.join('KR', prior_states.NEWEST) in e.cache()
              and os.path.join('KR', 'standin_3dj_01_2609', 'set_b', 'ch3_thru1.s4p') in e.cache()
              and not [p for p in tree(e.p.dir) if p.endswith('.part')], e.cache())
        o2 = e.say(F1)
        check('F4: asked again, the zip is cached and unpacked: no download, and the matrix is planned at once',
              o2['type'] == 'PLAN' and 'download' not in ops(o2) and not run.fetch_pending(o2) and len(o2['points']) == 6
              and any(x.startswith('cache hit') for x in o2['announce']) and e.newest()[0] == 1, ops(o2))

    with Env(fx, confirmed=False) as e:
        q = e.say(F1)
        check('F2: with no interface confirmed it asks, KR first with the evidence (RUNTAG), and the page is not read',
              q['type'] == 'QUESTION' and q['question']['options'][0].startswith('KR (')
              and 'RUNTAG' in q['question']['text'] and e.newest() == (0, 0), q.get('question'))
        a = e.say('KR')
        check('F2: the answer KR plans the download of the newest KR zip', a['type'] == 'PLAN' and ops(a) == F1_CHAIN
              and a['steps'][1]['args'].get('interface') == 'KR', ops(a))
        b = e.say(F1)
        check('F2: the answer is kept for the project: the next download does not ask again',
              b['type'] == 'PLAN' and b['steps'][1]['args'].get('how') == 'confirmed for this project earlier', ops(b))

    with Env(fx, multi=True) as e:
        q = e.say(F1)
        a = e.say('2')
        check('F11: the second zip of the newest entry, chosen by number, is the one planned',
              q['type'] == 'QUESTION' and a['type'] == 'PLAN'
              and a['steps'][3]['args'].get('zip') == 'standin_3dj_01b_2609.zip', (a['type'], a['steps'][3:4]))

    with Env(fx, unpaired=True) as e:
        _, q = e.through(F1)
        check('F6: FEXT and NEXT files that cannot be paired ask, with the best guess written to inventory.csv',
              q['type'] == 'QUESTION' and q['question']['options'] == ['continue', 'run thru-only only', 'cancel'],
              q.get('question'))
        only = e.say('run thru-only only')
        check('F6: run thru-only only plans the two THRUs alone',
              only['type'] == 'PLAN' and [p['values']['mode'] for p in only['points']] == ['thru_only', 'thru_only'],
              (only['type'], only.get('points')))
        _, q = e.through(F1)
        inv = os.path.join(e.p.dir, 'cache', 'KR', 'standin_3dj_01_2609.inventory.csv')
        rows = list(csv.DictReader(open(inv, newline='', encoding='utf-8')))
        for r in rows:
            if r['file'] == 'chans/aggr_a_fext.s4p':
                r['thru'], r['rule'] = 'chans/lane1_thru.s4p', 'user'
        run.write_inventory(inv, rows)
        c = e.say('continue')
        x = {p['values']['channel']: p for p in c.get('points') or [] if p['values']['mode'] == 'xtalk'}
        check('F6: continue plans the xtalk runs with the pairing as corrected in inventory.csv',
              c['type'] == 'PLAN' and [ch[0].replace(os.sep, '/').rsplit('/', 1)[-1] for ch in
                                       x['chans/lane1_thru.s4p']['channels']] == ['lane1_thru.s4p', 'aggr_a_fext.s4p'],
              (c['type'], c.get('reason'), {k: v['channels'] for k, v in x.items()}))

    with Env(fx, no_touchstone=True) as e:
        _, q = e.through(F1)
        a = e.say('1')
        check('F8: a zip with no Touchstone file asks with the next candidate zip; choosing it plans that zip',
              q['type'] == 'QUESTION' and 'readme.txt' in q['question']['text'] and a['type'] == 'PLAN'
              and a['steps'][3]['args'].get('zip') == 'standin_3dj_02_2606.zip', (q.get('question'), a['type']))

    with Env(fx, thru_only=True) as e:
        _, nxt = e.through(F1)
        check('F10: a zip with THRU files only runs every channel thru-only and says xtalk runs are not possible',
              nxt['type'] == 'PLAN' and [p['values']['mode'] for p in nxt['points']] == ['thru_only'] * 3
              and any(x.startswith('xtalk runs are not possible') for x in nxt['announce']),
              (nxt['type'], nxt['announce'][-4:]))

    with Env(fx) as e:
        e.settings('max_new_runs = 4')
        _, q = e.through(F1)
        a = e.say('run all')
        check('Decision 6 on a fetched batch (F1 note): more new runs than max_new_runs asks first; run all plans '
              'them', q['type'] == 'QUESTION' and q['question']['options'] == ['run all', 'cancel']
              and a['type'] == 'PLAN' and a['new_runs'] == 6, (q.get('question'), a['type']))

    with Env(fx) as e:
        e.site.add(prior_states.TOOLS + 'KR/' + prior_states.NEWEST,
                   standin_ieee.zip_bytes({'chans/ch1_thru.s4p': prior_states.s4p_bytes(200),
                                           '../../evil_thru.s4p': b'outside'}))
        _, nxt = e.through(F1)
        evil = [p for p in tree(os.path.dirname(e.ctx.root)) if 'evil' in p]
        check('V3.3 through the runner: a downloaded zip with a path that leaves the cache is refused, nothing is '
              'unpacked, and the zip is removed from the cache', nxt['type'] == 'STOP' and 'would leave' in nxt['reason']
              and e.cache() == [] and not evil, (nxt.get('reason'), e.cache(), evil))

    with Env(fx, network='down', cached=True) as e:
        q = e.say(F1)
        check('F3 fallback: with the site unreachable and a zip in the cache, it asks with the cached zip',
              q['type'] == 'QUESTION' and q['question']['options'] == [prior_states.NEWEST, 'cancel'], q.get('question'))
        a, nxt = e.through(prior_states.NEWEST)
        check('F3 fallback: choosing it plans from the cache with no network', a['type'] == 'PLAN'
              and 'download' not in ops(a) and nxt['type'] == 'PLAN' and len(nxt['points']) == 6, (a['type'], ops(a)))


def v32_checks(fx):
    import prior_states
    with Env(fx) as e:
        e.settings('max_download_mb = 0')
        q = e.say(F1)
        check('V3.2: a download larger than max_download_mb asks first, and nothing is downloaded until the answer',
              q['type'] == 'QUESTION' and q['question']['options'] == ['download it', 'cancel']
              and 'max_download_mb' in q['question']['text'] and e.newest()[0] == 0 and e.cache() == [],
              (q.get('question'), e.newest()))
        a = e.say('download it')
        dl = next((s['args'] for s in a['steps'] if s['op'] == 'download'), {})
        check('V3.2: once the size is agreed to, the download limit is that size, not max_download_mb',
              dl.get('max_mb') is not None and dl['max_mb'] * 1e6 >= dl.get('size', 0) > 0, dl)
        nxt = run.carry_out(e.p, a)['next'] if a['type'] == 'PLAN' else a
        check('V3.2: after the answer the zip is downloaded and the matrix planned',
              a['type'] == 'PLAN' and 'download' in ops(a) and nxt['type'] == 'PLAN' and e.newest()[0] == 1,
              (a['type'], nxt['type']))
    with Env(fx) as e:
        o = e.say(F1)
        dl = next((s['args'] for s in o['steps'] if s['op'] == 'download'), {})
        check('the download step carries its limit, max_download_mb (500 by default)', dl.get('max_mb') == 500, dl)
    with Env(fx) as e:
        e.settings('max_download_mb = 1')
        e.site.add(prior_states.TOOLS + 'KR/' + prior_states.NEWEST,
                   standin_ieee.zip_bytes({'chans/ch1_thru.s4p': os.urandom(1500000)}), length=False)
        o, nxt = e.through(F1)
        check('a server that gives no size: the plan does not ask, and the download stops once it passes '
              'max_download_mb, with nothing in the cache and no partial file',
              o['type'] == 'PLAN' and nxt['type'] == 'STOP' and 'refused' in nxt['reason']
              and 'max_download_mb' in nxt['reason'] and e.cache() == []
              and not [p for p in tree(e.p.dir) if p.endswith('.part')], (nxt.get('reason'), e.cache()))
    for retries in (1, 2, 0):
        with Env(fx, interrupted=True) as e:
            if retries != 1:
                e.settings('download_retries = %d' % retries)
            o, nxt = e.through(F1)
            left = [p for p in tree(e.p.dir) if not p.endswith(('history.jsonl', 'pending.json', 'assist.ini', '.gitignore'))]
            check('V3.2, F9: an interrupted download is tried 1 + download_retries times (download_retries = %d), stops '
                  'with download incomplete, and leaves nothing in the cache and no partial file' % retries,
                  nxt['type'] == 'STOP' and 'incomplete' in nxt['reason'] and e.newest()[0] == 1 + retries
                  and not left, (nxt.get('reason'), e.newest(), left))
            h = e.p.read_history()
            check('F9: the plan is recorded as failed, and the STOP after it', h[-2]['status'] == 'failed'
                  and h[-1]['outcome'] == 'STOP', [(r['outcome'], r['status']) for r in h])
    base = tempfile.mkdtemp(prefix='fd_')
    site = standin_ieee.Site()
    try:
        os.environ[fetch.INDEX_ENV] = site.url('index.html')
        url = site.add('z.zip', standin_ieee.zip_bytes({'a_thru.s4p': b'x' * 5000}), interrupt=True)
        try:
            fetch.download(url, os.path.join(base, 'cache', 'z.zip'), os.path.join(base, 'z.zip.part'), retries=0)
            ok = False
        except fetch.FetchError as e:
            ok = 'sent' in str(e)
        check('fetch.download with retries = 0 tries once, then stops with nothing kept',
              ok and site.hits('z.zip')[0] == 1 and tree(base) == [], tree(base))
        url = site.add('n.zip', b'not a zip at all')
        try:
            fetch.download(url, os.path.join(base, 'cache', 'n.zip'), os.path.join(base, 'n.zip.part'), retries=0)
            ok = False
        except fetch.FetchError as e:
            ok = 'not a zip' in str(e)
        check('what arrives whole but is not a zip is not kept either', ok and tree(base) == [], tree(base))
    finally:
        os.environ.pop(fetch.INDEX_ENV, None)
        shutil.rmtree(base, ignore_errors=True)


def run_checks(fx):
    for flags, n_run, n_skip in (({}, 6, 0), ({'invalid': True}, 4, 2)):
        with Env(fx, **flags) as e:
            argv = os.path.join(e.ctx.root, 'argv.jsonl')
            os.environ['SICOPR_ASSIST_STANDIN_ARGV'] = argv
            try:
                buf = io.StringIO()
                final, done = cli.handle_and_run(F1, e.p, out=buf, child=STANDIN)
            finally:
                os.environ.pop('SICOPR_ASSIST_STANDIN_ARGV', None)
            calls = [json.loads(x) for x in open(argv, encoding='utf-8')] if os.path.exists(argv) else []
            shown = buf.getvalue()
            tag = 'F7' if flags else 'F1'
            check('%s carried out from the command line: the download plan, then the run plan, %d runs' % (tag, n_run),
                  final['type'] == 'PLAN' and len(done['run_ids']) == n_run and len(calls) == n_run
                  and shown.count('PLAN:') == 2, (final['type'], done.get('run_ids'), len(calls)))

            def roles(c):
                out, role = [], None
                for x in c[2:]:
                    if x in ('--thru', '--fext', '--next'):
                        role = x[2:]
                    elif x.startswith('--'):
                        role = None
                    elif role:
                        out.append((role, os.path.basename(x)))
                return out
            got = [roles(c) for c in calls]
            want = [[('thru', 'ch1_thru.s4p')], [('thru', 'ch1_thru.s4p'), ('fext', 'ch1_fext1.s4p'),
                                                  ('next', 'ch1_next1.s4p')]]
            check('%s: the engine gets the THRU alone for thru-only, and THRU, FEXT, NEXT for xtalk' % tag,
                  got[:2] == want, got[:2])
            rows = list(csv.DictReader(open(os.path.join(e.p.runs_dir, 'batch_summary.csv'), newline='',
                                            encoding='utf-8')))
            skipped = [r for r in rows if r['status'] == 'skipped']
            check('%s: batch_summary.csv lists every point (6), %d skipped with the reason' % (tag, n_skip),
                  len(rows) == 6 and len(skipped) == n_skip and all('not a valid Touchstone file' in r['note']
                                                                    for r in skipped), [r['status'] for r in rows])
            if not flags:
                again = core.handle(F1, e.p)
                check('asked again after the runs: no download, no unpacking, and every point reused',
                      again['type'] == 'PLAN' and not run.fetch_pending(again) and again['new_runs'] == 0
                      and again['reused_runs'] == 6, (again['type'], again.get('new_runs'), again.get('reused_runs')))


# ----------------------------------------------------------------------------- live (the orchestrator runs it once)
def live_checks():
    if os.environ.get('SICOPR_ASSIST_LIVE_FETCH') != '1':
        print('SKIP: the live test of the real IEEE page runs only with SICOPR_ASSIST_LIVE_FETCH=1')
        return
    url = fetch.INDEX_URL
    entries = fetch.parse_index(fetch.read_index(url), url)
    n = sum(len(e['zips']) for e in entries)
    print('LIVE: %s: %d entries, %d zips' % (url, len(entries), n))
    check('LIVE: the real page is read: at least 40 entries with a zip link', len(entries) >= 40, len(entries))
    sel = core.select_zip(entries, 'KR')
    check('LIVE: one newest KR zip is selected, with no question', sel['zip'] is not None and sel['ask'] is None,
          sel['ask'])
    if sel['zip'] is None:
        return
    z = sel['zip'][1]
    size = fetch.head_size(z['url'])
    print('LIVE: newest KR zip %s, %s, %s bytes (Content-Length); skipped: %s'
          % (z['name'], z['date_text'], size, [s[0]['name'] for s in sel['skipped']]))
    check('LIVE: the server gives the size of the newest KR zip (HEAD, Content-Length)', size and size > 0, size)
    check('LIVE: the newest KR zip is akinwale_3dj_01_2310.zip, as on 7 October 2026', z['name'] ==
          'akinwale_3dj_01_2310.zip', z['name'])
    if os.environ.get('SICOPR_ASSIST_LIVE_FETCH_ZIP') != '1':
        print('SKIP: the zip itself is downloaded only with SICOPR_ASSIST_LIVE_FETCH_ZIP=1')
        return
    base = tempfile.mkdtemp(prefix='lv_')
    try:
        dest = os.path.join(base, 'c', z['name'])
        got = fetch.download(z['url'], dest, os.path.join(base, z['name'] + '.part'),
                             say=lambda t: print('LIVE:   ' + t))
        un = fetch.unpack(dest, os.path.join(base, 'c', 'u'))
        known = engine.known_channels()
        rows = core.fetch_inventory(os.path.join(base, 'c', 'u'), un['files'], known)
        mine = [k for k in known if k['ieee_url'] == z['url']]
        chans = [r for r in rows if r['kind'] != 'other']
        have = {r['sha256'] for r in rows}
        print('LIVE: %d bytes, %d files, %d channel files; channels.csv lists %d for this zip'
              % (got['bytes'], len(rows), len(chans), len(mine)))
        check('LIVE: every file channels.csv lists for this contribution is in the zip with the same SHA-256',
              mine and all(k['sha256'] in have for k in mine), len(mine))
        check('LIVE: every role agrees with channels.csv',
              all(r['kind'].upper() == r['known_role'] for r in chans if r['known_role']))
        thrus = [r for r in chans if r['kind'] == 'thru']
        check('LIVE: every FEXT and NEXT file is paired with a THRU by Decision 19 (no guess)',
              all(r['rule'] in ('name', 'only_thru') for r in chans if r['kind'] != 'thru'), len(thrus))
        print('LIVE: %d THRU, each with %s' % (len(thrus), sorted({(
            len([r for r in chans if r['thru'] == t['file'] and r['kind'] == 'fext']),
            len([r for r in chans if r['thru'] == t['file'] and r['kind'] == 'next'])) for t in thrus})))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    page_checks()
    unpack_checks()
    guard_checks()
    pairing_checks()
    if not fixtures.find_starting_configs():
        print('SKIP: the four starting workbooks (by SHA-256, in tests\\configs or SICOPR_ASSIST_CONFIGS) are absent '
              'or hidden; the plan, answer and run checks need them')
    else:
        with fixtures.Fixtures(variants=False) as fx:
            plan_checks(fx)
            v32_checks(fx)
            run_checks(fx)
    live_checks()
    finish()


if __name__ == '__main__':
    sys.exit(main())

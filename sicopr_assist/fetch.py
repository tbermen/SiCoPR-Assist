"""Channel download: the IEEE P802.3dj tools page, its zips, and unpacking them.

This is the only module that touches the network, and only when the user asks for a download. It reads only
https://www.ieee802.org (or the one site named by SICOPR_ASSIST_FETCH_INDEX), for the page, for every zip and after
every redirect. Nothing here plans or runs anything: core.py decides what to download and how
the channels are run, and run.py carries the plan out.

    read_index(url)                 the tools page as text (the page is Windows-1252, served with no charset)
    parse_index(text, url)          its entries, each with its zips: date, interface, size, superseded, do not use
    head_size(url)                  the server's Content-Length for a zip, or None
    download(url, dest, part, ...)  the zip, through a partial file outside the cache: complete, or nothing kept;
                                    stopped once more than max_bytes have arrived
    unpack(zip, folder)             the zip into folder; every member path, the number of files and their size
                                    unpacked are checked before anything is written

How the page gives an entry (read on 7 October 2026): one table row per entry, whose first cell holds
the zip link (its text is the title), then a line with the date in free text (16-May 2023, 12-Sept 2023,
25-July 2022 (25.7M), July-2022), then a presentation link. A row whose first cell holds no link continues the
entry above with more authors and is skipped. The interface is the folder of the link: tools/KR/, tools/CR/, c2c/,
c2m/. A note in the cell that says the files have been superseded covers every zip of that entry; "do not use" in
the text of one link covers only that zip. The date of a zip is the first line under its link that starts with a
date, never a date inside a note. A size is given for a few zips only, in parentheses near the date.

IEEE public-area channel files may be used here. They are never committed or redistributed.
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import datetime
import html.parser
import http.client
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

INDEX_URL = 'https://www.ieee802.org/3/dj/public/tools/index.html'
INDEX_ENV = 'SICOPR_ASSIST_FETCH_INDEX'        # another index URL, for a mirror or a test's local stand-in
PAGE_ENCODING = 'cp1252'
INTERFACE_FOLDERS = ('kr', 'cr', 'c2c', 'c2m')       # the link folders of the page, in the order the tool offers them
INTERFACES = {f: f.upper() for f in INTERFACE_FOLDERS}  # link folder -> interface
TIMEOUT = 60
CHUNK = 1 << 20
MAX_PATH = 260                                  # Windows: a longer path cannot be written or read by default
NESTED_DEPTH = 3
SITE = ('https', 'www.ieee802.org')            # the only site read, unless SICOPR_ASSIST_FETCH_INDEX names another
ZIP_NAME = re.compile(r'[\w.\-]+\.zip')
MAX_RATIO = 20                                  # unpacked size at most this many times the size of the zip,
MIN_UNPACKED = 100 * 10 ** 6                    # or 100 MB for a small zip,
MAX_UNPACKED = 20 * 10 ** 9                     # and never more than 20 GB
MAX_MEMBERS = 20000                             # files in a zip, nested zips counted

_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
           'november', 'december')
_DATE_LINE = re.compile(r'^(?:(\d{1,2})[-\s]+)?([A-Za-z]{3,9})[-\s,]+(\d{4})(?!\d)')
_SIZE = re.compile(r'(\d+(?:\.\d+)?)\s*(GB|MB|G|M)\b')


class FetchError(RuntimeError):
    """The page or a zip could not be read, a download did not complete, or a zip cannot be unpacked safely."""


class FetchRefused(FetchError):
    """A URL that is not on the site the tool reads, a zip name that is not plain, or a download larger than its
    limit. Trying again would give the same answer, so it is not retried."""


def index_url():
    return os.environ.get(INDEX_ENV) or INDEX_URL


def _origin(url):
    p = urllib.parse.urlparse(url)
    return p.scheme.lower(), p.netloc.lower()


def allowed(url):
    """Whether url is on a site the tool reads: https://www.ieee802.org, or the scheme and host of the index named by
    SICOPR_ASSIST_FETCH_INDEX (a mirror, or a test's local stand-in)."""
    sites = {SITE}
    if os.environ.get(INDEX_ENV):
        sites.add(_origin(os.environ[INDEX_ENV]))
    return _origin(url) in sites


def check_url(url):
    """Raise FetchRefused unless url is on a site the tool reads."""
    if not allowed(url):
        raise FetchRefused('%s is not on %s://%s, the only site SiCoPR-Assist downloads from' % (url, SITE[0], SITE[1]))


def plain_zip_name(name):
    """Whether name is a plain zip file name: letters, digits, _, . and - only, ending in .zip, not starting with a
    dot. Only such a name is used for a file in the cache."""
    return bool(ZIP_NAME.fullmatch(name or '')) and not name.startswith('.')


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a site the tool reads."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_Redirects)


def _open(url, timeout, method=None):
    """The response for url, after checking url and, once it is open, the URL it ended at."""
    check_url(url)
    r = _OPENER.open(urllib.request.Request(url, headers=_agent(), method=method), timeout=timeout)
    try:
        check_url(r.geturl())
    except FetchRefused:
        r.close()
        raise
    return r


def _agent():
    from sicopr_assist import __version__
    return {'User-Agent': 'SiCoPR-Assist/%s' % __version__}


# ----------------------------------------------------------------------------- the page
def read_index(url=None, timeout=TIMEOUT):
    """The tools page as text. Raises FetchError when the site cannot be reached or the page is not served."""
    url = url or index_url()
    try:
        with _open(url, timeout) as r:
            data = r.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise FetchError('%s could not be read: %s' % (url, getattr(e, 'reason', None) or e)) from e
    return data.decode(PAGE_ENCODING, errors='replace')


class _Cells(html.parser.HTMLParser):
    """The first cell of every table row, as a list of items: ('text', s), ('br',), ('a', href, text)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._cell = None                        # items of the first cell of the row being read
        self._col = 0
        self._link = None                        # [href, text] while inside a link of the first cell

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self._col = 0
            self._cell = None
        elif tag == 'td':
            self._col += 1
            if self._col == 1:
                self._cell = []
                self.rows.append(self._cell)
        elif self._cell is not None and self._col == 1:
            if tag == 'br':
                self._cell.append(('br',))
            elif tag == 'a':
                self._link = [dict(attrs).get('href') or '', '']

    def handle_endtag(self, tag):
        if tag == 'a' and self._link is not None and self._cell is not None:
            self._cell.append(('a', self._link[0], self._link[1]))
            self._link = None
        elif tag == 'td' and self._col == 1:
            if self._link is not None and self._cell is not None:
                self._cell.append(('a', self._link[0], self._link[1]))
                self._link = None
            self._col = 2 if self._cell is not None else self._col

    def handle_data(self, data):
        if self._cell is None or self._col != 1:
            return
        if self._link is not None:
            self._link[1] += data
        else:
            self._cell.append(('text', data))


def _squash(text):
    return ' '.join(str(text).split())


def parse_date(line):
    """(ISO date, True when the day is given) for a line that starts with a date, else None. A date with no day
    (July-2022) is taken as the first of its month."""
    m = _DATE_LINE.match(line.strip())
    if not m:
        return None
    word = m.group(2).lower()
    month = next((i for i, name in enumerate(_MONTHS, 1) if name.startswith(word) and len(word) >= 3), None)
    if month is None:
        return None
    day = int(m.group(1)) if m.group(1) else 1
    try:
        return datetime.date(int(m.group(3)), month, day).isoformat(), bool(m.group(1))
    except ValueError:
        return None


def size_mb(text):
    """The size a page gives in parentheses, in MB (1 MB = 1e6 bytes), or None: (21.7M), (Note - 600 MB file),
    (Note 1.1 GB file)."""
    for inside in re.findall(r'\(([^()]*)\)', text):
        m = _SIZE.search(inside)
        if m:
            return float(m.group(1)) * (1000.0 if m.group(2).startswith('G') else 1.0)
    return None


def interface_of(url):
    """KR, CR, C2C or C2M from the folder that holds the zip (tools/KR/x.zip), else None."""
    parts = urllib.parse.urlparse(url).path.split('/')
    return INTERFACES.get(parts[-2].lower()) if len(parts) >= 2 else None


def parse_index(text, url=None):
    """The entries of the page, newest first as the page lists them. Each entry is
    {'name', 'title', 'superseded' (the note, or None), 'zips': [...]}, and each zip is {'url', 'name', 'text',
    'interface', 'date', 'day_given', 'date_text', 'size_mb', 'size_text', 'do_not_use'}. Relative links are
    resolved against the page's URL. Rows whose first cell holds no zip link are left out."""
    url = url or index_url()
    p = _Cells()
    p.feed(text)
    p.close()
    entries = []
    for items in p.rows:
        zips, pending, line, after, notes = [], [], '', {}, []
        cell_text = []

        def end_line():
            ln = _squash(line)
            if not ln:
                return
            if 'superseded' in ln.lower():
                notes.append(ln)
            for z in list(pending):
                after[z['url']].append(ln)
            got = parse_date(ln) if pending else None
            if got:
                for z in pending:
                    z['date'], z['day_given'] = got
                    z['date_text'] = ln
                    seen = ' '.join(after[z['url']])
                    z['size_mb'] = size_mb(seen)
                    z['size_text'] = next((s for s in re.findall(r'\([^()]*\)', seen) if size_mb(s) is not None), None)
                pending.clear()

        for it in items:
            if it[0] == 'br':
                end_line()
                line = ''
            elif it[0] == 'text':
                line += it[1]
                cell_text.append(it[1])
            else:
                href, ltext = it[1], _squash(it[2])
                if href.split('?')[0].lower().endswith('.zip'):
                    zurl = urllib.parse.urljoin(url, href.strip())
                    z = {'url': zurl, 'name': os.path.basename(urllib.parse.urlparse(zurl).path), 'text': ltext,
                         'interface': interface_of(zurl), 'date': None, 'day_given': False, 'date_text': None,
                         'size_mb': None, 'size_text': None, 'do_not_use': 'do not use' in ltext.lower()}
                    zips.append(z)
                    pending.append(z)
                    after[zurl] = []
                else:
                    line += ' '
        end_line()
        if not zips:
            continue
        for z in pending:                        # a zip with no date line under it: the page gives none
            seen = ' '.join(after[z['url']])
            z['size_mb'] = size_mb(seen)
        entries.append({'name': os.path.splitext(zips[0]['name'])[0], 'title': zips[0]['text'],
                        'superseded': notes[0] if notes else None, 'zips': zips})
    return entries


def head_size(url, timeout=TIMEOUT):
    """The server's Content-Length for url, in bytes, or None when it gives none or cannot be asked (a URL off the
    site the tool reads is not asked)."""
    try:
        with _open(url, timeout, method='HEAD') as r:
            n = r.headers.get('Content-Length')
    except (FetchError, urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return None
    try:
        return int(n) if n is not None else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------- the download
def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _too_big(n, max_bytes):
    return FetchRefused('the download passed %d MB, more than its limit of %d MB (max_download_mb), so it was stopped'
                        % (n // 1000000, max_bytes // 1000000))


def _get(url, part, say, timeout, max_bytes=None):
    t0 = time.time()
    with _open(url, timeout) as r:
        total = r.headers.get('Content-Length')
        total = int(total) if total and total.isdigit() else None
        if max_bytes is not None and total is not None and total > max_bytes:
            raise _too_big(total, max_bytes)
        got, shown = 0, 0
        with open(part, 'wb') as f:
            while True:
                block = r.read(CHUNK)
                if not block:
                    break
                f.write(block)
                got += len(block)
                if max_bytes is not None and got > max_bytes:   # a server that gives no size, or the wrong one
                    raise _too_big(got, max_bytes)
                if say and total and got * 10 // total > shown:
                    shown = got * 10 // total
                    say('%d of %d MB (%d %%)' % (got // 1000000, total // 1000000, 100 * got // total))
    if total is not None and got != total:
        raise FetchError('the server sent %d of %d bytes' % (got, total))
    if not zipfile.is_zipfile(part):
        raise FetchError('what arrived (%d bytes) is not a zip file' % got)
    return got, time.time() - t0


def download(url, dest, part, retries=1, say=None, timeout=TIMEOUT, max_bytes=None):
    """Download url to dest through the partial file part, which lies outside the cache. The download is tried
    1 + retries times, and stopped once more than max_bytes have arrived (None: no limit). A complete zip is moved to
    dest; anything else is removed, so the cache holds a zip only when it arrived whole. Returns {'bytes', 'seconds',
    'tries'}; raises FetchError when every try failed, and FetchRefused at once for a URL off the site the tool reads,
    a redirect away from it, a zip name that is not plain, or a download over max_bytes."""
    if not plain_zip_name(os.path.basename(dest)):
        raise FetchRefused('%r is not a plain zip file name, so it is not downloaded' % os.path.basename(dest))
    check_url(url)
    os.makedirs(os.path.dirname(part), exist_ok=True)
    last = None
    for k in range(1 + max(0, int(retries))):
        try:
            got, took = _get(url, part, say, timeout, max_bytes)
        except FetchRefused:
            _remove(part)
            raise
        except (FetchError, urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            _remove(part)
            last = getattr(e, 'reason', None) or e
            if say:
                say('try %d of %d did not complete: %s' % (k + 1, 1 + retries, last))
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(part, dest)
        return {'bytes': got, 'seconds': took, 'tries': k + 1}
    _remove(part)
    raise FetchError('%d %s did not complete, the last one: %s' % (1 + retries, 'try' if retries == 0 else 'tries',
                                                                     last))


# ----------------------------------------------------------------------------- unpacking
def member_parts(name):
    """The parts of a zip member path, or None when it would leave the folder it is unpacked into: an absolute
    path (/x, \\x, C:\\x or C:x), a .. part, or a part with a colon. Both / and \\ separate parts."""
    n = name.replace('\\', '/')
    if n.startswith('/') or re.match(r'^[A-Za-z]:', n):
        return None
    parts = [x for x in n.split('/') if x not in ('', '.')]
    if any(x == '..' or ':' in x for x in parts):
        return None
    return parts


def _inside(folder, target):
    a = os.path.realpath(folder)
    b = os.path.realpath(target)
    return os.path.normcase(os.path.commonpath([a, b])) == os.path.normcase(a)


def unpack(zip_path, folder, depth=0):
    """Unpack zip_path into folder. Every member path is checked to stay inside folder before anything is written;
    one that does not stops the unpacking with nothing written. So does a zip that would unpack to more than
    MAX_MEMBERS files, or to more than MAX_RATIO times its own size (MIN_UNPACKED at least, MAX_UNPACKED at most);
    the files of a nested zip count against the same limits. A zip inside the zip is unpacked in place, into a folder
    named after it, with the same checks, and then removed. Returns {'files': [paths relative to folder, with /], 'warnings': [...]}; raises
    FetchError, and on any failure folder is removed."""
    size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0
    budget = {'bytes': min(MAX_UNPACKED, max(MIN_UNPACKED, MAX_RATIO * size)), 'members': MAX_MEMBERS}
    try:
        return _unpack(zip_path, folder, depth, budget)
    except FetchError:
        if depth == 0:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError) as e:
        if depth == 0:
            shutil.rmtree(folder, ignore_errors=True)
        raise FetchError('%s could not be unpacked: %s' % (os.path.basename(zip_path), e)) from e


def long_path_warning(path):
    """A warning for a path Windows cannot write or read by default (MAX_PATH), else None."""
    n = len(os.path.abspath(path))
    if n < MAX_PATH:
        return None
    return ('%s is %d characters long, more than the %d that Windows allows by default: unpack the zip in a folder '
            'with a shorter path' % (os.path.abspath(path), n, MAX_PATH - 1))


def _spend(zip_path, infos, budget):
    """Take the files of one zip from the budget left, or raise FetchRefused when they do not fit."""
    n = sum(1 for i in infos if not i.is_dir())
    size = sum(i.file_size for i in infos if not i.is_dir())
    if n > budget['members'] or size > budget['bytes']:
        raise FetchRefused('%s would unpack to %d files of %d MB in all, more than is left of the limit (%d files '
                           'and %d MB; the limit is %d times the size of the zip, at most %d GB). Nothing was unpacked'
                           % (os.path.basename(zip_path), n, size // 1000000, budget['members'],
                              budget['bytes'] // 1000000, MAX_RATIO, MAX_UNPACKED // 10 ** 9))
    budget['members'] -= n
    budget['bytes'] -= size


def _unpack(zip_path, folder, depth, budget):
    files = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        bad = [i.filename for i in infos if member_parts(i.filename) is None or
               (member_parts(i.filename) and not _inside(folder, os.path.join(folder, *member_parts(i.filename))))]
        if bad:
            raise FetchError('%s holds %s that would leave the folder it is unpacked into: %s. Nothing was unpacked'
                             % (os.path.basename(zip_path), 'a path' if len(bad) == 1 else '%d paths' % len(bad),
                                ', '.join(repr(b) for b in bad[:5])))
        _spend(zip_path, infos, budget)
        warnings = [w for w in (long_path_warning(os.path.join(folder, *member_parts(i.filename)))
                                for i in infos if member_parts(i.filename)) if w]
        os.makedirs(folder, exist_ok=True)
        for info in infos:
            parts = member_parts(info.filename)
            if not parts:
                continue
            target = os.path.join(folder, *parts)
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
            except OSError as e:
                raise FetchError('%s could not be written: %s%s' % ('/'.join(parts), e, ''.join(
                    '; %s' % w for w in warnings[:3]))) from e
            rel = '/'.join(parts)
            if rel.lower().endswith('.zip') and depth < NESTED_DEPTH and zipfile.is_zipfile(target):
                inner = target[:-len('.zip')]
                got = _unpack(target, inner, depth + 1, budget)
                os.remove(target)
                stem = rel[:-len('.zip')]
                files += ['%s/%s' % (stem, f) for f in got['files']]
                warnings += got['warnings']
            else:
                files.append(rel)
    return {'files': sorted(files), 'warnings': warnings}

"""A local stand-in for the IEEE P802.3dj tools page and its zips, so tests never touch the network.

The page is written by the test in the markup recorded from the real page on 7 October 2026: a reduced copy of its structure, not the saved page. One table row per entry; the first cell holds the zip link
(its text is the title), a line with the date in free text, then a presentation link; a superseded note in the
cell, before or after the links; "do not use" inside one link's text; a row with an empty first cell that only
continues the authors of the entry above; one relative link; Windows-1252 bytes; sections for MTF data (not an
interface), CR and KR together, C2C and C2M. The zips hold small Touchstone files written by the test.

    site = Site()                          files served at http://127.0.0.1:<port>/s<k>/ by one local server
    site.add(path, data, interrupt=False)  a file; interrupt: the body stops halfway, as a dropped download;
                                           length=False: no Content-Length, the body ends when the connection closes
    site.redirect(path, url)               a 302 to url
    site.url(path), site.hits(path)        its URL, and how many GET and HEAD requests it had
    page(sections, base)                   the page as bytes, in the recorded markup
    zip_bytes(files)                       a zip of {member path: bytes}
"""
# Copyright 2026 Todd Bermensolo
# SPDX-License-Identifier: BSD-3-Clause
import http.server
import io
import threading
import zipfile

_FILES = {}
_SERVER = []
_LOCK = threading.Lock()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _file(self):
        return _FILES.get(self.path.split('?')[0])

    def _head(self, f):
        if f.get('to'):
            self.send_response(302)
            self.send_header('Location', f['to'])
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', f['type'])
        if f['length']:
            self.send_header('Content-Length', str(len(f['data'])))
        else:
            self.close_connection = True
        self.end_headers()

    def do_HEAD(self):
        f = self._file()
        if f is None:
            self.send_error(404)
            return
        f['heads'] += 1
        self._head(f)

    def do_GET(self):
        f = self._file()
        if f is None:
            self.send_error(404)
            return
        f['gets'] += 1
        self._head(f)
        if f.get('to'):
            return
        if f['interrupt']:
            self.wfile.write(f['data'][:len(f['data']) // 2])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(f['data'])


def _server():
    with _LOCK:
        if not _SERVER:
            srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _SERVER.append(srv)
        return _SERVER[0]


class Site:
    """One stand-in site: a URL prefix of the local server, with the files a test adds to it."""
    _k = [0]

    def __init__(self):
        srv = _server()
        with _LOCK:
            Site._k[0] += 1
            self.prefix = '/s%d' % Site._k[0]
        self.base = 'http://127.0.0.1:%d%s' % (srv.server_address[1], self.prefix)

    def add(self, path, data, interrupt=False, ctype='application/zip', length=True):
        _FILES[self.prefix + '/' + path.lstrip('/')] = {'data': data, 'interrupt': interrupt, 'type': ctype,
                                                        'length': length, 'gets': 0, 'heads': 0}
        return self.url(path)

    def redirect(self, path, to):
        _FILES[self.prefix + '/' + path.lstrip('/')] = {'to': to, 'gets': 0, 'heads': 0}
        return self.url(path)

    def url(self, path):
        return self.base + '/' + path.lstrip('/')

    def hits(self, path):
        f = _FILES[self.prefix + '/' + path.lstrip('/')]
        return f['gets'], f['heads']


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


# ----------------------------------------------------------------------------- the page, in the recorded markup
_HEAD = '''<!-- /groups/802/3/dj/index.html -->

<html>
<head>
	<title>P802.3dj Channel / Tool</title>
</head>
<body>
	<table border="0" cellpadding="0" cellspacing="0" width="100%" id="AutoNumber1">
		<tr>
			<td width="10%"></td>
			<td width="80%"><center><h1>IEEE P802.3dj </h1><h1>Tools and Channel Data Area<br>(After 27 Jan 2024)</h1></center></td>
		</tr>
	</table>
	<h2 class="auto-style2">COM</h2>
	<p class="auto-style7"><a href="https://www.ieee802.org/3/ad_hoc/COM/public/index.html">IEEE 802.3 COM Open Source Project</a></p>
'''
_TAIL = '''	<hr>
	<center><p><a href="../index.html">Return to the IEEE P802.3dj Public Area</a><br>Last Update: 16-Dec 2025</p></center>
</body>
</html>
'''
_PAD = '&nbsp;&nbsp;&nbsp;&nbsp;'


def _entry_row(e, k):
    """One entry: {'zips': [(href, text)], 'date', 'size' (after the date, as '(21.7M)'), 'link_note' (after the
    first link, as '(Note - 600 MB file)'), 'note_before', 'note_after', 'title_before', 'authors', 'company'}."""
    cls = 'auto-style4' if k % 2 else 'auto-style5'
    cell = []
    if e.get('note_before'):
        cell.append('\t\t\t%s<br><br>' % e['note_before'])
    if e.get('title_before'):
        cell.append('\t\t\t%s <br>%s' % (e['title_before'], _PAD))
    for i, (href, text) in enumerate(e['zips']):
        tail = ' %s' % e['link_note'] if i == 0 and e.get('link_note') else ''
        cell.append('\t\t\t<a href="%s">\n\t\t\t%s</a>%s<br>' % (href, text, tail))
    cell.append('%s \n\t\t\t%s%s<br>%s' % (_PAD, e['date'], ' %s' % e['size'] if e.get('size') else '', _PAD))
    cell.append('\t\t\t<a href="https://www.ieee802.org/3/dj/public/26_09/standin_%d.pdf">\n\t\t\tSupporting '
                'Presentation</a>' % k)
    if e.get('note_after'):
        cell.append('<br><br>%s Note - \n\t\t\t%s ' % (_PAD, e['note_after']))
    rows = ['\t\t<tr>\n\t\t\t<td style="width: 1020px; height: 55" valign="top" class="%s">\n%s</td>\n'
            '\t\t\t<td style="width: 502px; height: 55" valign="top" class="%s">\n\t\t\t%s</td>\n'
            '\t\t\t<td style="height: 55; width: 576px;" valign="top" class="%s">\n\t\t\t%s</td>\n\t\t</tr>\n'
            % (cls, '\n'.join(cell), cls, e.get('authors', 'A. Author<br>B. Author'), cls,
               e.get('company', 'Stand-in Company'))]
    if e.get('continuation'):
        rows.append('\t\t<tr>\n\t\t\t<td style="width: 1020px; height: 55" valign="top" class="%s">\n\t\t\t&nbsp;</td>\n'
                    '\t\t\t<td style="width: 502px; height: 55" valign="top" class="%s">\n\t\t\t%s</td>\n'
                    '\t\t\t<td style="height: 55; width: 576px;" valign="top" class="%s">\n\t\t\tOther Company</td>\n'
                    '\t\t</tr>\n' % (cls, cls, e['continuation'], cls))
    return ''.join(rows)


def page(sections):
    """The page as Windows-1252 bytes. sections: [(heading level 'h2' or 'h3', heading, [entry, ...])]; an h2
    section opens a table of its own, an h3 section is a heading row inside the current table, as on the page."""
    out = [_HEAD]
    open_table = False
    k = 0
    for level, heading, entries in sections:
        if level == 'h2':
            if open_table:
                out.append('\t\t</table>\n')
            out.append('\t<h2 class="auto-style2">%s</h2>\n\n    <table align="center" style="width: 100%%; height: 30;" '
                       'class="auto-style5">\n' % heading)
            open_table = True
        else:
            out.append('\t\t<tr>\n\t\t\t<td style="width: 1020px; height: 30px" valign="top">\n\t\t\t<h3 class='
                       '"auto-style2">%s</h3>\n\t\t\t</td>\n\t\t\t<td style="width: 502px; height: 30px" valign="top">'
                       '&nbsp;</td>\n\t\t\t<td style="height: 30px; width: 576px;" valign="top">&nbsp;</td>\n\t\t</tr>\n'
                       % heading)
        for e in entries:
            k += 1
            out.append(_entry_row(e, k))
    if open_table:
        out.append('\t\t</table>\n\n')
    out.append(_TAIL)
    return ''.join(out).encode('cp1252')

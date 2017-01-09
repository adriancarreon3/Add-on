# -*- coding: utf-8 -*-

from __future__ import print_function
from json import loads
import os
from os.path import join as pjoin
import os.path
from pprint import pformat
import re
import shutil
import sys
import tempfile
import time
from unicodedata import normalize
from urllib import FancyURLopener, unquote, quote_plus, urlencode, quote
from urlparse import parse_qs

try:
    import xbmc
except ImportError:
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        import unittest  # NOQA
        try:
            import mock  # NOQA
        except ImportError:
            print("TARADO!.\n")
            sys.exit(1)
else:
    from xbmc import (LOGDEBUG, LOGINFO, LOGNOTICE, LOGWARNING, LOGERROR,
                      LOGSEVERE, LOGFATAL, LOGNONE)
    import xbmcaddon
    import xbmcgui
    import xbmcplugin
    import xbmcvfs

__addon__ = xbmcaddon.Addon()
__author__     = __addon__.getAddonInfo('author')
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__    = __addon__.getAddonInfo('version')
__language__   = __addon__.getLocalizedString

__cwd__        = xbmc.translatePath(__addon__.getAddonInfo('path').decode("utf-8"))
__profile__    = xbmc.translatePath(__addon__.getAddonInfo('profile').decode("utf-8"))


MAIN_SUBDIVX_URL = "http://www.subdivx.com/"
SEARCH_PAGE_URL = MAIN_SUBDIVX_URL + \
    "index.php?accion=5&masdesc=&oxdown=1&pg=%(page)s&buscar=%(query)s"

INTERNAL_LINK_URL_BASE = "plugin://%s/?"
SUB_EXTS = ['srt', 'sub', 'txt']
HTTP_USER_AGENT = "User-Agent=Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2.3) Gecko/20100401 Firefox/3.6.3 ( .NET CLR 3.5.30729)"

PAGE_ENCODING = 'latin1'


# Parametros de expresiones regulares

SUBTITLE_RE = re.compile(r'''<a\s+class="titulo_menu_izq2?"\s+
                         href="http://www.subdivx.com/(?P<subdivx_id>.+?)\.html">
                         .+?<img\s+src="img/calif(?P<calif>\d)\.gif"\s+class="detalle_calif"\s+name="detalle_calif">
                         .+?<div\s+id="buscador_detalle_sub">(?P<comment>.*?)</div>
                         .+?<b>Downloads:</b>(?P<downloads>.+?)
                         <b>Cds:</b>
                         .+?<b>Subido\ por:</b>\s*<a.+?>(?P<uploader>.+?)</a>.+?</div></div>''',
                         re.IGNORECASE | re.DOTALL | re.VERBOSE | re.UNICODE |
                         re.MULTILINE)

DETAIL_PAGE_LINK_RE = re.compile(r'<a rel="nofollow" class="detalle_link" href="http://www.subdivx.com/(?P<id>.*?)"><b>Bajar</b></a>',
                                 re.IGNORECASE | re.DOTALL | re.MULTILINE | re.UNICODE)

DOWNLOAD_LINK_RE = re.compile(r'bajar.php\?id=(?P<id>.*?)&u=(?P<u>[^"\']+?)', re.IGNORECASE |
                              re.DOTALL | re.MULTILINE | re.UNICODE)

# Aqui estan las funciones


def es_archivo_subtitulos(fn):
    """Detectar si el archivo tiene una extensión que reconocemos como subtítulo"""
    ext = fn.split('.')[-1]
    return ext.upper() in [e.upper() for e in SUB_EXTS]


def log(msg, level=LOGDEBUG):
    fname = sys._getframe(1).f_code.co_name
    s = u"SUBDIVX - %s: %s" % (fname, msg)
    xbmc.log(s.encode('utf-8'), level=level)


def get_url(url):
    class MyOpener(FancyURLopener):
        version = ''
    my_urlopener = MyOpener()
    log(u"Fetching %s" % url)
    try:
        response = my_urlopener.open(url)
        content = response.read()
    except Exception:
        log(u"Failed to fetch %s" % url, level=LOGWARNING)
        content = None
    return content


def get_todos_subs(searchstring, languageshort, file_orig_path):
    if languageshort != "es":
        return []
    subs_list = []
    page = 1
    while True:
        log(u"Trying page %d" % page)
        url = SEARCH_PAGE_URL % {'page': page,
                                 'query': quote_plus(searchstring)}
        content = get_url(url)
        if content is None or not SUBTITLE_RE.search(content):
            break
        for match in SUBTITLE_RE.finditer(content):
            groups = match.groupdict()

            subdivx_id = groups['subdivx_id']

            dls = re.sub(r'[,.]', '', groups['downloads'])
            downloads = int(dls)

            descr = groups['comment']
            # Remover lineas nuevas
            descr = re.sub('\n', ' ', descr)
            # Remover Google Adds
            descr = re.sub(r'<script.+?script>', '', descr,
                           re.IGNORECASE | re.DOTALL | re.MULTILINE |
                           re.UNICODE)
            # Eliminar las etiquetas HTML
            descr = re.sub(r'<[^<]+?>', '', descr)
            descr = descr.rstrip(' \t')

            # Si el nombre de nuestro archivo de video real aparece en la descripción, entonces establezca la sincronización en True porque tiene mejores posibilidades de que su sincronización coincida
            _, fn = os.path.split(file_orig_path)
            name, _ = os.path.splitext(fn)
            sync = re.search(re.escape(name), descr, re.I) is not None

            try:
                log(u'Subtitles found: (subdivx_id = %s) "%s"' % (subdivx_id,
                                                                  descr))
            except Exception:
                pass
            item = {
                'descr': descr.decode(PAGE_ENCODING),
                'sync': sync,
                'subdivx_id': subdivx_id.decode(PAGE_ENCODING),
                'uploader': groups['uploader'],
                'downloads': downloads,
                'score': int(groups['calif']),
            }
            subs_list.append(item)
        page += 1

    # Poner subs con sync= True en la parte superior
    subs_list = sorted(subs_list, key=lambda s: s['sync'], reverse=True)
    return subs_list


def calcular_ratings(subs_list):
    max_dl_count = 0
    for sub in subs_list:
        dl_cnt = sub.get('downloads', 0)
        if dl_cnt > max_dl_count:
            max_dl_count = dl_cnt
    for sub in subs_list:
        if max_dl_count:
            sub['rating'] = int((sub['downloads'] / float(max_dl_count)) * 5)
        else:
            sub['rating'] = 0
    log(u"subs_list = %s" % pformat(subs_list))


def agregar_subtitulos(item, filename):
    if __addon__.getSetting('show_nick_in_place_of_lang') == 'true':
        item_label = item['uploader']
    else:
        item_label = 'Spanish'
    listitem = xbmcgui.ListItem(
        label=item_label,
        label2=item['descr'],
        #iconImage=str(item['rating']),
        thumbnailImage=''
    )
    listitem.setProperty("sync", 'true' if item["sync"] else 'false')
    listitem.setProperty("hearing_imp",
                         'true' if item.get("hearing_imp", False) else 'false')

    url = INTERNAL_LINK_URL_BASE % __scriptid__
    xbmc_url = construir_xbmc_item_url(url, item, filename)
    # Añadir a la lista, esto se puede hacer tantas veces como sea necesario para todos los subtítulos encontrados
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                url=xbmc_url,
                                listitem=listitem,
                                isFolder=False)


def construir_xbmc_item_url(url, item, filename):
    # Devolver una pseudo-url interna de Kodi para el resultado de búsqueda secundaria
    try:
        xbmc_url = url + urlencode((('id', item['subdivx_id']),
                                    ('filename', filename)))
    except UnicodeEncodeError:
        try:
            subdivx_id = item['subdivx_id'].encode(PAGE_ENCODING)
            xbmc_url = url + urlencode((('id', subdivx_id),
                                        ('filename', filename)))
        except Exception:
            log('Problematic subdivx_id: %s' % subdivx_id)
            raise
    return xbmc_url


def Search(item):
    # Se llama cuando se solicita la descarga de subtítulos en XBMC
    file_original_path = item['file_original_path']
    title = item['title']
    tvshow = item['tvshow']
    season = item['season']
    episode = item['episode']

    if item['manual_search']:
        searchstring = unquote(item['manual_search_string'])
    elif tvshow:
        searchstring = "%s S%#02dE%#02d" % (tvshow, int(season), int(episode))
    else:
        searchstring = title
    log(u"Search string = %s" % searchstring)

    subs_list = get_todos_subs(searchstring, "es", file_original_path)

    calcular_ratings(subs_list)

    for sub in subs_list:
        agregar_subtitulos(sub, file_original_path)


def _esperar_por_extraccion(workdir, base_filecount, base_mtime, limit):
    waittime = 0
    filecount = base_filecount
    newest_mtime = base_mtime
    while (filecount == base_filecount and waittime < limit and
           newest_mtime == base_mtime):
        time.sleep(1)
        files = os.listdir(workdir)
        filecount = len(files)
        for fname in files:
            if not es_archivo_subtitulos(fname):
                continue
            fname = fname
            mtime = os.stat(pjoin(workdir, fname)).st_mtime
            if mtime > newest_mtime:
                newest_mtime = mtime
        waittime += 1
    return waittime != limit


def _manejar_subtitulosComprimidos(workdir, compressed_file):
    MAX_UNZIP_WAIT = 15
    files = os.listdir(workdir)
    filecount = len(files)
    max_mtime = 0
    # Determinar el archivo más reciente
    for fname in files:
        if not es_archivo_subtitulos(fname):
            continue
        mtime = os.stat(pjoin(workdir, fname)).st_mtime
        if mtime > max_mtime:
            max_mtime = mtime
    base_mtime = max_mtime
    # Espere 2 segundos para que los archivos descomprimidos sean al menos 1 segundo más nuevos
    time.sleep(2)
    xbmc.executebuiltin("XBMC.Extract(%s, %s)" % (
                        compressed_file.encode("utf-8"),
                        workdir.encode("utf-8")))

    retval = False
    if _esperar_por_extraccion(workdir, filecount, base_mtime, MAX_UNZIP_WAIT):
        files = os.listdir(workdir)
        for fname in files:
            # Podría haber más archivos de subtítulos, así que seguro que obtenemos el archivo de subtítulos recién creado
            if not es_archivo_subtitulos(fname):
                continue
            fname = fname
            fpath = pjoin(workdir, fname)
            if os.stat(fpath).st_mtime > base_mtime:
                # Archivo descomprimido recien cerado
                retval = True
                break

    if retval:
        log(u"Archivo de subtitulos descomprimido '%s'" % normalize_string(fpath))
    else:
        log(u"Error al descomprimir subtitulos", level=LOGSEVERE)
    return retval, fpath

def rmgeneric(path, __func__):
    try:
        __func__(path)
        log(u"Borrado %s" % normalize_string(path))
    except OSError, (errno, strerror):
        log(u"Error al borrar %(path)s, %(error)s" % {'path' : normalize_string(path), 'error': strerror }, level=LOGFATAL)

def BorrarTodos(dir):
    if not os.path.isdir(dir):
      return
    files = os.listdir(dir)
    for file in files:
      if os.path.isdir(pjoin(dir, file)):
        BorrarTodos(file)
      else:
        f=os.remove
        rmgeneric(pjoin(dir, file), f)
    f=os.rmdir
    rmgeneric(dir, f)

def ensure_workdir(workdir):
    if xbmcvfs.exists(workdir):
        BorrarTodos(workdir)
    xbmcvfs.mkdirs(workdir)
    return xbmcvfs.exists(workdir)

def _salvar_subtitulos(workdir, content):
    header = content[:4]
    if header == 'Rar!':
        type = '.rar'
        is_compressed = True
    elif header == 'PK\x03\x04':
        type = '.zip'
        is_compressed = True
    else:
        # Nunca encontró / descargó un archivo de subtítulos descomprimido, supongamos que el subarchivo descomprimido sea un '.srt'
        type = '.srt'
        is_compressed = False
    tmp_fname = pjoin(workdir, "subdivx" + type)
    log(u"Saving subtitles to '%s'" % tmp_fname)
    try:
        with open(tmp_fname, "wb") as fh:
            fh.write(content)
    except Exception:
        log(u"Failed to save subtitles to '%s'" % tmp_fname, level=LOGSEVERE)
        return None
    else:
        if is_compressed:
            rval, fname = _manejar_subtitulosComprimidos(workdir, tmp_fname)
            if rval:
                return fname
        else:
            return tmp_fname
    return None


def Download(subdivx_id, workdir):
    subtitle_detail_url = MAIN_SUBDIVX_URL + quote(subdivx_id)
    html_content = get_url(subtitle_detail_url)
    if html_content is None:
        log(u"No content found in selected subtitle intermediate detail/final download page",
            level=LOGFATAL)
        return []
    match = DETAIL_PAGE_LINK_RE.search(html_content)
    if match is None:
        log(u"Intermediate detail page for selected subtitle or expected content not found. Handling it as final download page",
            level=LOGWARNING)
    else:
        id_ = match.group('id')
        html_content = get_url(MAIN_SUBDIVX_URL + id_)
    if html_content is None:
        log(u"No content found in final download page", level=LOGFATAL)
        return []
    match = DOWNLOAD_LINK_RE.search(html_content)
    if match is None:
        log(u"Expected content not found in final download page",
            level=LOGFATAL)
        return []
    id_, u = match.group('id', 'u')
    actual_subtitle_file_url = MAIN_SUBDIVX_URL + "bajar.php?id=" + id_ + "&u=" + u
    content = get_url(actual_subtitle_file_url)
    if content is None:
        log(u"Got no content when downloading actual subtitle file",
            level=LOGFATAL)
        return []
    saved_fname = _salvar_subtitulos(workdir, content)
    if saved_fname is None:
        return []
    return [saved_fname]


def _double_dot_fix_hack(video_filename):

    log(u"video_filename = %s" % video_filename)

    work_path = video_filename
    if _subtitles_setting('storagemode'):
        custom_subs_path = _subtitles_setting('custompath')
        if custom_subs_path:
            _, fname = os.path.split(video_filename)
            work_path = pjoin(custom_subs_path, fname)

    log(u"work_path = %s" % work_path)
    parts = work_path.rsplit('.', 1)
    if len(parts) > 1:
        rest = parts[0]
        bad = rest + '..' + 'srt'
        old = rest + '.es.' + 'srt'
        if xbmcvfs.exists(bad):
            log(u"%s exists" % bad)
            if xbmcvfs.exists(old):
                log(u"%s exists, renaming" % old)
                xbmcvfs.delete(old)
            log(u"renaming %s to %s" % (bad, old))
            xbmcvfs.rename(bad, old)


def _subtitles_setting(name):
    command = '''{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "Settings.GetSettingValue",
    "params": {
        "setting": "subtitles.%s"
    }
}'''
    result = xbmc.executeJSONRPC(command % name)
    py = loads(result)
    if 'result' in py and 'value' in py['result']:
        return py['result']['value']
    else:
        raise ValueError


def normalize_string(str):
    return normalize('NFKD', unicode(unicode(str, 'utf-8'))).encode('ascii',
                                                                    'ignore')

def get_params(argv):
    params = {}
    qs = argv[2].lstrip('?')
    if qs:
        if qs.endswith('/'):
            qs = qs[:-1]
        parsed = parse_qs(qs)
        for k, v in parsed.iteritems():
            params[k] = v[0]
    return params

def debug_dump_path(victim, name):
    t = type(victim)
    xbmc.log("%s (%s): %s" % (name, t, victim), level=LOGDEBUG)


def main():
    params = get_params(sys.argv)
    action = params.get('action', 'Unknown')
    xbmc.log(u"SUBDIVX - Version: %s -- Action: %s" % (__version__, action), level=LOGINFO)

    if action in ('search', 'manualsearch'):
        item = {
            'temp': False,
            'rar': False,
            'year': xbmc.getInfoLabel("VideoPlayer.Year"),
            'season': str(xbmc.getInfoLabel("VideoPlayer.Season")),
            'episode': str(xbmc.getInfoLabel("VideoPlayer.Episode")),
            'tvshow': normalize_string(xbmc.getInfoLabel("VideoPlayer.TVshowtitle")),
            # Trata de obtener el titulo
            'title': normalize_string(xbmc.getInfoLabel("VideoPlayer.OriginalTitle")),
            # Ruta completa de un archivo de reproducción
            'file_original_path': unquote(xbmc.Player().getPlayingFile().decode('utf-8')),
            '3let_language': [],
            '2let_language': [],
            'manual_search': 'searchstring' in params,
        }

        if 'searchstring' in params:
            item['manual_search_string'] = params['searchstring']

        for lang in unquote(params['languages']).decode('utf-8').split(","):
            item['3let_language'].append(xbmc.convertLanguage(lang, xbmc.ISO_639_2))
            item['2let_language'].append(xbmc.convertLanguage(lang, xbmc.ISO_639_1))

        if not item['title']:
            # No hay título original, solo Título
            item['title'] = normalize_string(xbmc.getInfoLabel("VideoPlayer.Title"))

        if "s" in item['episode'].lower():
            # Verificar si es una temporada "Especial"
            item['season'] = "0"
            item['episode'] = item['episode'][-1:]

        if "http" in item['file_original_path']:
            item['temp'] = True

        elif "rar://" in item['file_original_path']:
            item['rar'] = True
            item['file_original_path'] = os.path.dirname(item['file_original_path'][6:])

        elif "stack://" in item['file_original_path']:
            stackPath = item['file_original_path'].split(" , ")
            item['file_original_path'] = stackPath[0][8:]

        Search(item)

    elif action == 'download':
        debug_dump_path(xbmc.translatePath(__addon__.getAddonInfo('profile')),
                        "xbmc.translatePath(__addon__.getAddonInfo('profile'))")
        debug_dump_path(__profile__, '__profile__')
        xbmcvfs.mkdirs(__profile__)
        workdir = pjoin(__profile__, 'temp')
        workdir = workdir + os.path.sep
        workdir = xbmc.translatePath(workdir)

        ensure_workdir(workdir)
        subs = Download(params["id"], workdir)
        for sub in subs:
            listitem = xbmcgui.ListItem(label=sub)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=sub,
                                        listitem=listitem, isFolder=False)

    # Enviar final del directorio a XBMC
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

    if (action == 'download' and
            __addon__.getSetting('show_nick_in_place_of_lang') == 'true'):
        time.sleep(3)
        _double_dot_fix_hack(params['filename'])


if __name__ == '__main__':
    main()

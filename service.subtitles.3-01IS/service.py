# -*- coding: utf-8 -*-

import os
import sys
import xbmc
import urllib
import xbmcvfs
import xbmcaddon
import xbmcgui
import xbmcplugin
import shutil
import unicodedata
import re
import string
import json

__addon__ = xbmcaddon.Addon()
__author__ = __addon__.getAddonInfo('author')
__scriptid__ = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__ = __addon__.getAddonInfo('version')
__language__ = __addon__.getLocalizedString

__cwd__ = xbmc.translatePath(
    __addon__.getAddonInfo('path')
).decode("utf-8")
__profile__ = xbmc.translatePath(
    __addon__.getAddonInfo('profile')
).decode("utf-8")
__resource__ = xbmc.translatePath(
    os.path.join(__cwd__, 'resources', 'lib')
).decode("utf-8")
__temp__ = xbmc.translatePath(
    os.path.join(__profile__, 'temp')
).decode("utf-8")
__temp__ = __temp__ + os.path.sep

sys.path.append(__resource__)

from Funciones_Extra import log, geturl

api_search_url = "http://argenteam.net/api/v1/search"
api_tvshow_url = "http://argenteam.net/api/v1/tvshow"
api_episode_url = "http://argenteam.net/api/v1/episode"
api_movie_url = "http://argenteam.net/api/v1/movie"
main_url = "http://www.argenteam.net/"


def search(item):
    filename = os.path.splitext(os.path.basename(item['file_original_path']))[0]
    log(__name__, "Search_argenteam='%s', filename='%s', addon_version=%s" % (
        item,
        filename,
        __version__)
    )

    if item['mansearch']:
        search_string = urllib.unquote(item['mansearchstr'])
        buscar_argenteam_api(search_string)
    elif item['tvshow']:
        search_string = "%s S%#02dE%#02d" % (
            item['tvshow'].replace("(US)", ""),
            int(item['season']),
            int(item['episode'])
        )
        buscar_argenteam_api(search_string)
    elif item['title'] and item['year']:
        search_string = item['title'] + " " + item['year']
        buscar_argenteam_api(search_string)
    else:
        buscar_Nombre_Archivo(filename, item['3let_language'])


def buscar_pelicula(movie_id):
    url = api_movie_url + "?id=" + str(movie_id)
    content, response_url = geturl(url)

    return buscar_coincidencia(content)


def buscar_programaTV(result):
    subs = []

    if result['type'] == "tvshow":
        url = api_tvshow_url + "?id=" + str(result['id'])
        content, response_url = geturl(url)
        content = content.replace("null", '""')
        result_json = json.loads(content)

        for season in result_json['seasons']:
            for episode in season['episodes']:
                subs.extend(buscar_episodio(episode['id']))

    elif result['type'] == "episode":
        subs.extend(buscar_episodio(result['id']))

    return subs


def buscar_episodio(episode_id):
    url = api_episode_url + "?id=" + str(episode_id)
    content, response_url = geturl(url)

    return buscar_coincidencia(content)


def buscar_coincidencia(content):
    if content is not None:
        log(__name__, "Resultados encontrados...")
        #object_subtitles = find_subtitles(content)
        items = []
        result = json.loads(content)

        if "releases" in result:
            for release in result['releases']:
                for subtitle in release['subtitles']:
                    item = {}
                    item['lang'] = "Spanish"
                    item['filename'] = urllib.unquote_plus(
                        subtitle['uri'].split("/")[-1]
                    )
                    item['rating'] = str(subtitle['count'])
                    item['image'] = 'es'
                    item['id'] = subtitle['uri'].split("/")[-2]
                    item['link'] = subtitle['uri']

                    #Comprueba si hay subtítulos
                    if "-CC" in item['filename']:
                        item['hearing_imp'] = True
                    else:
                        item['hearing_imp'] = False

                    items.append(item)

        return items


def buscar_Nombre_Archivo(filename, languages):
    title, year = xbmc.getCleanMovieTitle(filename)
    log(__name__, "clean title: \"%s\" (%s)" % (title, year))
    try:
        yearval = int(year)
    except ValueError:
        yearval = 0
    if title and yearval > 1900:
        search_string = title + "+" + year
        buscar_argenteam_api(search_string)
    else:
        match = re.search(
            r'\WS(?P<season>\d\d)E(?P<episode>\d\d)',
            title,
            flags=re.IGNORECASE
        )
        if match is not None:
            tvshow = string.strip(title[:match.start('season')-1])
            season = string.lstrip(match.group('season'), '0')
            episode = string.lstrip(match.group('episode'), '0')
            search_string = "%s S%#02dE%#02d" % (
                tvshow,
                int(season),
                int(episode)
            )
            buscar_argenteam_api(search_string)
        else:
            buscar_argenteam_api(filename)


def buscar_argenteam_api(search_string):
    url = api_search_url + "?q=" + urllib.quote_plus(search_string)
    content, response_url = geturl(url)
    response = json.loads(content)
    subs = []

    if response['total'] > 0:
        for result in response['results']:
            if result['type'] == "tvshow" or result['type'] == "episode":
                subs.extend(buscar_programaTV(result))
            elif result['type'] == "movie":
                subs.extend(buscar_pelicula(result['id']))

    agregar_subtitulos(subs)


def agregar_subtitulos(items):

    items.sort(key=lambda x: x['rating'], reverse=True)
    index = 0
    for item in items:
        index += 1
        listitem = xbmcgui.ListItem(
            label=item['lang'],
            label2=item['filename'],
            iconImage=item['rating'],
            thumbnailImage=item['image']
        )

        #listitem.setProperty("sync",  'true' if item["sync"] else 'false')
        listitem.setProperty(
            "hearing_imp",
            'true' if item["hearing_imp"] else 'false'
        )

        ## Los argumentos siguientes son opcionales, se puede utilizar para pasar cualquier información necesaria
        ## en la funcion descargar
        ## cualquier cosa después de "action = download &" se enviará a addon
        ## una vez que el usuario haga clic en los subtítulos listados para descargar
        url = ("plugin://%s/?action=download&actionsortorder=%s&link=%s"
               "&filename=%s&id=%s") % (
            __scriptid__,
            str(index).zfill(2),
            item['link'],
            item['filename'],
            item['id']
        )

        ## Añadir a la lista, esto se puede hacer tantas veces como sea necesario para todos los subtítulos encontrados
        xbmcplugin.addDirectoryItem(
            handle=int(sys.argv[1]),
            url=url,
            listitem=listitem,
            isFolder=False
        )

def get_parametros():
    param = {}
    paramstring = sys.argv[2]
    if len(paramstring) >= 2:
        params = paramstring
        cleanedparams = params.replace('?', '')
        if (params[len(params) - 1] == '/'):
            params = params[0:len(params) - 2]
        pairsofparams = cleanedparams.split('&')
        param = {}
        for i in range(len(pairsofparams)):
            splitparams = pairsofparams[i].split('=')
            if (len(splitparams)) == 2:
                param[splitparams[0]] = splitparams[1]

    return param


def descargar(id, url, filename, search_string=""):
    subtitle_list = []
    exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]

    # Limpia temp dir, descargamos y descomprimimos los subtitulos
    # en la carpeta temporal y pasar que a XBMC para copiar y activar
    # hasta aqui llegamos nosotros lo demas lo hace Kodi
    if xbmcvfs.exists(__temp__):
        shutil.rmtree(__temp__)
    xbmcvfs.mkdirs(__temp__)

    filename = os.path.join(__temp__, filename + ".zip")

    sub = urllib.urlopen(url).read()
    with open(filename, "wb") as subFile:
        subFile.write(sub)
    subFile.close()

    xbmc.sleep(500)
    xbmc.executebuiltin(
        (
            'XBMC.Extract("%s","%s")' % (filename, __temp__,)
        ).encode('utf-8'), True)

    for file in xbmcvfs.listdir(__temp__)[1]:
        file = os.path.join(__temp__, file)
        if os.path.splitext(file)[1] in exts:
            if search_string and string.find(
                string.lower(file),
                string.lower(search_string)
            ) == -1:
                continue
            log(__name__, "=== returning subtitle file %s" % file)
            subtitle_list.append(file)

    return subtitle_list


def normalizeString(str):
    return unicodedata.normalize(
        'NFKD', unicode(unicode(str, 'utf-8'))
    ).encode('ascii', 'ignore')

params = get_parametros()

if params['action'] == 'search' or params['action'] == 'manualsearch':
    item = {}
    item['temp'] = False
    item['rar'] = False
    item['mansearch'] = False
    item['year'] = xbmc.getInfoLabel("VideoPlayer.Year")
    item['season'] = str(xbmc.getInfoLabel("VideoPlayer.Season"))
    item['episode'] = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    item['tvshow'] = normalizeString(
        xbmc.getInfoLabel("VideoPlayer.TVshowtitle")
    )
    item['title'] = normalizeString(
        xbmc.getInfoLabel("VideoPlayer.OriginalTitle")
    )
    item['file_original_path'] = urllib.unquote(
        xbmc.Player().getPlayingFile().decode('utf-8')
    )
    item['3let_language'] = []

    if 'searchstring' in params:
        item['mansearch'] = True
        item['mansearchstr'] = params['searchstring']
        print params['searchstring']

    for lang in urllib.unquote(params['languages']).decode('utf-8').split(","):
        item['3let_language'].append(
            xbmc.convertLanguage(lang, xbmc.ISO_639_2)
        )

    if item['title'] == "":
        # Sin titulo original, solo titulo
        item['title'] = normalizeString(xbmc.getInfoLabel("VideoPlayer.Title"))

    # Compruebe si la temporada es "Especial"
    if item['episode'].lower().find("s") > -1:
        item['season'] = "0"
        item['episode'] = item['episode'][-1:]

    if item['file_original_path'].find("http") > -1:
        item['temp'] = True

    elif item['file_original_path'].find("rar://") > -1:
        item['rar'] = True
        item['file_original_path'] = os.path.dirname(
            item['file_original_path'][6:]
        )

    elif item['file_original_path'].find("stack://") > -1:
        stackPath = item['file_original_path'].split(" , ")
        item['file_original_path'] = stackPath[0][8:]

    search(item)

elif params['action'] == 'download':
    ## Recogemos todos nuestros argumentos enviados desde def Search ()
    if 'find' in params:
        subs = descargar(params["link"], params["find"])
    else:
        subs = descargar(params["id"],params["link"], params["filename"])
    for sub in subs:
        listitem = xbmcgui.ListItem(label=sub)
        xbmcplugin.addDirectoryItem(
            handle=int(sys.argv[1]),
            url=sub,
            listitem=listitem,
            isFolder=False
        )

xbmcplugin.endOfDirectory(int(sys.argv[1]))  # Enviar al directorio de XBMC











# -*- coding: utf-8 -*-
# Subdivx.com subtitles, based on a mod of Undertext subtitles
# Adaptation: enric_godes@hotmail.com | Please use email address for your
# comments
# Port to XBMC 13 Gotham subtitles infrastructure: cramm, Mar 2014

from __future__ import print_function
import os
from os.path import join as pjoin
from pprint import pformat
import re
import shutil
import sys
import time
import unicodedata
import urllib
from urlparse import parse_qs

try:
    import xbmc
except ImportError:
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        import unittest  # NOQA
        try:
            import mock  # NOQA
        except ImportError:
            print("You need to install the mock Python library to run "
                  "unit tests.\n")
            sys.exit(1)
else:
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

__cwd__        = xbmc.translatePath(__addon__.getAddonInfo('path')).decode("utf-8")
__profile__    = xbmc.translatePath(__addon__.getAddonInfo('profile')).decode("utf-8")
__resource__   = xbmc.translatePath(pjoin(__cwd__, 'resources', 'lib')).decode("utf-8")
__temp__       = xbmc.translatePath(pjoin(__profile__, 'temp')).decode("utf-8")

sys.path.append(__resource__)


MAIN_SUBDIVX_URL = "http://www.subdivx.com/"
SEARCH_PAGE_URL = MAIN_SUBDIVX_URL + "index.php?accion=5&masdesc=&oxdown=1&pg=%(page)s&buscar=%(query)s"

INTERNAL_LINK_URL = "plugin://%(scriptid)s/?action=download&id=%(id)s&filename=%(filename)s"
SUB_EXTS = ['srt', 'sub', 'txt']
HTTP_USER_AGENT = "User-Agent=Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2.3) Gecko/20100401 Firefox/3.6.3 ( .NET CLR 3.5.30729)"


def is_subs_file(fn):
    """Detect if the file has an extension we recognise as subtitle."""
    ext = fn.split('.')[-1]
    return ext.upper() in [e.upper() for e in SUB_EXTS]


# ============================
# Regular expression patterns
# ============================

# Subtitle pattern example:
# <div id="menu_titulo_buscador"><a class="titulo_menu_izq" href="http://www.subdivx.com/X6XMjEzMzIyX-iron-man-2-2010.html">Iron Man 2 (2010)</a></div>
# <img src="img/calif5.gif" class="detalle_calif">
# </div><div id="buscador_detalle">
# <div id="buscador_detalle_sub">Para la versión Iron.Man.2.2010.480p.BRRip.XviD.AC3-EVO, sacados de acá. ¡Disfruten!</div><div id="buscador_detalle_sub_datos"><b>Downloads:</b> 4673 <b>Cds:</b> 1 <b>Comentarios:</b> <a rel="nofollow" href="popcoment.php?idsub=MjEzMzIy" onclick="return hs.htmlExpand(this, { objectType: 'iframe' } )">14</a> <b>Formato:</b> SubRip <b>Subido por:</b> <a class="link1" href="http://www.subdivx.com/X9X303157">TrueSword</a> <img src="http://www.subdivx.com/pais/2.gif" width="16" height="12"> <b>el</b> 06/09/2010  </a></div></div>
# <div id="menu_detalle_buscador">

SUBTITLE_RE = re.compile(r'''<a\s+class="titulo_menu_izq2?"\s+
                         href="http://www.subdivx.com/(?P<id>.+?)\.html">
                         .+?<div\s+id="buscador_detalle_sub">(?P<comment>.*?)</div>
                         .+?<b>Downloads:</b>(?P<downloads>.+?)
                         <b>Cds:</b>.+?</div></div>''',
                         re.IGNORECASE | re.DOTALL | re.VERBOSE | re.UNICODE |
                         re.MULTILINE)
# 'id' named group: ID to fetch the subs files
# 'comment' named group: Translation author comment, may contain filename
# 'downloads' named group: Downloads, used for ratings

DOWNLOAD_LINK_RE = re.compile(r'bajar.php\?id=(.*?)&u=(.*?)\"', re.IGNORECASE |
                              re.DOTALL | re.MULTILINE | re.UNICODE)

# ==========
# Functions
# ==========


def log(msg):
    s = u"SUBDIVX - %s" % msg
    xbmc.log(s.encode('utf-8'), level=xbmc.LOGDEBUG)


def get_url(url):
    class MyOpener(urllib.FancyURLopener):
        # version = HTTP_USER_AGENT
        version = ''
    my_urlopener = MyOpener()
    log(u"get_url(): Getting url %s" % url)
    try:
        response = my_urlopener.open(url)
        content = response.read()
    except Exception:
        log(u"get_url(): Failed to get url: %s" % url)
        content = None
    return content


def get_all_subs(searchstring, languageshort, languagelong, file_original_path):
    subs_list = []
    if languageshort == "es":
        log(u"Getting '%s' subs ..." % languageshort)
        page = 1
        while True:
            url = SEARCH_PAGE_URL % {'page': page,
                                     'query': urllib.quote_plus(searchstring)}
            content = get_url(url)
            if content is None or not SUBTITLE_RE.search(content):
                break
            for match in SUBTITLE_RE.finditer(content):
                id = match.groupdict()['id']
                dls = re.sub(r'[,.]', '', match.groupdict()['downloads'])
                downloads = int(dls)
                rating = downloads / 1000
                if rating > 10:
                    rating = 10
                description = match.groupdict()['comment']
                text = description.strip()
                # Remove new lines
                text = re.sub('\n', ' ', text)
                # Remove Google Ads
                text = re.sub(r'<script.+?script>', '', text,
                              re.IGNORECASE | re.DOTALL | re.MULTILINE |
                              re.UNICODE)
                # Remove HTML tags
                text = re.sub(r'<[^<]+?>', '', text)
                # If our actual video file's name appears in the description
                # then set sync to True because it has better chances of its
                # synchronization to match
                _, fn = os.path.split(file_original_path)
                name, _ = os.path.splitext(fn)
                sync = re.search(re.escape(name), text, re.I) is not None
                try:
                    log(u"Subtitles found: %s (id = %s)" % (text, id))
                except Exception:
                    pass
                item = {
                    'rating': str(rating),
                    'filename': text.decode('latin1'),
                    'sync': sync,
                    'id': id,
                    # 'language_flag': 'flags/' + languageshort + '.gif',
                    'language_name': languagelong,
                }
                subs_list.append(item)
            page += 1

        # Put subs with sync=True at the top
        subs_list = sorted(subs_list, key=lambda s: s['sync'], reverse=True)

    log(u"get_all_subs(): Returning %s" % pformat(subs_list))
    return subs_list


def append_subtitle(item):
    listitem = xbmcgui.ListItem(
        label=item['language_name'],
        label2=item['filename'],
        iconImage=item['rating'],
        thumbnailImage='es'
    )

    listitem.setProperty("sync", 'true' if item["sync"] else 'false')
    listitem.setProperty("hearing_imp",
                         'true' if item.get("hearing_imp", False) else 'false')

    # Below arguments are optional, it can be used to pass any info needed in
    # download function anything after "action=download&" will be sent to addon
    # once user clicks listed subtitle to download
    args = dict(item)
    args['scriptid'] = __scriptid__
    url = INTERNAL_LINK_URL % args

    # Add it to list, this can be done as many times as needed for all
    # subtitles found
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                url=url,
                                listitem=listitem,
                                isFolder=False)


def Search(item):
    """Called when subtitle download is requested from XBMC."""
    log(u'Search(): item = %s' % pformat(item))
    # Do what's needed to get the list of subtitles from service site
    # use item["some_property"] that was set earlier.
    # Once done, set xbmcgui.ListItem() below and pass it to
    # xbmcplugin.addDirectoryItem()
    file_original_path = item['file_original_path']
    title = item['title']
    tvshow = item['tvshow']
    season = item['season']
    episode = item['episode']

    if tvshow:
        searchstring = "%s S%#02dE%#02d" % (tvshow, int(season), int(episode))
    else:
        searchstring = title
    log(u"Search string = %s" % searchstring)

    subs_list = get_all_subs(searchstring, "es", "Spanish", file_original_path)

    for sub in subs_list:
        append_subtitle(sub)


def Download(id, filename):
    """Called when subtitle download request from XBMC."""
    # Cleanup temp dir, we recommend you download/unzip your subs in temp folder
    # and pass that to XBMC to copy and activate
    if xbmcvfs.exists(__temp__):
        shutil.rmtree(__temp__)
    xbmcvfs.mkdirs(__temp__)

    subtitles_list = []
    # Get the page with the subtitle link,
    # i.e. http://www.subdivx.com/X6XMjE2NDM1X-iron-man-2-2010
    subtitle_detail_url = MAIN_SUBDIVX_URL + str(id)
    content = get_url(subtitle_detail_url)
    match = DOWNLOAD_LINK_RE.findall(content)

    actual_subtitle_file_url = MAIN_SUBDIVX_URL + "bajar.php?id=" + match[0][0] + "&u=" + match[0][1]
    content = get_url(actual_subtitle_file_url)
    if content is not None:
        header = content[:4]
        if header == 'Rar!':
            local_tmp_file = pjoin(__temp__, "subdivx.rar")
            packed = True
        elif header == 'PK\x03\x04':
            local_tmp_file = pjoin(__temp__, "subdivx.zip")
            packed = True
        else:
            # Never found/downloaded an unpacked subtitles file, but just to be
            # sure ...
            # Assume unpacked sub file is a '.srt'
            local_tmp_file = pjoin(__temp__, "subdivx.srt")
            subs_file = local_tmp_file
            packed = False
        log(u"Saving subtitles to '%s'" % local_tmp_file)
        try:
            local_file_handle = open(local_tmp_file, "wb")
            local_file_handle.write(content)
            local_file_handle.close()
        except Exception:
            log(u"Failed to save subtitles to '%s'" % local_tmp_file)
        if packed:
            files = os.listdir(__temp__)
            init_filecount = len(files)
            log(u"init_filecount = %d" % init_filecount)
            filecount = init_filecount
            max_mtime = 0
            # Determine the newest file from __temp__
            for file in files:
                if is_subs_file(file):
                    mtime = os.stat(pjoin(__temp__, file)).st_mtime
                    if mtime > max_mtime:
                        max_mtime = mtime
            init_max_mtime = max_mtime
            # Wait 2 seconds so that the unpacked files are at least 1 second
            # newer
            time.sleep(2)
            xbmc.executebuiltin("XBMC.Extract(%s, %s)" % (
                                local_tmp_file.encode("utf-8"),
                                __temp__.encode("utf-8")))
            waittime = 0
            while filecount == init_filecount and waittime < 20 and init_max_mtime == max_mtime:
                # Nothing yet extracted
                time.sleep(1)  # wait 1 second to let the builtin function
                               # 'XBMC.Extract' unpack
                files = os.listdir(__temp__)
                filecount = len(files)
                # Determine if there is a newer file created in __temp__ (marks
                # that the extraction had completed)
                for file in files:
                    if is_subs_file(file):
                        mtime = os.stat(pjoin(__temp__, file.decode("utf-8"))).st_mtime
                        if mtime > max_mtime:
                            max_mtime = mtime
                waittime = waittime + 1
            if waittime == 20:
                log(u"Failed to unpack subtitles in '%s'" % __temp__)
            else:
                log(u"Unpacked files in '%s'" % __temp__)
                for file in files:
                    # There could be more subtitle files in __temp__, so make
                    # sure we get the newly created subtitle file
                    if is_subs_file(file) and os.stat(pjoin(__temp__, file)).st_mtime > init_max_mtime:
                        # unpacked file is a newly created subtitle file
                        log(u"Unpacked subtitles file '%s'" % file)
                        subs_file = pjoin(__temp__, file.decode("utf-8"))
                        subtitles_list.append(subs_file)
                        break
        else:
            subtitles_list.append(subs_file)
    return subtitles_list


def normalize_string(str):
    return unicodedata.normalize('NFKD', unicode(unicode(str, 'utf-8'))).encode('ascii', 'ignore')


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


def main():
    """Main entry point of the script when it is invoked by XBMC."""

    # Get parameters from XBMC and launch actions
    params = get_params(sys.argv)

    if params['action'] == 'search':
        item = {}
        item['temp']               = False
        item['rar']                = False
        item['year']               = xbmc.getInfoLabel("VideoPlayer.Year")
        item['season']             = str(xbmc.getInfoLabel("VideoPlayer.Season"))
        item['episode']            = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
        item['tvshow']             = normalize_string(xbmc.getInfoLabel("VideoPlayer.TVshowtitle"))
        # Try to get original title
        item['title']              = normalize_string(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))
        # Full path of a playing file
        item['file_original_path'] = urllib.unquote(xbmc.Player().getPlayingFile().decode('utf-8'))
        item['3let_language']      = []
        item['2let_language']      = []

        for lang in urllib.unquote(params['languages']).decode('utf-8').split(","):
            item['3let_language'].append(xbmc.convertLanguage(lang, xbmc.ISO_639_2))
            item['2let_language'].append(xbmc.convertLanguage(lang, xbmc.ISO_639_1))

        if not item['title']:
            # No original title, get just Title
            item['title'] = normalize_string(xbmc.getInfoLabel("VideoPlayer.Title"))

        if "s" in item['episode'].lower():
            # Check if season is "Special"
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

    elif params['action'] == 'download':
        # We pickup all our arguments sent from the Search() function
        subs = Download(params["id"], params["filename"])
        # We can return more than one subtitle for multi CD versions, for now
        # we are still working out how to handle that in XBMC core
        for sub in subs:
            listitem = xbmcgui.ListItem(label=sub)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=sub,
                                        listitem=listitem, isFolder=False)

    # Send end of directory to XBMC
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


if __name__ == '__main__':
    main()

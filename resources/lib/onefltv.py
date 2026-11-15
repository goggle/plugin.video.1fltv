# -*- coding: utf-8 -*-

# Copyright (C) 2026 Alexander Seiler
#
#
# This file is part of plugin.video.1fltv.
#
# plugin.video.1fltv is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# plugin.video.1fltv is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with plugin.video.1fltv.
# If not, see <http://www.gnu.org/licenses/>.

import html
import json
import re
import sys
from urllib.parse import parse_qsl, urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ICON = ADDON.getAddonInfo('icon')
LANGUAGE = ADDON.getLocalizedString

HOST_URL = 'https://1fl.li'
API_URL = HOST_URL + '/wp/wp-json/wp/v2'
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64; rv:140.0) '
              'Gecko/20100101 Firefox/140.0')
TIMEOUT = 30
PER_PAGE = 20

SHOW_IMAGE_REGEX = re.compile(
    r'<a class="third" href="/wp/sendungen/(?P<slug>[^"/]+)/?">\s*'
    # The src attributes are broken on the site, but srcset is fine:
    r'<img[^>]+srcset="(?P<image>[^" ]+)')


def log(msg, level=xbmc.LOGDEBUG):
    xbmc.log('%s: %s' % (ADDON_ID, msg), level=level)


def fetch(url):
    """Download a URL and return its content and response headers."""
    log('fetch %s' % url)
    req = Request(url, headers={'User-Agent': USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as response:
        return response.read().decode('utf-8'), response.headers


def fetch_json(path, **params):
    """Query the WordPress REST API and return (data, total_pages)."""
    content, headers = fetch('%s/%s?%s' % (API_URL, path, urlencode(params)))
    return json.loads(content), int(headers.get('X-WP-TotalPages') or 1)


def absolute_url(url):
    return url if url.startswith('http') else HOST_URL + '/' + url.lstrip('/')


def strip_tags(text):
    text = re.sub(r'<(script|video)\b.*?</\1>|<!--.*?-->', ' ', text,
                  flags=re.DOTALL)
    text = re.sub(r'<br\s*/?>|</(p|h\d|li)>', '\n', text)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    lines = (re.sub(r'\s+', ' ', line).strip() for line in text.split('\n'))
    return '\n'.join(line for line in lines if line)


def find(regex, text):
    """Return the first group of a regex match or ''."""
    match = re.search(regex, text, re.DOTALL)
    return match.group(1) if match else ''


def show_images():
    """Map the show slugs of the 'Sendungen' page to their images."""
    page, _ = fetch(HOST_URL + '/wp/sendungen/')
    return {m.group('slug'): absolute_url(m.group('image'))
            for m in SHOW_IMAGE_REGEX.finditer(page)}


def show_image(images, slug):
    """Find the image of a show, allowing for slight slug differences
    (e.g. 'lorez-health-training' vs. 'lorez-health')."""
    for key, image in images.items():
        if slug and (slug.startswith(key) or key.startswith(slug)):
            return image
    return ICON


class OneFLTV:
    def __init__(self, base_url, handle):
        self.base_url = base_url
        self.handle = handle

    def build_url(self, **params):
        return '%s?%s' % (self.base_url, urlencode(params))

    def add_folder(self, label, url, image=ICON):
        list_item = xbmcgui.ListItem(label)
        list_item.setArt({'thumb': image, 'icon': image})
        xbmcplugin.addDirectoryItem(self.handle, url, list_item, True)

    def main_menu(self):
        self.add_folder(LANGUAGE(30051), self.build_url(mode='episodes'))
        self.add_folder(LANGUAGE(30050), self.build_url(mode='shows'))

    def list_shows(self):
        categories, _ = fetch_json(
            'categories', per_page=100, hide_empty='true')
        images = show_images()
        for category in sorted(categories, key=lambda c: c['name'].lower()):
            if category['slug'] == 'uncategorized':
                continue
            self.add_folder(
                html.unescape(category['name']),
                self.build_url(mode='episodes', cat=category['id']),
                show_image(images, category['slug']))

    def list_episodes(self, category=None, page=1):
        params = {
            'per_page': PER_PAGE,
            'page': page,
            '_fields': 'id,date,title,content',
        }
        if category:
            params['categories'] = category
        posts, total_pages = fetch_json('posts', **params)
        images = show_images()

        for post in posts:
            content = post['content']['rendered']
            video_url = find(r'src="([^"?]+\.mp4)', content)
            if not video_url:
                continue
            title = html.unescape(post['title']['rendered']).strip()
            show = strip_tags(find(r'<h2>(.*?)</h2>', content)).strip()
            if not category and show:
                # Mixed list of all shows: Tell which show it belongs to
                title = '%s: %s' % (show, title)
            slug = find(r'href="/wp/sendungen/([^"/]+)', content)
            plot = strip_tags(re.sub(
                r'<h2>.*?</h2>|<a class="btn".*?</a>', ' ', content,
                flags=re.DOTALL)).strip()
            image = show_image(images, slug)

            list_item = xbmcgui.ListItem(title)
            list_item.setArt({'thumb': image, 'icon': image})
            info = list_item.getVideoInfoTag()
            info.setMediaType('video')
            info.setTitle(title)
            info.setPlot(plot)
            info.setFirstAired(post['date'][:10])
            xbmcplugin.addDirectoryItem(
                self.handle, absolute_url(video_url), list_item, False)

        if page < total_pages:
            params = {'mode': 'episodes', 'page': page + 1}
            if category:
                params['cat'] = category
            self.add_folder(LANGUAGE(30052), self.build_url(**params))


def run():
    base_url, handle = sys.argv[0], int(sys.argv[1])
    params = dict(parse_qsl(sys.argv[2].lstrip('?')))
    mode = params.get('mode')
    plugin = OneFLTV(base_url, handle)

    try:
        if mode == 'shows':
            plugin.list_shows()
        elif mode == 'episodes':
            plugin.list_episodes(
                params.get('cat'), int(params.get('page', 1)))
        else:
            plugin.main_menu()
    except Exception as err:
        log('Error in mode %s: %s' % (mode, err), xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo('name'), LANGUAGE(30100),
            xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setContent(handle, 'videos')
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)

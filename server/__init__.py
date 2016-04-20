#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import os.path
import mimetypes
import time
import logging
import json
import types
import itertools
import re
import datetime
import functools
import urlparse

import wx
import jinja2
import base64

try:
    from cStringIO import StringIO  # C module
except ImportError:
    from StringIO import StringIO  # Python fallback

import utils
import config
import my_env
import constants.constants as constants

import gevent
from gevent.pywsgi import WSGIServer

from wxproxy import WxProxy

from .comm import DownloaderXHRConn

# Syntax sugar (attribute getter)
from utils import attribute

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    pass

def speed_limit_setter(v):
    # KB/s str to int B/s
    if v == "auto":
        return -1
    try:
        v = int(v)
        if v < 1:
            return -1
        if sys.maxint < v:
            return sys.maxint
        return v*1000
    except ValueError:
        raise ValidationError, "Parser cannot translate fromt %s to int" % (repr(v),)

def speed_limit_getter(v):
    if v == -1:
        return "auto"
    return "%d" % round(v/1000.)

def bounded_int(minint, maxint=sys.maxint):
    def parser(v):
        return max(minint, min(int(v), maxint))
    return parser

SETTINGS_TO_CONFIG = {
    # designer's input name, real config key, getter parser, setter parser (also validator)
    "language": ("language", str, str),
    "downloads-folder": ("download_dir", str, str),
    "set-default": ("torrent_default", bool, bool),
    "prevent-sleeping": ("keep_awake", bool, bool),
    "run-startup": ("run_at_startup", bool, bool),
    "auto-ports": ("auto_ports", bool, bool),
    "standard-download-speed-limit": ("download_standard_downspeed", speed_limit_getter, speed_limit_setter),
    "standard-upload-speed-limit": ("download_standard_upspeed", speed_limit_getter, speed_limit_setter),
    "standard-maximum-simultaneous-downloads": ("download_standard_active_downloads", int, bounded_int(1)),
    "snail-download-speed-limit": ("download_slow_downspeed", speed_limit_getter, speed_limit_setter),
    "snail-upload-speed-limit": ("download_slow_upspeed", speed_limit_getter, speed_limit_setter),
    "snail-maximum-simultaneous-downloads": ("download_slow_active_downloads", int, bounded_int(1)),
    "notify-downloads": ("download_notification", bool, bool),
    #port-BACKEND-N stuff is handled directly on SettingsManager __getattr__ and __setattr__
    }

_html_whitestrip = re.compile(">( |\\n)+<", re.MULTILINE)
def whitestrip(data):
    return data
    #return _html_whitestrip.sub("><", data)

class PlayCardMixin(object):
    _html_cache = ""
    _html_cache_last_update = 0

    @property
    def preview(self, url):
        return None

    @property
    def preview_path(self):
        if self.preview:
            return "/card_image/" + self.path
        return None

    @property
    def html(self):
        last_update = self.last_update
        if last_update > self._html_cache_last_update:
            self._html_cache_last_update = last_update
            self._html_cache = whitestrip(self._template.module.card(self))
        return self._html_cache

    @property
    def base(self):
        return self.path

    @property
    def json(self):
        return {
            "path": self.path,
            "progress": self.progress,
            "name": self.name,
            "type": self.type,
            "preview": self.preview_path,
            }


class DownloadPlayCard(PlayCardMixin):
    @property
    def last_update(self):
        return self._last_update

    _medatata_creation = 0
    _last_update_progress = -1
    @last_update.setter
    def last_update(self, v):
        self._last_update = v

        # _progress_cache refresh
        new_progress = int(self._download.progress*100)
        if self._last_update_progress != new_progress:
            self.last_update_progress = new_progress
            self._progress_cache = None

        # _metadata_creation set
        if self._medatata_creation == 0 and self._download.has_metadata():
            self._medatata_creation = v

    _catcache = None
    @property
    def category(self):
        if self._catcache:
            return self._catcache
        elif self._download.user_data and "type" in self._download.user_data and config.validate_web_category(self._download.user_data["type"]):
            self._catcache = r = self._download.user_data["type"]
            return r
        elif self._download.filenames:
            self._catcache = r = config.guess_web_category(self._download.filenames)
            return r
        return "unknown"

    def _preview_finished(self, r):
        if not r:
            return  # no image as raw data, nothing to save
        imgsize = utils.image_size(r)
        if imgsize[0] > 50 and imgsize[1] > 50:
            self.data["img_data"] = r
            self._server.update_download(self._download)

    def _preview_failed(self, e):
        del self.data["img_data"] # makes retry again later
        logger.debug(e)

    @property
    def preview(self):
        if "img_data_scaled" in self.data:
            # Nice, we already have a scaled version of the image
            return self.data["img_data_scaled"]
        elif "img_data" in self.data and self.data["img_data"] is not None:
            # Get its size and see if we need to rescale it
            data = self.data["img_data"]
            img = wx.ImageFromStream(StringIO(data), utils.image_type(data))
            w, h = img.GetSize()
            if w > 150 or h > 150:
                f = 150. / min(w, h)  # factor used to rescale
                img.Rescale(int(f*w), int(f*h), wx.IMAGE_QUALITY_HIGH)
                io_data_new = StringIO()  # will contain the raw image rescaled
                img.SaveStream(io_data_new, type=wx.BITMAP_TYPE_PNG)
                self.data["img_data_scaled"] = io_data_new.getvalue()
                img.Destroy()
            else:
                self.data["img_data_scaled"] = data
            return self.data["img_data_scaled"]
        elif self._download.user_data and self._download.user_data.get("img", None):
            self.data["img_data"] = None
            url = self._download.user_data["img"]
            utils.async(utils.GetURL(url).read_all, success=self._preview_finished, error=self._preview_failed)
        return None

    @property
    def filetype(self):
        category = self.category
        if category in constants.CATEGORY_TO_FILETYPE:
            return constants.CATEGORY_TO_FILETYPE[self.category]
        logger.debug("no filetype for %s found" % category)
        return ""

    def __init__(self, server, download, template, is_new=False):
        self._server = server
        self._download = download
        self._template = template
        self._new = is_new
        self.ext = None
        self.type = "download"
        self.last_update = time.time()
        self.creation = time.time()

    def remove(self):
        self._download.remove()

    def remove_path(self, path):
        fspath = self.fspath + os.sep + path.replace("/", os.sep)
        self._download.remove_file(fspath)

    @classmethod
    def _subto(cls, txt, start, sep):
        pos = txt.find(sep, start)
        if pos == -1:
            return txt
        return txt[:pos]

    @property
    def base(self):
        if self._download.path != self._download.download_dir:
            return self.path + "/" + self._download.path[len(self._download.download_dir + os.sep):].replace(os.sep, "/")
        return self.path

    def get_content_of(self, path):
        prefix = self._download.download_dir + os.sep
        base = self._download.download_dir + os.sep
        path = path.replace("/", os.sep).rstrip("/")
        sep = os.sep

        if path == "" or self._download.path.startswith(base + path + os.sep):
            # Jump if path is in middle of download path
            path = self._download.path[len(base):]

        if path:
            prefix = path + sep
            prefix_len = len(prefix)
            filtered_files = frozenset(
                self._subto(path, prefix_len, sep)
                for path in self._download.filenames
                if path.startswith(prefix)
                )
        else:
            filtered_files = frozenset(
                self._subto(path, 0, sep)
                for path in self._download.filenames
                )

        if filtered_files:
            listdir = my_env.get_listdir(base + path)
            if path:
                listdir = (path + sep + i for i in listdir)
            for path in filtered_files.intersection(listdir): # Much faster than check for existence
                yield self.get_playcard(path)

    _progress_cache = None
    def get_progress_of(self, path):
        if self._download.finished or self._download.hidden:
            return 1
        path = path.replace("/", os.sep)
        cache = self._progress_cache
        if cache is None:
            try:
                self._progress_cache = cache = self._download.files_progress
            except BaseException as e:
                logger.exception(e)
                return 0
        if path in cache:
            done, total = cache[path]
        else:
            prefix = path + os.sep
            p = [v for k, v in cache.iteritems() if k.startswith(prefix)]
            done = sum(i[0] for i in p)
            total = sum(i[1] for i in p)
            cache[path] = (done, total)
        if total == 0:
            return 0
        return float(done)/total

    def get_category_of(self, path):
        path = path.replace("/", os.sep)
        filenames = self._download.filenames
        if path in filenames:
            filenames = (path,)
        else:
            prefix = path + os.sep
            filenames = [f for f in filenames if f.startswith(prefix)]
        return config.guess_web_category(filenames)

    def get_playcard(self, path):
        if path:
            return FilePlayCard(self, path)
        return self

    @attribute
    def data(self):
        if self._download.user_data and "play_data" in self._download.user_data:
            return self._download.user_data["play_data"]
        r = {}
        if isinstance(self._download.user_data, dict):
            self._download.user_data["play_data"] = r
        else:
            self._download.user_data = {"play_data": r}
        return r

    @property
    def numfiles(self):
        return len(self._download.filenames)

    _new = False
    @property
    def new(self):
        return self._new

    @property
    def name(self):
        if "force_name" in self.data:
            return self.data["force_name"]
        name = self._download.name or self.data.get("name", "")
        # Strip extension
        if "." in name:
            pos = name.rindex(".")
            if name.rfind(" ") < pos:
                name = name[:pos]
        # Non-space separators
        if " " in name:
            return name
        for i in "._":
            if i in name:
                return name.replace(i, " ")
        return name

    @name.setter
    def name(self, v):
        if v == self._download.name:
            if "force_name" in self.data:
                del self.data["force_name"]
        else:
            self.data["force_name"] = v

    @property
    def progress(self):
        if self._download.finished or self._download.hidden:
            return 1
        return self._download.progress

    @attribute
    def path(self):
        ''' path for play '''
        return str(id(self._download))

    @property
    def fspath(self):
        ''' download directory '''
        return self._download.download_dir

    @property
    def folder(self):
        ''' main directory (top level directory in download tree) '''
        return self._download.path


class FilePlayCard(PlayCardMixin):
    def __init__(self, parent, path):
        self._parent = parent
        self._template = parent._template
        self._path = path

        basename = os.path.basename(path)
        self._name = basename[:basename.rfind(".")] if "." in basename else basename
        self.ext = basename[len(self._name):] # We want the dot

        self.path = parent.path + "/" + path.replace(os.sep, "/")

    def remove(self):
        self._parent.remove_path(self._path)

    def __getattr__(self, k):
        return getattr(self._parent, k)

    @property
    def last_update(self):
        return self._parent.last_update

    @last_update.setter
    def last_update(self, v):
        self._parent.last_update = v

    @property
    def creation(self):
        return self._parent._medatata_creation

    @property
    def data(self):
        if self._path in self._parent.data.get("file_data", ()):
            return self._parent.data["file_data"][self._path]
        r = {}
        if "file_data" in self._parent.data:
            self._parent.data["file_data"][self._path] = r
        else:
            self._parent.data["file_data"] = {self._path: r}
        return r

    @property
    def name(self):
        return self.data.get("force_name", self._name)

    @name.setter
    def name(self, v):
        if v != self._name:
            self.data["force_name"] = v
        elif "force_name" in self.data:
            del self.data["force_name"]

    @attribute
    def category(self):
        return self._parent.get_category_of(self._path)

    @property
    def preview(self):
        #TODO(felipe): implement
        return None

    @attribute
    def filetype(self):
        return constants.CATEGORY_TO_FILETYPE[self.category]

    @property
    def progress(self):
        return self._parent.get_progress_of(self._path)

    @attribute
    def type(self):
        fspath = self.fspath
        if os.path.isdir(fspath):
            return "folder"
        elif not os.path.exists(fspath):
            return "virtual"
        return "file"

    @property
    def content(self):
        return self._parent.get_content_of(self._path)

    @property
    def fspath(self):
        return self._parent.fspath + os.sep + self._path.replace("/", os.sep)

    @property
    def folder(self):
        if self.type == "file":
            return os.path.dirname(self.fspath)
        return self.fspath


class Breadcrumb(object):
    def __init__(self, path, name, template):
        self.path = path
        self.name = name
        self._template = template

    @property
    def html(self):
        return whitestrip(self._template.module.breadcrumb(self))

    @property
    def json(self):
        return {
            "path": self.path,
            "html": self.html,
            "name": self.name,
            }


class Category(object):
    def __init__(self, path, name, css, selected, template):
        self.path = path
        self.name = name
        self.selected = selected
        self.css = css
        self._template = template

    @property
    def html(self):
        return whitestrip(self._template.module.category(self))

    @property
    def json(self):
        return {
            "path": self.path,
            "html": self.html,
            "name": self.name,
            "css": self.css,
            "selected": self.selected,
            }


class SettingsManager(object):
    @classmethod
    def _getter(cls, prop, self):
        key, getparse, setparse = SETTINGS_TO_CONFIG[prop]
        return getparse(self.config[key])

    @classmethod
    def _setter(cls, prop, self, v):
        key, getparse, setparse = SETTINGS_TO_CONFIG[prop]
        try:
            self.config[key] = setparse(v)
        except ValidationError as e:
            logger.debug("Validation error", extra={"error":e})
        except BaseException as e:
            logger.exception(e)

    @classmethod
    def _delter(cls, prop, self, v):
        key, getparse, setparse = SETTINGS_TO_CONFIG[prop]
        del self.config[key]

    def __new__(cls, *args, **kwargs):
        for prop in SETTINGS_TO_CONFIG:
            getter = property(functools.partial(cls._getter, prop),
                              functools.partial(cls._setter, prop),
                              functools.partial(cls._delter, prop))
            setattr(SettingsManager, prop, getter)
        SettingsManager.__new__ = object.__new__ # prevent running twice
        return object.__new__(cls)

    def _config_callback(self, k, v):
        if not self._updating: # prevent recursion error
            self.update()

    def __getattr__(self, k):
        if k.startswith("port-") and k.count("-") > 1 and k[k.rfind("-")+1:].isdigit():
            config_key = k.replace("-", "_")
            if config_key in self.config:
                return self.config[config_key]
            else:
                try:
                    name = k[5:k.rfind("-")]
                    port_index = int(k[k.rfind("-")+1:])
                    desc, port = self.app.backend.get_backend(name).ports[port_index]
                    return port
                except BaseException as e:
                    logger.exception(e)
            return -1
        return object.__getattribute__(self, k)

    def __setattr__(self, k, v):
        if k.startswith("port-") and k.count("-") > 1 and k[k.rfind("-")+1:].isdigit():
            if (isinstance(v, int) and 1023 < int(v) < 65535) or (isinstance(v, basestring) and v.isdigit()):
                self.config[k.replace("-", "_")] = int(v)
        else:
            object.__setattr__(self, k ,v)

    def __init__(self, app):
        self.app = app
        self.last_update = time.time()
        self.known_settings = set(SETTINGS_TO_CONFIG)

        for p in SETTINGS_TO_CONFIG.itervalues():
            self.config.on(p[0], self._config_callback)

    _updating = False
    _buttons = {"downloads-folder-button", "set-default"}
    def update(self, settings=None):
        if settings:
            for i in self._buttons.intersection(settings):
                del settings[i]
                self.button(i)
            self.known_settings.update(settings) # Must be after button cleaning
            self._updating = True
            for k, v in settings.iteritems():
                setattr(self, k, v)
            self._updating = False
        t = time.time()
        if t > self.last_update:
            self.last_update = t

    _notset = type("ValueNotSet", (), {})
    def button(self, kind):
        v = self._notset
        if kind == "downloads-folder-button":
            kind = "downloads-folder"
            dialog = wx.DirDialog(
                self.app.frame.obj,
                "Select download dir", getattr(self, kind),
                wx.DD_DEFAULT_STYLE, wx.DefaultPosition)
            if dialog.ShowModal() == wx.ID_OK:
                v = dialog.GetPath()
        elif kind == "set-default":
            my_env.set_default_for_torrent()
            v = True
        if not v is self._notset:
            self.__setattr__(kind, v)

    @property
    def config(self):
        return self.app.config

    @property
    def json(self):
        return {k: getattr(self, k) for k in self.known_settings}

class Request(object):
    last = None
    class Abort(Exception):
        pass

    _dow = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    _ym = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    def __init__(self, server, environ):
        self.server = server
        self.environ = environ

        Request.last = self

        # Default response data
        self.response_code = '200 OK'
        self.response_headers = {"Set-Cookie": []}
        self.response_body = None

        self._cache_headers(-86400) # yesterday

    def _cache_headers(self, seconds):
        dtime = datetime.datetime.fromtimestamp(time.time()+seconds)
        expires = dtime.strftime(
            '%s, %%d %s %%Y %%H:%%M:%%S GMT' % ( # Thu, 01 Dec 1994 16:00:00 GMT
                self._dow[dtime.weekday()].capitalize(),
                self._ym[dtime.month-1].capitalize()
                ))
        if seconds <= 0:
            self.response_headers.update({
                "Cache-Control": "no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": expires,
                })
        else:
            self.response_headers.update({
                "Cache-Control": "max-age=%d" % seconds,
                "Pragma": "max-age=%d" % seconds,
                "Expires": expires,
                })

    def cache_for(self, seconds):
        self._cache_headers(seconds)

    def cache_forever(self):
        self._cache_headers(31536000) # a year

    def error(self, code=None):
        self.response_code = "500 SERVER ERROR"
        self.response_body = "Server error"
        if code == 404:
            self.response_code = '404 NOT FOUND'
            self.response_body = 'File not found'

    def abort(self, code=None):
        self.error(code)
        raise Abort, self.response_code

    def render_template(self, path, **kwargs):
        # Headers
        # Content-Length and Date headers are managed by gevent's WSGIHandler
        if not "Content-Type" in self.response_headers:
            self.response_headers['Content-Type'] = "text/html; charset=utf-8"
        if not "X-UA-Compatible" in self.response_headers:
            self.response_headers['X-UA-Compatible'] = "IE=edge"

        try:
            if my_env.is_windows and self.environ['REMOTE_ADDR'].startswith("127."):
                kwargs["uridata_support"] = my_env.win32.get_ieversion()[0] > 8
            else:
                # IE 8+ supports uridata, but identify itself as ie7 so we cannot detect it
                kwargs["uridata_support"] = not "MSIE" in self.environ["HTTP_USER_AGENT"]
        except:
            kwargs["uridata_support"] = False

        stream = self.server.get_template(path).stream(kwargs)
        stream.enable_buffering(2) # In jinja2 objects, not bytes
        return stream

    @utils.attribute
    def query(self):
        return urlparse.parse_qs(self.environ["QUERY_STRING"])

    @utils.attribute
    def path(self):
        return self.environ['PATH_INFO']

    @property
    def response_header_list(self):
        return [(k, i)
          for k, v in self.response_headers.iteritems()
          for i in (v if isinstance(v, (list, tuple)) else (v,))
          if not i is None
          ]


class TemplateLoader(jinja2.BaseLoader):
    _script_re = re.compile(r'<script(?P<attributes>\b[^>]*)></script>', re.IGNORECASE)
    _link_re = re.compile(r'<link(?P<attributes>\b[^>]*)>', re.IGNORECASE)
    _url_re = re.compile(r'url\((?P<url>[^)]*)\)')
    def __init__(self, base, static):
        self.base = base
        self.static = static
        self.autoreload = config.DEBUG and not my_env.is_archive

    @classmethod
    def _parse_attr(cls, attrstring):
        return dict(
            (k.split("=", 1)[0].strip(), k.split("=", 1)[1].strip().strip("\"").strip("\'"))
            if "=" in k else
            (k, k)
            for k in attrstring.split() if k.strip()
            )

    @classmethod
    def _dump_attr(cls, attrdict):
        return " ".join("%s=\"%s\"" % (k, v.replace("\"", "&quot;")) for k, v in attrdict.iteritems())

    @classmethod
    def _check_uri(cls, uri):
        if uri:
            for i in ("//", "{{"):
                if i in uri:
                    return False
            return True
        return False

    @classmethod
    def _up_to_date(cls, mtime, path):
        return mtime == -1 or mtime == utils.get_resource_mtime(path)

    def _script_replace(self, match):
        rep = match.group("attributes").rstrip("/").split("src=", 1)[-1].split(None, 1)[0].strip("'").strip("\"")
        if self._check_uri(rep):
            path = self.static + "/" + rep.lstrip("/")
            data = utils.get_resource_data(path).decode("utf-8")
            if data:
                return "{% raw %}<script type=\"text/javascript\">\n" + data + "\n</script>{% endraw %}"
        return '<script %s></script>' % (match.group("attributes"),)

    def _link_replace(self, match):
        rep = match.group("attributes").rstrip("/").split("href=", 1)[-1].split(None, 1)[0].strip("'").strip("\"")
        if self._check_uri(rep):
            path = self.static + "/" + rep.lstrip("/")
            data = utils.get_resource_data(path).decode("utf-8")
            if data:
                data = self._url_re.sub(functools.partial(self._url_replace, path), data)
                return "{% raw %}<style type=\"text/css\">\n" + data + "\n</style>{% endraw %}"
        tagcontent = match.group("attributes")
        return '<link%s%s>' % (tagcontent, "" if tagcontent[-1] == "/" else "/")

    def _url_replace(self, path, match):
        url = match.group("url").strip("'").strip("\"")
        if self._check_uri(url):
            path = os.path.dirname(path)
            if url.startswith("/") or not path:
                absurl = self.static + "/" + url.lstrip("/")
            else:
                absurl = path + "/" + url
            absurl = os.path.normpath(absurl).replace(os.sep, "/")
            if absurl.startswith(self.static + "/"):
                url = absurl[len(self.static)+1:]
                ext = url[url.rfind(".")+1:]
                if ext in ("gif", "png", "jpg") and utils.get_resource_exists(absurl):
                    data = "data:image/" + ext + ";base64," + base64.b64encode(utils.get_resource_data(absurl))
                    return "url({% endraw %}{% if uridata_support %}" + data + "{% else %}'" + url + "'{% endif %}{% raw %})"
        return "url('%s')" % url

    def get_source(self, environment, path):
        rpath = os.path.join(self.base, path)
        data = utils.get_resource_data(rpath).decode("utf-8")
        if data is None:
            raise jinja2.TemplateNotFound, path
        data = self._link_re.sub(self._link_replace, data)
        data = self._script_re.sub(self._script_replace, data)
        mtime = utils.get_resource_mtime(rpath) if self.autoreload else -1
        return data, path, functools.partial(self._up_to_date, mtime, rpath)


class Server(object):
    _all_servers = set()
    def __init__(self, app, port=0, static="server/static", templates="server/templates"):
        self.app = app
        self.settings = SettingsManager(app)
        self.static = static
        self.port = port if port else 5000 if config.DEBUG else utils.choose_port()
        self.page = "index.html"
        self.url = "http://127.0.0.1:%d" % self.port
        self.sio_server = None
        self.comm = DownloaderXHRConn(self)
        self.buffsize = 524288 # 512 KiB
        self.open_handler = {}

        # Jinja2 config
        autoreload = config.DEBUG and not my_env.is_archive
        self._jinjaenv = jinja2.Environment(
            loader = TemplateLoader(templates, static),
            auto_reload = autoreload,
            extensions=['jinja2.ext.i18n']
            #cache_size = 0 if autoreload else 10
            )
        self._jinjaenv.globals.update({
            "domain": self.url.split(":", 1)[-1], # strip http:
            "APP_DEBUG": config.DEBUG,
            "APP_NAME": constants.APP_NAME,
            "APP_SHORT_NAME": constants.APP_SHORT_NAME,
            "WEB_CATEGORY_PLACEHOLDERS": constants.WEB_CATEGORY_PLACEHOLDERS,
            "SERVER_LOCATION": self.url,
            "LANGUAGES": constants.LANGUAGES.items(),
            })

        self._async_actions = {}
        self._handler_cache = {}
        self._playcards = {}
        self._last_jump_id = None
        self._removed_playcards = []
        self._data = {
            "server": self,
            }
        self._used_hidden_categories = set()

    def set_language(self, catalog):
        self._jinjaenv.install_gettext_translations(catalog)

    _last_remove = 0
    @property
    def last_remove(self):
        return self._last_remove

    _last_update = 0
    @property
    def last_update(self):
        return self._last_update

    @property
    def last_settings(self):
        return self.settings.last_update

    _last_category_update = 0
    @property
    def last_category_update(self):
        return self._last_category_update

    _last_jump = 0
    @property
    def last_jump(self):
        return self._last_jump

    def get_last_removed_playcards(self, lt=0):
        for t, did in self._removed_playcards:
            if t > lt:
                yield did

    def get_last_jump_path(self, lt=0):
        if self._last_jump_id in self._playcards:
            return "all:%s" % self._last_jump_id
        return None

    def get_toolbar_tasks(self, category, download=None, path=""):
        '''
        if isinstance(category, (int, long)):
            numcards = category
        elif download is None:
            numcards = len(self._playcards)
        elif download in self._playcards:
            numcards = sum(1 for i in self._playcards[download].get_content_of(path))
        else:
            numcards = 0
        '''
        numcards = -1
        template = self.get_template("play.html")
        return template.module.toolbar_tasks(numcards, self.get_num_files())

    def get_num_files(self):
        return sum(download.numfiles for download in self._playcards.itervalues())

    def get_playcard(self, category="all", download=None, path="", mintime=0):
        if download in self._playcards:
            return self._playcards[download].get_playcard(path)
        return None

    def get_playcards_json(self, category="all", download=None, path="", mintime=0):
        for card in self.get_playcards(category, download, path, mintime):
            # HTML was deferred until now for performance
            json = card.json
            json["html"] = card.html if card.creation > mintime else None
            yield json

    def get_playcards(self, category="all", download=None, path="", mintime=0):
        if download is None:
            # Getting all downloads
            if category == "all":
                for i in self._playcards.itervalues():
                    if i.last_update > mintime:
                        yield i
            elif category == "recent":
                for i in self._playcards.itervalues():
                    if i.last_update > mintime and i.new:
                        yield i
            else:
                for i in self._playcards.itervalues():
                    if i.last_update > mintime and i.category == category:
                        yield i
        elif download in self._playcards:
            # Getting all files on download path
            download_playcard = self._playcards[download]
            lfr = (category != "recent" or download_playcard.new)
            if download_playcard.last_update > mintime and lfr:
                if category == "all":
                    for i in download_playcard.get_content_of(path):
                        yield i
                else:
                    for i in download_playcard.get_content_of(path):
                        if i.category == category:
                            yield i

    def get_breadcrumbs(self, category="all", download=None, path=""):
        if download in self._playcards:
            template = self.get_template("play.html")
            apath = "%s:%s" % (category, download)
            download = self._playcards[download]
            yield Breadcrumb(apath, download.name, template)
            if path:
                base = "%s:%s" % (category, download.base)
                for component in path.split("/"):
                    apath += "/" + component
                    if apath > base: # We do not show breadcrumbs for directories until base
                        yield Breadcrumb(apath, component, template)


    def get_categories(self, category="all", download=None, path=""):
        template = self.get_template("play.html")
        #apath = ""
        #if download in self._playcards:
        #    apath = self._playcards[download].path
        #    if path:
        #        apath += "/" + path
        #for cat in ("all", "recent", "video", "music", "image", "doc", "software"):
        #    yield Category("%s:%s" % (cat, apath), cat, cat == category, template)
        for cat, text, css in constants.PLAY_CATEGORIES:
            if text:
                if cat in constants.HIDDEN_CATEGORIES and not cat in self._used_hidden_categories:
                    continue
                yield Category("%s:" % cat, _(text).decode('utf-8'), css, cat == category, template)

    _async_actions = None
    def async_action(self, action, *args, **kwargs):
        '''
        socket.io server should not call application functions directly
        so this function allows queueing tasks that will be processed
        in mainloop.
        '''
        self._async_actions.setdefault(action, []).append((args, kwargs))

    def process_async_actions(self):
        while self._async_actions:
            action, calls = self._async_actions.popitem()
            for args, kwargs in calls:
                getattr(self, "action_%s" % action)(*args, **kwargs)

    def action_rename(self, card):
        tlw = WxProxy.unproxize(self.app.GetTopWindow()) if self.app else None
        new_name = wx.GetTextFromUser(_("Rename"), wx.GetTextFromUserPromptStr, card.name, tlw)
        if new_name:
            card.name = new_name
            card.last_update = time.time()
            if card.last_update > self._last_update:
                self._last_update = card.last_update

    def action_open(self, card):
        tlw = WxProxy.unproxize(self.app.GetTopWindow()) if self.app else None
        if os.path.isfile(card.fspath):
            category = card.category
            success = False
            if category in self.open_handler:
                success = self.open_handler[category](card)
            if not success:
                if not my_env.open_file(card.fspath):
                    wx.MessageDialog(
                        tlw, """\
There is no application for this file.\n
Your system has no application associated to this kind of file.""",
                        "Message", wx.OK | wx.ICON_EXCLAMATION).ShowModal()
        else:
            dialog = wx.MessageDialog(
                tlw, """\
This file no longer exists, remove it?\n
This file has been removed from disk, do you want to remove from your library too?""",
                "Question", wx.YES_NO)
            if dialog.ShowModal() == wx.ID_YES:
                card.remove()

    def action_open_folder(self, card):
        folder = card.folder
        if os.path.isdir(folder):
            my_env.open_folder(folder)

    def action_remove(self, card):
        tlw = WxProxy.unproxize(self.app.GetTopWindow()) if self.app else None
        dialog = wx.MessageDialog(tlw, "Remove this download from disk?",
                                  "Removing", wx.YES_NO)
        if dialog.ShowModal() == wx.ID_YES:
            card.remove()

    def _check_used_category(self, cat):
        if cat in constants.HIDDEN_CATEGORIES:
            cats = set(self._used_hidden_categories)
            for i in self._playcards.itervalues():
                cats.discard(i.category)
            if cats:
                self._last_category_update = time.time()
                self._used_hidden_categories.difference_update(cats)

    def _add_used_category(self, cat):
        if cat in constants.HIDDEN_CATEGORIES and not cat in self._used_hidden_categories:
            self._used_hidden_categories.add(cat)
            self._last_category_update = time.time()

    def action_settings(self, settings):
        self.settings.update(settings)

    def has_download(self, download):
        did = str(id(download))
        return did in self._playcards

    def update_download(self, download, is_new=False):
        did = str(id(download))
        if did in self._playcards:
            playcard = self._playcards[did]
            playcard.last_update = time.time()
        else:
            self._playcards[did] = playcard = DownloadPlayCard(self, download, self.get_template("play.html"), is_new)
        self._add_used_category(playcard.category)
        if playcard.last_update > self._last_update:
            self._last_update = playcard.last_update

    def remove_download_ids(self, download_ids):
        t = time.time()
        removed_downloads = []
        recheck_categories = set()
        for did in download_ids:
            did = str(did)
            if did in self._playcards:
                recheck_categories.add(self._playcards[did].category)
                removed_downloads.append((t, did))
                del self._playcards[did]
        if removed_downloads:
            self._removed_playcards.extend(removed_downloads)
            if len(self._removed_playcards) > 100:
                self._removed_playcards[:] = self._removed_playcards[-101:]
            if t > self._last_remove:
                self._last_remove = t
        for category in recheck_categories:
            self._check_used_category(category)

    def remove_downloads(self, downloads):
        self.remove_download_ids(id(i) for i in downloads)

    def handler(self, environ, start_response):
        "Handle server requests"

        if environ['PATH_INFO'] == "/comm":
            return self.comm.handle(environ, start_response)

        # Request object
        request = Request(self, environ)

        # Handler name
        if request.path.startswith("/card_image/"):
            handler = "handle_card_image"
        elif request.path == "/":
            handler = "handle_index"
        else:
            handler = "handle_" + request.path.strip("/").replace("/", "_")

        # Getting handler
        try:
            fnc = self._handler_cache.setdefault(handler, getattr(self, handler))
        except AttributeError:
            self._handler_cache[handler] = fnc = self.serve_file

        # Process
        try:
            r = fnc(request)
        except Request.Abort as e:
            logger.debug(e.msg)

        # Content-body test
        try:
            if isinstance(r, types.GeneratorType):
                r = itertools.chain((r.next(),), r) # For response headers
        except StopIteration:
            request.error(404)

        start_response(request.response_code, request.response_header_list)
        data = request.response_body or r

        # UTF8 body
        if request.response_headers.get("Content-Type", "").endswith("; charset=utf-8"):
            if isinstance(data, unicode):
                return (data.encode("utf-8"), ) # PYWSGI expects iterable
            elif hasattr(data, "__iter__"):
                return (i.encode("utf-8") if isinstance(i, unicode) else i for i in data)
            return ()

        # Data must be iterable
        if isinstance(data, basestring):
            return (data, )  # PYWSGI expects iterable
        elif hasattr(data, "__iter__"):
            return data
        return ()

    def get_template(self, path):
        return self._jinjaenv.get_template(path)

    def get_static(self, path):
        return utils.get_resource_data(self.static + "/" + path)

    def handle_error(self, request):
        return request.render_template(
            "error.html",
            home_url = request.query["url"][0],
            home_method = request.query["method"][0].upper()
            )

    def handle_play(self, request):
        return request.render_template(
            "play.html",
            num_files = -1,
            total_files = self.get_num_files(),
            breadcrumbs = self.get_breadcrumbs(),
            playitems = sorted(self.get_playcards(), key=lambda x: x.name.lower()),
            categories = self.get_categories()
            )

    def handle_settings(self, request):
        return request.render_template(
            "settings.html",
            backends = self.app.backend.backends,
            num_backends = len(self.app.backend.backends)
            )

    def handle_card_image(self, request):
        path = request.path[12:] # len("/card_image/") == 12
        if "/" in path:
            download, path = path.split("/", 1)
        else:
            download = path
            path = ""
        if download in self._playcards:
            data = self.get_playcard("all", download, path).preview
            if data:
                request.response_headers['Content-Type'] = "image/%s" % utils.image_format(data)
                request.cache_forever()
                return data
        request.error(404)

    _forced_mimes = {
        "png": "image/png",
        "gif": "image/gif",
        "jpg": "image/jpg",
        "js": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "swf": "application/x-shockwave-flash",
        }
    def serve_file(self, request):
        ''' Load files from static directory '''
        path = os.path.join(self.static, request.path.lstrip('/')).replace(os.sep, '/')
        if path.startswith(self.static): # extra check due ".." components
            if utils.get_resource_isdir(path):
                path = path.rstrip("/") + "/index.html"
            if utils.get_resource_exists(path):
                ext = path.rsplit(".", 1)[-1]
                if ext in self._forced_mimes:
                    mime = self._forced_mimes[ext]
                else:
                    mime, encoding = mimetypes.guess_type(path)
                    if mime is None:
                        mime = "application/octet-stream"
                    if encoding:
                        mime += "; " + encoding
                request.response_headers['Content-Type'] = mime
                fp = utils.get_resource_stream(path)
                chunk = fp.read(self.buffsize)
                if not config.DEBUG:
                    request.cache_for(3600) # an hour
                while chunk:
                    yield chunk
                    chunk = fp.read(self.buffsize)
            else:
                request.error(404)
        else:
            request.error(404)

    def jump_play(self, download):
        self._last_jump = time.time()
        self._last_jump_id = str(id(download))

    def jump_settings(self, tbd):
        pass

    def loop(self, event=None):
        if self.running:
            self.process_async_actions()
            try:
                gevent.sleep()
            except KeyboardInterrupt:
                self.app.close_app()

    @property
    def running(self):
        #return self._thread.is_alive()
        return self in self._all_servers

    @classmethod
    def shutdown_all(cls):
        for i in tuple(cls._all_servers):
            i.shutdown()

    def shutdown(self):
        if self.running:
            self._server.stop()
            self._all_servers.remove(self)

    _wkutimer = None
    def start(self):
        if not self._wkutimer:
            self._wkutimer = wx.Timer(
                WxProxy.unproxize(self.app),
                wx.ID_ANY
                ) # WakeUp timer on wxApp

        self._all_servers.add(self)
        self._server = WSGIServer(
            ('0.0.0.0' if config.DEBUG else '127.0.0.1', self.port),
            self.handler,
            log=None #log="default" if config.DEBUG else None,
            )
        self._server.start()
        self.app.Bind(wx.EVT_TIMER, self.loop, None, self._wkutimer.GetId())
        self._wkutimer.Start(50) # Using EVT_IDLE eats CPU

        logger.debug("Local SocketIO server on %s" % self.url)

    def _fill_list(self, l, *args):
        l.extend(args)
        return l

    def get_url(self, url):
        environ = os.environ.copy()
        environ["PATH_INFO"] = url
        r = self.handler(environ, functools.partial(self._fill_list, l))
        if not isinstance(r, basestring):
            r = "".join(r)
        return l[0], l[1], r

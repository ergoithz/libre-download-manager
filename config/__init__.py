#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import os.path
import logging
import atexit
import codecs
import threading
import collections
import shutil
import time
import json
import platform
import wx
import zlib

import traceback

import locale

try:
    import cPickle as pickle # C module
except ImportError:
    import pickle # Python fallback

try:
    import cStringIO as StringIO # C module
except ImportError:
    import StringIO # Python fallback

import my_env

# Local imports
import utils

from constants import constants
from utils import attribute, DefaultAttrDict, StaticClass
from .extensions import extensions

NO_IMAGE = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7".decode("base64")

CATEGORY_PRIORITY = ("executable", "plugin", "backup", "disk image", "compressed", "video", "ebook", "audio", "music", "3d image", "raster image", "camera raw", "vector image", "cad", "database", "spreadsheet",  "font", "settings", "game", "gis", "data", "page layout",  "developer", "web", "text", "encoded", "system", "misc")

# BOSS ORDER
CATEGORY_ICONS = {k: constants.WEB_CATEGORY_ICONS[v] for k, v in constants.CATEGORY_WEB_CATEGORY.iteritems()}
WEB_CATEGORIES = set(constants.CATEGORY_WEB_CATEGORY.itervalues())
WEB_CATEGORIES.update(constants.WEB_CATEGORY_ICONS)

EXTENSION_ICONS = {
    #"exe": "windows-executable",
    #"msi": "windows-executable",
    #"msu": "windows-executable",
    #"xhmtl": "text-xhtml+xml",
    #"xml": "text-xhtml+xml",
    #"swf": "application-x-shockwave-flash",
    #"rb": "application-x-ruby",
    #"torrent": "torrent",
    #"jpg": "image-jpeg",
    #"png": "image-png",
    #"tiff": "image-tiff",
    #"tif": "image-tiff",
    #"bmp": "image-bmp",
    #"ico": "image-x-ico",
    #"xcf": "image-x-xcf",
    #"psd": "image-x-psd",
    #"ai": "image-x-eps",
    #"py": "text-x-python",
    #"pyw": "text-x-python",
    #"zip": "zip",
    #"rar": "application-x-rar",
    #"jar": "application-x-jar",
    #"java": "application-x-java",
    #"7z": "application-7zip",
    #"ace": "application-x-ace",
    #"js": "application-javascript",
    #"rtf": "application-rtf",
    #"doc": "application-msword",
    #"docx": "application-msword",
    #"odt": "application-vnd.oasis.opendocument.text",
    #"ogg": "application-ogg",
    #"oga": "application-ogg",
    #"wav": "audio-x-wav",
    #"wma": "audio-x-ms-wma",
    #"mp3": "audio-mpeg",
    #"pdf": "application-pdf",
    #"pgp": "application-pgp-encrypted",
    #"ppt": "application-vnd.ms-powerpoint",
    #"pptx": "application-vnd.ms-powerpoint",
    #"sxi": "application-vnd.openxmlformats-officedocument.presentationml.presentation",
    }

if my_env.is_frozen:
    APPEXE = os.path.abspath(sys.executable)
    APPDIR = os.path.dirname(APPEXE)
    if hasattr(sys, "_MEIPASS"):  # using pyinstaller!
        RESOURCESDIR = sys._MEIPASS
else:
    APPEXE = None
    APPDIR = os.path.dirname(os.path.abspath(utils.__file__))
    if ('/site-packages' in __file__ or
        '/dist-packages' in __file__):  # we have python setup.py install-ed
        RESOURCESDIR = os.path.abspath(os.path.join(APPDIR, '../../..'))
    else:
        RESOURCESDIR = APPDIR

DEBUG = ("--debug" in sys.argv)
SLAVE = ("--slave" in sys.argv)

LOCALEDIR = os.path.join(RESOURCESDIR, "locale")

def guess_category(filenames, criteria=None):
    '''
    Detect category of torrent based on its files.

    Params:
        filenames:
        criteria:

    Returns:
        Category as basestring.
    '''
    fexts = frozenset(i.rsplit(".")[-1] for i in filenames if "." in i)
    fcats = frozenset(cat for ext in fexts if ext in extensions for cat in extensions[ext] )
    if fcats:
        if criteria is None:
            criteria = CATEGORY_PRIORITY.index
        return min(fcats, key=criteria)
    return "misc"

def web_category_criteria(x):
    '''
    Criteria for `guess_web_category` for `using guess_category`.

    Params:
        x

    Returns:
        Category as basestring.
    '''
    if constants.CATEGORY_WEB_CATEGORY.get(x, "unknown") == "unknown":
        return sys.maxint
    return CATEGORY_PRIORITY.index(x)

def guess_web_category(filenames, criteria=None):
    '''
    Detect category of torrent using web categories based on its files.


    '''
    if criteria is None:
        criteria = web_category_criteria
    return constants.CATEGORY_WEB_CATEGORY.get(guess_category(filenames, criteria), "unknown")

def validate_web_category(category):
    '''
    Check if given web category is valid.

    Returns:
        True if given category is in configuration (and is handled), False
        otherwise.
    '''
    return category in WEB_CATEGORIES and not category in constants.BAD_WEB_CATEGORIES


def get_default_language():
    "Return lang code of the default locale (like 'en') if available, or None"
    try:
        syslang, encoding = locale.getdefaultlocale()
        if syslang:
            for lang in constants.LANGUAGES:
                if syslang.startswith(lang):
                    return lang
    except ValueError:  # ignore bug on mac
        pass
    return None


class HangException(Exception):
    pass

class ResourceManager(object):
    VALUE_UNSET = StaticClass.new("ValueUnsetType")
    icon_dir = "icons"
    data_dir = "data"
    image_dir = "gui"

    def __init__(self):
        self._guess_icon_cache = {(): CATEGORY_ICONS["misc"]}
        self._guess_web_icon_cache = {(): constants.WEB_CATEGORY_ICONS["unknown"]}
        self.data = DefaultAttrDict(factory=self._data_factory)
        self.bitmap = DefaultAttrDict(factory=self._bitmap_factory)
        self.image = DefaultAttrDict(factory=self._image_factory)

    def _data_factory(self, k):
        return utils.get_resource_data(os.path.join(self.data_dir, k))

    _use_input_stream = not "(phoenix)" in wx.version()
    @classmethod
    def _bitmap_from_stream(cls, stream):
        if cls._use_input_stream:
            stream =  wx.InputStream(stream)
        return wx.BitmapFromImage(wx.ImageFromStream(stream))

    @classmethod
    def _bitmap_from_data(cls, data):
        return cls._bitmap_from_stream(StringIO.StringIO(data))

    _bitmap_empty_cache = None
    @classmethod
    def _bitmap_empty(cls):
        if cls._bitmap_empty_cache is None:
            cls._bitmap_empty_cache = cls._bitmap_from_data(NO_IMAGE)
        return cls._bitmap_empty_cache

    def _bitmap_factory(self, k, directory=icon_dir):
        if k is None:
            return self._bitmap_empty()
        if not k[-4:] in (".ico", ".png", ".cur"):
            k += ".png"
        stream = utils.get_resource_stream(os.path.join(directory, k))
        if stream is None:
            logging.warn("%s bitmap resource is unavaliable" % k)
            return self._bitmap_empty()
        return self._bitmap_from_stream(stream)

    def _image_factory(self, k):
        return self._bitmap_factory(k, self.image_dir)

    def load_text(self, k):
        data = self.data["%s.txt" % k]
        if data is None:
            return wx.EmptyString
        if data.startswith(codecs.BOM_UTF8):
            data = data[len(codecs.BOM_UTF8):]
        return data.decode("utf-8")

    def load_icon(self, name):
        return wx.IconFromBitmap(self.bitmap[name])

    def load_mscur(self, name):
        stream = utils.get_resource_stream(os.path.join(self.icon_dir, "%s.cur" % name))
        if not stream is None:
            return wx.CursorFromImage(wx.ImageFromStream(wx.InputStream(stream), wx.BITMAP_TYPE_CUR))
        return wx.NullCursor

    def _guess_icon(self, filenames, guesser):
        fcat = guesser(filenames)
        return

    _guess_icon_cache = None
    def guess_icon(self, filenames):
        r = tuple(sorted(filenames))
        if not r in self._guess_icon_cache:
            category = guess_category(filenames)
            for i in filenames:
                ext = i[i.find(".", max(i.find(os.sep), 0))+1: ]
                if ext in EXTENSION_ICONS and category in extensions[ext]:
                    icon = EXTENSION_ICONS[ext]
                    break
            else:
                icon = CATEGORY_ICONS[category]
            self._guess_icon_cache[r] = icon
        return self.image[self._guess_icon_cache[r]]

    _guess_web_icon_cache = None
    def guess_web_icon(self, filenames):
        r = tuple(sorted(filenames))
        if not r in self._guess_web_icon_cache:
            category = guess_web_category(filenames)
            icon = constants.WEB_CATEGORY_ICONS.get(category, constants.WEB_CATEGORY_ICONS["unknown"])
            self._guess_web_icon_cache[r] = icon
        return self.image[self._guess_web_icon_cache[r]]

    def get_web_category_icon(self, name):
        if name in constants.WEB_CATEGORY_ICONS:
            return self.image[constants.WEB_CATEGORY_ICONS[name]]
        return self.image[CATEGORY_ICONS["misc"]]

class Config(dict, utils.EventHandler):
    @attribute
    def config_file(self):
        return os.path.join(my_env.get_config_dir(),
                            "state.bin" if my_env.is_windows else "state")

    @attribute
    def default_download_dir(self):
        "Return the path to the default downloads dir for the application"
        return os.path.join(my_env.get_download_dir(),
                            "%s downloads" % constants.APP_NAME)

    '''
    def trash(self, path):
        try:
            send2trash.send2trash(path)
        except OSError as e:
            logging.exception(e)
    '''

    def __repr__(self):
        return object.__repr__(self)

    def handle_torrent_default(self, k, v):
        if v:
            my_env.set_default_for_torrent()
        else:
            # Cannot disable being the default app
            pass

    def handle_run_at_startup(self, k, v):
        my_env.set_run_startup(v)

    def handle_auto_ports(self, k, v):
        if v:
            for i in self.port_keys:
                self[i] = -1
                del self[i]

    def handle_slow_mode(self, k, v):
        mode = "slow" if v else "standard"
        self["max_downspeed"] = self["download_%s_downspeed" % mode]
        self["max_upspeed"] = self["download_%s_upspeed" % mode]
        self["max_active_downloads"] = self["download_%s_active_downloads" % mode]

    def handle_mode_downspeed(self, k, v):
        slow_mode = k.split("_", 2)[1] == "slow"
        if self["download_slow_mode"] == slow_mode:
            self["max_downspeed"] = v

    def handle_mode_upspeed(self, k, v):
        slow_mode = k.split("_", 2)[1] == "slow"
        if self["download_slow_mode"] == slow_mode:
            self["max_upspeed"] = v

    def handle_mode_active_downloads(self, k, v):
        slow_mode = k.split("_", 2)[1] == "slow"
        if self["download_slow_mode"] == slow_mode:
            self["max_active_downloads"] = v

    @classmethod
    def _extract_port_keys(cls, iterable):
        '''
        Backend and ports are initially unknown by design, but all of
        them use the same format: "port_%(BACKEND_NAME)s_%(PORT_NUMBER)d".

        We need this function to get all ports keys in iterable.
        '''
        return [i for i in iterable if i.startswith("port_") and i.count("_") > 1 and i[i.rfind("_")+1:].isdigit()]

    @property
    def port_keys(self):
        return self._extract_port_keys(self)

    def __init__(self, appname, appversion):
        self.appname = appname
        self.appversion = appversion

        data = {}
        if os.path.isfile(self.config_file):
            f = open(self.config_file, "rb")
            try:
                data = pickle.load(f)
            except BaseException:
                data = {}
            f.close()

        # Fix current language if not in languages list
        if "language" in data and data["language"] not in constants.LANGUAGES:
            del data["language"]

        # keys in blacklist are not saved, useful for enviroment variables
        self.__blacklist = {
            # Virtual
            "torrent_default", "run_at_startup", "auto_ports",
            # System config
            "max_half_open_connections"
            }
        # keys are not saved if equal to default

        half_open_connections = my_env.get_max_half_open_connections()

        self.__defaults = {
            "download_dir": self.default_download_dir,
            "download_notification": True,
            "torrent_default": my_env.get_default_for_torrent(),
            "run_at_startup": my_env.get_run_startup(),
            "auto_ports": not bool(self._extract_port_keys(data)), # auto_ports if no port data
            "keep_awake": False,
            "download_slow_mode": False,
            "download_standard_downspeed": -1,
            "download_standard_upspeed": -1,
            "download_standard_active_downloads": 3,
            "download_slow_downspeed": 10000,
            "download_slow_upspeed": 5000,
            "download_slow_active_downloads": 1,
            "max_downspeed": -1,
            "max_upspeed": -1,
            "max_active_downloads": 3,
            "max_connections": 250,
            "max_half_open_connections": half_open_connections or 100,
            }
        dict.__init__(self, data)

        # Remove blacklisted keys from old data
        for i in self.__blacklist.intersection(self):
            logging.debug("Blacklisted key in config found: %s" % i)
            del self[i]

        # Configure event handling
        self.enable_reemit(lastonly=True)

        # Initial value emits emits
        current_values = dict(self.__defaults)
        current_values.update(self)
        for k, v in current_values.iteritems():
            self.emit(k, k, v)

        # Default event handlers
        handlers = {
            # Virtual
            "torrent_default": [self.handle_torrent_default],
            "run_at_startup": [self.handle_run_at_startup],
            "auto_ports": [self.handle_auto_ports],
            # Special
            "download_slow_mode": [self.handle_slow_mode],
            "download_standard_downspeed": [self.handle_mode_downspeed],
            "download_standard_upspeed": [self.handle_mode_upspeed],
            "download_standard_active_downloads": [self.handle_mode_active_downloads],
            "download_slow_downspeed": [self.handle_mode_downspeed],
            "download_slow_upspeed": [self.handle_mode_upspeed],
            "download_slow_active_downloads": [self.handle_mode_active_downloads],
            }
        for event_name, handlers in handlers.iteritems():
            for handler in handlers:
                self.on(event_name, handler)

    def realtime_speed(self, downspeed, upspeed):
        ''' Stub for calculations '''
        pass

    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        if k in self.__defaults:
            return self.__defaults[k]
        raise KeyError, "Key %s not found in config or defaults" % repr(k)

    def __setitem__(self, k, v):
        value_changed = True
        if dict.__contains__(self, k):
            if k in self.__defaults and v == self.__defaults[k]:
                del self[k]
            elif self[k] != v:
                dict.__setitem__(self, k, v)
            else:
                value_changed = False
        else:
            dict.__setitem__(self, k, v)

        if value_changed:
            self.emit(k, k, v)
            if not k in self.__blacklist:
                self.save()

    def __contains__(self, k):
        return dict.__contains__(self, k) or self.__defaults.__contains__(k)

    def save(self):
        path = os.path.dirname(self.config_file)
        data = {
            k: v
            for k, v in self.iteritems()
            if not k in self.__blacklist
            }
        if not os.path.isdir(path):
            os.makedirs(path)
        f = open(self.config_file, "wb")
        pickle.dump(data, f)
        f.close()

class SingleInstance(object):
    _alone = False
    _other_pid = None
    @property
    def alone(self):
        return self._alone

    def __init__(self, unique = True):
        userid = wx.GetUserId()

        self.pidfile = my_env.tempfilepath("pid_%s" % userid)
        self.commfilepath = my_env.tempfilepath("comm_%s" % userid)
        self.update_interval = 1 # Timeout for commfile check

        if unique:
            # Reading pid file and check if running
            self._alone = not my_env.get_running_pidfile(self.pidfile)
            if self._alone:
                self._write_pid()

    def _write_pid(self):
        # Writing pid file
        with open(self.pidfile, "w") as f:
            f.write(str(os.getpid()))

    def check(self):
        if os.path.isfile(self.commfilepath):
            with open(self.commfilepath, "r") as f:
                data = f.read().decode("utf-8").splitlines()

            for line in data:
                if line: # Strips EOLs unlike readlines, filter empty lines
                    yield line

            last_error = "commfile wasn't deleted"
            for i in xrange(10):
                try:
                    os.remove(self.commfilepath)
                except BaseException as e:
                    last_error = e
                else:
                    break
            else:
                logging.warn(last_error)

    def send(self, line):
        logging.debug(os.linesep.join(traceback.format_stack()))
        f = open(self.commfilepath, "a+", 0) # buffsize 0
        f.write("%s\n" % line.encode("utf-8"))
        f.close()
        w = self.update_interval/3.
        for i in xrange(6):
            if not os.path.exists(self.commfilepath):
                break
            time.sleep(w)
        else:
            os.remove(self.commfilepath)
            raise HangException("Main instance does not respond")

    def kill_other(self):
        if not self._alone:
            my_env.kill_process_pidfile(self.pidfile)
            self._alone = True
            self._write_pid()

    def release(self):
        if self._alone and os.path.isfile(self.pidfile):
            os.remove(self.pidfile)

    def __del__(self):
        self.release()

class AutoUpdater(object):

    class ServerMessage(dict):
        @property
        def shown(self):
            return self._uid in self._shown

        @shown.setter
        def shown(self, v):
            if v:
                self._shown.add(self._uid)
            elif self.shown:
                self._shown.remove(self._uid)

        def __init__(self, updater, data):
            dict.__init__(self, data)

            if "id" in data:
                self._shown = updater.known_messages
                self._uid = data["id"]
            else:
                self._shown = updater.shown_messages
                self._uid = hash(json.dumps(data))

    download_chunk_size = 4096
    enabled = False

    _checked = False
    @property
    def checked(self):
        if self.enabled:
            return self._checked
        return True

    @checked.setter
    def checked(self, v):
        self._checked = v

    _checking_thread = None
    @property
    def checking(self):
        if self._checking_thread is None:
            return False
        return self._checking_thread.isAlive()

    _downloading_thread = None
    @property
    def downloading(self):
        if self._downloading_thread is None:
            return False
        return self._downloading_thread.isAlive()

    text = ""
    title = ""

    new_version = None
    downloaded = False
    outdated = False
    simple_mode = constants

    clean_error = None

    known_messages = None # Store ids for non-repeatable messages
    shown_messages = None # Store hashes for repeatable messages to do not repeat in session

    def __init__(self, uid, app, version, useragent, lang="en"):
        self._appversion = version
        self._useragent = useragent
        self.known_messages = utils.OrderedSet()
        self.shown_messages = set()
        self.update_data = {}
        self.appname = app
        self.version_url = ""

        if constants.APP_UPDATE_MODE == 2:
            self.default_text = _(
                "New version of %s is ready to install.\n"
                "Do you want to upgrade?"
                ) % app
            self.default_title = _("Update available")
            self.update_commands = []
            self.download_url = None # Update mode 2 uses no download url
            self.version_url = constants.URL_UPDATE_INFO_URL
            self.version = version
            self.lang = lang
            self._check = self._newcheck  # confusingly enough
            self._download = self._newdownload
            self._apply = self._newapply

        self.platform = platform.platform()
        self.must_download = (self.version_url and my_env.is_windows and my_env.is_frozen)
        self.must_check = constants.APP_UPDATE_MODE > 1 or self.must_download

        # Prepare download dir
        self.download_path = my_env.tempdirpath("update")

        self.enabled = self.must_check

        if self.must_download:
            # Download updates only applies to WinNT frozen exe distributions
            self.download_chunk_size = my_env.get_blocksize(self.download_path)
            self.remove_old_download()

        # Old download cleanup
        if os.path.isdir(self.download_path):
            shutil.rmtree(self.download_path, True)

    def remove_old_download(self):
        last_error = None
        if os.path.isdir(self.download_path):
            for i in xrange(100):
                try:
                    shutil.rmtree(self.download_path)
                except BaseException as e:
                    logging.debug(e)
                    last_error = e
                else:
                    break
                time.sleep(0.1)
        self.clean_error = last_error if os.path.isdir(self.download_path) else None

    def _iter_unshown_messages(self):
        for message in self.update_data["messages"]:
            r = self.ServerMessage(self, message)
            if not r.shown:
                yield r

    def poll_messages(self):
        if "messages" in self.update_data and self.update_data["messages"]:
            return list(self._iter_unshown_messages())
        return []

    def _newcheck(self, current_version):
        # This one make a request to self.version_url with a POST,
        # giving all the information about version, lang and platform
        args = {"version": self.version,
                "lang": self.lang,
                "platform": self.platform}
        response = utils.GetURL(
            self.version_url % args, args=args, useragent=self._useragent)
        if response.code == 200:
            self.update_data = json.load(response)
            logging.debug("Server: %r" % (self.update_data,))
        self.checked = True

        if self.must_download and ( # APP_UPDATE_MODE 2 allows check without download
          "update" in self.update_data and
          "files" in self.update_data["update"] and
          self.update_data["update"]["files"]
          ):
            self.outdated = True
            self.new_version = max(i.get("version", 0) for i in self.update_data["update"]["files"])
        else:
            self.outdated = False
            self.new_version = None

    def _check(self, current_version):
        response = utils.GetURL(self.version_url, useragent = self._useragent)
        if response.code == 200:
            updates = []
            for i in response.lines:
                try:
                    version, filename = i.strip().split(None, 1)
                    updates.append((filename, version))
                except BaseException as e:
                    logging.debug(e)
            self.update_files.clear()
            self.update_files.update(updates)

        self.checked = True
        self.outdated = any(v > current_version for v in self.update_files.itervalues())
        self.new_version = max(v for k, v in self.update_files.iteritems()) if self.outdated else None

    def check(self, current_version):
        if self.must_check:
            self.remove_old_download()
            self._checking_thread = threading.Thread(target=self._check, args=(current_version,))
            self._checking_thread.start()
        else:
            self.checked = True
            self.outdated = False
            self.new_version = None

    def _newdownload(self):
        del self.update_commands[:]
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)

        if "update" in self.update_data and "files" in self.update_data["update"]:
            for n, fdata in enumerate(self.update_data["update"]["files"]):
                response = utils.GetURL(
                    fdata["url"],
                    buffsize = self.download_chunk_size,
                    useragent = self._useragent
                    )
                if response.code == 200:
                    setup_path = os.path.join(self.download_path, "update_%d.exe" % n)
                    with open(setup_path, "wb") as f:
                        for data in response:
                            f.write(data)
                    self.update_commands.append((setup_path,) + tuple(fdata["argv"]))
                else:
                    # TODO(felipe): on error, try again later
                    logging.error("GET %s %s" % (response.code, fdata["url"]))
                    break
            else:
                self.downloaded = bool(self.update_commands)
                self.text = self.update_data["update"].get("text", self.default_text)
                self.title = self.update_data["update"].get("title", self.default_title)
        else:
            self.downloaded = False
            self.text = self.default_text
            self.title = self.default_title

    def _download(self):
        self.downloaded_files.clear()
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)
        for filename, version in self.update_files.iteritems():
            response = utils.GetURL(
                self.download_url % {"version": self._appversion, "file": filename, "platform": self.platform},
                buffsize = self.download_chunk_size,
                useragent = self._useragent
                )
            if response.code == 200:
                setup_path = os.path.join(self.download_path, filename)
                response.save(setup_path)
                self.downloaded_files[filename] = response.finished and not response.failed
            else:
                self.downloaded_files[filename] = False
        self.downloaded = any(self.downloaded_files.itervalues())
        self.text = self.simple_update_text % {"appname": self.appname, "version": self.new_version}
        self.title = self.simple_update_title % {"appname": self.appname, "version": self.new_version}

    def download(self):
        if self.must_download: # needless extra check
            self.remove_old_download()
            self._downloading_thread = threading.Thread(target=self._download)
            self._downloading_thread.start()

    def _newapply(self):
        for command in self.update_commands:
            my_env.call(my_env.resolve_app_params(command), shellexec=True)

    def _apply(self):
        version = self._appversion.replace(" ", "_")
        for filename, downloaded in self.downloaded_files.iteritems():
            if downloaded:
                setup_path = os.path.join(self.download_path, filename)
                my_env.call([
                    setup_path, "/SILENT", "/NORESTART",
                    "/RESTARTAPPLICATIONS", "/LAUNCH", "/VERSION=%s" % version],
                            shellexec=True)

    def apply(self):
        if my_env.is_windows:
            self._apply()


def list_icons():
    '''
    # New GUI icons are static
    icons = [
        icon
        for icondict in (CATEGORY_ICONS, EXTENSION_ICONS)
        for icon in icondict.itervalues()
        ]
    return {48: icons}
    '''
    return {}

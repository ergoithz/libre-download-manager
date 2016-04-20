#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import os.path
import utils
import config
import time

import my_env

choose_port = utils.choose_port
faster_url = utils.CheckURL.faster_url
old_download_dir = my_env.get_old_download_dir()

def parse_port_tuple(defaults, port_tuple):
    if isinstance(port_tuple, int):
        return (port_tuple, ) + defaults[1:]
    if len(port_tuple) == 0:
        return defaults
    if len(port_tuple[0]) == 2:
        return parse_port_tuple(defaults, tuple(i[1] for i in port_tuple))
    return port_tuple + defaults[len(port_tuple):]

class Download(object):
    name = ""
    state = "unknown"
    processing = False
    downloading = False
    finished = False
    paused = False
    stopped = False
    queued = False
    downspeed = 0
    upspeed = 0
    sources = 0
    size = 0
    progress = 0
    backend = None
    properties = ()
    available_peers = (-1, -1) # Complete and incomplete
    availability = -1
    last_update = 0

    position = -1
    user_data = None

    eta = None
    def __init__(self, backend, resume_data=None):
        self.backend = backend
        self.resume_data = resume_data
        self._blacklist = {}

        if resume_data:
            self.position = resume_data.get("position", -1)
            self.user_data = resume_data.get("user_data", None)
            self.hidden = resume_data.get("hidden", False)

    def blacklist_add(self, path=None):
        return False

    _hidden = False
    @property
    def hidden(self):
        return self._hidden

    @hidden.setter
    def hidden(self, v):
        if self._hidden != v:
            self.backend.emit("download_hide" if v else "download_unhide", self)
            self._hidden = v

    @property
    def download_dir(self):
        return self.backend.download_dir

    @download_dir.setter
    def download_dir(self, v):
        pass

    @property
    def blacklist(self):
        return frozenset()

    def hide(self):
        self.hidden = True

    @property
    def file_progress(self):
        return {}

    @property
    def position(self):
        return self.backend.manager.get_download_position(self)

    @position.setter
    def position(self, v):
        self.backend.manager.set_download_position(self, v)
        self.backend.outdated_downloads.add(self)

    @property
    def visible_position(self):
        # TODO(felipe): Optimize this
        s = 0
        for i in self.backend.manager.downloads:
            if i is self:
                break
            if i and not i.hidden:
                s += 1
        return s

    def refresh(self):
        self.last_update = time.time()

    def resume(self):
        pass

    def pause(self):
        pass

    def has_metadata(self):
        return False

    @property
    def filenames(self):
        return []

    _path_cache = None
    @property
    def path(self):
        if self._path_cache is None:
            filenames = self.filenames
            if filenames:
                base = os.path.dirname(filenames[0]) # Path refers to directories
                while base:
                    sepbase = base + os.sep
                    if all(i.startswith(sepbase) for i in filenames):
                        self._path_cache = r = os.path.join(self.download_dir, base)
                        return r
                    base = os.path.dirname(base)
            return self.download_dir
        return self._path_cache

    def recheck(self):
        pass

    def remove(self):
        pass

    def json(self):
        return dict(
            (i, getattr(self, i))
            for i in dir(self)
            if not (i.startswith("__") or hasattr(getattr(self, i), "__call__"))
            )


class Backend(utils.EventHandler):
    '''
    Backends
     - Create Downloads, store and manage them.
     - Could be managed by MultiBackend.

    If backend is manager, it must implement instacemethod
    prepare_position_for_download(new_position, download) which will
    be called everytime a download position is changed in order to
    fix others' positions.

    - Events emitted:
        |- download_new
        |  |- Emited once download is added to queue.
        |  `- Callable params: download_instance
        |- download_update
        |  |- Emited once download information is changed.
        |  `- Callable params: download_instance
        |- download_remove
        |  |- Emited once download is removed from queue.
        |  `- Callable params: download_instance
        |- download_hide
        |  |- Emited once download is hidden.
        |  `- Callable params: download_instance.
        `- download_unhide
           |- Emited once download is not hidden after being hidden.
           `- Callable params: download_instance
    - Events emitted by managers:
        |- backend_add
        |  |- Emited when new backend is added to manager
        |  `- Callable params: new backend instance.
        `- backend_remove
           |- Emited when backend is removed from manager
           `- Callable params: removed backend instance.

    '''
    enabled = False
    priority = 0
    download_dir = None
    appname = None
    appversion = None
    manager = None
    downspeed = 0
    upspeed = 0
    ports = ()
    downloads = None

    @property
    def download_dir(self):
        return self.config["download_dir"]

    def __init__(self, config, app=None, version=None, manager=None):
        self.appname = app
        self.appversion = version
        self.downloads = []
        self.outdated_downloads = set()
        self.config = config
        # Backends are self-managed if not manager is specified
        self.manager = self if manager is None else manager

        # Reemit download_new events on subscribing
        self.enable_reemit("download_new")

        self.on("download_remove", self._on_download_remove)

    def _on_download_remove(self, download):
        self.cancel_reemit("download_new", download)

    def invalidate(self, v=None):
        if v is None:
            self.manager.invalidate(self)
        elif v is self:
            raise RuntimeError("%s failed." % self.__class__.__name__)

    @property
    def status(self):
        return ()

    @property
    def name(self):
        name = self.__class__.__module__.split(".")[-1]
        if name.startswith("_"):
            return name[1:]
        return name

    @property
    def last_position(self):
        return self.downloads[-1].position

    def count_downloads(self):
        return len(self.downloads)

    def set_state(self, state):
        if state is None:
            return
        assert isinstance(state, dict), "State of %s must be a dict" % self.__class__.__name__

    def get_state(self):
        return None

    def get_run_state(self):
        return self.get_state()

    def run(self):
        pass

    def stop(self):
        pass

    def pause(self):
        pass

    def resume(self):
        pass

    def get_download_position(self, download):
        try:
            return self.downloads.index(download)
        except ValueError:
            return len(self.downloads)

    def set_download_position(self, download, pos):
        if download in self.downloads:
            if self.downloads.index(download) == pos:
                return
            self.downloads.remove(download)
        if pos == -1:
            self.downloads.append(download)
        else:
            ldown = len(self.downloads)
            if pos >= ldown:
                self.downloads.extend(None for i in xrange(ldown, pos))
                self.downloads.append(download)
            elif self.downloads[pos] is None:
                self.downloads[pos] = download
            else:
                self.downloads.insert(pos, download)

    def can_download(self, uri):
        '''
        Test if this backend can handle this kind of link
        '''
        return False

    def download(self, uri, user_data=None):
        '''
        Try to add the download to the backend

        Must return the ID the download will have in future.
        '''
        return False

    def refresh(self):
        while self.outdated_downloads:
            outdated_download = self.outdated_downloads.pop()
            outdated_download.refresh()
            self.emit("download_update", outdated_download)

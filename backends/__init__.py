#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import operator
import functools
import utils

from .base import Backend as BackendBase

logger = logging.getLogger(__name__)

_g = globals()
_l = locals()
available_backends = [
    __import__("backends._%s" % module, _g, _l, ("Backend",), -1).Backend
    for module in ["libtorrent"] #, "amule")
    ]
class MultiBackend(BackendBase):
    # Property proxies

    @property
    def download_dir(self):
        download_dirs = frozenset(i.download_dir for i in self.backends if i)
        assert len(download_dirs) == 1, RuntimeError("Multiple or Zero download dirs are not supported.")
        return iter(download_dirs).next()

    @download_dir.setter
    def download_dir(self, v):
        for i in self.backends:
            i.download_dir = v

    @property
    def appname(self):
        appnames = frozenset(i.appname for i in self.backends if i)
        assert len(appnames) == 1, RuntimeError("Multiple or Zero appnames are not supported.")
        return iter(appnames).next()

    @appname.setter
    def appname(self, v):
        for i in self.backends:
            i.appname = v

    @property
    def appversion(self):
        appversions = frozenset(i.appversion for i in self.backends if i)
        assert len(appversions) == 1, RuntimeError("Multiple or Zero appnames are not supported.")
        return iter(appversions).next()

    @appversion.setter
    def appversion(self, v):
        for i in self.backends:
            i.appversion = v

    @property
    def downspeed(self):
        return sum(o.downspeed for o in self.backends)

    @property
    def upspeed(self):
        return sum(o.upspeed for o in self.backends)

    @property
    def max_upspeed(self):
        return sum(o.max_upspeed for o in self.backends)

    @max_upspeed.setter
    def max_upspeed(self, v):
        # TODO(felipe): adjust automatically based on bandwidth consuption on multiple backends
        for o in self.backends:
            o.max_upspeed = v

    @property
    def max_downspeed(self):
        return sum(o.max_downspeed for o in self.backends)

    @max_downspeed.setter
    def max_downspeed(self, v):
        # TODO(felipe): adjust automatically based on bandwidth consuption on multiple backends
        for o in self.backends:
            o.max_downspeed = v

    @property
    def max_active_downloads(self):
        return sum(o.max_active_downloads for o in self.backends)

    @max_active_downloads.setter
    def max_active_downloads(self, v):
        # TODO(felipe): adjust automatically based on download number of every backend
        for o in self.backends:
            o.max_active_downloads = v

    @property
    def max_connections(self):
        return sum(o.max_connections for o in self.backends)

    @max_connections.setter
    def max_connections(self, v):
        # TODO(felipe): adjust automatically based on download number of every backend
        for o in self.backends:
            o.max_connections = v

    @property
    def last_position(self):
        return self.downloads[-1].position if self.downloads else 0

    def refresh(self):
        for backend in self.backends:
            backend.refresh()

        self.downloads = []
        for backend in self.backends:
            for download in backend.downloads:
                self.downloads.append(download)
        self.downloads.sort(key=operator.attrgetter("position"))

        BackendBase.refresh(self)

    def count_downloads(self):
        return len(self.downloads)

    def has_backend(self, backend_name):
        return any(backend.name == backend_name for backend in self.backends)

    def __init__(self, config, app=None, version=None, manager=None):
        # MultiBackend is manager unless specified
        if manager is None:
            manager = self

        self._appname = app
        self._appversion = version

        self.old_state = {}
        self.backends = []
        BackendBase.__init__(self, config, app, version)

        # Wrap BackendBase public interface
        self_attrs = self.__dict__.keys()
        self_attrs.extend(self.__class__.__dict__)
        self_attrs.extend(utils.EventHandler.__dict__)
        for name in dir(BackendBase):
            if not name.startswith("_") and callable(getattr(BackendBase, name)) and not name in self_attrs:
                setattr(self, name, functools.partial(self.__proxy, name))

    def invalidate(self, v):
        BackendBase.invalidate(self, v)
        self.backends.remove(v)

    def get_download_position(self, download):
        return BackendBase.get_download_position(self, download)

    def set_download_position(self, download, v):
        return BackendBase.set_download_position(self, download, v)

    def __proxy(self, prop_name, *args, **kwargs):
        # Public interface wrapper
        tr = {i.name: getattr(i, prop_name)(*args, **kwargs)
              for i in self.backends}
        if any(not i is None for i in tr.values()):
            return tr
        return None

    def set_state(self, state):
        '''
        Set state (given by get_state method) to backends.
        If not backend is available for any state, will be stored.
        '''
        if state is None:
            return
        self.old_state = state.copy()
        for i in self.backends:
            if i.name in state:
                i.set_state(state[i.name])

    def _get_state_with(self, method):
        d = self.old_state.copy()
        for backend in self.backends:
            try:
                d[backend.name] = getattr(backend, method)()
            except BaseException as e:
                logger.exception(e)
        return d

    def get_state(self):
        return self._get_state_with("get_state")

    def get_backend(self, name):
        if isinstance(name, int):
            return self.backends[name]
        for i in self.backends:
            if i.name == name:
                return i
        raise KeyError, "There is no backend with name %s" % repr(name)

    def get_run_state(self):
        return self._get_state_with("get_run_state")

    def can_download(self, url):
        return any(backend.can_download(url) for backend in self.backends)

    def download(self, url, user_data=None):
        return any(backend.download(url, user_data) for backend in self.backends)

    def run(self):
        current_backends_classes = {backend.__class__ for backend in self.backends}
        new_backends = [
            backend(self.config, self._appname, self._appversion, self.manager)
            for backend in available_backends
            if not backend in current_backends_classes and backend.is_available()
            ]
        if new_backends:
            # Update backend list
            self.backends.extend(new_backends)
            self.backends.sort(key=operator.attrgetter("priority"))
            # Initialize new_backends
            for backend in new_backends:
                # Proxy events
                for name in ("download_new", "download_update",
                             "download_remove", "download_hide",
                             "download_unhide"):
                    backend.on(name, functools.partial(self.emit, name))
                # Setting known state
                try:
                    name = backend.name
                    if name in self.old_state:
                        backend.set_state(self.old_state[name])
                except BaseException as e:
                    logger.exception(e)
                # Backend intialization
                try:
                    backend.run()
                except BaseException as e:
                    # If backend cannot initialize, we disable it
                    logger.exception(e)
                    self.backends.remove(backend)
                    continue
                # Backend added 'backend_add' event emitted
                try:
                    self.emit("backend_add", backend)
                except BaseException as e:
                    logger.exception(e)

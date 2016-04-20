#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''

Extra system:
    Plugins or addons are called 'extras'.
    Extras come with it's own installer a the moment.

'''
import threading
import logging
import sys
import os
import os.path
import time
import zipfile
import collections
import functools
import shutil

import imp
import tempfile

import zipsign
import config
import utils
import extras.sandbox as sandbox

import wx # we need wx.CallAfter due threading usage

import my_env

logger = logging.getLogger(__name__)

class InternalExtra(utils.StaticClass):
    locations = ()

    @classmethod
    def subdirectory(cls):
        '''
        Get subdirectory inside extras dir where current available extra is
        located.

        Returns:
            Path as unicode or None if not in extras dir.
        '''
        if cls.check_extra():
            data = cls.available()
            sep = data["path"].find(os.sep, len(my_env.get_extra_dir() + os.sep))
            if sep != -1:
                return data["path"][:sep]
        return None

    @classmethod
    def available(cls):
        '''
        Get first available location

        Returns:
            Path as unicode or None if no location is available.
        '''
        for data in cls.locations:
            if os.path.exists(data["path"]):
                return data
        return None

    @classmethod
    def check(cls):
        '''
        Get if current extra is available or not.

        Returns:
            True if available on any location, False otherwise.
        '''
        return not cls.available() is None

    @classmethod
    def check_extra(cls):
        '''
        Get if current extra is available inside extras dir or not.

        Returns:
            True if available on any location inside extras directory, False
            otherwise.
        '''
        data = cls.available()
        return data and data["path"].startswith(my_env.get_extra_dir() + os.sep)

    @classmethod
    def initialize(cls, app):
        '''
        Initialize internal extra.

        Params:
            app: running application instance.
        '''
        pass

    @classmethod
    def deinitialize(cls, app):
        '''
        Deinitialize internal extra.

        Params:
            app: running application instance.
        '''
        pass

    @classmethod
    def uninstall(cls):
        '''
        Uninstall internal extra.
        May raise UninstallError exceptions.
        '''
        data = cls.available()
        if data:
            if "uninstall_error" in data: # ununinstallable
                v = {"appname": config.constants.APP_NAME}
                raise UninstallError, data["uninstall_error"] % v
            subdir = cls.subdirectory()
            if subdir is None:
                if cls.check_extra():
                    # should not happen: extras should have a subdir in extras
                    os.remove(data["path"])
                else:
                    logger.warn("Extra outside extra directory with no related 'uninstall_error'")
                    # should not happen: extras not in extras should have an uninstall_error
                    raise UninstallError, "Extra cannot be uninstalled."
            else:
                # most common case
                shutil.rmtree(subdir)

    @classmethod
    def checksum(cls):
        '''
        Get checksum for this internal extra related files.

        Returns:
            Checksum as integer.
        '''
        checksum = 1 # default adler32 value (same for empty string)
        if cls.check_extra():
            # Get all extra files
            root = cls.subdirectory()
            if root:
                # Subdir in extra: look for all files recursively
                paths = [ os.path.join(dirpath, name)
                          for dirpath, dirnames, filenames in os.walk(root)
                          for name in filenames
                          if not my_env.is_hidden(os.path.join(dirpath, name))]
                paths.sort(key=lambda x: x.lower())
            else:
                # No subdir, available path only
                data = cls.available()
                paths = [data["path"]] if data else [] # shoudn't be necessary

            # Calculate checksum of all files in folder
            for path in paths:
                try:
                    checksum = my_env.adler32_file_checksum(path, checksum)
                except BaseException as e:
                    logger.exception(e)
        return checksum


class ExecutableInternalExtra(InternalExtra):
    @classmethod
    def available(cls):
        '''
        Get first available executable location

        Returns:
            Path as unicode or None if no location is available.
        '''
        for data in cls.locations:
            if my_env.is_executable(data["path"]):
                return data
        return None


class InternalMPlayer(ExecutableInternalExtra):
    '''
    Internal extra for managing PLAY integrated player
    '''
    locations = (
        {"path": os.environ.get("MPLAYER_PATH", None),
         "uninstall_error":
            "Integrated player is using an application defined as an environment variable and"
            "because of it cannot be uninstalled as 'extra'."},
        {"path": os.path.join(my_env.get_extra_dir(), "player", "mplayer.exe")},
        {"path": os.path.join(config.APPDIR, "mplayer.exe"),
         "uninstall_error":
            "Integrated player was installed alongside %(appname)s and "
            "because of it cannot be uninstalled as 'extra'."},
        {"path": my_env.which("mplayer"),
         "uninstall_error":
            "Integrated player is using system applications and"
            "because of it cannot be uninstalled as 'extra'."},
        ) if not my_env.is_mac else ()

    @classmethod
    def initialize(cls, app):
        data = cls.available()
        if data:
            os.environ["MPLAYER_PATH"] = data["path"]

    @classmethod
    def deinitialize(cls, app):
        if "MPLAYER_PATH" in os.environ:
            del os.environ["MPLAYER_PATH"]


class InternalAmule(ExecutableInternalExtra):
    '''
    Internal extra for managing amule backend executables.
    '''
    locations = (
        {"path": os.environ.get("AMULE_DAEMON_PATH", None),
         "uninstall_error":
            "Ed2k integration is using an application defined as an environment variable and"
            "because of it cannot be uninstalled as 'extra'."},
        {"path": os.path.join(my_env.get_extra_dir(), "ed2k", "ed2k.exe")},
        {"path": os.path.join(config.APPDIR, "ed2kd.exe"),
         "uninstall_error":
            "Ed2k integration was installed alongside %(appname)s and "
            "because of it cannot be uninstalled as 'extra'."},
        {"path": my_env.which("amuled"),
         "uninstall_error":
            "Ed2k integration is using system applications and"
            "because of it cannot be uninstalled as 'extra'."},
        )

    @classmethod
    def available(cls):
        return None # Disabled ATM

    @classmethod
    def initialize(cls, app):
        data = cls.available()
        if data:
            os.environ["AMULE_DAEMON_PATH"] = data["path"]
            app.backend.run() # Look for new backends

    @classmethod
    def deinitialize(cls, app):
        if "AMULE_DAEMON_PATH":
            del os.environ["AMULE_DAEMON_PATH"]
        app.backend.invalidate() # TODO(felipe): implement


class SignedPlugin(object):
    '''
    Python's zipimporter cannot load zip files with comments, where we store
    zip signatures, so we need to implement our own path hook.
    '''
    def __init__(self, path):
        '''
        Create new hook

        Params:
            path: path of signed plugin file.
        '''
        self.path = path
        with zipfile.ZipFile(self.path) as zf:
            self.mb = {i for i in zf.namelist() if not i.endswith("/")} # only files
        self.cache = {}

    def modulepath(self, fullname):
        '''
        Get virtual module path

        Params:
            fullname: Full name of module (with all parents) as string.

        Returns:
            Virtual module path as basestring or None.
        '''
        if fullname in self.cache:
            return self.cache[fullname]
        path = fullname.replace(".", "/")
        for alt in (path, path+"/__init__"):
            for ext in (".py", ".pyc", ".pyo"):
                relpath = alt+ext
                if relpath in self.mb:
                    self.cache[fullname] = relpath
                    return relpath
        return None

    _types = {
        ".py": imp.PY_SOURCE,
        ".pyc": imp.PY_COMPILED,
        ".pyo": imp.PY_COMPILED,
        ".pyd": imp.C_EXTENSION,
        }
    _modes = {
        ".py": "r",
        ".pyc": "rb",
        ".pyo": "rb",
        ".pyd": "rb",
        }
    def load_module(self, fullname):
        '''
        Load module (if not loaded) and return it.

        Params:
            fullname: Full name of module (with all parents) as string.

        Returns:
            Module object.
        '''
        if fullname in sys.modules:
            return sys.modules[fullname]

        relpath = self.modulepath(fullname)
        fullpath = os.path.join(self.path, relpath)
        suffix = relpath[relpath.find("."):]
        info = (suffix, self._modes[suffix], self._types[suffix])

        with zipfile.ZipFile(self.path) as zf:
            with zf.open(relpath) as f:
                data = f.read()

        with tempfile.TemporaryFile() as tf:
            tf.write(data)
            tf.seek(0, os.SEEK_SET)
            fo = tf.file if hasattr(tf, "file") else tf
            module = imp.load_module(fullname, fo, fullpath, info)

        module.__loader__ = self
        return module

    def find_module(self, fullname, syspath=None):
        '''
        Find module

        Param:
            fullname: full module name with all parents
            syspath: optional, unused.

        Returns:
            SignedPlugin instance.
        '''
        if self.modulepath(fullname) is None:
            raise ImportError, "No module named %r" % fullname
        return self

    @classmethod
    def unload_module(self, fullname):
        '''

        '''
        if fullname in sys.modules:
            del sys.modules[fullname]

    @classmethod
    def import_hook(cls, path):
        '''
        Import hook function for sys.path_hooks

        Params:
            path: path of signed plugin file.

        Returns:
            SignedPlugin instance.
        '''
        if zipfile.is_zipfile(path):
            return cls(path)
        raise ImportError, "Not signed plugin"

    @classmethod
    def install(cls):
        '''
        Insert this hook in sys.path_hooks, allowing importing signed plugins.

        Note: Signed plugins are zipfiles with comments, which are not allowed
        by python builtin zipextimport.
        '''
        if not cls.import_hook in sys.path_hooks:
            sys.path_hooks.append(cls.import_hook)

    @classmethod
    def uninstall(cls):
        '''
        Remove this hook from sys.path_hooks.
        '''
        if cls.import_hook in sys.path_hooks:
            sys.path_hooks.remove(cls.import_hook)
        tr = [k for k, v in sys.path_importer_cache.iteritems() if v is cls.import_hook]
        for name in tr:
            del sys.path_importer_cache[name]

class GetURLException(Exception):
    pass

class InvalidGetURL(GetURLException):
    pass

class GetURLFailed(GetURLException):
    pass

class UninstallError(Exception):
    pass

class ExtraInstaller(threading.Thread):
    '''
    Download types:
        - plugin (zip) files
            Placed directly in configdir/modules
        - installer (exe on windows, scripts elsewhere)
            Installers are moved to tmp and then installed
            (should place plugin in configdir/modules)
    '''

    _fake_progress = 0
    _fake_progress_nt = 0
    @property
    def progress(self):
        '''
        Download progress (with some tweaks)
        '''
        if self.geturl:
            margin = 0.01 if self.installer else 0
            if self.is_alive():
                if self.geturl.size:
                    # Size is known, we can calc percent
                    p = self.geturl.tell() / float(self.geturl.size + margin)
                    return p - p*margin
                elif self.geturl.ready:
                    # Headers received with no size, fake progress
                    t = time.time()
                    if self._fake_progress_nt < t: # fake progress control
                        self._fake_progress_nt = t + 1
                        self._fake_progress += float(1 - margin - self._fake_progress)/4
                    return self._fake_progress
                # No response yet
                return 0
            elif self.geturl.finished:
                # Finished
                return 1 - margin
        # No request yet
        return 0

    @property
    def installing(self):
        '''
        Get if install process is in progress.
        '''
        return self.installer and self.geturl.finished and self.is_alive()

    _instances = []
    def __init__(self, manager, url, extra_name, installer, params):
        '''
        Thread for downloading and installing plugins

        Params:
            manager
            modulepath: extra directory
            url: extra URL
            extra_name: extra name
            installer: True if URL refers to an executable (installer)
        '''
        threading.Thread.__init__(self)

        self.manager = manager
        self.name = extra_name
        self.modulepath = self.manager._modulepath
        self.installer = installer
        self.params = params
        self.url = url
        self.progress_updater = threading.Thread(target=self._progress_updater_loop)

        if installer:
            self.path = my_env.tempfilepath("extra", my_env.appname_to_bin(extra_name))
        else:
            self.path = os.path.join(self.modulepath, extra_name)

        try:
            self.geturl = utils.GetURL(url)
        except:
            self.geturl = None

        self._instances.append(self)

    def clean(self):
        '''
        Removing downloaded files
        '''
        if self in self._instances:
            self._instances.remove(self)
        if self.installer and os.path.exists(self.path):
            os.remove(self.path)


    def _progress_updater_callback(self):
        '''
        This method is necessary for ensure manager's _download_progress is not
        called after finish this thread.
        '''
        if self.is_alive():
            self.manager._download_progress(self)

    def _progress_updater_loop(self):
        '''
        Progress updater thread body
        '''
        last_state = 0
        while not (self.geturl.failed or self.geturl.finished):
            new_state = self.progress
            if last_state != new_state:
                wx.CallAfter(self._progress_updater_callback)
            time.sleep(0.1)
        wx.CallAfter(self._progress_updater_callback)

    def run(self):
        '''
        ExtraInstaller thread body
        '''
        try:
            if self.geturl is None:
                raise InvalidGetURL("GetURL failed to initialize for %r" % self.url)
            if not os.path.exists(self.modulepath):
                os.makedirs(self.modulepath)
            self.progress_updater.start()
            self.geturl.save(self.path)
            if self.geturl.failed:
                raise GetURLFailed("GetURL failed to save %r to %r" % (self.url, self.path))
            # If installer, we need to call it and wait until completion
            if self.installer:
                cmd = [self.path]
                cmd.extend(my_env.resolve_app_params(self.params))
                my_env.call(cmd)
            try:
                wx.CallAfter(self.manager._download_finished, self)
            except BaseException as e:
                logger.exception(e)
        except GetURLException as e:
            logger.debug(e)
            wx.CallAfter(self.manager._download_failed, self)
        except BaseException as e:
            logger.exception(e)
            wx.CallAfter(self.manager._download_failed, self)
        finally:
            self.clean()

    def abort(self):
        self.geturl.close()


class AppProxy(object):
    '''
    Proxy to give to sandboxed plugins
    '''
    def __init__(self, app):
        self._app = app

    _whitelist = set()
    _blacklist = set()
    _blacklist_prefixes = {"_", "handle_", "on_"}
    def __getattr__(self, p):
        if not p in self._whitelist and any(p.startswith(i) for i in self._blacklist_prefixes) or p in self._blacklist:
            raise "%r object has no attribute %r" % (self._app.__class__, p)
        return getattr(self._app, p)


class InternalModuleError(Exception):
    '''
    Exception to be used by internal modules initialize and check functions
    '''
    pass


class ExtraManager(utils.EventHandler):
    '''
    ExtraManager

    Module types:
        internal - integrated on program itself
        plugin   - sandboxed plugin
        signed.plugin - unsandboxed plugin (signed by developer)

    Module extra states:
       -4 - not updateable (not used here, only useful for app compatibility)
       -3 - not compatible (not stored, only returned by state method with
                            internal extras, also useful for app compatibility)
       -2 - error (not stored, only sent with 'state' event on fails)
       -1 - outdated (not stored, only returned by state method if checksum
                      rovided)
        0 - not available (stored only for internal modules)
        1 - downloading (not stored, but returned by state methods and events)
        2 - available
        3 - initialized

    Events emitted:
        progress
            name
            progress
        state
            name
            state
    '''

    _modulepath = my_env.get_extra_dir()
    _namesep = ".-" # plugin can be versioned

    _internal_modules = {
        # name: check, initializer
        "player.internal": InternalMPlayer,
        "amule.internal": InternalAmule,
        }

    def __init__(self, app):
        self.app = app
        self._downloads = {}
        self._extra_state = collections.defaultdict(int)
        self._sandboxed_extras = {}
        self._checksums = {}
        self.refresh()

    def state(self, extra_name, checksum=0, minversion=""):
        '''
        Get state of given extra name

        Params:
            extra_name: extra name as used by this object

        Returns:
            An integer representing state.
        '''
        if extra_name in self._downloads:
            return 1 + self._downloads[extra_name].progress
        if extra_name.endswith(".internal") and not extra_name in self._extra_state:
            return -3
        r = self._extra_state[extra_name]
        if r > 1 and checksum and self._checksums.get(extra_name, 0):
            # Server and client must provide checksums for checksum validation
            try:
                # Valid checksums are int
                if self._checksums[extra_name] != int(checksum):
                    return -1
            except ValueError:
                return -1
        return r

    def uninstallable(self, extra_name):
        '''
        Get if given extra_name could be uninstalled.

        Params:
            extra_name: extra name as used by this object

        Returns:
            True if uninstallable and False otherwise.
        '''
        if extra_name in self._internal_modules:
            if 1 <= self.state(extra_name) < 2:
                return True
            internal = self._internal_modules[extra_name]
            # If check is false: not installed -> uninstallable
            # If check and check_extra: installed and extra -> uninstallable
            # If check but check_extra is false: installed but not extra -> ununinstallable
            return not internal.check() or internal.check_extra()
        return True

    def states(self):
        '''
        Return all about known states

        Returns:
            Dictionary with extra names and its state.
        '''
        d = {k: v for k, v in self._extra_state.iteritems() if v > 0}
        d.update((k, 1) for k in self._downloads)
        return d

    def uninstall(self, extra_name):
        '''

        '''
        # Extra is being downloaded
        if extra_name in self._downloads:
            download = self._downloads[extra_name]
            if download.installing:
                raise UninstallError, "Extra is being installed"
            elif download.progress < 1:
                self._downloads[extra_name].abort()
                return
            # Shouldn't happen
            raise UninstallError, \
                "'%s' is being processed, try again later" % extra_name

        # Internal extra case
        if extra_name in self._internal_modules:
            internal = self._internal_modules[extra_name]
            if self._extra_state[extra_name] < 2:
                raise UninstallError, \
                    "'%s' is not available" % extra_name
            self._deinitialize_internal(extra_name)
            internal.uninstall()
        elif extra_name in self._extra_state:
            # Extra is regular
            for path in self.find_modules(safe=False):
                name = self.extra_name(path)
                if name == extra_name:
                    if self._extra_state[extra_name] < 2:
                        raise UninstallError, \
                            "'%s' is not available" % extra_name
                    self._deinitialize_module(name)
                    try:
                        os.remove(path)
                    except:
                        raise UninstallError, (
                            "Error removing '%s'.\n\n"
                            "You can try removing file manually and restarting the application.\n"
                            "File is located at: %s"
                            ) % (extra_name, path)
                    break
            else:
                # extra_name not found
                raise UninstallError, (
                    "Error removing '%s'.\n\n"
                    "Extra not found in filesystem."
                    ) % extra_name
        else:
            # We have no knownledge about this extra
            logger.warn("Attempted to uninstall unknown extra '%s'" % extra_name)
            return

        del self._extra_state[extra_name]
        self.emit("state", extra_name, 0)

        self.refresh()

    def progress(self):
        '''
        Get progress of downloading modules
        '''
        return {
            name: installer.progress
            for name, installer in self._downloads.iteritems()
            }

    def refresh(self):
        '''
        Update internal module state detecting whose modules are available
        for importing.
        '''
        for name, internal in self._internal_modules.iteritems():
            if name in self._downloads:
                # Extra is being downloaded, we cannot refresh
                continue
            firstime = not name in self._extra_state
            self._checksums[name] = internal.checksum()
            if self._extra_state[name] < 2:
                oldvalue = self._extra_state[name]
                newvalue = 2 if internal.check() else 0
                self._extra_state[name] = newvalue
                if firstime or oldvalue != newvalue:
                    self.emit("state", name, newvalue)

        for path in self.find_modules():
            if name in self._downloads:
                # Extra is being downloaded, we cannot refresh
                continue
            name = self.extra_name(path)
            self._checksums[name] = my_env.adler32_file_checksum(path)
            if self._extra_state[name] < 2:
                self._extra_state[name] = 2
                self.emit("state", name, 2)

    def _module_path(self, extra_name):
        '''
        Return module path for given extra name
        '''
        for path in self.find_module(safe=False):
            name = self.extra_name(path)
            if name == extra_name:
                return path

    def _initialize_module(self, path=None):
        '''
        Initialize module for given path
        '''
        extra_name = self.extra_name(path)
        if self._extra_state[extra_name] != 2:
            # State must be 2 (available)
            return

        name = self._modulename(path)
        if path.endswith(".signed.plugin"):
            sys.path.insert(0, path)
            try:
                if not name in sys.modules:
                    __import__(name)
                if hasattr(sys.modules[name], "init_app"):
                    sys.modules[name].init_app(self.app)
                state = 3
            except BaseException as e:
                logger.exception(e)
                state = 0
            sys.path.remove(path)
        else:
            try:
                modglobals = sandbox.Sandbox.load(name, path, logger=logger, reraise=True)
                if "init_app" in modglobals:
                    modglobals["init_app"](AppProxy(self.app))
                state = 2
            except BaseException as e:
                logger.warn(e)
                state = 0
        self._extra_state[extra_name] = state
        self.emit("state", extra_name, state)

    def _deinitialize_module(self, path=None):
        '''
        Deinitialize module for given path
        '''
        extra_name = self.extra_name(path)
        if self._extra_state[extra_name] != 3:
            # State must be 3 (initialized)
            return

        name = self._modulename(path)
        state = None
        if path.endswith(".signed.plugin"):
            if name in sys.modules:
                try:
                    module = sys.modules[name]
                    if hasattr(module, "deinit_app"):
                        module.deinit_app(self.app)
                except BaseException as e:
                    logger.exception(e)
                SignedPlugin.unload_module(name)
                state = 2
        else:
            try:
                if name in self._sandboxed_extras:
                    if "deinit_app" in self._sandboxed_extras[name]:
                        self._sandboxed_extras[name]["deinit_app"](self.app)
                    del self._sandboxed_extras[name]
                    state = 2
            except BaseException as e:
                logger.warn(e)
                state = 2
        if not state is None:
            self._extra_state[extra_name] = state
            self.emit("state", extra_name, state)

    def _initialize_internal(self, name):
        '''
        Initialize internal with given name
        '''
        internal = self._internal_modules[name]
        if self._extra_state[name] == 2:
            # State must be 2 (available) and initialization must be implemented
            try:
                internal.initialize(self.app)
                self._extra_state[name] = 3
                self.emit("state", name, 3)
            except InternalModuleError as e:
                logger.debug(e)
            except BaseException as e:
                logger.exception(e)

    def _deinitialize_internal(self, name):
        '''
        Deinitialize internal with given name
        '''
        internal = self._internal_modules[name]
        if self._extra_state[name] == 3:
            # State must be 3 (initialized) and deinitialization must be implemented
            try:
                internal.deinitialize(self.app)
                self._extra_state[name] = 2
                self.emit("state", name, 2)
            except InternalModuleError as e:
                logger.debug(e)
            except BaseException as e:
                logger.exception(e)

    @classmethod
    def _modulename(self, path):
        '''
        Gets module import name from extra module path

        Params:
            path: module path as should be added to sys.path

        Returns:
            Module name suitable for import
        '''
        filename = os.path.basename(path)
        pos = min(filename.index(i) if i in filename else sys.maxint for i in self._namesep)
        return filename[:pos]

    @classmethod
    def extra_name(cls, path):
        '''
        Gets extra name from given extra module path.

        Params:
            path: module path as should be added to sys.path

        Returns:
            Extra name as used internal and externally by this object
        '''
        if path.endswith(".signed.plugin"):
            return cls._modulename(path) + ".signed.plugin"
        if path.endswith(".plugin"):
            return cls._modulename(path) + ".plugin"

    @classmethod
    def verify_module(cls, path, verify=True):
        '''
        Test if given path is a valid extra module path

        Params:
            path: extra module path
            verify: optional. If True, performs signature and zipfile
                    verification, defaults to True.

        Returns:
            True if valid, False otherwise.
        '''
        if os.path.isfile(path) and zipfile.is_zipfile(path):
            # Test signature if signed
            if verify and path.endswith(".signed.plugin") and not zipsign.verify(path, config.constants.EXTRA_PUBKEY):
                return False
            # Test if zipfile
            if path.endswith(".plugin"):
                if verify:
                    with zipfile.ZipFile(path) as f:
                        return f.testzip() is None
                return True
        return False

    def extra_checksum(self, extra_name):
        '''
        Returns checksum for given module if is available

        Params:
            extra_name: name of extra

        Returns:
            Checksum value as int or 0 if not checksum available.
        '''
        return self._checksums.get(extra_name, 0)

    def find_modules(self, safe=True):
        '''
        Look for modules in plugin module path.

        Params:
            safe: optional. If True perfoms signature verification on signed
                  plugins, and test all plugin integrity. Defaults to True.

        Yields:
            found filenames
        '''
        if os.path.isdir(self._modulepath):
            for path in os.listdir(self._modulepath):
                path = os.path.join(self._modulepath, path)
                if self.verify_module(path, safe):
                    yield path

    def initialize_modules(self):
        '''
        Initializes all extra modules, importing them and calling its init_app
        function.
        '''
        for name in self._internal_modules:
            self._initialize_internal(name)

        SignedPlugin.install()
        for path in self.find_modules():
            # We iterate over files, not over modules, because we do not keep
            # track of module paths.
            self._initialize_module(path)
        SignedPlugin.uninstall()

    def deinitialize_modules(self):
        '''
        Call all imported extra modules' deinit function.
        '''
        for name in self._internal_modules:
            self._deinitialize_internal(name)

        for path in self.find_modules(safe=False):
            self._deinitialize_module(path)

    def download(self, extra_name, url, executable=False, params=()):
        '''
        Download extra_name from url

        Params:
            extra_name:  Extra name (will be used for path and state)
            url:         URL will be used to get extra file
            executable:  True if downloads is an installer (executable)
        '''
        if self._extra_state[extra_name] > 0 or extra_name in self._downloads:
            self.uninstall(extra_name)
        self.emit("state", extra_name, 1)
        installer = ExtraInstaller(self, url, extra_name, executable, params)
        self._downloads[extra_name] = installer
        installer.start()

    def _download_progress(self, installer):
        '''
        Called in interval if progress changed
        '''
        extra_name = installer.name
        self.emit("progress", extra_name, installer.progress)

    def _download_finished(self, installer):
        '''
        Called once a new extra_name is download is finished

        Params:
            installer: ExtraInstaller instance
        '''
        extra_name = installer.name
        del self._downloads[extra_name]
        del self._extra_state[extra_name]
        if not installer.installer and not self.verify_module(installer.path):
            # Cannot be verified, that means download failed
            self.emit("state", extra_name, -2)
        self.refresh()
        self.initialize_modules()

    def _download_failed(self, installer):
        '''
        Called when installer for extra_name failed

        Params:
            installer: ExtraInstaller instance
        '''
        extra_name = installer.name
        del self._downloads[extra_name]
        del self._extra_state[extra_name]
        self.emit("state", extra_name, -2)
        self.refresh()


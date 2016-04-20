# -*- coding: utf-8 -*-

"""
This is where we centralize all references to the platform where we are
running. It also knows if we are running in an exe (sys.frozen == True).
"""

import platform
import sys

os_system = platform.system().lower()
is_windows = (os_system == "windows")
is_linux = (os_system == "linux")
is_mac = (os_system == "darwin")

is_windows_xp = is_windows and (platform.win32_ver()[0].lower() == "xp")

is_frozen = getattr(sys, "frozen", False)
is_archive = getattr(sys, "archive", False)

import config
import locale
import logging
import os
import os.path
import tempfile

if is_windows:
    import win32
else:
    import errno
    import signal
    import subprocess

    if is_mac:
        import mac
    elif is_linux:
        import linux

    try:
        import glib as GLib # GTK2 GLib
    except ImportError:
        try:
            from gi.repository import GLib # GTK3 GLib
        except ImportError:
            raise OSError, "GLib not found."
    try:
        import gio as Gio # GTK2 gio
    except ImportError as e:
        try:
            from gi.repository import Gio # GTK3 Gio
        except ImportError as e:
            raise OSError, "Gio not found. " + info

# module global state
class state:
    appname = None
    appguid = None

### INITIALIZATION
def init(appname, appguid):
    state.appname = appname
    state.appguid = appguid

    if is_windows:
        win32.init(is_frozen)
    elif is_mac:
        mac.init(is_frozen)
    elif is_linux:
        linux.init(appname, is_frozen)


def init_browser():
    if is_windows:
        win32.force_ie_edge(state.appname)

### PROCESSES

def fix_argv_param(param):
    '''
    Look for filepaths in command line param and make them absolute

    Params:
        param: command line parameter as string

    Returns:
        Command line parameter as string with path absolutized.
    '''
    if not param or param[0] == "-":
        return param
    if os.path.isabs(param):
        return param
    if os.path.exists(param):
        return os.path.abspath(param)
    return param

def get_argv():
    '''
    Get argv as unicode list.
    Python sys.argv is broken in some platforms due encoding problems, this
    function takes care of specific problems.

    Returns:
        List of unicode strings.
    '''
    if is_windows:
        return [fix_argv_param(param) for param in win32.get_argv()]
    else:
        encoding = locale.getpreferredencoding()
        try:
            return [fix_argv_param(i.decode(encoding)) for i in sys.argv]
        except LookupError:
            return [fix_argv_param(i) for i in sys.argv]


def resolve_app_params(params):
    "Return list of parameters with some of them possibly replaced"
    replacements = {"/APPDIR":   '/DIR="%s"' % config.APPDIR,
                    "/EXTRADIR": '/DIR="%s"' % get_extra_dir()}
    return [replacements.get(p, p) for p in params]


def get_running(pid):
    '''
    Return True if pid is running, false otherwise

    Params:
        pid: integer representing process pid

    Returns:
        True if process is alive, False otherwise.
    '''
    if is_windows:
        return win32.get_running(pid)
    else:
        try:
            os.kill(pid, 0)
        except OSError as err:
            if err.errno != errno.ESRCH: # this should be the error
                logging.exception(err)
            return False
        return True


def get_running_pidfile(path):
    '''
    Windows needs a maximum creation time due to its pid recycle behavior.

    Params:
        path: filesystem path of pidfile, its content is used as pid and its
              creation or modification time as maximum process creation time.
              This is necessary on windows because windows recycles pids very
              fast.

    Returns:
        Returns True if pidfile refers to an alive process, False otherwise.
    '''
    if not os.path.isfile(path):
        logging.debug("No pidfile %r" % path)
        return False
    try:
        with open(path, "r") as f:
            pid = int(f.read().strip())
    except BaseException as e:
        logging.debug("No pidfile %r" % path)
        return False
    if is_windows:
        ctime, atime, mtime = get_filetime(path)
        maxtime = max(ctime, mtime)
        return win32.get_running(pid, max_ctime=maxtime)
    else:
        return get_running(pid)

def kill_process(pid):
    '''
    Kill process by kid.
    '''
    if pid == os.getpid():
        logging.warn("Attemping to kill own process. Operation ignored.")
    elif is_windows:
        win32.kill(pid)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except BaseException as err:
            logging.exception(err)

def kill_process_pidfile(path):
    '''
    If path refers to a pidfile of an alive process, kill it.

    Params:
        path
    '''
    if get_running_pidfile(path):
        with open(path, "r") as f:
            pid = int(f.read().strip())
        kill_process(pid)

def set_signal_handler(handler):
    if is_windows:
        win32.set_signal_handler(handler)
    else:
        for sig in (signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, handler)

def open_folder(path):
    if is_windows:
        os.startfile(os.path.normpath(path), "open")
    elif is_linux:
        subprocess.call(["xdg-open", path])
    elif is_mac:
        subprocess.call(["open", path])

def open_file(path):
    if is_windows:
        if win32.file_association(path):
            os.startfile(os.path.normpath(path), "open")
            return True
    elif is_linux:
        return subprocess.call(["xdg-open", path]) == 0
    elif is_mac:
        return subprocess.call(["open", path]) == 0
    return False

def open_url(url):
    if is_windows:
        os.startfile(url, "open")
    elif is_linux:
        subprocess.call(["xdg-open", url])
    elif is_mac:
        subprocess.call(["open", url])


def call(cmd, shell=False, shellexec=False, verb="open", show=True, unicode_env=True):
    "Calls command, waits until it is finished and return True if ok"
    # cmd is a list, [executable, param1, param2, ...]
    if is_windows:
        pid = win32.call(cmd, shell, shellexec, verb, show, unicode_env)
        if pid == 0:
            return False  # problems!
        else:
            win32.wait_pid(pid)
            return True  # all fine
    else:
        code = subprocess.call(cmd, shell=shell)
        # and ignore things like shellexec, etc
        return (code == 0)  # if the return code is 0, all went fine


def appname_to_bin(name, suffix=""):
    '''
    Create a normalized command or executable (on windows) name based on
    given name.

    Params:
        name: basestring, application name
        suffix: basestring, something to add and end of name.

    Returns:
        Filename in ascii (suitable for any filesystem) as string
    '''
    pname = name.lower().split()
    if suffix:
        pname.append(suffix.lower())
    if is_windows:
        return "_".join(pname).encode("ascii", "ignore") + ".exe"
    else:
        return "-".join(pname).encode("ascii", "ignore") + ".bin"

### FILESYSTEM

def get_filetime(path):
    '''
    Gets ctime, atime and mtime of file as tuple

    Args:
        path: filesystem path to file

    Returns:
        Tuple as (ctime, atime, mtime)
    '''
    if is_windows:
        return win32.get_file_time(path)
    stat = os.stat(path)
    return (stat.st_ctime, stat.st_atime, stat.st_mtime)

def is_executable(path):
    '''
    Get if given path is an executable file

    Params:
        path: basestring

    Returns:
        True if given path is executable, False otherwise.
    '''
    return path and os.path.exists(path) and os.access(path, os.X_OK)

def is_hidden(path):
    '''
    Get if given path is an hidden file at os level

    Params:
        path: basestring

    Returns:
        True if given path is a hidden file, False otherwise.
    '''
    if is_windows and win32.file_hidden(path):
        return True
    return path[0] == "."

def get_listdir(path):
    "Like os.listdir but works well with unicode paths on NT"
    if is_windows:
        return win32.listdir(path)
    return os.listdir(path)

def get_blocksize(path):
    '''
    Writing one block at once on disk is the optimal approach for file
    downloads.

    Args:
        path: basestring, path of file whose filesystem will we take care of.

    Returns:
        Int or Long, block size in bytes.
    '''
    if is_windows:
        return win32.blocksize(path)
    return os.statvfs(path).f_bsize

def get_free_space(path):
    '''
    Get free space on filesystem corresponding to given path.

    Params:
        path: path on filesystem will be checked for free space

    Returns:
        Free space in bytes on given device.
    '''
    if os.path.isfile(path):
        path = os.path.dirname(os.path.abspath(path))
    if is_windows:
        return win32.get_free_space(path)
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize

def adler32_file_checksum(path, value=1):
    '''
    Compute an adler32 file checksum in an memory and CPU efficient way.

    Returns:
        Integer adler32 checksum
    '''
    chunksize = get_blocksize(path)
    with open(path, "rb") as f:
        d = f.read(chunksize)
        while d:
            value = zlib.adler32(d, value)
            d = f.read(chunksize)
    return value

_allowed_chars = frozenset("{}-_.abcdefghijklmnopkrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
def safe_filename(filename):
    return "".join(i for i in filename if i in _allowed_chars)

def tempfilepath(*args):
    assert len(args)>0, "filename must be given"
    return os.path.join(tempdirpath(*args[:-1]), safe_filename(args[-1]))

def tempdirpath(*args):
    path = os.path.join(get_temp_dir(), *map(safe_filename, args))
    if not os.path.isdir(path):
        if os.path.isfile(path): # Happened once: then test alternative paths
            c = 1
            opath = path
            while os.path.isfile(path):
                c += 1
                path = u"%s_%d" % (opath, c)
        os.makedirs(path)
    return path

def get_temp_dir():
    '''
    Returns app temporal directory path in user temp folder

    Returns:
        Returns path as folder.
    '''
    return os.path.join(tempfile.gettempdir(), state.appguid)

def choose_filename(path):
    '''
    Try to create a writeable file in path, retry with new few names,
    and returns a valid one. If cannot, raises IOError.
    '''
    # Name choosing, (we cannot write in open files)
    path, name = os.path.split(path)
    ext = ""
    nname = name
    for i in xrange(2, 11): # 9 retries
        try:
            dest = os.path.join(path, nname)
            with open(dest, "wb"): pass # Write empty file
            break
        except:
            # Split name and extension if not done yet
            if "." in name and not ext:
                name, ext = name.rsplit(".", 1)
                secondary_ext = name.rfind(".")
                # take a second extension if less than 4 characters
                if secondary_ext + 5 > len(name):
                    ext = name[secondary_ext+1:] + "." + ext
                    name = name[:secondary_ext]
            nname = "%s - %d%s%s" % (name, i, "." if ext else "", ext)
    else:
        raise IOError, "Cannot write to file."
    return dest

def samefile(path1, path2):
    if is_windows:
        return win32.samefile(path1, path2)
    else:
        return os.path.samefile(path1, path2)

### USER

def which(name):
    '''
    POSIX 'which' reimplementation: Get absolute path of command in PATH.

    Params:
        name: basestring, name of command

    Returns:
        Absolute path of command in PATH or None if not found.
    '''
    for path in os.environ.get("PATH", "").split(os.pathsep):
        path = os.path.abspath(os.path.join(path.strip("\""), name)) # remove quotes and join path
        if is_executable(path):
            return path
    return None

def get_user_home():
    '''
    Returns user home directory

    Returns:
        User home directory as string.
    '''
    if is_windows:
        return win32.get_user_home()
    return os.environ["HOME"]


def get_config_dir():
    '''
    Returns app config directory path in user config folder

    Returns:
        Returns path as folder.
    '''
    if is_windows:
        appdata = win32.get_appdata()
        return os.path.join(appdata, state.appname)
    elif is_linux:
        return os.path.join(get_user_home(), ".config", state.appname)
    else:
        return os.path.join(get_user_home(), ".config", state.appname)
        # really?


def get_com_dir():
    '''
    Return app subdir on app configuration dir suitable for COM wrapper
    generation.

    Returns:
        Path as string or None if environ is not NT
    '''
    if is_windows:
        return os.path.join(get_config_dir(), "com")
    return None


def get_extra_dir():
    '''
    Return app subdir on app configuration dir suitable for plugin storing.

    Returns:
        Path as string
    '''
    return os.path.join(get_config_dir(), "extra")



def get_old_download_dir():
    if is_windows:
        directory = os.path.join(get_user_home(), "Downloads")
        if os.path.isdir(directory):
            return directory
        # Fallback directory: My documents\Downloads
        mydocs = win32.get_my_documents() # My Documents
        return os.path.join(mydocs, "Downloads")
    else:
        if GLib: # GLib should be dependency for POSIX systems
            return GLib.get_user_special_dir(GLib.USER_DIRECTORY_DOWNLOAD)
        return os.path.join(get_user_home(), "Downloads")


def get_download_dir():
    "Return the path to the user's default downloads directory"
    if is_windows:
        # WinVista Win7 and so on:
        # Win32 API does not provides IDs for its new
        # SHGetKnownFolderPath, but it seems the folder name is
        # locale unaware (at least in Win7).
        directory = os.path.join(get_user_home(), "Downloads")
        if os.path.isdir(directory):
            return directory
        # Fallback directory: My documents\Downloads
        mydocs = win32.get_my_documents() # My Documents
        return mydocs
    else:
        if GLib: # GLib should be dependency for POSIX systems
            ddir = GLib.get_user_special_dir(GLib.USER_DIRECTORY_DOWNLOAD)
            if ddir:
                return ddir
        return get_user_home()


### ENVIRONMENT

def get_default_for_torrent():
    '''
    Get if current app is default torrent app
    '''
    if is_windows:
        return win32.get_register(state.appname)
    elif is_linux:
        return linux.get_default_for_torrent()
    else:
        logging.warn("Not implemented")
    return False


def set_default_for_torrent():
    '''
    Set current app as default torrent app
    '''
    if is_windows:
         win32.register(state.appname)
    elif is_linux:
        linux.set_default_for_torrent()
    else:
        logging.warn("Not implemented")


def get_run_startup():
    '''
    Get if current app is set to run at startup
    '''
    if is_windows:
        return win32.get_startup(state.appname)
    elif is_linux:
        return linux.get_run_startup()
    elif is_mac:
        return mac.get_run_startup()
    else:
        logging.warn("Not implemented")
    return False


def set_run_startup(value):
    '''
    Set this app to lauch at startup
    '''
    if is_windows:
        if value:
            win32.startup(state.appname)
        else:
            win32.startup_disable(state.appname)
    elif is_linux:
        linux.set_run_startup(value)
    elif is_mac:
        mac.set_run_startup(state.appname, value)
    else:
        logging.warn("Not implemented")


def error_message(title, text):
    '''
    Crossplatform error message

    Params:
        title: window title
        text: window message
    '''
    if is_windows:
        win32.error_message(title, text)
    elif is_linux:
        title = u'%s' % title.replace('"','\\"')
        text = u'%s' % text.replace('"','\\"')
        def call(x):
            return subprocess.call(x, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        # Main alternatives
        if call(["which", "zenity"]) == 0:
            call(["zenity", "--error", u"--title=%s" % title, u"--text=%s" % text])
        elif call(["which", "kdialog"]) == 0:
            call(["kdialog", "--title", title, "--error", text])
        # Legacy
        elif call(["which", "gdialog"]) == 0:
            call(["gdialog", "--title", title, "--msgbox", text, "0", "0"])
        elif call(["which", "Xdialog"]) == 0:
            call(["Xdialog", "--title", title, "--msgbox", text])
        else:
            print >> sys.stderr, u"%s\n%s" % (title, text)
    else:
        print >> sys.stderr, u"%s\n%s" % (title, text)


def get_max_half_open_connections():
    if is_windows:
        return win32.get_max_half_open_connections()
    else:
        return None


def set_idleness_mode(sleep=True, screensaver=True, reason="No reason."):
    '''
    Config system to prevent from suspending and/or launching the screensaver.
    Set argument to False to disable a feature.

    For further information, read https://en.wikipedia.org/wiki/In_Praise_of_Idleness_and_Other_Essays.
    '''
    if is_windows:
        win32.set_sleep_mode(sleep)
        win32.set_screensaver_mode(screensaver)
    elif is_linux:
        linux.set_sleep_mode(sleep, reason)
        linux.set_screensaver_mode(screensaver, reason)
    elif is_mac:
        if not screensaver:
            raise NotImplemented("Screensaver disable is not available yet in this OS.")
        if sleep:
            mac.unprevent_sleep()
        else:
            mac.prevent_sleep(reason)


def idleness_tick():
    if is_windows:
        win32.idleness_tick()
    elif is_linux:
        linux.idleness_tick()
    else:
        pass


### DESKTOP COMPOSITION

def get_compositing():
    '''
    Get if system allows window composition (currently in NT systems only).

    Returns:
        True if system allows window compositing and False otherwise.
    '''
    if is_windows:
        return win32.composite()
    return False

def composite_frame(frame, margins):
    if is_windows:
        win32.composite_frame(frame, margins)


import os

# py2exe needs some DLLs for compilation
os.environ["PATH"] += os.pathsep + os.path.join("..", "libs")

from distutils.core import setup
from py2exe.build_exe import py2exe

exclude_encodings = {
    "mac_arabic",
    "mac_centeuro",
    "mac_croatian",
    "mac_cyrillic",
    "mac_farsi",
    "mac_greek",
    "mac_iceland",
    "mac_latin2",
    "mac_roman",
    "mac_romanian",
    "mac_turkish",
    "palmos",
    "_codecs_jp",
        "shift_jis_2004",
        "euc_jp",
        "cp932",
        "euc_jisx0213",
        "shift_jisx0213",
        "euc_jis_2004",
        "shift_jis",
    "_codecs_tw",
        "big5",
        "cp950",
    "_codecs_kr",
        "johab",
        "cp949",
        "euc_kr",
    }

MAIN_PATH = "front.py" # used to be "__main__.py"
PY2EXE_DIST_DIR = "."
SHOW_MODULE_XREF = False

module_excludes = ["encodings.%s" % i for i in exclude_encodings]

# FAKE EXCLUDES WITH EMPTY MODULES
import py2exe.mf
pre = py2exe.mf.ModuleFinder
class ModuleFinder(pre):
    def ensure_fromlist(self, m, fromlist, recursive=0):
        self.msg(4, "ensure_fromlist", m, fromlist, recursive)
        for sub in fromlist:
            if sub == "*":
                if not recursive:
                    all = self.find_all_submodules(m)
                    if all:
                        self.ensure_fromlist(m, all, 1)
            elif not hasattr(m, sub):
                subname = "%s.%s" % (m.__name__, sub)
                submod = self.import_module(sub, subname, m)
                if not (submod or subname in self.excludes):
                    raise ImportError, "No module named " + subname
py2exe.mf.ModuleFinder = ModuleFinder


manifest_winapi = "".join(line for line in open("../templates/manifest.winapi")
                          if not line.strip().startswith("#")) % {
                                  "appname": "Zipsign",
                                  "version": "0.1.0.0"}

class ZipSign:
    script = MAIN_PATH
    icon_resources = []
    bitmap_resources = []
    other_resources = [(24, 1, manifest_winapi)]
    dest_base = "zipsign"
    version = "0.1"
    company_name = "Foofind Labs, S.L."
    copyright = "Foofind Labs, S.L. (c) 2013"
    name = "zipsign"

setup(
    name = "zipsign",
    version = "0.1",
    description = "zip sign tool",
    author = "Foofind Labs, S.L.",
    data_files = [], #data_files,
    options = {
        "py2exe": {
            "unbuffered": False,
            "compressed": True,
            "optimize": 2,
            "includes": [],
            "excludes": [
                "_gtkagg", "_tkagg", "bsddb", "curses", "email",
                "pywin.debugger", "pywin.debugger.dbgcon",
                "pywin.dialogs", "tcl", "Tkconstants", "Tkinter",
                "plistlib", # for Mac
                #"wx", # wx
                "pydoc", "difflib", "unittest", "inspect", "doctest", "pdb", # debug stuff
                "_ssl", # No https is used
                "multiprocessing",
                ] + module_excludes,
            "packages": [], # Removed wx (let py2exe resolve dependencies)
            "dll_excludes": [
                "libgdk-win32-2.0-0.dll", "libgobject-2.0-0.dll",
                "tcl84.dll", "tk84.dll",
                "w9xpopen.exe" # Win9x support
                ],
            "bundle_files": 1,
            "dist_dir": PY2EXE_DIST_DIR,
            "xref": SHOW_MODULE_XREF,
            "skip_archive": False,
            "ascii": False,
            }
        },
    zipfile = None,
    console = [ZipSign],
    windows = [],
    service = [],
    com_server = [],
    ctypes_com_server = [],
    )

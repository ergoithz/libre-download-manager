# -*- coding: utf-8 -*-
from collections import OrderedDict

APP_URL = "http://foofind.is/en/downloader"  # language included...
APP_GUID = "{D0FC6861-DD0F-49D3-A7A4-BED8F1EFD3ED}"
APP_NAME = "Foofind Download Manager"
APP_SHORT_NAME = "Foofind"
APP_AUTHOR = "Foofind Labs S.L. <hola@foofind.com>"
APP_COMPANY = "Foofind Labs, S.L."
APP_COPYRIGHT = "Copyright (c) 2012-2014 Foofind Labs, S.L."
APP_VERSION = "0.3-20140421-W32" # Change before any new release!

APP_UPDATE_MODE = 2 # 0: disabled, 1: simple (not used anymore!), 2: advanced

# Extra PUBLIC KEY
EXTRA_PUBKEY = '''
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAjS278yPeUuJTTVfd9Wogvj8z01NPC5X+L1nCh4RBlb+OD4JlbdXC
uD9VBSuV1w4+9dt+3GUGkEdv4FzqMFCw+/cn4mjTduw9ror+aHaT2jK28r1JNpgL
e6oPwYbYjBEhLzfOxhFQHiuB3LB7boBzKHiFP6cCjKWj+kZiKU/9LxolkF6f5mk+
+sLWItvmDCmxvouyfS1ARYr7SDZofFiMdJFMj5dB4Acvf/lrgLAfo4JTHC+vIUMb
8O1CEUQZqBrRc/FLUJMGvMH2EMH+GrgJXuFfaDuCECACVJtFxSLbMrXkMTmD1GSj
rtBxjMI5SxgdhMr+l+XPRjEcN8WsYRz7DwIDAQAB
-----END RSA PUBLIC KEY-----
'''

# Updater with server messages
URL_UPDATE_INFO_URL = "http://foofind.is/%(lang)s/downloader/update"

# Tab urls
TAB_FIND_URL = "http://appweb.foofind.is/%(lang)s"
TAB_FIND_SAFE_LOCATIONS = ("http://appweb.foofind.is", )
TAB_EXTRA_URL = ""
TAB_EXTRA_SAFE_LOCATIONS = ()

# Installer urls
URL_INSTALLER_SUCCESS = "%s/success?version=%%(version)s" % APP_URL
URL_INSTALLER_SETUP = "%s/setup.exe?version=%%(version)s" % APP_URL

# Languages
LANGUAGES = OrderedDict([
    ("en", (u"English", "LANGUAGE_ENGLISH")),
    ("es", (u"Español", "LANGUAGE_SPANISH")),
    ("fr", (u"Français", "LANGUAGE_FRENCH"))])
DEFAULT_LANG = "en"

# Map for internal categories and web categories
CATEGORY_WEB_CATEGORY = {
    "executable": "software",
    "plugin": "software",
    "backup": "software",
    "disk image": "unknown",
    "compressed": "unknown",
    "video": "video",
    "ebook": "document",
    "audio": "audio",
    "music": "audio",
    "3d image": "image",
    "raster image": "image",
    "camera raw": "image",
    "vector image": "image",
    "cad": "document",
    "database": "unknown",
    "spreadsheet": "document",
    "font": "software",
    "settings": "unknown",
    "game": "software",
    "gis": "unknown",
    "data": "unknown",
    "page layout": "unknown",
    "developer": "software",
    "web": "document",
    "text": "document",
    "encoded": "unknown",
    "system": "software",
    "misc": "unknown"
    }

# Icons for web categories
WEB_CATEGORY_ICONS = {
    "video": "ico.filetype-24-vid-off",
    "audio": "ico.filetype-24-mus-off",
    "image": "ico.filetype-24-img-off",
    "document": "ico.filetype-24-doc-off",
    "software": "ico.filetype-24-pc-off",
    "unknown": "ico.filetype-24-all-off",
    }

# Categories on play: category, play string, category css
_ = lambda x: x  # so xgettext gets the categories text
PLAY_CATEGORIES = (
    ("all", _("all"), "all"),
    ("recent", _("recent"), "recent"),
    ("video", _("video"), "video"),
    ("audio", _("music"), "music"),
    ("image", _("images"), "image"),
    ("document", _("docs"), "doc"),
    ("software", _("software"), "software"),
    ("unknown", None, None),
    )

# CSS class for each category on play
CATEGORY_TO_FILETYPE = {
    "all": "unknown",
    "video": "video",
    "audio": "audio",
    "image": "image",
    "document": "document",
    "software": "software",
    "unknown": "unknown",
    }

WEB_CATEGORY_PLACEHOLDERS = {
    "video": "bg.placeholder-video",
    "audio": "bg.placeholder-audio",
    "image": "bg.placeholder-image",
    "document": "bg.placeholder-doc",
    "software": "bg.placeholder-software",
    "unknown": "bg.placeholder-unknown",
    }

PLAYER_CATEGORIES = {"video"}
HIDDEN_CATEGORIES = {}
BAD_WEB_CATEGORIES = {"unknown"}

#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Libre Download Manager
Copyright © 2012-2014 Foofind Labs, S.L.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
'''

import logging
import atexit

logger = logging.getLogger(__name__)

class atexit_patch:
    _callbacks = []
    _stacks = []
    @classmethod
    def register(cls, func, *args, **kwargs):
        cls._callbacks.append((func, args, kwargs))

    @classmethod
    def run(cls):
        if cls._callbacks:
            cls._callbacks.reverse()
            for fnc, args, kwargs in cls._callbacks:
                try:
                    fnc(*args, **kwargs)
                except BaseException as e:
                    logger.exception(e)
            cls._callbacks[:] = ()

atexit.register(atexit_patch.run)
atexit.register = atexit_patch.register

import functools
import traceback
import sys
import os
import os.path
import errno
import urllib

import signal
import time
import threading
import platform
import subprocess

import my_env
import config
my_env.init(config.constants.APP_NAME,
            config.constants.APP_GUID.lower())


import utils
import backends
import collections
import server
import extras

import gettext
import locale

from wxproxy import WxProxy, WxAppProxy, XrcProxy, \
                    ArtProvider, WxPartGauge, \
                    WxNiceDownloadPanel, WxNiceTabPanel, \
                    WxNiceStatusBar, WxNiceBrowser, WxNiceToolbar, \
                    WxNiceButton, WxNicePlayerDialog, \
                    pwx as wx

from constants import theme
from utils import sizeof_fmt, size_in, time_fmt, attribute
from gui import MessageDialog, NotificationsManager

if my_env.is_linux:
    try:
        import dbus
    except ImportError:
        dbus = None


try:
    # Setting debug mode for MplayerCtrl
    import wxproxy.mplayerctrl
    wxproxy.mplayerctrl.DEBUG = config.DEBUG
except ImportError:
    logger.warn("ImportError: contrib.mplayerctrl")

try:
    import wx.py.PyShell
    wxdev_environ = True
except ImportError:
    wxdev_environ = False

try:
    import comtypes
except ImportError:
    comtypes = None

try:
    import simplejson as json
except ImportError:
    import json

__app__ = config.constants.APP_NAME
__author__ = config.constants.APP_AUTHOR
__company__ = config.constants.APP_COMPANY
__copyright__ = config.constants.APP_COPYRIGHT
__version__ = config.constants.APP_VERSION

__guid__ = config.constants.APP_GUID
__description__ = "%s is a fast and easy to use P2P client." % __app__ # Visible in about dialog
__url__ = config.constants.APP_URL
__useragent__ = '%s/%s' % (__app__, __version__)



class MenuTaskBarIcon(wx.TaskBarIcon):
    def __init__(self, app, *args, **kwargs):
        wx.TaskBarIcon.__init__(self, *args, **kwargs)
        self.app = app

    def CreatePopupMenu(self):
        return self.app.create_tray_menu()



class Main(WxAppProxy):
    '''
    FDM wx.App object.

    This objects takes care of global event handling, trayicons and menu stuff,
    dialog initialization, and all other stuff's initialization.

    '''
    _icons = {
        "trayicon": ("tray_16",),
        "frame": {
            "MainFrame": ("app_%d" % size for size in (16, 24, 32, 48, 96)),
            },
        }

    _events = {
        "app": (
            (wx.EVT_IDLE, "idle"),
            (wx.EVT_CLOSE, "close_app"),
            (wx.EVT_QUERY_END_SESSION, "end_session"),
            (wx.EVT_SET_FOCUS, "app_focus"),
            ),
        "frame": (
            (wx.EVT_PALETTE_CHANGED , "palette"),
            (wx.EVT_CLOSE, "main_close"),
            (wx.EVT_MOUSEWHEEL, "main_mousewheel"),
            (wx.EVT_SET_FOCUS, "main_focus"),
            ),
        "browser_search": (
            (wx.EVT_WEBVIEW_DOWNLOAD, "web_download"),
            ),
        "browser_extra": (
            (wx.EVT_WEBVIEW_ACTION, "extra_action"),
            (wx.EVT_WEBVIEW_LOADED, "extra_loaded"),
            ),
        "contextmenu": (
            ("ItemResume", wx.EVT_MENU, "resume_download"),
            ("ItemPause", wx.EVT_MENU, "pause_download"),
            ("ItemRecheck", wx.EVT_MENU, "recheck_download"),
            ("ItemPrioUp", wx.EVT_MENU, "prio_up"),
            ("ItemPrioDown", wx.EVT_MENU, "prio_down"),
            ("ItemOpenFolder", wx.EVT_MENU, "open_folder"),
            ("ItemOpenDownload", wx.EVT_MENU, "open_download"),
            ("ItemRemove", wx.EVT_MENU, "remove"),
            ("ItemProperties", wx.EVT_MENU, "properties"),
            ),
        "propertiesdialog": (
            ("PropertiesClose", wx.EVT_BUTTON, "properties_close"),
            ),
        "urldialog": (
            ("UrlEntry", wx.EVT_TEXT, "urlentry_text"),
            ("UrlEntry", wx.EVT_TEXT_ENTER, "url_ok"),
            ("URLOk", wx.EVT_BUTTON, "url_ok"),
            ("URLCancel", wx.EVT_BUTTON, "url_cancel"),
            ),
        "aboutdialog": (
            ("AboutOk", wx.EVT_BUTTON, "about_ok"),
            ),
        "trayicon": (
            (wx.EVT_TASKBAR_LEFT_DCLICK, "tray_dlclick"),
            (wx.EVT_TASKBAR_LEFT_UP, "tray_lclick"),
            (wx.EVT_TASKBAR_RIGHT_UP, "tray_rclick"),
            ),
        "scrolled_window": (
            (wx.EVT_LEFT_DOWN, "scrolled_window_click"),
            (wx.EVT_KEY_DOWN, "scrolled_window_keydown"),
            (wx.EVT_CHILD_FOCUS, "scrolled_window_child_focus"),
            ),
        "maintoolbar": (
            ("ToolbarSearchbox", wx.EVT_SEARCH_TEXT, "toolbar_search_text"),
            ("ToolbarSearchbox", wx.EVT_SEARCH_ENTER, "toolbar_search_enter"),
            ),
        "tabpanel": (
            (wx.EVT_TAB_CHANGE, "tabpanel_change"),
            ),
        "slowbutton": (
            (wx.EVT_BUTTON, "slowbutton"),
            ),
        "backend": (
            ("download_new", "download_new"),
            ("download_update", "download_update"),
            ("download_remove", "download_remove"),
            ("download_hide", "download_hide"),
            ("download_unhide", "download_unhide"),
            ("backend_add", "backend_add"),
            ("backend_remove", "backend_remove"),
            ),
        "config": (
            ("keep_awake", "on_keep_awake"),
            ("download_notification", "on_download_notification"),
            ("download_slow_mode", "on_download_slow_mode"),
            ("language", "on_language"),
            ),
        "extra": (
            ("state", "on_extra_state"),
            ("progress", "on_extra_progress"),
            ),
        }

    _menus = {
        "contextmenu": '''
            MainContextMenu
                ItemResume
                ItemPause
                -
                ItemRecheck
                -
                ItemPrioUp
                ItemPrioDown
                -
                ItemOpenFolder
                ItemOpenDownload
                -
                ItemRemove
                -
                ItemProperties
            '''
        }

    def create_tray_menu(self):
        new_menu = wx.Menu()

        new_item = wx.MenuItem(new_menu, wx.NewId(), _('Show window'), kind=wx.ITEM_CHECK)
        if my_env.is_windows:
            new_item.SetBitmaps(self.resources.bitmap["dialog-ok"], self.resources.bitmap["unchecked"])
        new_menu.AppendItem(new_item)
        new_item.Check(self.frame.IsShown())
        wx.EVT_MENU(self, new_item.GetId(), self.handle_toggle_window)

        new_menu.AppendSeparator()


        new_item = wx.MenuItem(new_menu, wx.NewId(), _('Add torrent link'),
                               _("Add torrent from remote internet location"))
        new_item.SetBitmap(self.resources.bitmap["list-add"])
        new_menu.AppendItem(new_item)
        wx.EVT_MENU(self, new_item.GetId(), self.handle_add_url)

        new_item = wx.MenuItem(new_menu, wx.NewId(), _('Add torrent file'),
                               _("Add torrent from downloaded torrent file"))
        new_item.SetBitmap(self.resources.bitmap["list-add"])
        new_menu.AppendItem(new_item)
        wx.EVT_MENU(self, new_item.GetId(), self.handle_add_torrent)

        new_menu.AppendSeparator()

        new_item = wx.MenuItem(new_menu, wx.NewId(), _('About'))
        new_item.SetBitmap(self.resources.bitmap["help-about"])
        new_menu.AppendItem(new_item)
        wx.EVT_MENU(self, new_item.GetId(), self.handle_about)

        new_menu.AppendSeparator()

        new_item = wx.MenuItem(new_menu, wx.NewId(), _('Exit'))
        new_item.SetBitmap(self.resources.bitmap["application-exit"])
        new_menu.AppendItem(new_item)
        wx.EVT_MENU(self, new_item.GetId(), self.handle_exit)

        return new_menu

    _current_panel = None
    @property
    def current_panel(self):
        return self._current_panel

    @current_panel.setter
    def current_panel(self, panel):
        if panel != self._current_panel:
            if self._current_panel:
                self._current_panel.active = False
            if panel:
                for k, v in self.dpanels.iteritems():
                    if v[0] == panel:
                        self._current_download = k
                        self._current_panel = panel
                        panel.active = True
                        panel.SetFocusIgnoringChildren()
                        return

            # avoid infinite recursion
            self._current_download = None
            if self._current_panel:
                old_current_panel = self._current_panel
                self._current_panel = None

                focus = self.scrolled_window.FindFocus()
                if focus and old_current_panel.FindWindowById(focus.GetId()):
                    self.scrolled_window.SetFocusIgnoringChildren()

    _current_download = None
    @property
    def current_download(self):
        return self._current_download

    @current_download.setter
    def current_download(self, v):
        self.current_panel = self.dpanels[v][0] if v in self.dpanels else None

    @property
    def moving_panel(self):
        return self.moving_panel_timer.IsRunning()

    def on_keep_awake(self, k, v):
        if not self.playerdialog.is_playing:
            my_env.set_idleness_mode(sleep=not v, screensaver = True, reason = "Sleep prevented from %s." % __app__)

    def on_download_notification(self, k, v):
        self.must_show_download_notification = v

    def on_download_slow_mode(self, k, v):
        self.slowbutton.SetActive(v)

    def on_language(self, k, v):
        "What happens each time someone changes the language in settings"

        dict.__setitem__(self.config, "language", v)
        # This is like  self.config["language"] = v  without calling the setter
        # which would also emit a signal that calls on_language(), ourselves!

        # When the application is starting, this function gets called
        # too, but we only want to show the next message if someone
        # changes the language in "settings", not at startup.
        if self.fully_initializated:
            wx.MessageBox(_("Language changed.\n\nPlease restart the "
                            "application for the change to apply."),
                          _("Information"),  wx.OK | wx.ICON_INFORMATION)

    def on_extra_state(self, name, state):
        if name in self._extra_interesting_states:
            self.browser_extra.RunScript('window.update_plugin_state({"%s":%d})' % (name, state))

    def on_extra_progress(self, name, progress):
        if name in self._extra_interesting_states:
            self.browser_extra.RunScript('window.update_plugin_state({"%s":%f})' % (name, 1+progress))

    def download_by_match(self, text):
        '''
        Get download by name match to text

        Params:
            text

        Returns:
            download or None
        '''
        if self.dpanels:
            p = sys.maxint
            r = None
            for download in self.dpanels:
                if text.lower() in download.name.lower() and download.position < p:
                    p = download.position
                    r = download
            return r
        return None

    def panel_by_download(self, download):
        if download in self.dpanels:
            return self.dpanels[download][0]
        return None

    def download_by_panel(self, panel):
        for k, v in self.dpanels.iteritems():
            if v[0] == panel:
                return k
        return None

    def lock(self, lockid):
        try:
            while self._locks[lockid]:
                time.sleep(0.1)
        except KeyError:
            pass
        self._locks[lockid] = True

    def unlock(self, lockid):
        self._locks[lockid] = False

    def __init__(self, single_instance_checker, argv = ()):
        self.fully_initializated = False
        # The app will not initialize completely until after calling self.main()

        self.finished_downloads = set()

        self.ident = threading.current_thread().ident
        self._locks = collections.defaultdict(threading.Lock)
        self._max_position = 0
        self._status_messages = {}
        self._native_dialogs = [] # For closing in close app
        self.search_cooldown = 30
        self.debug_interval = 1
        self.resume_data_interval = 20
        self.update_interval = single_instance_checker.update_interval # FIXME
        self.update_interval_threshold = self.update_interval * 0.9
        self.update_system_cache_interval = 5
        self.config = config.Config(__app__, __version__)

        self.extra = extras.ExtraManager(self)
        self.must_show_download_notification = True

        download_dir = self.config["download_dir"]
        if not isinstance(download_dir, unicode):
            download_dir = unicode(download_dir, "utf-8")
        if not os.path.isdir(download_dir):
            os.makedirs(download_dir)

        self.last_signal = None
        self.checker = single_instance_checker
        self.initial_argv = argv
        self.dpanels = {}

        self.resources = config.ResourceManager()
        lang = self.config.get("language", config.get_default_language())
        self.updater = config.AutoUpdater(__guid__, __app__, __version__, __useragent__,
                                          lang or config.constants.DEFAULT_LANG)

        self.webserver = server.Server(self)
        self.webserver.open_handler = {
            i: lambda card: self.playerdialog.Play(card.name, card.fspath)
            for i in config.constants.PLAYER_CATEGORIES
            }

        self.backend = backends.MultiBackend(self.config, __app__, __version__)

        self.app = self # Autoref for events
        self.update_on_exit = False
        self.update_ignored = False

        self.screen_saver_cookie = None  # used for dbus comms with screensaver

        my_env.set_signal_handler(self.signal_handler)

        WxAppProxy.__init__(self)

    def signal_handler(self, signum, frame):
        self.last_signal = signum
        if not my_env.is_windows and signum == signal.SIGHUP:
            self.sync_downloads()
        else:
            self.close_app()

    def wait_for_signal(self):
        while self.last_signal is None:
            time.sleep(0.1)

    def open_download(self, download):
        self.webserver.jump_play(download)
        self.tabpanel.SetActiveTab(2)

    def handle_update_timer(self, event):
        for line in self.checker.check():
            logging.debug(repr(line))
            self.process_argv(line.split("\0"))
        self.sync_downloads()

    def handle_awake_timer(self, event):
        is_playing = self.playerdialog.is_playing
        if self.last_is_playing!=is_playing:
            if is_playing:
                my_env.set_idleness_mode(sleep=False, screensaver = False, reason = "Sleep prevented from %s." % __app__)
            else:
                my_env.set_idleness_mode(sleep=not self.config["keep_awake"], screensaver = True)

            self.last_is_playing = is_playing
        my_env.idleness_tick()

    def handle_resume_data_timer(self, event):
        logger.debug("Saving resume data (start)")
        try:
            # TODO(felipe): optimize this
            self.config["backend"] = self.backend.get_run_state()
            logger.debug("Saving resume data (success)")
        except BaseException as e:
            logger.debug("Saving resume data (failed)")
            if isinstance(e, IOError) and e.errno == errno.ENOSPC:
                self.show_notification(e.strerror)
            else:
                logger.exception(e)

    def handle_debug_timer(self, event):
        utils.output_memory()

    def get_links_from_clipboard(self):
        if not wx.TheClipboard.IsOpened():
            wx.TheClipboard.Open()
            do = wx.TextDataObject()
            success = wx.TheClipboard.GetData(do)
            wx.TheClipboard.Close()
            if success:
                for i in do.GetText().splitlines():
                    text = i.strip()
                    if self.backend.can_download(text):
                        yield text

    def handle_urlentry_text(self, event):
        okbutton = self.urldialog["URLOk"]
        new_value = bool(self.urldialog["UrlEntry"].value.strip())
        if okbutton.is_enabled()!= new_value:
            okbutton.enable(new_value)

    def handle_add_url(self, event):
        self.urldialog["UrlEntry"].value = os.linesep.join(self.get_links_from_clipboard())
        if self.urldialog.show_modal() == wx.ID_OK:
            data = self.urldialog["UrlEntry"].value.strip()
            if data:
                error_urls = []
                for i in data.splitlines():
                    uri = i.strip()
                    if not self.backend.download(uri):
                        error_urls.append(uri)
                if error_urls:
                    self.show_warning(_("Cannot download:") + os.linesep +
                                      os.linesep.join(error_urls))

    def handle_url_ok(self, event):
        self.urldialog.end_modal(wx.ID_OK)

    def handle_url_cancel(self, event):
        self.urldialog.end_modal(wx.ID_CANCEL)

    def handle_add_torrent(self, event):
        dialog = wx.FileDialog(
            self.frame.obj, _("Choose torrent file"),
            style=wx.FD_FILE_MUST_EXIST,
            wildcard="*.torrent")
        self._native_dialogs.append(dialog)
        #dialog.Centre(wx.CENTRE_ON_SCREEN) #wxWidgets uses non-native dialog on centre
        if dialog.ShowModal() == wx.ID_OK:
            self._add_torrent_dialog = None
            path = dialog.GetPath()
            if not self.backend.download(path):
                self.show_warning(_("Cannot add torrent:") + os.linesep + path)
        self._native_dialogs.remove(dialog)
        del dialog

    def show_warning(self, message, caption=None):
        if caption is None:
            caption = _("Problem found")
        dialog = wx.MessageDialog(
            self.frame.obj, message, caption,
            style=wx.OK | wx.ICON_EXCLAMATION)
        dialog.ShowModal()

    def show_update(self, title, text):
        self.update_ignored = True
        dialog = wx.MessageDialog(
            self.frame.obj, text, title,
            style=wx.YES_NO | wx.ICON_QUESTION)
        # Note: MessageDialog shows no icon in Windows later than Vista
        # due its guidelines:
        # http://msdn.microsoft.com/en-us/library/aa511273.aspx
        self._native_dialogs.append(dialog)
        if dialog.ShowModal() == wx.ID_YES:
            self.update_on_exit = True
            self.close_app()
        self._native_dialogs.remove(dialog)

    def show_update_clean_error(self, exc):
        self.update_ignored = True
        dialog = wx.MessageDialog(
            self.frame.obj,
            _("Something (maybe your antivirus) is preventing %(app)s for "
              "removing old installation files.\nIf you want to "
              "update, you can remove the old installer manually and "
              "restart this application.") % {"app": __app__},
            _("Update available but not installable"),
            style=wx.ICON_ERROR)
        #sizer = dialog.CreateButtonSizer(wx.OK)
        #if sizer:
        #    sizer.Add(wx.Button(sizer.GetParent(), 666, "Open old installer directory."))
        if dialog.ShowModal() == 666:
            my_env.open_folder(self.updater.download_path)

    def show_notification(self, title, message=None):
        self.notifications.show_notification(title, message)

    def handle_start(self, event):
        self.backend.resume()
        self.sync_downloads()

    def handle_pause(self, event):
        self.backend.pause()
        self.sync_downloads()

    def handle_about(self, event):
        self.aboutdialog["AboutDescription"].Wrap(300)
        self.aboutdialog.show_modal()

    def handle_exit(self, event):
        self.close_app()

    def handle_about_ok(self, event):
        self.aboutdialog.end_modal(wx.ID_OK)

    _last_panel_click = (0, 0, 0)
    def handle_panel_dclick(self, panel, event):
        self._last_panel_click = (0, 0, 0)
        if not self.current_panel == panel: # Selected panel doublecheck
            self.current_panel = panel
        self.open_download(self.current_download)

    _change_cursor_delay = None
    def handle_panel_click(self, panel, event):
        "What happens if we click on an item in Downloads"
        target = event.GetEventObject()
        if target.GetName() in ("DownloadPauseButton","DownloadDeleteButton", "DownloadDoneButton"):
            # We cannot start moving panel in pause or delete buttons
            return

        # Another WxWidgets bug: focus control methods (AcceptsFocus,
        # CanAcceptFocus and so on) do not work, so we have to stop
        # the event here and set focus manually.
        event.Skip()  # TODO: check if it makes sense (was: .cancel())

        self.current_panel = panel # Sets focus on panel

        nx = event.GetX()
        ny = event.GetY()

        # Relativizing mouse position to panel (mouse position is relative to target)
        cx, cy = event.GetEventObject().GetScreenPosition()
        self.moving_panel_mouse_position = wx.Point(cx + nx, cy + ny)
        self.moving_panel_click_relative = panel.ScreenToClient(self.moving_panel_mouse_position)

        self.moving_panel_timer.Start()
        dclick_time = wx.SystemSettings.GetMetric(wx.SYS_DCLICK_MSEC)/1000.
        self._change_cursor = time.time()+dclick_time

        # Workaround for another wxWidgets bug: wxGauge doesn't emit dclick
        # Manual dclick detection
        if isinstance(event.GetEventObject(), (wx.Gauge, wx._core.Gauge)):
            nt = time.time()
            ot, ox, oy = self._last_panel_click
            if ( abs(nx-ox) < wx.SystemSettings.GetMetric(wx.SYS_DCLICK_X) and
                 abs(ny-oy) < wx.SystemSettings.GetMetric(wx.SYS_DCLICK_Y) and
                    (nt-ot) < dclick_time ):
                self.handle_panel_dclick(panel, event)
            else:
                self._last_panel_click = (nt, nx, ny)

    def get_download_for_panel(self, panel):
        '''
        Return download related to given panel

        Params:
            panel: download panel object.

        Returns:
            Download object related to panel or None if not found
        '''
        for k, v in self.dpanels.iteritems():
            if v[0] == panel:
                return k
        return None

    def get_panel_at_pos(self, y):
        '''
        Get panel on virtual scrolled_window vertical coordinate given
        in pixels.
        This assume all panels have the same height for performance

        Params:
            y: vertical offset

        Returns:
            Download panel object or None
        '''
        if self.dpanels:
            if y >= 0: # y cannot be less than zero
                first_panel_height = self.dpanels.itervalues().next()[0].GetSize().height
                pos = int(y/first_panel_height)
                if pos < len(self.dpanels):
                    return self.scrolled_window.Sizer.GetItem(pos).Window
        return None

    _download_panel_in_frame = None
    def download_panel_to_frame(self, panel=None, reattach=True):
        if self._download_panel_in_frame == panel:
            return

        sizer = self.scrolled_window.GetSizer()
        if self._download_panel_in_frame:
            # For seamlessly transition
            pos = self.dummy_download_panel.GetPosition()

            #  Hide
            self.download_panel_frame.Hide()
            self.dummy_download_panel.Hide()

            old_panel = self._download_panel_in_frame
            old_panel.GetContainingSizer().Detach(old_panel)
            if reattach:
                # Final position
                position = sizer.GetItemIndex(self.dummy_download_panel) % 2

                # Moving download panel from frame to scrolled window
                old_panel.Hide()
                old_panel.Reparent(self.scrolled_window)
                old_panel.SetPosition(pos)
                old_panel.SetAlternative(position % 2)
                old_panel.Show()

                # Replace dummy panel for download itself
                sizer.Replace(self.dummy_download_panel, old_panel)

                # Focus
                old_panel.SetFocusIgnoringChildren()
            else:
                # Detaching dummy_download_panel
                sizer.Detach(self.dummy_download_panel)
                sizer.Layout()
                old_panel.Destroy()
            self._download_panel_in_frame = None

        if panel:
            # For seamlessly transition
            pos = panel.GetPosition()
            rect = panel.GetScreenRect()

            # Dummy panel
            sizer.Replace(panel, self.dummy_download_panel)
            self.dummy_download_panel.SetMinSize((-1, rect.GetHeight()))
            self.dummy_download_panel.SetPosition(pos)

            # Floating panel
            panel.Reparent(self.download_panel_frame)
            sizer = self.download_panel_frame.GetSizer()
            sizer.Add(panel, 0, wx.EXPAND)
            self.download_panel_frame.SetDimensions(rect.GetX(), rect.GetY(), rect.GetWidth(), rect.GetHeight(), wx.SIZE_FORCE)
            sizer.Layout()

            # Show
            self.dummy_download_panel.Show()
            self.download_panel_frame.Show()

            panel.SetFocusIgnoringChildren()
            self._download_panel_in_frame = panel

    _last_panel_y = None
    _update_moving_panel_cursor_blacklist = {"DownloadPauseButton", "DownloadDeleteButton"}
    def handle_moving_panel_timer(self, event):
        "What happens when you are moving an item in the Download tab"

        if self.current_panel is None or not wx.GetMouseState().ButtonIsDown(wx.MOUSE_BTN_LEFT):
            self.moving_panel_timer.Stop()
            if self.current_panel:
                self.download_panel_to_frame()
            else:
                self.download_panel_to_frame(reattach=False) # Destroy instead

            self.scrolled_window.SetCursor(wx.NullCursor)
            self._change_cursor = -1
            self._last_panel_y = None
        else:
            mouse_position = wx.GetMousePosition()

            if self._change_cursor > -1:
                # Change cursor
                change_cursor = False
                if mouse_position != self.moving_panel_mouse_position:
                    # if panel has been moved
                    self._change_cursor = -1
                    change_cursor = True
                elif self._change_cursor < time.time():
                    # if delay is bigger than double click
                    self._change_cursor = -1
                    change_cursor = True
                if change_cursor:
                    # change cursor for scrolled_window based on download_panel_frame one
                    self.scrolled_window.SetCursor(self.download_panel_frame.GetCursor())

            if mouse_position != self.moving_panel_mouse_position:
                self.moving_panel_mouse_position = mouse_position
                self.download_panel_to_frame(self.current_panel) # Ensure download_panel is in frame
                dummy_rect = self.dummy_download_panel.GetScreenRect()
                scrolled_rect = self.scrolled_window.GetScreenRect()

                # New position
                px = dummy_rect.GetX()
                py = mouse_position.y - self.moving_panel_click_relative.y

                # Scrolling
                min_y = scrolled_rect.GetY()
                max_y = scrolled_rect.GetBottom() - self.download_panel_frame.GetClientSize().GetHeight()

                pux, puy = self.scrolled_window.GetScrollPixelsPerUnit()
                vsx, vsy = self.scrolled_window.GetViewStart()
                csx, csy = pux * vsx, puy * vsy
                if py <= min_y:
                    self.scrolled_window.Scroll(-1, max(0, float(csy + py - min_y) / puy))
                    py = min_y
                    scrolled = (csy > 0) # stop scrolling at panel start
                elif py >= max_y:
                    self.scrolled_window.Scroll(-1, float(csy + py - max_y) / puy)
                    py = max_y
                    scrolled = True
                else:
                    scrolled = False

                # Change queue order if required
                mouse_y = mouse_position.y
                moveup = mouse_y < dummy_rect.GetY()
                movedown = mouse_y > dummy_rect.GetBottom()

                if moveup or movedown or scrolled: # scroll implies moving
                    rx, ry = self.scrolled_window.CalcUnscrolledPosition(self.scrolled_window.ScreenToClient(mouse_position))

                    dest = self.get_panel_at_pos(max(ry, 0))
                    if dest != self.dummy_download_panel:
                        download = self.get_download_for_panel(dest)
                        if download:
                            position = download.position
                        elif mouse_y < 0:
                            position = 0
                        else:
                            position = self._max_position

                        if position != self.current_download.position:
                            self.current_download.position = position
                            self.sync_downloads()

                self.download_panel_frame.SetPosition((px, py))

    def handle_scrolled_window_click(self, event):
        self.scrolled_window.SetFocusIgnoringChildren()

    def handle_panel_focus(self, panel, event):
        if self.current_panel != panel:
            self.current_panel = panel

    def handle_panel_unfocus(self, panel, event):
        if not self.moving_panel:
            if self.current_panel == panel: # Ensure panel is the current one
                self.current_panel = None
                window = event.GetWindow()
                if window and not panel.FindWindowById(window.GetId()) is None:
                    # If new focus is children, set focus again to self
                    self.current_panel = panel
                    event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_panel_context(self, panel, event):
        self.current_panel = panel
        self.update_context_menu()
        self.scrolled_window.PopupMenu(self.contextmenu.obj)

    def handle_panel_delete(self, download, event):
        "When you click the trash icon next to an item in Downloads"
        if not self.moving_panel:
            if download.finished:
                download.hide()
            else:
                download.remove()
            self.sync_downloads()

    def handle_panel_done(self, download, event):
        if not self.moving_panel:
            self.current_download = download
            self.open_download(download)
            event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_panel_pause(self, download, event):
        if not self.moving_panel:
            self.current_download = download
            obj = event.GetEventObject()
            if download.paused or download.queued:
                obj.SetActive(False)
                download.resume()
            else:
                obj.SetActive(True)
                download.pause()
            self.sync_downloads()
            event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_tray_dlclick(self, event):
        if self.frame.is_shown():
            self.frame.hide()
        else:
            self.bring_to_front()

    def handle_toggle_window(self, event):
        if self.frame.is_shown():
            self.frame.hide()
        else:
            self.bring_to_front()

    def handle_tray_lclick(self, event):
        if self.frame.is_shown():
            self.bring_to_front()

    def handle_tray_rclick(self, event):
        self.trayicon.PopupMenu(self.create_tray_menu())

    def update_context_menu(self):
        if self.current_download:
            if self.current_download.paused:
                self.contextmenu["ItemResume"].enabled = True
                self.contextmenu["ItemPause"].enabled = False
            else:
                self.contextmenu["ItemResume"].enabled = False
                self.contextmenu["ItemPause"].enabled = True

            checkeable = self.current_download.backend.name in ("libtorrent",)
            self.contextmenu["ItemRecheck"].enabled = checkeable
            self.contextmenu["ItemOpenDownload"].enabled = (
                self.current_download.finished or
                os.path.isdir(self.current_download.path)
                )

    _minimized_to_tray_once = False
    def handle_main_close(self, event):
        "What happens when you click the close button on the main window"

        # Close the application for systems diffent than Windows (GNU/Linux...)
        if my_env.is_linux:
            self.close_app()
            return

        # Hide the main window and notify that it is minimized to tray
        if event.CanVeto(): # Close could have Veto or not
            event.Veto()
            self.frame.hide()

            # Minimized to tray showed only once
            if not self._minimized_to_tray_once:
                self._minimized_to_tray_once = True
                self.show_notification(_("Application has been minimized to tray"))


    def handle_scrolled_window_keydown(self, event):
        kc = event.GetKeyCode()
        cur = 0
        if kc  == wx.WXK_DOWN:
            cur = -1
        elif kc == wx.WXK_UP:
            cur = 1
        if cur != 0:
            index = 0
            sizer = self.scrolled_window.Sizer
            panels = sizer.children
            npanels = sizer.item_count
            if self.current_panel and self.current_panel in panels:
                index = panels.index(self.current_panel) - cur
            if index < 0:
                panel = panels[index+npanels]
            elif index < npanels:
                panel = panels[index]
            else:
                panel = panels[index-npanels]
            self.current_panel = panel

    def handle_panel_keydown(self, panel, event):
        kc = event.GetKeyCode()
        if kc in (wx.WXK_DOWN, wx.WXK_UP):
            self.handle_scrolled_window_keydown(event)
        elif kc == wx.WXK_DELETE:
            if self.current_download.finished:
                self.current_download.hide()
            else:
                self.current_download.remove()
            self.sync_downloads()
            event.Skip()  # TODO: check if it makes sense (was: .cancel())
        elif kc == wx.WXK_RETURN:
            self.open_download(self.current_download)

    _last_update = 0
    def sync_downloads(self, force=False):
        # Prevent for update too often
        t = time.time()
        time_from_last_update = (t-self._last_update)
        if self.update_interval_threshold < time_from_last_update < self.update_interval and not force:
            wx.MilliSleep((self.update_interval-time_from_last_update)*1000) # Wait for update
            return

        self._last_update = t

        # Backend loop
        self._changed_panels = False
        self.backend.refresh()
        if self._changed_panels:
            self.alternatize_panels()

        # Max position
        self._max_position = self.backend.last_position

        self.update_context_menu()
        self.sync_status()

        parent = self.scrolled_window
        parent.SetVirtualSize(parent.GetBestVirtualSize()) # layout without scroll break

    _sync_status_downloads = ()
    _sync_status_finished = ()
    _current_download_notification = 0
    _current_library_notification = 0
    def sync_status(self):

        download_ids = frozenset(id(i) for i in self.dpanels)
        new_downloads_number = len(download_ids.difference(self._sync_status_downloads)) if self.fully_initializated else 0
        self._sync_status_downloads = download_ids

        finished_ids = frozenset(id(i) for i in self.finished_downloads)
        new_finished_number = len(finished_ids.difference(self._sync_status_finished)) if self.fully_initializated else 0
        self._sync_status_finished = finished_ids

        if self.update_timer.IsRunning(): # Am I updating download list?
            for tc, number, cn in (
              (self.scrolled_window, new_downloads_number, "_current_download_notification"),
              (self.browser_library, new_finished_number, "_current_library_notification"),
                ):

                tab = self.tabpanel.GetContentTab(tc)
                dn_active = not self.tabpanel.GetTabNotification(tab) is None
                if dn_active:
                    number += getattr(self, cn)
                setattr(self, cn, number)

                if number > 0:
                    self.tabpanel.SetTabNotification(tab, str(number))
                elif dn_active:
                    self.tabpanel.SetTabNotification(tab, None)

        self.config.realtime_speed(self.backend.downspeed, self.backend.upspeed)

        status_text = u" ▼  %s/s    ▲  %s/s" % (
                "%s" % sizeof_fmt(self.backend.downspeed),
                "%s" % sizeof_fmt(self.backend.upspeed),
                )

        self.trayicon.SetIcon(
            self.resources.load_icon(self._icons["trayicon"][0]),
            u"%s\n%s" % (__app__.capitalize(), status_text))

        self.statusbar.SetStatusText(u"%s" % status_text, -1)

    def handle_resume_download(self, event):
        self.current_download.resume()
        self.sync_downloads()

    def handle_pause_download(self, event):
        self.current_download.pause()
        self.sync_downloads()

    def handle_recheck_download(self, event):
        self.current_download.recheck()
        self.sync_downloads()

    def handle_remove(self, event):
        if self.current_download.finished:
            self.current_download.hide()
        else:
            self.current_download.remove()
        self.sync_downloads()

    def handle_open_folder(self, event):
        my_env.open_folder(self.current_download.path)

    def handle_open_download(self, event):
        self.open_download(self.current_download)

    _gauge_values = frozenset((True, False))
    _properties_dialog_download = None
    def handle_properties(self, event):
        dialog = self.propertiesdialog
        parent = dialog["PropertiesScrolledWindow"]
        parent.Freeze()
        bgcolor = parent.GetBackgroundColour().Get()
        sizer = parent.Sizer

        download = self.current_download
        for n, (k, v) in enumerate(download.properties):
            obj = wx.StaticText(parent, wx.ID_ANY, k.capitalize(), wx.DefaultPosition, wx.DefaultSize, 0, "%sKey" % k.capitalize())
            font = obj.GetFont()
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            obj.SetFont(font)
            sizer.Add(obj, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
            obj.Layout()
            if isinstance(v, (list, tuple)) and self._gauge_values.issuperset(v):
                obj = WxPartGauge(parent, v)
                obj.SetName("%sValue" % k.capitalize())
                sizer.Add(obj, 1, wx.TOP | wx.RIGHT | wx.EXPAND, 10)
                obj.Layout()
            else:
                if isinstance(v, basestring):
                    lines = v.splitlines() if v else [""]
                elif isinstance(v, float):
                    v = round(v, 2) # Property dialog values must be user-friendly
                    lines = [str(int(v)) if int(v) == v else str(v)]
                else:
                    lines = [str(v)]

                maxline = len(lines) -1

                for n, line in enumerate(lines):
                    lastline = n < maxline
                    sflags = wx.RIGHT | wx.EXPAND
                    if n == 0:
                        sflags |= wx.TOP
                    obj = wx.TextCtrl(parent, wx.ID_ANY, line, wx.DefaultPosition, wx.DefaultSize, wx.BORDER_NONE | wx.TE_READONLY | wx.TE_BESTWRAP)

                    obj.SetBackgroundColour(bgcolor)
                    sizer.Add(obj, 1, sflags, 10)
                    #obj.SetMinSize(obj.GetTextExtent(line))
                    obj.Layout()
                    if lastline:
                        obj = wx.StaticText(parent, wx.ID_ANY, "", wx.DefaultPosition, wx.DefaultSize, 0)
                        sizer.Add(obj, 1, wx.EXPAND, 0)
                        obj.Layout()
        sizer.Layout()
        parent.Thaw()
        parent.SetScrollRate(10, 10)
        parent.SetInitialSize(wx.Size(600, 500))
        parent.SetVirtualSize(parent.GetBestVirtualSize())
        dialog.SetInitialSize(dialog.GetBestSize())
        dialog.Centre(wx.CENTRE_ON_SCREEN)
        self._properties_dialog_download = download
        dialog.show_modal()
        self._properties_dialog_download = None

    def handle_properties_close(self, event):
        self.propertiesdialog.end_modal(wx.ID_OK)
        parent = self.propertiesdialog["PropertiesScrolledWindow"]
        sizer = parent.Sizer
        for child in parent.Children:
            sizer.Remove(child)
            parent.RemoveChild(child)
            child.Destroy()
        parent.Layout()

    _check_messages = True
    _check_updates = True
    _download_retry = 0
    def handle_idle(self, event):
        if self._check_updates:
            recheck = False
            if not self.update_ignored:
                if self.updater.checked:
                    if self._check_messages:
                        # Server messages
                        self._check_messages = False
                        self.servermsgdialog.messages = self.updater.poll_messages()
                        # Setting value to messages blocks this thread
                        # execution, but handle_idle is called again
                        # due EVT_IDLE, so we need to elif here for
                        # preventing another updater check.
                        recheck = True
                    elif self.updater.outdated:
                        # Downloading updates
                        if self.updater.downloading:
                            recheck = True
                        elif self.updater.clean_error:
                            self.show_update_clean_error(self.updater.clean_error)
                        elif self.updater.downloaded:
                            self.show_update(self.updater.title, self.updater.text)
                        elif self._download_retry < 10:
                            self._download_retry += 1
                            self.updater.download()
                            recheck = True
                        else:
                            logger.warn("Updater: download retries exhausted.")
                elif self.updater.checking:
                    # TODO(felipe): poll status
                    recheck = True
                else:
                    recheck = True
                    self._check_messages = True
                    self._download_retry = 0
                    self.updater.check(__version__)
            self._check_updates = recheck

    def handle_updater_timer(self, event):
        if not self.update_ignored:
            # force recheck version
            self._check_updates = True
            self.updater.checked = False

    def handle_end_session(self, event):
        self.close_app()

    def handle_close_app(self, event):
        self.close_app()

    def handle_navigation_error(self, error_info):
        self.browser_search.LoadURL(self.webserver.url + "/error")

    def bring_to_front(self):
        '''
        Brings application to front (on some platforms just put window into a
        'request attention' state).
        '''
        was_shown = self.frame.is_shown()
        # WxWidgets bring to front workaround (as Raise doesn't seems to work)
        # http://forums.wxwidgets.org/viewtopic.php?p=29892&sid=d403a0d41930dc81b92b3607da982012#p29892
        self.frame.Iconize(False)
        self.frame.SetFocus()
        self.frame.Raise()
        self.frame.Show(True)

        if not was_shown:
            self.sync_downloads()

        self.focus_tab_content()

    def focus_tab_content(self):
        '''
        Set focus current selected tab's content.
        '''
        focus = wx.Window.FindFocus()
        if focus and focus.GetTopLevelParent() == self.frame:
            active_tab = self.tabpanel.GetActiveTab()
            if active_tab is None:
                pass
            elif active_tab == 1:
                # Prevent refocus
                if self.scrolled_window.HasFocus():
                    return
                self.scrolled_window.SetFocusIgnoringChildren()
            else:
                content = self.tabpanel.GetTabContent(active_tab)
                if content:
                    if isinstance(content, (list, tuple)):
                        content = content[0]
                    if not content.HasFocus():
                        content.SetFocus()

    def process_argv(self, argv, startup=False):
        '''
        Process command line arguments (currently looks for downloads and run
        PyShell on debug mode if available).

        Params:
            argv: command line arguments array
            startup: boolean, must be True if is called during startup with
                     current arguments.
        '''
        processed = False
        parameter = False
        for arg in argv[1:]:
            if not arg.startswith("--"):
                parameter |= True
                processed |= self.backend.download(arg)
        if config.DEBUG and "--shell" in argv:
            if wxdev_environ:
                pyshell = wx.py.PyShell
                shellvars = pyshell.__main__.__dict__
                if not "app" in shellvars:
                    shellvars.update(globals())
                    shellvars["app"] = self
                    pyshell.original.extend(shellvars)
                pyshell.main()
            else:
                logger.debug("--shell param not available")

        if startup:
            self.tabpanel.SetActiveTab(1) if processed else 0
        elif not parameter:
            # App has been called directly (with no download)
            self.bring_to_front()
        elif processed and self.frame.is_shown():
            # Download added and window is visible
            self.bring_to_front()

    def apply_events(self):
        '''
        Apply events to wxEventHandler objects or custom EventHandler objects
        based on ´_event´ class attribute.
        '''
        # wxwidgets events
        for parent, handlers in self._events.iteritems():
            element = getattr(self, parent)
            if isinstance(element, utils.EventHandler):
                # FDM EventHandlers
                for event, handler in handlers:
                    element.on(event, getattr(self, handler))
            else:
                # WxEventHandler
                for hargs in handlers:
                    if isinstance(hargs[0], basestring):
                        name, evt, handler = hargs
                        assert not element[name] is None, "Cannot find element %s " % name
                        element.bind(evt, getattr(self, "handle_%s" % handler), element[name])
                    else:
                        evt, handler = hargs
                        element.Bind(evt, getattr(self, "handle_%s" % handler))

    def apply_icons(self):
        '''
        Apply icons to wxProxy objects based on `_icons` class method
        specification.
        '''
        for parent, icondict in self._icons.iteritems():
            element = getattr(self, parent)
            if hasattr(element, "apply_icons"):
                if not isinstance(icondict, dict):
                    icondict = {None: icondict}
                element.apply_icons(
                    (label, self.resources.bitmap[icon]
                            if isinstance(icon, basestring) else
                            [self.resources.bitmap[o] for o in icon])
                    for label, icon in icondict.iteritems())
            else:
                if isinstance(icondict, basestring):
                    icondict = (icondict,)
                icon = icondict[0]
                element.SetIcon(self.resources.load_icon(icon), *icondict[1:])

    def apply_menus(self):
        '''
        Apply names to wxMenuProxy objects and its children based on `_menu`
        class attribute specification.
        '''
        # WxMenuBar
        # Workaround: wxWidgets is very poor designed as it does not
        #             provide names for menus or toolbar items (along
        #             with other issues).
        #             WxProxy's apply_names make this possible along
        #             with its abstraction layer.
        for parent, namedef in self._menus.iteritems():
            element = getattr(self, parent)
            element.apply_names(namedef)

    def handle_search_key(self, event):
        if event.key_code == wx.WXK_ESCAPE:
            self.frame.focus = False

    def handle_palette(self, event=None):
        # Do not seems to work after all...
        # TODO(felipe): check and report upstream bug
        pass

    def handle_scrolled_window_child_focus(self, event):
        # A bug on MSW makes scrolling on unwanted child
        if event.GetWindow() != self.current_panel:
            event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_main_mousewheel(self, event):
        self.focus_tab_content()

    def handle_main_focus(self, event):
        self.focus_tab_content()
        event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_app_focus(self, event):
        self.focus_tab_content()
        event.Skip()  # TODO: check if it makes sense (was: .cancel())

    def handle_prio_up(self, event):
        if self.current_download and self.current_download.position > 0:
            self.current_download.position -= 1
            self.sync_downloads()

    def handle_prio_down(self, event):
        if self.current_download:
            self.current_download.position += 1
            self.sync_downloads()

    def handle_toolbar_search_text(self, event):
        download = self.download_by_match(event.GetString())
        panel = self.panel_by_download(download)
        if panel:
            self.current_panel = panel

    def handle_toolbar_search_enter(self, event):
        download = self.download_by_match(event.GetString())
        panel = self.panel_by_download(download)
        if panel:
            self.current_panel = panel

    def handle_web_download(self, event):
        downloaded = False
        data = event.data

        if not downloaded and "magnet" in data and data["magnet"]:
            downloaded = self.backend.download(data["magnet"], data)

        if not downloaded and "sources" in data and data["sources"]:
            downloaded = any(self.backend.download(url, data) for url in data["sources"])

        if not downloaded:
            name = data.get("name", None)
            self.show_warning(
                _("Cannot download: %(name)s") % {'name': name}
                if name else
                _("Cannot download.")
                )

    _extra_interesting_url = None
    _extra_interesting_states = ()
    def handle_extra_action(self, event):
        data = event.data
        action = data[:data.find("(")]

        params = data[data.find("(")+1:data.rfind(")")]
        params = json.loads(params) if params else None

        if action == "state":
            self._extra_interesting_url = self.browser_extra.GetCurrentURL()
            self._extra_interesting_states = [i["name"] for i in params]
            states = {}
            for data in params:
                state = self.extra.state(data["name"], data.get("checksum", 0))
                if data.get("minversion", "") > __version__:
                    # Server version is incompatible
                    if state == 0: # Installable > incompatible
                        state = -3
                    elif state == -1: # Updateable > non updateable
                        state = -4
                states[data["name"]] = state
            self.browser_extra.RunScript("window.update_plugin_state(%s);" % json.dumps(states))
        elif action == "download":
            try:
                self.extra.download(
                    params["name"],
                    params["url"],
                    params.get("installer", False),
                    params.get("params", ())
                    )
            except extras.UninstallError as e:
                self.show_warning("\n".join(e.args), type(e).__name__)
        elif action == "list":
            states = [
                {"name": name,
                 "state": state,
                 "uninstallable": self.extra.uninstallable(name)}
                for name, state in self.extra.states().iteritems()
                ]
            self.browser_extra.RunScript("window.update_plugin_list(%s);" % json.dumps(states))
        elif action == "uninstall":
            try:
                self.extra.uninstall(params["name"])
            except extras.UninstallError as e:
                self.show_warning("\n".join(e.args), type(e).__name__)

    def handle_extra_loaded(self, event):
        '''
        Should be called when browser_extra sends EVT_WEBVIEW_LOADED, and
        ensures '_extra_interesting_url' and '_extra_interesting_states' are
        cleaned for pages which did not send which plugins are showing.
        '''
        if event.GetURL() == self.browser_extra.GetCurrentURL() != self._extra_interesting_url:
            self._extra_interesting_url = None
            self._extra_interesting_states = ()

    _old_tab = None
    def handle_tabpanel_change(self, event):
        current_tab = event.n
        if current_tab != self._old_tab:
            if not self._old_tab is None:
                self.tabpanel.SetTabNotification(self._old_tab, None)
            self._old_tab = current_tab
        self.focus_tab_content()

    def handle_slowbutton(self, event):
        self.config["download_slow_mode"] = not event.GetEventObject().GetActive()

    def update_download_panel(self, download, initialization = False):
        '''
        Update download panel based on download and state.
        '''

        dpos = pos = download.visible_position
        sizer = self.scrolled_window.Sizer

        p, state = self.dpanels[download]

        layout_changed = False
        metadata_changed = False
        state_changed = False
        position_changed = False

        label_name = p.FindWindowByName('label_name')
        label_sources = p.FindWindowByName("label_status")
        download_rate_icon = p.FindWindowByName("DownloadRateIcon")
        download_rate_label = p.FindWindowByName("DownloadRateLabel")
        upload_rate_icon = p.FindWindowByName("UploadRateIcon")
        upload_rate_label = p.FindWindowByName("UploadRateLabel")
        download_icon = p.FindWindowByName("icon")
        progress_bar = p.FindWindowByName("progress_bar")
        progress_label = p.FindWindowByName("DownloadLabelProgress")
        progress_label2 = p.FindWindowByName("DownloadLabelProgress2")
        estimated_label = p.FindWindowByName("DownloadEstimatedLabel")

        pause_button = p.FindWindowByName("DownloadPauseButton")
        remove_button = p.FindWindowByName("DownloadDeleteButton")
        done_button = p.FindWindowByName("DownloadDoneButton")

        if initialization: # first time download is seen, initialize
            sizer.Insert(dpos, p, 0, wx.EXPAND | wx.ALL)

            # Style
            label_name.SetWindowStyleFlag(wx.ST_ELLIPSIZE_END |
                                          label_name.GetWindowStyleFlag())
            label_name.Refresh()
            label_sources.SetWindowStyleFlag(wx.ST_ELLIPSIZE_END |
                                             label_sources.GetWindowStyleFlag())
            label_sources.Refresh()
            estimated_label.SetWindowStyleFlag(wx.ST_ELLIPSIZE_END |
                                               estimated_label.GetWindowStyleFlag())
            estimated_label.Refresh()
            progress_label.SetWindowStyleFlag(wx.ST_ELLIPSIZE_END |
                                              progress_label.GetWindowStyleFlag())
            progress_label.Refresh()

            download_rate_icon.SetBitmap(self.resources.image["ico.download-arrow-down"])
            upload_rate_icon.SetBitmap(self.resources.image["ico.download-arrow-up"])

            remove_button.SetToolTipString(_("Remove from list"))
            done_button.SetLabel(_("play_download"))


            # Events
            pause_button.Bind(wx.EVT_BUTTON, functools.partial(self.handle_panel_pause, download))
            remove_button.Bind(wx.EVT_BUTTON, functools.partial(self.handle_panel_delete, download))
            done_button.Bind(wx.EVT_BUTTON, functools.partial(self.handle_panel_done, download))
            button_list = (pause_button, remove_button, done_button)

            p.Bind(wx.EVT_KEY_DOWN, functools.partial(self.handle_panel_keydown, p))
            p.Bind(wx.EVT_SET_FOCUS, functools.partial(self.handle_panel_focus, p))
            p.Bind(wx.EVT_KILL_FOCUS, functools.partial(self.handle_panel_unfocus, p))

            def offspring(x):  # object and descendants (children, grandchildren...)
                return [x] + \
                    [desc for child in x.GetChildren() if isinstance(child, wx.Window)
                          for desc in offspring(child) if isinstance(desc, wx.Window)]
            #children = list(p.GetChildren())  # would be simpler, but probably not correct
            children = offspring(p)

            for subp in children:
                subp.Bind(wx.EVT_CONTEXT_MENU, functools.partial(self.handle_panel_context, p))
            for button in button_list:
                children.remove(button)
            for subp in children:
                #subp.Bind(wx.EVT_SET_FOCUS, functools.partial(self.handle_panel_focus, p))
                subp.Bind(wx.EVT_LEFT_DCLICK, functools.partial(self.handle_panel_dclick, p))
                subp.Bind(wx.EVT_LEFT_DOWN, functools.partial(self.handle_panel_click, p))

            position_changed = True
            metadata_changed = True
            layout_changed = True
        else: # update values and check
            # Download list position check
            if p == self._download_panel_in_frame:
                panel_to_move = self.dummy_download_panel
            else:
                panel_to_move = p

            pos = sizer.GetItemIndex(panel_to_move)

            if pos != dpos:
                # Fix dpos
                numitems = sizer.GetItemCount()
                dpos = numitems if dpos == -1 else min(dpos, numitems)

                position_changed = True
                sizer.Detach(panel_to_move)
                sizer.Insert(dpos, panel_to_move, 0, wx.EXPAND | wx.ALL)

            # Update properties in open dialog
            if download == self._properties_dialog_download and self.propertiesdialog.is_shown():
                properties = dict(download.properties)
                if "pieces" in properties:
                    # There are some bugs proxying gauge
                    gauge = self.propertiesdialog["PiecesValue"].obj
                    gauge.parts = properties["pieces"]

            # Metadata update
            if not "metadata" in state and download.has_metadata():
                state.add("metadata")
                metadata_changed = True

        quality = 0
        seeds, leechs = download.available_peers
        min_seeds = 5
        ideal_seeds = 10

        try:
            if seeds == leechs == -1 and download.user_data:
                seeds = int(download.user_data.get("seeds", -1))
                leechs = int(download.user_data.get("leechs", -1))
        except:
            pass

        if seeds == -1:
            if download.sources > 0:
                availability = download.availability
                quality = min(float(availability/min_seeds), 1)*0.8
                if availability > ideal_seeds:
                    quality += 0.2
        elif seeds > 0:
            if leechs > 0:
                # We have leechs, we assume we must compete against
                # them for seeds, but we can download parts from
                # them too, so this is an statistical approach

                # We assume each seed makes some leechs to complete the download in some factor
                sources = seeds +  min(seeds*2, leechs) - 1
                peers = seeds + leechs + min_seeds
                quality = min(float(sources)/peers, 1)*0.8
                if sources > ideal_seeds:
                    quality += 0.2
            else:
                quality = min((seeds - 1)/10., 1)*0.8
                if seeds > ideal_seeds:
                    quality += 0.2

        p.SetQuality(quality)

        if metadata_changed:
            name = download.name
            if not name:
                name = _("No name")
                if download.user_data and "name" in download.user_data:
                    name = download.user_data["name"]

            # name may change
            label_name.SetLabel(name)

            if download.user_data and "type" in download.user_data and config.validate_web_category(download.user_data["type"]):
                download_icon.SetBitmap(self.resources.get_web_category_icon(download.user_data["type"]))
            elif download.filenames:
                download_icon.SetBitmap(self.resources.guess_web_icon(download.filenames))
            else:
                download_icon.SetBitmap(self.resources.image["ico.filetype-24-all-off"])
            layout_changed = True

        seeds, leechs = download.available_peers

        if download.user_data and seeds == leechs == -1 and not download.downloading:
            seeds = download.user_data.get("seeds", -1)
            leechs = download.user_data.get("leechs", -1)

        if seeds == -1 or leechs == -1:
            download_peers = "%s %s" % (download.sources or "no", "peer" if download.sources == 1 else "peers")
        else:
            download_peers = "%s %s" % (seeds or "no", "seed" if seeds == 1 else "seeds")
            if leechs != -1:
                download_peers += u" · %s %s" % (leechs or "no", "leech" if leechs == 1 else "leechs")

        if label_sources.Label != download_peers:
            layout_changed = True
            label_sources.SetLabel(download_peers.replace('&', '&&'))

        if download.processing and not (download.paused or download.queued):
            if not "pulsing" in state:
                state.add("pulsing")
                progress_bar.Pulse()
        else:
            force_value = False
            if "pulsing" in state:
                force_value = True
                state.remove("pulsing")
            new_value = 1000 if download.finished else int(download.progress * 1000)
            if progress_bar.GetValue() != new_value or force_value:
                progress_bar.SetValue(new_value)
                state_changed = True

        if download.finished:
            if not "finished" in state:
                state.add("finished")
                if self.must_show_download_notification:
                    self.show_notification(_("Download finished"),
                                           download.name)
                p.SetDispatchable(True)
        elif "finished" in state:
            state.remove("finished")
            p.SetDispatchable(False)

        if download.finished:
            progress_label_text = sizeof_fmt(download.size)
            progress_label2_text = u" ·  100%"
            estimated_label_text = _("finished")
        elif download.size:
            if download.downloaded:
                size = sizeof_fmt(download.size)
                progress_label_text = _("%(progress)s of %(size)s") % {"progress":locale.format("%.1f", size_in(download.downloaded, size.split()[-1])), "size":size}
            else:
                progress_label_text = sizeof_fmt(download.size)

            progress_label2_text = u" ·  %d%%" % (100 * download.progress)

            if download.eta and download.downloading:
                t = " ".join("%d %s" % (n, _(unit))
                             for n,unit in time_fmt(download.eta)[:2])
                estimated_label_text = _("%(time)s left") % {"time": t}
            else:
                estimated_label_text = _("unknown")
        else:
            progress_label_text = ""
            progress_label2_text = ""
            estimated_label_text = ""

        if download.queued:
            if not "queued_icon" in state:
                pause_button.bitmap_selected = self.resources.image["ico.button-18-queue-on"]
                state.add("queued_icon")
        elif "queued_icon" in state:
            pause_button.bitmap_selected = self.resources.image["ico.button-18-pause-on"]
            state.remove("queued_icon")

        if download.paused:
            estimated_label_text = _("paused")
        elif download.queued:
            estimated_label_text = _("queued")
        elif download.processing:
            if download.has_metadata():
                estimated_label_text = _("checking")
            else:
                estimated_label_text = _("downloading")

        if progress_label_text != progress_label.Label:
            layout_changed = True
            progress_label.SetLabel(progress_label_text)

        if progress_label2_text != progress_label2.Label:
            layout_changed = True
            progress_label2.SetLabel(progress_label2_text)

        if estimated_label_text != estimated_label.Label:
            layout_changed = True
            estimated_label.SetLabel(estimated_label_text)

        upspeed = download.upspeed
        if upspeed > 0:
            layout_changed = True
            if not "upload_rate" in state:
                state.add("upload_rate")
                upload_rate_icon.SetBitmap(self.resources.image["ico.download-arrow-up"])
            upload_rate_label.SetLabel(sizeof_fmt(upspeed, fmt="%.0f %s/s"))
        elif "upload_rate" in state:
            state.remove("upload_rate")
            upload_rate_icon.SetBitmap(self.resources.bitmap[None])
            upload_rate_label.SetLabel("")
        elif initialization:
            upload_rate_icon.SetBitmap(self.resources.bitmap[None])
            upload_rate_label.SetLabel("")

        downspeed = download.downspeed
        if downspeed > 0:
            layout_changed = True
            if not "download_rate" in state:
                state.add("download_rate")
                download_rate_icon.SetBitmap(self.resources.image["ico.download-arrow-down"])
            download_rate_label.SetLabel(sizeof_fmt(downspeed, fmt="%.0f %s/s"))
        elif "download_rate" in state:
            state.remove("download_rate")
            download_rate_icon.SetBitmap(self.resources.bitmap[None])
            download_rate_label.SetLabel("")
        elif initialization:
            download_rate_icon.SetBitmap(self.resources.bitmap[None])
            download_rate_label.SetLabel("")

        pause_button_active = download.paused or download.queued
        if pause_button_active != pause_button.GetActive():
            pause_button.SetActive(pause_button_active)

        pause_button_tip = (_("resume") if pause_button_active else _("pause")).capitalize()
        if pause_button.GetToolTipString() != pause_button_tip:
            pause_button.SetToolTipString(pause_button_tip)

        if metadata_changed or state_changed:
            self.webserver.update_download(download, self.fully_initializated)

        if position_changed:
            self._changed_panels = True

        if initialization:
            p.Show(True)
        elif layout_changed:
            p.Layout()
        #p.thaw()

    def remove_download_panel(self, download):
        # Moving download panel
        if download == self.current_download:
            current_panel = self.current_panel
            self.current_panel = None # stop moving_panel_timer if running
            position = current_panel.Parent.Sizer.GetItemIndex(current_panel)
            if current_panel == self._download_panel_in_frame:
                del self.dpanels[download] # case handled by moving_panel_timer

        # Removing panel
        if download in self.dpanels:
            p, state = self.dpanels.pop(download)

            parent = p.GetParent()
            sizer = p.GetContainingSizer()
            position = sizer.GetItemIndex(p)

            sizer.Detach(p)
            parent.RemoveChild(p)

            parent.Update()
            parent.Refresh()
            parent.Layout()
            wx.CallAfter(p.Destroy)

        # Updating
        if self.dpanels:
            # Toolbar tasks message
            tasks = len(self.dpanels)
            txt = _("%(num)s tasks") % {'num': tasks} if tasks > 1 else _("1 task")
            self.maintoolbar.FindWindowByName("ToolbarCounter").SetLabel(txt)
        else:
            # No downloads message
            self.show_nodownloads(True)
            self.maintoolbar.FindWindowByName("ToolbarCounter").SetLabel("")

        # For sync_downloads
        self._changed_panels = True

    def alternatize_panels(self, starting=0):
        for n, data in enumerate(self.dpanels.itervalues()):
            download_panel = data[0]
            panel = self.dummy_download_panel if download_panel == self._download_panel_in_frame else download_panel
            position = panel.Parent.Sizer.GetItemIndex(panel)
            if position >= starting:
                download_panel.SetAlternative(position % 2)

    _nodownloads = False # Is "no current downloads" message visible?
    def download_new(self, download):
        # Skip hidden downloads
        if download.hidden:
            if not self.fully_initializated:
                self.webserver.update_download(download)
            return

        parent = self.scrolled_window
        if download in self.dpanels:
            p, state = self.dpanels[download]
        else:
            # No panel for download, add panel and initialize
            state = set() # Cross sync tags, used for optimizations
            c = self.xrc.LoadPanel(parent, "DownloadPanel")
            p = WxNiceDownloadPanel.Impersonate(c)
            p.SetWindowStyleFlag(wx.WANTS_CHARS)
            self.dpanels[download] = (p, state)

        self.update_download_panel(download, True)
        self.show_nodownloads(False)

        # Toolbar tasks message
        tasks = len(self.dpanels)
        txt = _("%(num)s tasks") % {'num': tasks} if tasks > 1 else _("1 task")
        self.maintoolbar.FindWindowByName("ToolbarCounter").SetLabel(txt)

        if self.fully_initializated and not self.frame.is_shown():
            # Application is minimized to tray and fully initialized so let's
            # show non-intrussive notification.
            self.show_notification(_("Download added"), download.name)

    def download_update(self, download):
        # Skip hidden downloads
        if download in self.dpanels:
            self.update_download_panel(download)
        if download.finished and download in self.dpanels:
            self.finished_downloads.add(download)

    def download_remove(self, download):
        self.webserver.remove_downloads([download])
        if download in self.dpanels:
            self.remove_download_panel(download)

    def download_hide(self, download):
        if download in self.dpanels:
            self.remove_download_panel(download)

    def download_unhide(self, download):
        if not download in self.dpanels:
            self.download_new(download)

    def backend_changed(self):
        networks = set()
        if self.backend.has_backend("amule"):
            networks.add("ed2k")
        if self.backend.has_backend("libtorrent"):
            networks.add("torrent")

        # Backend related labels
        if len(networks) == 1 and "torrent" in networks:
            txt = _("%(appname)s is a fast and easy-to-use torrent client.") % {'appname': __app__}
            self.aboutdialog.FindWindowByName("AboutDescription").SetLabel(txt)
            ready, message = _("Ready, waiting for torrents to download").split(",", 1)
        else:
            txt = _("%(appname)s is a fast and easy-to-use P2P client.") % {'appname': __app__}
            self.aboutdialog.FindWindowByName("AboutDescription").SetLabel(txt)
            ready, message = _("Ready, waiting for downloads").split(",", 1)

        # Same thing, from contextmenu
        itemResume = self.contextmenu["ItemResume"]
        itemResume.SetText(_("Resume"))

        itemPause = self.contextmenu["ItemPause"]
        itemPause.SetText(_("Pause"))

        itemRecheck = self.contextmenu["ItemRecheck"]
        itemRecheck.SetText(_("Recheck"))

        itemPrioUp = self.contextmenu["ItemPrioUp"]
        itemPrioUp.SetText(_("Increase Priority"))

        itemPrioDown = self.contextmenu["ItemPrioDown"]
        itemPrioDown.SetText(_("Decrease Priority"))

        itemOpenFolder = self.contextmenu["ItemOpenFolder"]
        itemOpenFolder.SetText(_("Open download folder"))

        itemOpenDownload = self.contextmenu["ItemOpenDownload"]
        itemOpenDownload.SetText(_("Open file"))

        itemRemove = self.contextmenu["ItemRemove"]
        itemRemove.SetText(_("Remove from list"))

        itemProperties = self.contextmenu["ItemProperties"]
        itemProperties.SetText(_("Properties"))


        self.aboutdialog.SetLabel(_("About"))

        self.urldialog.SetLabel(_("Download link"))
        urldialog_text = self.urldialog["m_staticText4"]
        urldialog_text.SetLabel(_("Paste your download links here"))

        self._waiting_for_ready = ready
        self._waiting_for_message = ",%s" % message

    def backend_add(self, backend):
        self.backend_changed()

    def backend_remove(self, backend):
        self.backend_changed()

    _waiting_for_ready = ""
    _waiting_for_message = ""
    def show_nodownloads(self, show):
        parent = self.scrolled_window
        if show:
            if not self._nodownloads:
                self._nodownloads = True
                p = self.xrc.LoadPanel(parent, "WaitingPanel")
                p.FindWindowByName("waiting_ready").SetLabel(self._waiting_for_ready)
                p.FindWindowByName("waiting_message").SetLabel(self._waiting_for_message)
                parent.Sizer.Add(p.obj, 1, wx.EXPAND | wx.ALL)
                parent.Layout()
        elif self._nodownloads:
            self._nodownloads = False
            sizer = parent.Sizer
            child = parent.FindWindowByName("WaitingPanel")
            sizer.Remove(child)
            parent.RemoveChild(child)
            child.Destroy()
            parent.Layout()

    _closing = False
    _closed = False
    def close_app(self):
        # Ensure this function is called on main thread
        if self.ident != threading.current_thread().ident:
            wx.CallAfter(self.close_app)
            return

        # Prevent calling close_app twice
        if self._closing:
            if self._closed:
                logger.debug("App should be closed, calling wxExitMainLoop")
                self.ExitMainLoop()
            else:
                logger.debug("Skiping close_app recall")
            return

        logger.debug("Starting close_app")
        self._closing = True

        # Deintializing extra modules
        try:
            self.extra.deinitialize_modules()
        except BaseException as e:
            logger.exception(e)

        try:
            if self.frame.IsMaximized():
                self.config["maximized"] = True
            else:
                self.config["maximized"] = False
                self.config["size"] = tuple(self.frame.size)
                self.config["position"] = tuple(self.frame.position)

            self.stop_all_timers()

            # Known message ids
            self.config["update_known_messages"] = tuple(self.updater.known_messages)[-100:] # Limit stored known messages

            # TopLevelWindows
            for group in (wx.GetTopLevelWindows(), self._native_dialogs):
                for frame in group:
                    if hasattr(frame, "IsModal") and frame.IsModal():
                        frame.EndModal(wx.ID_CLOSE)
                    frame.Show(False)
                    frame.Close(bool(frame.Parent or not isinstance(frame, wx._windows.Dialog)))
                    frame.Destroy()
        except BaseException as e:
            logger.exception(e)

        try:
            self.playerdialog.Exit()
        except BaseException as e:
            logger.exception(e)

        # Critical work, saving backend data
        try:
            # TODO(felipe): optimize this
            self.config["backend"] = self.backend.get_state()
        except BaseException as e:
            logger.exception(e)

        try:
            self.backend.stop()
            self.trayicon.RemoveIcon()
        except BaseException as e:
            logger.exception(e)

        try:
            # Servers
            server.Server.shutdown_all()
        except BaseException as e:
            logger.exception(e)

        try:
            # Thread managers
            utils.CheckURL.close_all_connections()
            utils.TaskPool.clean_all()
        except BaseException as e:
            logger.exception(e)

        self.ExitMainLoop()
        logger.debug("Ending close_app")
        self._closed = True

    def exit(self):
        self.close_app()

    def init_notifications(self):
        self.notifications = NotificationsManager(self.trayicon)

    def main(self):
        # Set language
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        # TODO: see if we can better put the locale with things like:
        #   get "en_US.utf8" etc somehow from config.constants.LANGUAGES
        #   locale.setlocale(locale.LC_ALL, the_locale_we_got)
        #   self.locale = wx.Locale(wx.__dict__[the_lang_we_got])
        if "language" not in self.config:
            lang_default = config.get_default_language()
            if lang_default:
                self.config["language"] = lang_default
            else:
                # Show a dialog and ask the user to choose language
                langs = [x[0] for x in config.constants.LANGUAGES.values()]
                dialog = wx.SingleChoiceDialog(
                    None,
                    message="Choose language",
                    caption="Language", choices=langs,
                    style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER|wx.CENTRE|wx.OK)
                dialog.Size = (200, 250)
                dialog.ShowModal()
                self.config["language"] = config.constants.LANGUAGES.keys()[dialog.Selection]
                dialog.Destroy()

        lang = self.config["language"]
        try:
            catalog = gettext.translation(
                'downloader', config.LOCALEDIR,
                languages=[lang], codeset='utf-8')
        except IOError as e:
            logging.error('Problem setting language "%s": %s' % (lang, e))
            catalog = gettext.NullTranslations()
        catalog.install(unicode=True)
        self.webserver.set_language(catalog)

        self.webserver.start()

        # Toolbar button image fix
        if my_env.is_windows and wx.GetApp().GetComCtl32Version() >= 600 and wx.DisplayDepth() >= 32:
            wx.SystemOptions.SetOption("msw.remap", "2")

        self.updater_timer = self.add_timer(self.handle_updater_timer, 21600000) # 6 hours
        self.update_timer = self.add_timer(self.handle_update_timer, int(self.update_interval*1000))
        self.awake_timer = self.add_timer(self.handle_awake_timer, 30000) # 30 seconds to keep screen or system active is OK
        self.last_is_playing = False
        self.resume_data_timer = self.add_timer(self.handle_resume_data_timer, int(self.resume_data_interval*1000))
        self.moving_panel_timer = self.add_timer(self.handle_moving_panel_timer, 50)
        self.debug_timer = self.add_timer(self.handle_debug_timer, int(self.debug_interval*1000))

        ArtProvider(self.resources)
        self.xrc = XrcProxy(self.resources.data["gui.xrc"], skip_bitmaps=True)

        self.frame = self.xrc.LoadFrame(None, "MainFrame")
        self.frame.Hide()

        self.frame.Bind(wx.EVT_CLOSE, self.handle_exit)
        self.servermsgdialog = MessageDialog(self.xrc.LoadDialog(self.frame, "MessageDialog"), __guid__)
        self.menubar = self.frame.menu_bar

        self.urldialog = self.xrc.LoadDialog(self.frame, "URLDialog")
        self.aboutdialog = self.xrc.LoadDialog(self.frame, "AboutDialog")
        self.propertiesdialog = self.xrc.LoadDialog(self.frame, "PropertiesDialog")
        self.playerdialog = WxNicePlayerDialog.Impersonate(self.xrc.LoadDialog(self.frame, "PlayerDialog"))

        for dialog in (self.urldialog, self.aboutdialog, self.propertiesdialog, self.playerdialog):
            dialog.SetWindowStyleFlag(dialog.GetWindowStyleFlag() | wx.FRAME_FLOAT_ON_PARENT | wx.FRAME_NO_TASKBAR)

        self.contextmenu = self.xrc.LoadMenu("MainContextMenu")

        self.trayicon = MenuTaskBarIcon(self, wx.TBI_CUSTOM_STATUSITEM)
        self.scrolled_window = self.frame.FindWindowByName("ScrolledWindow")

        wx.CallAfter(self.init_notifications)

        self.dummy_download_panel = wx.Panel(self.scrolled_window)
        self.dummy_download_panel.Hide()

        self.download_panel_frame = wx.Frame(self.scrolled_window, style=wx.BORDER_NONE | wx.FRAME_NO_TASKBAR | wx.FRAME_FLOAT_ON_PARENT)
        self.download_panel_frame.SetCursor(wx.StockCursor(wx.CURSOR_SIZING if my_env.is_windows else wx.CURSOR_CLOSED_HAND))

        self.download_panel_frame.SetDoubleBuffered(True)
        self.download_panel_frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self.download_panel_frame.Hide()

        # Main window intialization
        self.frame.SetTitle(__app__)
        self.frame.SetMinSize((740, 500))

        if self.config.get("maximized", False):
            self.frame.Maximize(True)

        # Startup position and size restrictions
        sx = wx.SystemSettings.GetMetric( wx.SYS_SCREEN_X )
        sy = wx.SystemSettings.GetMetric( wx.SYS_SCREEN_Y )
        w, h = self.config.get("size", (820, 650))
        w = min(w, sx)
        h = min(h, sy)
        if "position" in self.config:
            x, y = self.config["position"]
            x = min(sx-w, x)
            y = min(sy-h, y)
        else:
            x = (sx-w)/2
            y = (sy-h)/2
        self.frame.set_size((w, h))
        self.frame.set_position((max(x, 0), max(y, 0)))

        wxproxy.apply_style(self.scrolled_window, "downloads")
        self.frame.Show()

        # Toolbar
        self.maintoolbar = WxProxy(WxNiceToolbar.Impersonate(self.frame["MainToolbar"]))
        self.maintoolbar.FindWindowByName("ToolbarSearchbox").Show(False)
        self.maintoolbar.FindWindowByName("ToolbarCounter").SetLabel("")

        tabs = []
        # FIND tab
        self.browser_search = WxNiceBrowser.Impersonate(self.frame["BrowserFind"])
        if config.constants.TAB_FIND_URL:
            # Local error page
            url_find = config.constants.TAB_FIND_URL % {"lang": self.config["language"]}
            self.browser_search.SetErrorURL("%s/error?url=%s&method=post" %
                                            (self.webserver.url, urllib.quote_plus(url_find)))
            self.browser_search.AddSafeLocations(config.constants.TAB_FIND_SAFE_LOCATIONS)
            self.browser_search.AddSafeLocation(self.webserver.url)
            self.browser_search.PostURL(url_find, app=__app__, version=__version__)
            tabs.append((_(u"FIND"), _(u"Find downloads"),
                         self.browser_search))
        else:
            self.browser_search.Show(False)

        # DOWNLOADS tab
        tabs.append((_(u"DOWNLOADS"), _(u"Current downloads"),
                     (self.scrolled_window, self.maintoolbar, self.frame["ToolbarSep"])))

        # PLAY tab
        self.browser_library = WxProxy(WxNiceBrowser.Impersonate(self.frame["BrowserLibrary"], local=True))
        self.browser_library.LoadURL(self.webserver.url + "/play")
        self.browser_library.AddSafeLocation(self.webserver.url)
        tabs.append((_(u"PLAY"),_(u"Play stuff"),
                     self.browser_library))

        # EXTRAS tab
        self.browser_extra = WxProxy(WxNiceBrowser.Impersonate(self.frame["BrowserExtra"]))
        if config.constants.TAB_EXTRA_URL:
            # Local error page
            self.browser_extra.SetErrorURL("%s/error?url=%s&method=post" % (
                self.webserver.url,
                urllib.quote_plus(config.constants.TAB_EXTRA_URL)
                ))

            self.browser_extra.AddSafeLocations(config.constants.TAB_EXTRA_SAFE_LOCATIONS)
            self.browser_extra.AddSafeLocation(self.webserver.url)
            self.browser_extra.PostURL(config.constants.TAB_EXTRA_URL, app=__app__, version=__version__)
            tabs.append((_(u"EXTRAS"), _(u"Extra stuff for %s") % __app__,
                         self.browser_extra))
        else:
            self.browser_extra.Show(False)

        # SETTINGS tab
        self.browser_settings = WxProxy(WxNiceBrowser.Impersonate(self.frame["BrowserSettings"], local=True))
        self.browser_settings.LoadURL(self.webserver.url + "/settings")
        self.browser_settings.AddSafeLocation(self.webserver.url)
        tabs.append((_(u"Settings"), _(u"Settings"),
                     self.browser_settings))

        # Tabpanel
        self.tabpanel = WxNiceTabPanel.Impersonate(self.frame["TabPanel"])
        self.tabpanel.SetTabs([tab[0] for tab in tabs[:-1]])
        self.tabpanel.SetTabToolTips([tab[1] for tab in tabs[:-1]])
        self.tabpanel.SetTabContents([tab[2] for tab in tabs[:-1]])
        self.tabpanel.SetAppMenuToolTip(tabs[-1][1])
        self.tabpanel.SetAppMenu(tabs[-1][2])
        self.tabpanel.SetActiveTab(0)  # Show the "Find" tab

        # StatusBar
        self.statusbar = WxNiceStatusBar.Impersonate(self.frame["StatusBar"])

        self.slowbutton = WxNiceButton(self.statusbar, wx.ID_ANY, theme=theme.statusbar_button, style=wx.NO_BORDER)
        self.slowbutton.SetToolTipString(_("Toggle slow mode"))
        self.slowbutton.SetBitmap(self.resources.bitmap["turtle_24"])
        self.slowbutton.SetBitmapActive(self.resources.bitmap["turtle_white_24"])

        self.statusbar.SetFieldsCount(3)
        self.statusbar.SetStatusWidths([48, -1, 200])
        self.statusbar.SetStatusStyles([wx.SB_FLAT, wx.SB_FLAT, wx.SB_FLAT])
        self.statusbar.SetAligns([wx.ALIGN_CENTER, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL, wx.ALIGN_RIGHT| wx.ALIGN_CENTER_VERTICAL])
        self.statusbar.SetStatusWindow(self.slowbutton, 0)

        font = self.statusbar.GetFont()
        font.SetPointSize(9)
        self.statusbar.SetFont(font)

        # Scrolled_window
        self.scrolled_window.SetScrollRate(5, 20)

        # Double buffering for avoiding flickering

        # In WinXP WxNiceDownloadPanel is double buffered instead the whole
        # scrolled_window due wxScrolledWindow bugs in winXP
        self.scrolled_window.DoubleBuffered = True if not my_env.is_windows_xp else False

        self.propertiesdialog["PropertiesScrolledWindow"].double_buffered = True

        # About dialog font relative adjust

        about = self.aboutdialog["AboutLicense"]
        font = about.font
        font.SetPointSize(font.GetPointSize()*0.9)
        about.font = font


        # About dialog text
        self.aboutdialog["AboutLicense"].value = self.resources.load_text("license_about")
        self.aboutdialog["AboutVersion"].label = _("Version: %s") % __version__

        # Properties dialog initialization
        self.propertiesdialog["PropertiesScrolledWindow"].SetScrollRate(5, 20)

        # WxWidgets workarounds and events
        self.apply_menus() # Menu labeling (wxWidgets menu items has no names)
        self.apply_icons() # Icon loading (XRC has important deficiencies related to icons)

        # Appmenu needs apply_menus
        '''
        self._events["appmenu"] = self._events.pop("menubar")
        appmenu = WxAppMenu()
        appmenu.attach_menubar(self.menubar.obj,
            ignore_ids=(self.menubar["ItemExit"].GetId(),),
            add_to_end=("-", self.menubar["ItemExit"].obj))
        #self.tabpanel.appmenu = appmenu
        #self.appmenu = WxProxy(appmenu)
        '''
        self.frame.SetMenuBar(None)

        # Event table
        self.apply_events() # Event handling (wxPython has no event tables, so I define them as dict)

        # Platform integration stuff
        #     Main frame appearance
        self.frame["ToolbarSep2"].Show(False)

        #     Dialog background and separators
        if not my_env.is_windows_xp:
            bgcolor = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
            if bgcolor.Get() == (255, 255, 255):
                fgcolor = wx.Colour(0, 51, 153, 255)
                sepcolor = wx.Colour(223, 223, 223, 255)
            else:
                fgcolor = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
                sepcolor = wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DSHADOW)
            # Dialog title labels and panel backgrounds
            dialog_panels = (
                self.aboutdialog["AboutContent"],
                self.urldialog["URLContent"],
                self.servermsgdialog["MessageContent"],
                )
            for panel in dialog_panels:
                panel.SetBackgroundColour(bgcolor)
                for label in panel.get_all_children():
                    if type(label.obj) == wx._controls.StaticText:
                        font = label.GetFont()
                        font.SetPointSize(font.GetPointSize() + 2)
                        label.SetFont(font)
                        label.SetForegroundColour(fgcolor)
                        break
            # Dialog Separators
            msw_separators = (
                self.aboutdialog["AboutSeparator"],
                self.urldialog["URLSeparator"],
                self.servermsgdialog["MessageSeparator"],
                self.propertiesdialog["PropertiesSeparator"],
                )
            for sep in msw_separators:
                sep.SetBackgroundColour(sepcolor)
                if sep.is_shown():
                    sep.refresh()
                else:
                    sep.Show(True)
                    sep.GetContainingSizer().layout()

        # Button order
        if my_env.is_windows:
            urlok = self.urldialog["URLOk"]
            sizer = urlok.GetContainingSizer()
            item = sizer.GetItem(urlok)
            sizer.Detach(urlok)
            sizer.Insert(0, urlok, item.GetFlag(), item.GetBorder())

        # Backend initialization
        if "backend" in self.config:
            self.backend.set_state(self.config["backend"])

        if "update_known_messages" in self.config:
            self.updater.known_messages.update(self.config["update_known_messages"])

        self.backend.run()
        self.process_argv(self.initial_argv, True)

        # Enhancements for desktop with compositing
        if my_env.get_compositing():
            margins = (self.tabpanel.Size.height if self.tabpanel.compositing else 0, 0,
                       self.statusbar.Size.height if self.statusbar.compositing else 0, 0)
            my_env.composite_frame(self.frame, margins)

        # Show
        self.frame.Layout()

        if "--startup" in self.initial_argv:
            # Do not show
            self.frame.Hide()
        else:
            # Show
            self.frame.Show()
        self.sync_downloads(force=True)
        self.show_nodownloads(not self.dpanels)

        # Initialize timers
        self.update_timer.Start()
        self.updater_timer.Start()
        self.resume_data_timer.Start()
        self.awake_timer.Start()

        if config.DEBUG:
            utils.output_memory()
            self.debug_timer.Start()

        # Initialize plugins
        self.extra.initialize_modules()

        # Full initialization flag
        self.fully_initializated = True
        return True


class AppDebugger(wx.App):
    def __init__(self, stdout=None, stderr=None):
        self._stdpages = []
        self.stdout = stdout
        self.stderr = stderr
        self.checker = config.SingleInstance(False)

        # New AppDebugger instances must kill old ones
        self.pid = os.getpid()
        self.ownedfile = True

        self.debugfile = my_env.tempfilepath("pid_%s_debugger" % wx.GetUserId())

        with open(self.debugfile, "wb") as f:
            f.write(str(self.pid))
        self.debugtime = my_env.get_filetime(self.debugfile)

        wx.App.__init__(self, False, useBestVisual=True)

    def _stdpage(self, parent, path):
        ctrl = wx.TextCtrl(parent, wx.ID_ANY, "", wx.DefaultPosition, wx.DefaultSize, wx.TE_MULTILINE | wx.TE_RICH | wx.TE_READONLY | wx.BORDER_NONE)
        self._stdpages.append((ctrl, path, 0))
        return ctrl

    def OnMyTimer(self, evt):
        # Test if new instance is running, if so, exit
        debugtime = my_env.get_filetime(self.debugfile)
        if debugtime != self.debugtime:
            try:
                with open(self.debugfile, "rb") as f:
                    if int(f.read()) != self.pid:
                        self.ownedfile  = False
                        wx.CallAfter(self.main.Destroy)
                        return
                self.debugtime = debugtime
            except:
                self.ownedfile = False
                wx.CallAfter(self.main.Destroy)
                return

        for n, (ctrl, path_f, old_size) in enumerate(self._stdpages):
            size = old_size
            if isinstance(path_f, basestring):
                size = os.stat(path_f).st_size
                if size != old_size:
                    with open(path_f, "r") as f:
                        ctrl.ChangeValue(f.read())
            elif isinstance(path_f, utils.FileEater):
                size = len(path_f)
                if size != old_size:
                    ctrl.ChangeValue(path_f.value)
            if size != old_size:
                old_size = size
                ctrl.SetInsertionPointEnd() # ctrl.ShowPosition(ctrl.GetLastPosition()) is buggy
                ctrl.Refresh() # Workaround for stupid wxWidgets redraw bug
            self._stdpages[n] = ctrl, path_f, size

    def OnInit(self):
        self.timer = wx.Timer(self, wx.ID_ANY)
        self.Bind(wx.EVT_TIMER, self.OnMyTimer, None, self.timer.GetId())
        self.main = wx.Frame(None, wx.ID_ANY, "%s debug" % __app__, wx.Point(0, 0), wx.DefaultSize)

        # Dirty vertical maximize hack
        self.main.Maximize(True)
        height = self.main.GetSize().GetHeight()
        self.main.Maximize(False)
        self.main.SetSize(wx.Size(wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X)/2, height))

        self.main.SetSizer(wx.BoxSizer(wx.VERTICAL))
        notebook = wx.Notebook(self.main, wx.ID_ANY)
        if not self.stderr is None:
            notebook.AddPage(self._stdpage(notebook, self.stderr), "stderr", True)
        if not self.stdout is None:
            notebook.AddPage(self._stdpage(notebook, self.stdout), "stdout")

        if wxdev_environ:
            shellbutton = wx.Button(self.main, wx.ID_ANY, "Debug shell")
            shellbutton.Bind(wx.EVT_BUTTON, self.OnShell)

            buttonsizer = wx.BoxSizer(wx.HORIZONTAL)
            buttonsizer.Add(shellbutton)

            self.main.GetSizer().Add(buttonsizer, 0, wx.EXPAND)

        self.main.GetSizer().Add(notebook, 1, wx.EXPAND)

        self.main.Show(True)
        self.main.GetSizer().Layout()

        self.timer.Start(500)
        return True

    def __del__(self):
        if self.ownedfile:
            os.remove(self.debugfile)

    def OnShell(self, event):
        self.checker.send(u"%s\0--shell" % my_env.get_argv()[0])

    def OnExit(self):
        return True

def list_icons():
    icons = collections.defaultdict(set)

    for parent, icondict in Main._icons.iteritems():
        if isinstance(icondict, dict):
            for name, icon in icondict.iteritems():
                if name == "MainFrame":
                    for s, icon in zip((16, 24, 32, 48, 128), icon):
                        icons[s].add(icon)
                    continue
                size = 16
                if isinstance(icon, (list, tuple)):
                    icons[size].update(icon)
                else:
                    icons[size].add(icon)

    icons[16].update(("tray16", ))
    return icons


def print_running_processes():
    if not hasattr(sys, "_current_frames"):
        print >> sys.stderr, "Cannot debug open threads: sys._current_frames not available."
        return
    cdir = config.APPDIR + os.sep
    lcdir = len(cdir)
    print >> sys.stderr, "\n*** STACKTRACE - START ***\n"
    print >> sys.stderr, "\n\n".join(
        "# ThreadID: %s\n" % threadId +
        "\n".join(
            "File: \"%s\", line %d, in %s\n" % (
                filename[lcdir:] if filename.startswith(cdir) else filename,
                lineno, name ) +
            (("  %s" % line.strip()) if line else "")
            for filename, lineno, name, line in traceback.extract_stack(stack)
            )
        for threadId, stack in sys._current_frames().iteritems()
        )
    print >> sys.stderr, "\n*** STACKTRACE - END ***\n"


class STD:
    original = (sys.stdout, sys.stderr)

    @classmethod
    def redirect(cls, stdout, stderr=None):
        if stderr is None:
            sys.stdout = sys.stderr = open(stdout, "w")
        else:
            sys.stdout = open(stdout, "w")
            sys.stderr = open(stderr, "w")

    @classmethod
    def unredirect(cls):
        if (sys.stdout, sys.stderr) != cls.original:
            if not sys.stdout.closed:
                sys.stdout.close()
            if not sys.stderr.closed:
                sys.stderr.close()
            sys.stdout, sys.stderr = cls.original

def main():
    '''
    Main endpoint
    '''
    if config.DEBUG and not config.SLAVE:
        r = main_debugger()
    else:
        r = main_app()

    # std restoring (if changed)
    STD.unredirect()

    sys.exit(r or 0)


def main_debugger():
    '''
    Starts debugger (which relaunches the app in debug mode).
    '''

    if my_env.is_frozen:
        STD.redirect(
            my_env.tempfilepath("debugger.stdout.log"),
            my_env.tempfilepath("debugger.stderr.log")
            )

    if config.APPEXE:
        my_env.call([config.APPEXE, "--debug", "--slave"], shellexec=True)
        p = None
    else:
        args = [sys.executable] + sys.argv + ["--slave"]
        p = subprocess.Popen(args, 0, args[0], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p:
        stdout = utils.FileEater(p.stdout)
        stderr = utils.FileEater(p.stderr)
    else:
        stderr = my_env.tempfilepath("stderr.log")
        stdout = my_env.tempfilepath("stdout.log")
    main = AppDebugger(stdout, stderr)
    main.MainLoop()
    r = 0
    if p:
        stdout.finish()
        stderr.finish()
        while p.poll() is None:
            time.sleep(0.5)
            p.communicate()
        r = p.returncode

    return r

def main_app():
    '''
    Start app in normal or debug+slave mode.
    '''
    if my_env.is_frozen:
        STD.redirect(
            my_env.tempfilepath("stdout.log"),
            my_env.tempfilepath("stderr.log")
            )

    # Debug formatting
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if config.DEBUG else logging.ERROR)

    if config.DEBUG:
        # Reduce verbosity of comtypes
        logging.getLogger("comtypes").setLevel(logging.WARNING)
        logging.getLogger("server").setLevel(logging.WARNING)

    logging.basicConfig(
        format = "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt = "%Y.%m.%d %H.%M.%S"
        )

    # Mplayer could hang the entire execution
    WxNicePlayerDialog.killpids()

    start_application = False
    checker = config.SingleInstance()
    if checker.alone:
        start_application = True
    else:
        try:
            checker.send("\0".join(my_env.get_argv()))
        except config.HangException as e:
            logging.warn(e)
            checker.kill_other()
            start_application = True

    main = None
    if start_application:
        if config.DEBUG:
            logger.addHandler(utils.LoggerHandler())

        try:
            gettext.install('downloader', config.LOCALEDIR, unicode=True)

            main = Main(checker, my_env.get_argv())
            main.MainLoop()
        except BaseException as e:
            logging.exception(e)
            my_env.error_message(
                _("Startup error"),
                _("We're so sorry, %(app)s failed.\n"
                  "Stay tuned for updates.") % {'app': __app__})
        else:
            logging.debug("MainLoop ended.")

    checker.release()

    if main and main.update_on_exit:
        main.updater.apply()

    # Run atexit modules
    atexit_patch.run()

    if config.DEBUG:
        print_running_processes()

    # Wait for running threads
    if hasattr(sys, "_current_frames"):
        while len(sys._current_frames()) > 1:
            time.sleep(0.1)

    logging.debug("Exiting")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path
import threading
import urlparse
import logging
import subprocess
import time
import importlib
import my_env

import os
if my_env.is_windows:
    import wxproxy.webview_ie as html2
else:
    import wx.html2 as html2


import config
import utils

from constants import theme
from wxproxy import WxWindowProxy, WxAppProxy, pwx as wx


class MessageDialog(WxWindowProxy):
    '''
    Flexible dialog for showing message groups.
    '''
    _messages = ()
    @property
    def messages(self):
        return self._messages

    @messages.setter
    def messages(self, v):
        if v:
            new_messages = sorted(v, key=lambda x: (x.get("priority", 0), x.get("title", "").lower()))

            # Remove or rearrange current objects
            for page_data in (self.downloads, self.info):
                for k in page_data.keys():
                    message = self._messages[k]
                    data = page_data.pop(k)
                    if message in new_messages:
                        page_data[new_messages.index(message)] = data

            self.metrics.clear()

            self._messages = new_messages
            self._load_webviews()
            self.page = 0
            self.ShowModal()
        else:
            self._messages = ()

    _page = 0
    @property
    def page(self):
        return self._page

    @page.setter
    def page(self, v):
        numpages = len(self.messages)
        self._page = min(v, numpages)

        message = self.messages[v]
        message.shown = True # Discard message in the future

        self["MessageBack"].Show(numpages > 1)
        self["MessageBack"].Enable(v > 0)
        self["MessageNext"].Show(numpages > 1)
        self["MessageNext"].Enable(v < numpages-1)

        if numpages == 1 and any(i in message for i in ("go_url", "start_url")):
            self["MessageClose"].SetLabel(_("Cancel"))
        else:
            self["MessageClose"].SetLabel(_("Close"))

        # Download (and run) button
        # States:
        #     Download not available: show nothing
        #     Download available: download button
        #     Downloading: progress gauge and cancel button
        #     Failed: download button (and info message)
        #     Finished: show re-run command button (and info message)
        #               (useful when user accidentally cancel a command)
        if "start_url" in message:
            if v in self.downloads:
                download = self.downloads[v]
                if download.success:
                    download_state = "success"
                elif download.failed:
                    download_state = "failed"
                else:
                    download_state = "progress"
            else:
                download_state = "available"
        else:
            download_state = "no download"

        show_start = download_state in ("available", "failed")
        start_message = message.get("start_text", _("Download"))
        self["MessageStart"].Show(show_start and numpages == 1)
        self["MessageStart"].SetLabel(start_message)
        self["MessageMultiStart"].Show(show_start and numpages > 1)
        self["MessageMultiStart"].SetLabel(start_message)

        self["MessageDownloadGauge"].Show(download_state == "progress")
        self["MessageDownloadCancel"].Show(download_state == "progress")
        self["MessageRunAgain"].Show(download_state == "success")

        if download_state == "progress":
            self["MessageDownloadGauge"].SetValue(self.downloads[v].progress*100)

        # Go button (open url)
        go_btn = self["MessageMultiGo" if numpages > 1 else "MessageGo"]
        go_btn.SetLabel(message.get("go_text", _("Go")))
        go_btn.Show("go_url" in message)
        self["MessageGo" if numpages > 1 else "MessageMultiGo"].Show(False)

        # Message text
        lines = message["text"].split("\n", 1) if "text" in message else []
        numlines = len(lines)
        self["MessageLabel"].SetLabelMarkup(lines[0] if lines else "")
        self["MessageLabel"].Show(numlines > 0)
        self["MessageSubLabel"].SetLabelMarkup(lines[1] if numlines == 2 else "")
        self["MessageSubLabel"].Show(numlines == 2)

        # Message icon
        icon = None
        icon_height = None
        frame_icon = None
        if "icon" in message:
            try:
                icon = wx.ArtProvider.GetIcon(message["icon"], wx.ART_CMN_DIALOG)
                assert icon != wx.NullIcon, "No bitmap"
                frame_icon = wx.ArtProvider.GetIcon(message["icon"], wx.ART_FRAME_ICON)
            except BaseException as e:
                logging.exception(e)
                icon = None
                frame_icon = None

        if "text" in message and icon is None:
            icon = wx.ArtProvider.GetIcon("wxART_INFORMATION", wx.ART_CMN_DIALOG)

        bitmap = self["MessageBitmap"]
        if icon:
            icon_height = icon.GetHeight()
            bitmap.SetSize((icon.GetWidth(), icon_height))
            bitmap.SetIcon(icon)
            bitmap.Show(True)
        else:
            bitmap.Show(False)

        # Bitmap layout fixing
        if "text" in message:
            self["MessageLabel"].GetContainingSizer().Layout()
        bitmap.GetContainingSizer().Layout()

        # Webview
        for page, webview in self.webviews.iteritems():
            webview.Show(page == v)
        sizer = self["MessageContent"].GetSizer()
        sizer.GetItem(0).SetProportion(0 if v in self.webviews else 1)
        sizer.Layout()

        # Info text (download status)
        infotext = ""
        infoicon = None
        if v in self.info:
            infoicon, infotext = self.info[v]
            try:
                infoicon = wx.ArtProvider.GetIcon(infoicon, wx.ART_BUTTON)
                bitmap = self["MessageInfoIcon"]
                bitmap.SetSize((infoicon.GetWidth(), infoicon.GetHeight()))
                bitmap.SetIcon(infoicon)
            except:
                infoicon = None

        self["MessageInfo"].Show(
            bool(infotext) or
            self["MessageMultiStart"].IsShown() or
            self["MessageMultiGo"].IsShown()
            ) # MessageInfo is used for aligning too
        self["MessageInfoIcon"].Show(bool(infoicon and infotext))
        self["MessageInfo"].SetLabel(infotext)
        self["MessageInfo"].GetContainingSizer().Layout()

        # Dialog title and icon
        self.SetTitle(message.get("title", _("Message")))
        if not my_env.is_windows:
            # Windows does not use icons for dialogs
            # http://msdn.microsoft.com/en-us/library/windows/desktop/aa511277.aspx
            if frame_icon is None:
                frame_icon = wx.ArtProvider.GetIcon("wxART_INFORMATION", wx.ART_FRAME_ICON)
            self.SetIcon(frame_icon)

        # Metrics
        self.GetSizer().Layout()
        w, h = self.GetBestSize() # Ensure dialog is bigger than minsize
        w = max(w, 420)
        if not self.page in self.metrics:
            self.metrics[self.page] = w, h
        self.SetMinSize((w, h))  # Ensure dialog is bigger than minsize
        self.SetSize(self.metrics[self.page])
        self.Centre(wx.CENTRE_ON_SCREEN)

    def _load_webviews(self):
        '''
        Preload webviews for current messages
        '''
        parent = self["MessageContent"]
        parent.remove_children(self.webviews.itervalues())
        self.webviews.clear()
        for page, message in enumerate(self.messages):
            if "url" in message:
                webview = html2.WebView.New(parent.obj)
                minsize = message.get("size", (550, 350))
                webview.SetMinSize(minsize)
                webview.SetSize(minsize)
                webview.LoadURL(message["url"])
                flags = wx.EXPAND
                if any(i in message for i in ("text", "start_url", "go_url")):
                    if not "text" in message:
                        flags |= wx.TOP
                    flags |= wx.LEFT | wx.RIGHT | wx.BOTTOM
                else:
                    webview.SetWindowStyle(wx.BORDER_NONE)
                parent.sizer.insert(1, webview, 1, flags , 15)
                webview.Show(False)
                self.webviews[page] = webview

    def _next(self, event):
        self.page += 1

    def _back(self, event):
        self.page -= 1

    def _close(self, event):
        self.Close()

    def _go(self, event):
        page = self.page
        if page in self.info:
            del self.info[page]
        message = self.messages[page]
        my_env.open_url(message["go_url"])

    def _cancel(self, event):
        page = self.page
        if page in self.info:
            del self.info[page]
        if page in self.downloads:
            self.downloads.pop(page).cancel()
            self.reload_page()

    def _start(self, event):
        page = self.page
        if page in self.info:
            del self.info[page]
        if page in self.downloads:
            self.downloads[page].retry()
        else:
            message = self.messages[page]
            self.downloads[page] = Download(
                self.guid, # For temp dir
                message["start_url"],
                message.get("start_filename", None),
                message.get("start_argv", ()),
                message.get("start_close", False)
                )

    def _relaunch(self, event):
        page = self.page
        if page in self.downloads:
            self.downloads[page].launch()

    def handle_idle(self, event):
        '''
        Updates current page gauge, if present.
        '''
        if self.IsShown() and self.downloads:
            gauge = self["MessageDownloadGauge"]
            info = self["MessageInfo"]
            current_page = self.page

            info_label = info.GetLabel()
            gauge_visible = gauge.IsShown()
            gauge_value = gauge.GetValue()/100.

            for page, download in self.downloads.iteritems():
                download = self.downloads[page]
                current = page == current_page

                refresh = False
                downloading = False

                if download.failed:
                    self.info[page] = t = ("wxART_ERROR", download.error or "Download failed.")
                    refresh = current and t[1] != info_label
                elif download.success:
                    self.info[page] = t = ("wxART_TICK_MARK", "Download finished")
                    refresh = current and t[1] != info_label
                elif current:
                    downloading = True
                    refresh = not gauge_visible

                if refresh:
                    self.reload_page()
                elif downloading and download.progress != gauge_value:
                    gauge.SetValue(download.progress*100)

    def reload_page(self):
        self.page = self.page

    def handle_close(self, event):
        if self.obj.IsModal():
            self.obj.EndModal(wx.ID_CLOSE)
        if not event.CanVeto():
            Download.cancel_all()
        event.Skip()

    def __init__(self, obj, uid):
        WxWindowProxy.__init__(self, obj)
        self.obj.Bind(wx.EVT_CLOSE, self.handle_close)
        self.obj.Bind(wx.EVT_IDLE, self.handle_idle)

        self.info = {}
        self.downloads = {} # Downloads for current message group
        self.metrics = {}
        self.webviews = {}

        self._lock = threading.Lock()

        self.guid = uid

        # Button events
        self["MessageBack"].Bind(wx.EVT_BUTTON, self._back)
        self["MessageNext"].Bind(wx.EVT_BUTTON, self._next)
        self["MessageClose"].Bind(wx.EVT_BUTTON, self._close)
        self["MessageGo"].Bind(wx.EVT_BUTTON, self._go)
        self["MessageMultiGo"].Bind(wx.EVT_BUTTON, self._go)
        self["MessageStart"].Bind(wx.EVT_BUTTON, self._start)
        self["MessageMultiStart"].Bind(wx.EVT_BUTTON, self._start)
        self["MessageDownloadCancel"].Bind(wx.EVT_BUTTON, self._cancel)
        self["MessageRunAgain"].Bind(wx.EVT_BUTTON, self._relaunch)


class Download(object):
    def __init__(self, tmpfolder, url, name=None, argv=(), close=False):
        self.tmpfolder = my_env.tempdirpath(tmpfolder, "download")
        self.url = url
        self.filename = name
        self.argv = argv
        self.close = close
        self.retry()

    _geturl = None
    _all_downloads = [] # static
    _cthread = None
    def retry(self):
        # Cancel current download
        if self._cthread and self._cthread.is_alive():
            self.cancel()
            self._chtread.join()

        # GetURL (re)initialization
        if self._geturl:
            self._geturl.retry()
        else:
            try:
                bsize = my_env.get_blocksize(self.tmpfolder)
            except BaseException as e:
                logging.exception(e)
                bsize = 4096 # 4 KiB
            self._geturl = utils.GetURL(self.url, buffsize=bsize)

        # Thread info initialization
        self._ok = False
        self._dest = None

        self._cthread = threading.Thread(target=self._run)
        self._cthread.start()

    def _run(self):
        self._all_downloads.append(self)
        self._geturl.wait()
        if not self._geturl.failed:
            try:
                path = os.path.join(
                    self.tmpfolder,
                    self.filename or urlparse.urlparse(self._geturl.url).path.rsplit("/")[-1]
                    )
                # Name choosing, (we cannot write in open files)
                self._dest = my_env.choose_filename(path)
                self._geturl.save(self._dest)
                if self._geturl.finished:
                    self.launch()
            except BaseException as e:
                logging.exception(e)
        self._all_downloads.remove(self)

    def launch(self):
        if self._dest:
            cmd = [self._dest] + self.argv
            self._ok = my_env.call(cmd, shellexec=True)
            if self.close:
                WxAppProxy.get().close_app()

    def cancel(self):
        try:
            self._geturl.close()
        except BaseException as e:
            logging.exception(e)

    @property
    def error(self):
        return self._geturl.get_error_message()

    @property
    def finished(self):
        if self._cthread and self._cthread.is_alive():
            return False
        return self._geturl.finished

    @property
    def failed(self):
        return self._geturl.failed or (self.finished and not self._ok)

    @property
    def success(self):
        return self.finished and not self._geturl.failed

    @property
    def progress(self):
        dsize = self._geturl.size
        if dsize > 0:
            return float(self._geturl.tell()) / dsize
        return 0

    @classmethod
    def cancel_all(cls):
        for i in cls._all_downloads:
            i.cancel()


# notification libraries
NSUserNotification = None
#if my_env.is_mac:
#    try:
#        from Foundation import NSUserNotification, NSUserNotificationCenter
#    except:
#        pass

class NotificationsManager(object):
    def __init__(self, trayicon):
        self.trayicon = trayicon

        self.max_message_length = 255 if my_env.is_windows else 500

        self.next_notification_time = 0
        self.last_notification_title = None
        self.last_notification_message = ""
        self.last_notification = None

        self.preferred_method = self._notify_default
        if my_env.is_windows and trayicon and hasattr(trayicon, "ShowBalloon"):
            self.preferred_method = self._notify_balloon
        elif my_env.is_linux:
            try:
                self.pynotify = importlib.import_module("pynotify")
                self.pynotify.init(config.constants.APP_NAME)
                self.preferred_method = self._notify_pynotify
            except:
                try:
                    self.Notify = importlib.import_module("Notify")
                    self.Notify.init(config.constants.APP_NAME)
                    self.preferred_method = self._notify_notify
                except:
                    pass
        elif my_env.is_mac and NSUserNotification:
            self.notification_center = NSUserNotificationCenter.defaultUserNotificationCenter()
            self.preferred_method = self._notify_macos

    def show_notification(self, title, message=None):
        if message is None:
            message = title
            title = _("Information")

        t = time.time()
        accumulate = (
            t < self.next_notification_time and
            title == self.last_notification_title and
            message != self.last_notification_message and
            len(message) < self.max_message_length - 3
            )

        message = self._prepare_message(message, self.last_notification_message if accumulate else None)

        self.last_notification_title = title
        self.last_notification_message = message
        self.next_notification_time = t + 10

        self.last_notification = self.preferred_method(title, message, self.last_notification if accumulate else None)

    def _prepare_message(self, message, accumulated_message):
        if accumulated_message:
            message = accumulated_message + "\n" + message
            if len(message) > self.max_message_length:
                message_split = message.split("\n")
                message_length = 4
                message_lastpos = len(message_split)-1
                for i in xrange(message_lastpos, -1, -1):
                    message_length += len(message_split[i])
                    if message_length > self.max_message_length:
                        message = "...\n" + "\n".join(message_split[i+1:])
                        break
                else:
                    message = "..." + message[-self.max_message_length+3:]

        if len(message) > self.max_message_length:
            message = "%s..." % message[:self.max_message_length-3]

        return message

    def _notify_default(self, title, message, notification=None):
        return None

    def _notify_balloon(self, title, message, notification=None):
        self.trayicon.ShowBalloon("%s..." % title[:60] if len(title) > 63 else title, message, 10000, wx.ICON_INFORMATION)

    def _notify_pynotify(self, title, message, notification=None):
        if notification:
            notification.update(title, message, 'dialog-information')
        else:
            notification = self.pynotify.Notification(title, message, 'dialog-information')
        notification.show()
        return notification

    def _notify_notify(self, title, message, notification=None):
        if notification:
            notification.update(title, message, 'dialog-information')
        else:
            notification = self.Notify.Notification.new(title, message, 'dialog-information')
        notification.show()
        return notification

    def _notify_macos(self, title, message, notification=None):
        if notification:
            self.notification_center.removeDeliveredNotification_(notification)
        else:
            notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        self.notification_center.deliverNotification_(notification)
        return notification


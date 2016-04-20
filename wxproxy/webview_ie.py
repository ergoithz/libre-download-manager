
import logging
import wx
import ctypes
import comtypes
import comtypes.client
import comtypes.hresult

from comtypes.gen import myole4ax, MSHTML as mshtml

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
atl = ctypes.windll.atl

WS_CHILD        = 0x40000000
WS_VISIBLE      = 0x10000000
WS_CLIPCHILDREN = 0x2000000
WS_CLIPSIBLINGS = 0x4000000
CW_USEDEFAULT   = 0x80000000
WM_KEYDOWN      = 256
WM_DESTROY      = 2

clsID = '{8856F961-340A-11D0-A96B-00C04FD705A2}'
progID = 'Shell.Explorer.2'

# Flags to be used with the RefreshPage method
REFRESH_NORMAL = 0
REFRESH_IFEXPIRED = 1
REFRESH_CONTINUE = 2
REFRESH_COMPLETELY = 3

# Flags to be used with LoadUrl, Navigate, Navigate2 methods
NAV_OpenInNewWindow = 0x1
NAV_NoHistory = 0x2
NAV_NoReadFromCache = 0x4
NAV_NoWriteToCache = 0x8
NAV_AllowAutosearch = 0x10
NAV_BrowserBar = 0x20
NAV_Hyperlink = 0x40
NAV_EnforceRestricted = 0x80
NAV_NewWindowsManaged = 0x0100
NAV_UntrustedForDownload = 0x0200
NAV_TrustedForActiveX = 0x0400
NAV_OpenInNewTab = 0x0800
NAV_OpenInBackgroundTab = 0x1000
NAV_KeepWordWheelText = 0x2000

class WebViewEvent(wx.PyCommandEvent):
    # Workaround to wxPython bug: we cannot inherit from wx.NotifyEvent
    # we need to inherit from wx.PyCommandEvent and implement interface
    def __init__(self, type, id, href, target):
        wx.PyCommandEvent.__init__(self, type, id)

        self._target = target
        self._url = href

    def GetTarget(self):
        return self._target

    def GetURL(self):
        return self._url

    _allowed = True
    def Allow(self):
        self._allowed = True

    def IsAllowed(self):
        return self._allowed

    def Veto(self):
        self._allowed = False


wxEVT_COMMAND_WEBVIEW_NAVIGATING = wx.NewEventType()
wxEVT_COMMAND_WEBVIEW_NAVIGATED = wx.NewEventType()
wxEVT_COMMAND_WEBVIEW_LOADED = wx.NewEventType()
wxEVT_COMMAND_WEBVIEW_ERROR = wx.NewEventType()
wxEVT_COMMAND_WEBVIEW_NEWWINDOW = wx.NewEventType()
wxEVT_COMMAND_WEBVIEW_TITLE_CHANGED = wx.NewEventType()

EVT_WEBVIEW_NAVIGATING = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_NAVIGATING, 1)
EVT_WEBVIEW_NAVIGATED = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_NAVIGATED, 1)
EVT_WEBVIEW_LOADED = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_LOADED, 1)
EVT_WEBVIEW_ERROR = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_ERROR, 1)
EVT_WEBVIEW_NEWWINDOW = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_NEWWINDOW, 1)
EVT_WEBVIEW_TITLE_CHANGED = wx.PyEventBinder(wxEVT_COMMAND_WEBVIEW_TITLE_CHANGED, 1)

WEBVIEW_NAV_ERR_CONNECTION = 0
WEBVIEW_NAV_ERR_CERTIFICATE = 1
WEBVIEW_NAV_ERR_AUTH = 2
WEBVIEW_NAV_ERR_SECURITY = 3
WEBVIEW_NAV_ERR_NOT_FOUND = 4
WEBVIEW_NAV_ERR_REQUEST = 5
WEBVIEW_NAV_ERR_USER_CANCELLED = 6
WEBVIEW_NAV_ERR_OTHER = 7

class ActiveXCtrl(wx.PyAxBaseWindow):
    """
    A wx.Window for hosting ActiveX controls.  The COM interface of
    the ActiveX control is accessible through the ctrl property of
    this class, and this class is also set as the event sink for COM
    events originating from the ActiveX control.  In other words, to
    catch the COM events you mearly have to derive from this class and
    provide a method with the correct name.  See the comtypes package
    documentation for more details.

    Based on wx.lib.activex
    """

    def __init__(self, parent, axID, wxid=-1, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=0, name="activeXCtrl"):
        """
        All parameters are like those used in normal wx.Windows with
        the addition of axID which is a string that is either a ProgID
        or a CLSID used to identify the ActiveX control.
        """


        pos = wx.Point(*pos)    # in case the arg is a tuple
        size = wx.Size(*size)   # ditto

        x = pos.x
        y = pos.y
        if x == -1: x = CW_USEDEFAULT
        if y == -1: y = 20
        w = size.width
        h = size.height
        if w == -1: w = 20
        if h == -1: h = 20

        # create the control
        atl.AtlAxWinInit()
        hInstance = kernel32.GetModuleHandleA(None)
        hwnd = user32.CreateWindowExA(0, "AtlAxWin", axID,
                                      WS_CHILD | WS_VISIBLE
                                      | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                                      x,y, w,h, parent.GetHandle(), None,
                                      hInstance, 0)
        assert hwnd != 0

        # get the Interface for the Ax control
        unknown = ctypes.POINTER(comtypes.IUnknown)()
        res = atl.AtlAxGetControl(hwnd, ctypes.byref(unknown))
        assert res == comtypes.hresult.S_OK
        self._ax = comtypes.client.GetBestInterface(unknown)

        # Fetch the interface for IOleInPlaceActiveObject. We'll use this
        # later to call its TranslateAccelerator method so the AX Control can
        # deal with things like tab traversal and such within itself.
        self._ipao = self._ax.QueryInterface(myole4ax.IOleInPlaceActiveObject)

        # Use this object as the event sink for the ActiveX events
        self._evt_connections = []
        self.AddEventSink(self)

        # Turn the window handle into a wx.Window and set this object to be that window
        win = wx.PyAxBaseWindow_FromHWND(parent, hwnd)
        self.PostCreate(win)

        # Set some wx.Window properties
        if wxid == wx.ID_ANY:
            wxid = wx.Window.NewControlId()
        self.SetId(wxid)
        self.SetName(name)
        self.SetMinSize(size)

        self.Bind(wx.EVT_SET_FOCUS, self.OnSetFocus)
        self.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.OnDestroyWindow)

    def AddEventSink(self, sink, interface=None):
        """
        Add a new target to search for method names that match the COM
        Event names.
        """
        self._evt_connections.append(comtypes.client.GetEvents(self._ax, sink, interface))

    def GetCtrl(self):
        """Easy access to the COM interface for the ActiveX Control"""
        return self._ax

    def MSWTranslateMessage(self, msg):
        res = self._ipao.TranslateAccelerator(msg)
        if res == comtypes.hresult.S_OK:
            return True
        return wx.PyAxBaseWindow.MSWTranslateMessage(self, msg)

    def OnSetFocus(self, evt):
        self._ipao.OnFrameWindowActivate(True)

    def OnKillFocus(self, evt):
        self._ipao.OnFrameWindowActivate(False)

    def OnDestroyWindow(self, evt):
        # release our event sinks while the window still exists
        self._evt_connections = None

CoInternetSetFeatureEnabled = ctypes.windll.urlmon.CoInternetSetFeatureEnabled
CoInternetSetFeatureEnabled.argtypes = (
    ctypes.c_uint,
    ctypes.wintypes.DWORD,
    ctypes.c_bool
    )
CoInternetSetFeatureEnabled.restype = ctypes.wintypes.HRESULT

class WebView(ActiveXCtrl):
    '''
    Ctypes implementation of webview_ie

    Webview_ie has some important bugs so we have to reimplement this using
    the pure-python iewin object based on comtypes and ctypes.

    Based on wx.lib.iewin

    # Reference: https://github.com/wxWidgets/wxWidgets/blob/master/src/msw/webview_ie.cpp
    '''
    def __init__(self, parent, wxid=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=0, name='IEHTMLWindowWebView'):
        ActiveXCtrl.__init__(self, parent, progID, wxid, pos, size, style, name)
        try:
            hresult = CoInternetSetFeatureEnabled(
                0x2, # Process
                21, # FEATURE_DISABLE_NAVIGATION_SOUNDS
                True)
            if hresult != comtypes.hresult.S_OK:
                logging.warn("Unable to activate FEATURE_DISABLE_NAVIGATION_SOUNDS")
        except WindowsError as e:
            # This happens when running with wine
            logging.warn("Unable to activate FEATURE_DISABLE_NAVIGATION_SOUNDS: %s" % e)

        self._ax.Silent = True
        self._processing = False

    @classmethod
    def New(cls, *args, **kwargs):
        return cls(*args, **kwargs)

    def _ensure_document(self):
        if self._ax.Document is None:
            self.LoadURL('about:blank')

    def _event(self, evt, url, target=None):
        event = WebViewEvent(evt, self.GetId(), url, target or "")
        event.SetEventObject(self)
        return event

    def IsBusy(self):
        return self._ax.Busy or self._processing

    def GetPageSource(self):
        if self._ax.Document is None:
            return ""
        doc = self._ax.Document.QueryInterface(mshtml.IHTMLDocument2)

        # tries to find document's main element starting from body
        try:
            main_element = doc.body
            while main_element and hasattr(main_element, "parentElement") and main_element.parentElement:
                main_element = main_element.parentElement
            if hasattr(main_element, "outerHTML") and main_element.outerHTML:
                return main_element.outerHTML
        except BaseException as e:
            logging.exception(e)

        # if using body doesn't works, browse all items
        try:
            for idx in xrange(doc.all.length):
                item = doc.all.item(idx)
                if hasattr(item, "outerHTML") and item.outerHTML:
                    # We only want the first item with outerHTML (the html element)
                    return item.outerHTML
        except BaseException as e:
            logging.exception(e)
        return ""

    def RunScript(self, js):
        doc = self._ax.Document.QueryInterface(mshtml.IHTMLDocument2)
        window = doc.parentWindow.QueryInterface(mshtml.IHTMLWindow2)
        window.execScript(js, "javascript")

    def LoadURL(self, url):
        return self._ax.Navigate2(url, 0) # 0x4 navNoReadFromCache

    def SetPage(self, html, uri=None):
        self._ensure_document()
        doc = self._ax.Document
        doc.write(html)
        doc.close()

    def GetCurrentURL(self):
        return self._ax.LocationURL

    # Blacklisted protocols
    protocol_blacklist = {
        "ms-help", # http://technet.microsoft.com/en-us/security/advisory/2887505
        "tn3270", "cdl", "search-ms", "onenote", "vbscript", "skype-plugin",
        "myim", "ymsgr", "snews", "mms", "file", "ierss", "its", "mailto",
        "ftp", "slupkg", "xmpp", "gcf", "tv", "res", "mapi",
        "windowsmediacenterweb", "windowsmediacenterssl",
        "iehistory", "livecall", "mhtml", "bctp",
        "javascript", "search", "telnet", "magnet", "wlpg",
        "windowsmediacenterapp", "msnim", "ed2k", "news", "dht",
        "ms-its", "skype", "wlmailhtml", "rlogin", "dvd", "btdna", "mk",
        "steam", "aim", "mp2p", "nntp", "mailto", "ldap", "skype4com"
        }

    # COM event handlers (ActiveXCtrl autobinds events by method name)
    # Reference for DWebBrowserEvents and DWebBrowserEvents2:
    # http://msdn.microsoft.com/en-us/library/aa768309(v=vs.85).aspx
    # http://msdn.microsoft.com/en-us/library/aa768283(v=vs.85).aspx
    def BeforeNavigate2(self, this, disp, url, flags, target, post_data, headers, cancel):
        # this, disp, variant(string), variant(integer), variant(string), variant(string), variant(string), bool_variant
        self._processing = True

        event = self._event(wxEVT_COMMAND_WEBVIEW_NAVIGATING, url[0], target[0])
        protocol = url[0].split(":")[0].lower()
        force_continue = False
        if protocol == "javascript" and not target[0]:
            force_continue = True
            event.Veto()
        elif protocol in self.protocol_blacklist:
            logging.warn("Protocol %s is vetoed" % protocol)
            event.Veto()
        else:
            self.HandleWindowEvent(event)

        if not event.IsAllowed() and not force_continue:
            cancel[0] = True
        self._processing = False

    error_codes = {
        "HTTP_STATUS_CONTINUE": 100,
        "HTTP_STATUS_SWITCH_PROTOCOLS": 101,
        "HTTP_STATUS_OK": 200,
        "HTTP_STATUS_CREATED": 201,
        "HTTP_STATUS_ACCEPTED": 202,
        "HTTP_STATUS_PARTIAL": 203,
        "HTTP_STATUS_NO_CONTENT": 204,
        "HTTP_STATUS_RESET_CONTENT": 205,
        "HTTP_STATUS_PARTIAL_CONTENT": 206,
        "HTTP_STATUS_AMBIGUOUS": 300,
        "HTTP_STATUS_MOVED": 301,
        "HTTP_STATUS_REDIRECT": 302,
        "HTTP_STATUS_REDIRECT_METHOD": 303,
        "HTTP_STATUS_NOT_MODIFIED": 304,
        "HTTP_STATUS_USE_PROXY": 305,
        "HTTP_STATUS_REDIRECT_KEEP_VERB": 307,
        "HTTP_STATUS_BAD_REQUEST": 400,
        "HTTP_STATUS_DENIED": 401,
        "HTTP_STATUS_PAYMENT_REQ": 402,
        "HTTP_STATUS_FORBIDDEN": 403,
        "HTTP_STATUS_NOT_FOUND": 404,
        "HTTP_STATUS_BAD_METHOD": 405,
        "HTTP_STATUS_NONE_ACCEPTABLE": 406,
        "HTTP_STATUS_PROXY_AUTH_REQ": 407,
        "HTTP_STATUS_REQUEST_TIMEOUT": 408,
        "HTTP_STATUS_CONFLICT": 409,
        "HTTP_STATUS_GONE": 410,
        "HTTP_STATUS_LENGTH_REQUIRED": 411,
        "HTTP_STATUS_PRECOND_FAILED": 412,
        "HTTP_STATUS_REQUEST_TOO_LARGE": 413,
        "HTTP_STATUS_URI_TOO_LONG": 414,
        "HTTP_STATUS_UNSUPPORTED_MEDIA": 415,
        "HTTP_STATUS_RETRY_WITH": 449,
        "HTTP_STATUS_SERVER_ERROR": 500,
        "HTTP_STATUS_NOT_SUPPORTED": 501,
        "HTTP_STATUS_BAD_GATEWAY": 502,
        "HTTP_STATUS_SERVICE_UNAVAIL": 503,
        "HTTP_STATUS_GATEWAY_TIMEOUT": 504,
        "HTTP_STATUS_VERSION_NOT_SUP": 505,
        "INET_E_INVALID_URL": -2146697214,
        "INET_E_NO_SESSION": -2146697213,
        "INET_E_CANNOT_CONNECT": -2146697212,
        "INET_E_RESOURCE_NOT_FOUND": -2146697211,
        "INET_E_OBJECT_NOT_FOUND": -2146697210,
        "INET_E_DATA_NOT_AVAILABLE": -2146697209,
        "INET_E_DOWNLOAD_FAILURE": -2146697208,
        "INET_E_AUTHENTICATION_REQUIRED": -2146697207,
        "INET_E_NO_VALID_MEDIA": -2146697206,
        "INET_E_CONNECTION_TIMEOUT": -2146697205,
        "INET_E_INVALID_REQUEST": -2146697204,
        "INET_E_UNKNOWN_PROTOCOL": -2146697203,
        "INET_E_SECURITY_PROBLEM": -2146697202,
        "INET_E_CANNOT_LOAD_DATA": -2146697201,
        "INET_E_CANNOT_INSTANTIATE_OBJECT": -2146697200,
        "INET_E_REDIRECT_FAILED": -2146697196,
        "INET_E_REDIRECT_TO_DIR": -2146697195,
        "INET_E_CANNOT_LOCK_REQUEST": -2146697194,
        "INET_E_USE_EXTEND_BINDING": -2146697193,
        "INET_E_TERMINATED_BIND": -2146697192,
        "INET_E_INVALID_CERTIFICATE": -2146697191,
        "INET_E_CODE_DOWNLOAD_DECLINED": -2146696960,
        "INET_E_RESULT_DISPATCHED": -2146696704,
        "INET_E_CANNOT_REPLACE_SFP_FILE": -2146696448,
        "INET_E_CODE_INSTALL_BLOCKED_BY_HASH_POLICY": -2146695936,
        "INET_E_CODE_INSTALL_SUPPRESSED": -2146696192,
        }

    wxerror_codes = {
        "HTTP_STATUS_BAD_REQUEST": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_DENIED": WEBVIEW_NAV_ERR_AUTH,
        "HTTP_STATUS_PAYMENT_REQ": WEBVIEW_NAV_ERR_OTHER,
        "HTTP_STATUS_FORBIDDEN": WEBVIEW_NAV_ERR_AUTH,
        "HTTP_STATUS_NOT_FOUND": WEBVIEW_NAV_ERR_NOT_FOUND,
        "HTTP_STATUS_BAD_METHOD": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_NONE_ACCEPTABLE": WEBVIEW_NAV_ERR_OTHER,
        "HTTP_STATUS_PROXY_AUTH_REQ": WEBVIEW_NAV_ERR_AUTH,
        "HTTP_STATUS_REQUEST_TIMEOUT": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_CONFLICT": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_GONE": WEBVIEW_NAV_ERR_NOT_FOUND,
        "HTTP_STATUS_LENGTH_REQUIRED": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_PRECOND_FAILED": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_REQUEST_TOO_LARGE": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_URI_TOO_LONG": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_UNSUPPORTED_MEDIA": WEBVIEW_NAV_ERR_REQUEST,
        "HTTP_STATUS_RETRY_WITH": WEBVIEW_NAV_ERR_OTHER,
        "HTTP_STATUS_SERVER_ERROR": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_NOT_SUPPORTED": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_BAD_GATEWAY": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_SERVICE_UNAVAIL": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_GATEWAY_TIMEOUT": WEBVIEW_NAV_ERR_CONNECTION,
        "HTTP_STATUS_VERSION_NOT_SUP": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_INVALID_URL": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_NO_SESSION": WEBVIEW_NAV_ERR_CONNECTION,
        "INET_E_CANNOT_CONNECT": WEBVIEW_NAV_ERR_CONNECTION,
        "INET_E_RESOURCE_NOT_FOUND": WEBVIEW_NAV_ERR_NOT_FOUND,
        "INET_E_OBJECT_NOT_FOUND": WEBVIEW_NAV_ERR_NOT_FOUND,
        "INET_E_DATA_NOT_AVAILABLE": WEBVIEW_NAV_ERR_NOT_FOUND,
        "INET_E_DOWNLOAD_FAILURE": WEBVIEW_NAV_ERR_CONNECTION,
        "INET_E_AUTHENTICATION_REQUIRED": WEBVIEW_NAV_ERR_AUTH,
        "INET_E_NO_VALID_MEDIA": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_CONNECTION_TIMEOUT": WEBVIEW_NAV_ERR_CONNECTION,
        "INET_E_INVALID_REQUEST": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_UNKNOWN_PROTOCOL": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_SECURITY_PROBLEM": WEBVIEW_NAV_ERR_SECURITY,
        "INET_E_CANNOT_LOAD_DATA": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_REDIRECT_FAILED": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_REDIRECT_TO_DIR": WEBVIEW_NAV_ERR_REQUEST,
        "INET_E_CANNOT_LOCK_REQUEST": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_USE_EXTEND_BINDING": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_TERMINATED_BIND": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_INVALID_CERTIFICATE": WEBVIEW_NAV_ERR_CERTIFICATE,
        "INET_E_CODE_DOWNLOAD_DECLINED": WEBVIEW_NAV_ERR_USER_CANCELLED,
        "INET_E_RESULT_DISPATCHED": WEBVIEW_NAV_ERR_OTHER,
        "INET_E_CANNOT_REPLACE_SFP_FILE": WEBVIEW_NAV_ERR_SECURITY,
        "INET_E_CODE_INSTALL_BLOCKED_BY_HASH_POLICY": WEBVIEW_NAV_ERR_SECURITY,
        "INET_E_CODE_INSTALL_SUPPRESSED": WEBVIEW_NAV_ERR_SECURITY
        }

    _reversed_error_codes = {v: k for k, v in error_codes.iteritems()}
    def NavigateError(self, this, disp, url, target, status, cancel):
        # this, disp, variant(string), variant(string), variant, VARIANT_BOOL

        event = self._event(wxEVT_COMMAND_WEBVIEW_ERROR, url[0], target[0])

        error = self._reversed_error_codes[status[0]]
        event.SetString(error)
        event.SetInt(self.wxerror_codes[error])

        self.HandleWindowEvent(event)

    def NavigateComplete2(self, this, pDisp, url):
        # this, disp, variant(string)
        self.HandleWindowEvent(
            self._event(wxEVT_COMMAND_WEBVIEW_NAVIGATED, url[0])
            )

    def DocumentComplete(self, this, pdisp, url):
        # this, disp, variant(string)
        if self._ax.ReadyState != 4: # READYSTATE_COMPLETE
            return
        # TODO when needed: history
        self.HandleWindowEvent(
            self._event(wxEVT_COMMAND_WEBVIEW_LOADED, url[0])
            )

    def NewWindow3(self, this, ppDisp, cancel, dwFlags, bstrUrlContext, bstrUrl):
        # this, disp, VARIANT_BOOL, long, bstr, bstr
        self.HandleWindowEvent(
            self._event(wxEVT_COMMAND_WEBVIEW_NEWWINDOW, bstrUrl)
            )
        cancel[0] = True

    def TitleChange(self, this, sText):
        # this, bstr
        self.HandleWindowEvent(
            self._event(wxEVT_COMMAND_WEBVIEW_TITLE_CHANGED, sText)
            )

    def Quit(self):
        return self._ax.Quit()

    def _stub(self, *args):
        pass

    CommandStateChange = _stub
    StatusTextChange = _stub
    ProgressChange = _stub
    DownloadBegin = _stub
    DownloadComplete = _stub
    PropertyChange = _stub
    NewWindow2 = _stub
    OnQuit = _stub
    OnVisible = _stub
    OnToolBar = _stub
    OnMenuBar = _stub
    OnStatusBar = _stub
    OnFullScreen = _stub
    OnTheaterMode = _stub
    WindowSetResizable = _stub
    WindowSetLeft = _stub
    WindowSetTop = _stub
    WindowSetWidth = _stub
    WindowSetHeight = _stub
    WindowClosing = _stub
    ClientToHostWindow = _stub
    SetSecureLockIcon = _stub
    FileDownload = _stub
    PrintTemplateInstantiation = _stub
    PrintTemplateTeardown = _stub
    UpdatePageStatus = _stub
    PrivacyImpactedStateChange = _stub
    SetPhishingFilterStatus = _stub
    WindowStateChanged = _stub
    NewProcess = _stub
    ThirdPartyUrlBlocked = _stub
    RedirectXDomainBlocked = _stub

    # Undocumented sent events
    WebWorkerStarted = _stub
    WebWorkerFinsihed = _stub # WTF!
    BeforeScriptExecute = _stub



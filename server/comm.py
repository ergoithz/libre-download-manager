

import time
import logging
import config

logger = logging.getLogger(__name__)

try:
    import simplejson as json
except ImportError:
    import json

class EndRequest(Exception):
    pass

#import thread
import gevent

class XHRComm(object):
    '''
    Handle XMLHttpRequests
    '''

    def __init__(self):
        self._contexts = {}
        self._sessions = {}
        self._handlers = {} # For faster handler resolution
        self.session_expiration = 300 # 5 minutes

    @property
    def current_id(self):
        #return threading.current_thread().ident
        return gevent.getcurrent()

    @property
    def environ(self):
        return self._contexts[self.current_id]

    @property
    def response_headers(self):
        return self.environ["response_headers"]

    @property
    def session(self):
        try:
            return self._sessions[self.environ["session_id"]]
        except KeyError:
            logger.debug("Cannot get session object")
        return False

    _error_codes = {
        404: ('404 NOT FOUND', 'File not found'),
        405: ('405 METHOD NOT ALLOWED', "Method Not Allowed"),
        500: ("500 SERVER ERROR", "Server error")
        }
    def error(self, code):
        code, body = self._error_codes.get(code, self._error_codes[500])
        self.environ["response_code"] = code
        self.environ["response_body"] = body
        raise EndRequest

    def emit(self, *args):
        environ = self.environ
        if "response_emits" in environ:
            environ["response_emits"].append(args)
        else:
            environ["response_emits"] = [args]

    @classmethod
    def _do_nothing(cls, *args):
        pass

    def handle(self, environ, start_response):
        # Environ XHRComm initialization
        now = time.time()
        tid = self.current_id
        post = ()

        environ["response_code"] = '200 OK'
        environ["response_headers"] = {}
        environ["response_body"] = ""
        environ["QUERY_STRING"] = ""
        self._contexts[tid] = environ

        try:
            if environ['REQUEST_METHOD'].upper() != 'POST' or int(environ.get('CONTENT_LENGTH', 0)) == 0:
                self.error(405)
            self.response_headers["Content-Type"] = "application/json; charset=utf-8"

            # Form
            post_len = int(environ.get('CONTENT_LENGTH', 0))
            if post_len == 0:
                raise EndRequest, "Empty request"
            post_data = environ['wsgi.input'].read(post_len)
            if len(post_data) == 0:
                raise EndRequest, "Bad request"
            post = json.loads(post_data)
            #  Looks like: {u'tasks': [[u'open', u'all:52823376']],
            #               u'id': u'a8826aec-2bdf-4d2d-9a65-0441c806b163'}

            # Session initialize/update
            session_id = post["id"]
            if session_id in self._sessions:
                self._sessions[session_id]["_lt"] = now
            else:
                self._sessions[session_id] = {"_lt": now}
                self.emit("connect")
                self.initialize()
            environ["session_id"] = session_id

            # Processing
            for task in post["tasks"]:
                name = task[0]
                args = task[1:]

                # Cannot use try/except KeyError due gevent verbosity
                if name in self._handlers:
                    self._handlers[name](*args)
                elif hasattr(self, "on_"+name):
                    fnc = getattr(self, "on_"+name)
                    self._handlers[name] = fnc
                    fnc(*args)
                else:
                    self._handlers[name] = self._do_nothing

            self.on_heartbeat()

            # Session discarding
            for k, v in self._sessions.items():
                if now - v["_lt"] > self.session_expiration:
                    del self._sessions[k]
        except EndRequest:
            pass
        except BaseException as e:
            logger.exception(e)

        try:
            # Request response
            headers = self.response_headers
            start_response(
                environ["response_code"],
                [(k, i)
                 for k, v in headers.iteritems()
                 for i in (v if isinstance(v, (list, tuple)) else (v,))]
                )
            if environ.get("response_emits"):
                response_body = json.dumps(environ["response_emits"])
            elif self.response_headers.get("Content-Type", "").endswith("; charset=utf-8"):
                response_body = environ["response_body"].encode("utf-8")
            else:
                response_body = environ["response_body"]

            if config.DEBUG:
                t = time.time()-now
                if t > 0.5:
                    logger.debug("Slow XHR, %s: %s " % (t, [i[0] for i in post.get("tasks", ())]))
            return (response_body, ) if isinstance(response_body, basestring) else ()
        finally:
            del self._contexts[tid]
        return ()

    def on_error(self, error):
        if isinstance(error, basestring):
            error = error.replace("\n", "\n    "),
        else:
            error = repr(error)
        logger.debug(u"JS: %s" % error)

    def on_heartbeat(self):
        pass

    def initialize(self):
        pass

    def disconnect(self, *args, **kwargs):
        self.emit("disconnect")
        del self._sessions[self.environ["session_id"]]


class DownloaderXHRConn(XHRComm):
    def __init__(self, server):
        super(DownloaderXHRConn, self).__init__()
        self.server = server

    def on_heartbeat(self):
        if "subscriptions" in self.session:
            server = self.server
            subscriptions = self.session["subscriptions"]
            if "play" in subscriptions:
                if server.last_update > self.session["last_update"]:
                    logger.debug("HEARTBEAT: play > last update")
                    category, download, path = self.session["path"]
                    cards = list(server.get_playcards_json(category, download, path, self.session["last_update"]))
                    if cards:
                        self.emit("update", {
                            "tasks": server.get_toolbar_tasks(category, download, path),
                            "cards": cards,
                            })
                    self.session["last_update"] = server.last_update
                if server.last_category_update > self.session["last_category_update"]:
                    logger.debug("HEARTBEAT: play > last category update")
                    category, download, path = self.session["path"]
                    self.emit("update", {
                        "categories": [
                            cat.json
                            for cat in server.get_categories(category, download, path)
                            ]
                        })
                    self.session["last_category_update"] = server.last_category_update
                if server.last_remove > self.session["last_remove"]:
                    logger.debug("HEARTBEAT: play > last remove")
                    category, download, path = self.session["path"]
                    ids = list(server.get_last_removed_playcards(self.session["last_remove"]))
                    if ids:
                        self.emit("remove", {
                            "tasks": server.get_toolbar_tasks(category, download, path),
                            "ids": ids,
                            })
                    self.session["last_remove"] = server.last_remove
                if server.last_jump > self.session["last_jump"]:
                    self.on_open(server.get_last_jump_path(self.session["last_jump"]))
                    self.session["last_jump"] = server.last_jump
            if "settings" in subscriptions:
                if server.last_settings > self.session.get("last_settings", 0):
                    logger.debug("HEARTBEAT: play > last settings")
                    self.session["last_settings"] = server.last_settings
                    self.emit("settings", server.settings.json)

    def disconnect(self):
        if "subscriptions" in self.session:
            self.session["subscriptions"].clear()
        super(DownloaderXHRConn, self).disconnect()

    @classmethod
    def _path(cls, path=None):
        category, cpath = path.split(":", 1) if path else ("all", "")
        if "/" in cpath:
            download, cpath = cpath.split("/", 1)
        else:
            download = cpath or None
            cpath = ""
        return category, download, cpath

    _subsscription_defaults = {
        "play": {"path": ("all", None, ""), "last_update": 0, "last_remove":0, "last_category_update":0, "last_jump": 0},
        "settings": {"last_settings":0}
        }
    def on_subscribe(self, code, path="all:", jump=True):
        logger.debug("SUBSCRIBE %s" % code)
        if "subscriptions" in self.session:
            if code in self.session["subscriptions"]:
                return
            self.session["subscriptions"].add(code)
        else:
            self.session["subscriptions"] = {code}
        self.session.update(self._subsscription_defaults.get(code, ()))
        #self.spawn(self._listener)
        if code == "play":
            self.on_open(path, jump)

    def on_settings(self, data):
        self.server.async_action("settings", data)

    def on_rename(self, path):
        self.server.async_action("rename", self.server.get_playcard(*self._path(path)))

    def on_remove(self, path):
        self.server.async_action("remove", self.server.get_playcard(*self._path(path)))

    def on_folder(self, path):
        self.server.async_action("open_folder", self.server.get_playcard(*self._path(path)))

    def on_open(self, path, jump=True):
        '''
        Path format: category:download_id/relative/path/to/file
        '''
        category, download, cpath = self._path(path)
        server = self.server

        base_playcard = server.get_playcard(category, download, cpath)
        cardtype = "root" if base_playcard is None else base_playcard.type

        if cardtype in ("root", "folder", "download"):
            # TODO(felipe): best-file-prediction for download
            # Session update
            self.session.update({
                "path": (category, download, cpath),
                "last_update": server.last_update,
                "last_remove": server.last_remove,
                })

            if jump:
                # New data
                cards = list(server.get_playcards_json(category, download, cpath))
                self.emit("update", {
                    "path": path or "all:",
                    "tasks": server.get_toolbar_tasks(len(cards)),
                    "cards": cards,
                    "breadcrumbs": [
                        breadcrumb.json
                        for breadcrumb in server.get_breadcrumbs(category, download, cpath)
                        ],
                    "categories": [
                        cat.json
                        for cat in server.get_categories(category, download, cpath)
                        ],
                    })
        elif jump and cardtype != "virtual" and base_playcard.progress == 1:
            server.async_action("open", base_playcard)

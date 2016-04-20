#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import os.path
import socket
import logging
import collections
import urllib
import urllib2
import threading
import operator
import itertools
import functools
import hashlib
import weakref
import errno
import time
import traceback
import platform
import json
import zlib
import types
import base64
import gc
import pkg_resources
import locale

import Queue as queue

try:
    import wx
except ImportError:
    logging.warning("wx not available")

try:
    import cStringIO as StringIO
except ImportError:
    import StringIO as StringIO

import my_env
import config


class IteratorCallback(object):
    '''
    Create an interator and call a callback when exhausted
    '''
    def __init__(self, source, callback):
        self.source = iter(source)
        self.callback = callback

    def __iter__(self):
        return self

    def next(self):
        try:
            return self.source.next()
        except StopIteration:
            self.callback()
            raise

class StaticClass(object):
    '''
    Non instantiable class.
    '''
    def __new__(cls, *args, **kwargs):
        raise "%s type cannot be instanced" % cls.__name__

    @classmethod
    def new(cls, name, **kwargs):
        '''
        Convenience method, alias of type(name, (StaticClass,), kwargs)
        '''
        return type(name, (cls,), kwargs)


# from wheezy.core
class attribute(object):
    """ ``attribute`` decorator is intended to promote a
        function call to object attribute. This means the
        function is called once and replaced with
        returned value.

        WARNING: do not use it for double underscored __ (aka private) getters,
                 as this function cannot overwrite its reference.

        >>> class A:
        ...     def __init__(self):
        ...         self.counter = 0
        ...     @attribute
        ...     def count(self):
        ...         self.counter += 1
        ...         print "processed"
        ...         return self.counter
        >>> a = A()
        >>> a.count
        processed
        1
        >>> a.count
        1
    """
    __slots__ = ('f')

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, t=None):
        f = self.f
        val = f(obj)
        setattr(obj, f.__name__, val)
        return val


class DefaultAttrDict(dict):
    '''
    Attrdict with default values created by factory callable

    >>> ad = DefaultAttrDict((("a",1),("b",2)), ord)
    >>> ad
    DefaultAttrDict{'a': 1, 'b': 2 ; <built-in function ord> }
    >>> ad.a
    1
    >>> ad.c == ord('c')
    True
    '''
    def __init__(self, data=(), factory=None):
        dict.__init__(self, data)
        self.factory = factory if callable(factory) else lambda x: None

    def __getattr__(self, k):
        return self.__getitem__(k)

    def __getitem__(self, k):
        if not k in self:
            self[k] = self.factory(k)
        return dict.__getitem__(self, k)

    def __repr__(self):
        return "%s%s ; %s }" % (self.__class__.__name__, dict.__repr__(self)[:-1], self.factory)


class CappedDict(collections.OrderedDict):
    '''
    OrderedDict with maximum size

    >>> c = CappedDict(5, a=1)
    >>> c
    CappedDict([('a', 1)])
    >>> c.update((n, n) for n in xrange(10))
    >>> c
    CappedDict([(5, 5), (6, 6), (7, 7), (8, 8), (9, 9)])
    >>> c[10] = 1
    >>> c
    CappedDict([(6, 6), (7, 7), (8, 8), (9, 9), (10, 1)])
    '''
    update_methods = ("fromkeys", "update")
    maxsize = sys.maxint
    def __init__(self, *args, **kwargs):
        if isinstance(args[0], (int, long)):
            self.maxsize = args[0]
            args = args[1:]
        collections.OrderedDict.__init__(self, *args, **kwargs)
        self._check_size()
        for mn in self.update_methods:
            setattr(self, mn,
                functools.partial(
                    self._wrapper,
                    getattr(collections.OrderedDict, mn)
                    ))

    def _check_size(self):
        if len(self) > self.maxsize:
            for k in tuple(self)[:-self.maxsize]:
                del self[k]

    def _wrapper(self, parent_method, *args, **kwargs):
        r = parent_method(self, *args, **kwargs)
        self._check_size()
        return r

    def __setitem__(self, k, v):
        'od.__setitem__(i, y) <==> od[i]=y'
        if k in self:
            del self[k]
        elif len(self) == self.maxsize:
            del self[iter(self).next()]
        collections.OrderedDict.__setitem__(self, k, v)


class WeakCappedDict(weakref.WeakValueDictionary):
    '''
    Weakref WeakValueDictionary which keep a given number of hard references
    '''
    def __init__(self, size, d = ()):
        self._size = size
        self._strong_refs = queue.Queue(size)
        weakref.WeakValueDictionary.__init__(self, d)

    def _strongref(self, o):
        if self._strong_refs.full():
            self._strong_refs.get(False)
        self._strong_refs.put(o)

    def __setitem__(self, k, v):
        self._strongref(v)
        weakref.WeakValueDictionary.__setitem__(self, k, v)

    def __getitem__(self, k):
        v = weakref.WeakValueDictionary.__getitem__(self, k)
        self._strongref(v)
        return v

    def update(self, o):
        for k, v in dict(o).iteritems():
            self[k] = v


class OrderedSet(collections.MutableSet):
    '''
    >>> s = OrderedSet('abracadaba')
    >>> t = OrderedSet('simsalabim')
    >>> print(s | t)
    OrderedSet{'a', 'b', 'r', 'c', 'd', 's', 'i', 'm', 'l'}
    >>> print(s & t)
    OrderedSet{'a', 'b'}
    >>> print(s - t)
    OrderedSet{'r', 'c', 'd'}
    '''
    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]         # sentinel node for doubly linked list
        self.map = {}                   # key --> [key, prev, next]
        if iterable is not None:
            self |= iterable

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[1]
            curr[2] = end[1] = self.map[key] = [key, curr, end]

    def discard(self, key):
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[2] = next
            next[1] = prev

    def __iter__(self):
        end = self.end
        curr = end[2]
        while curr is not end:
            yield curr[0]
            curr = curr[2]

    def __reversed__(self):
        end = self.end
        curr = end[1]
        while curr is not end:
            yield curr[0]
            curr = curr[1]

    def pop(self, last=True):
        if not self:
            raise KeyError('set is empty')
        key = self.end[1][0] if last else self.end[2][0]
        self.discard(key)
        return key

    def __repr__(self):
        if not self:
            return '%s{}' % (self.__class__.__name__,)
        return '%s{%s}' % (self.__class__.__name__, repr(tuple(self))[1:-1])

    def __eq__(self, other):
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        return set(self) == set(other)

    def update(self, v):
        for i in v:
            self.add(i)

class CappedSet(OrderedSet):
    update_methods = ("update",)
    def __init__(self, maxsize, iterable=None):
        OrderedSet.__init__(self, iterable)
        self.maxsize = maxsize
        self._check_size()
        for mn in self.update_methods:
            setattr(self, mn,
                functools.partial(
                    self._wrapper,
                    getattr(collections.OrderedDict, mn)
                    ))

    def _check_size(self):
        if len(self) > self.maxsize:
            for k in tuple(self)[:-self.maxsize]:
                del self[k]

    def _wrapper(self, parent_method, *args, **kwargs):
        r = parent_method(self, *args, **kwargs)
        self._check_size()
        return r

    def add(self, v):
        if not v in self:
            if len(self) == self.maxsize:
                self.pop(False)
            OrderedSet.add(self, v)


class CheckURL(object):
    _all_instances = weakref.WeakSet()
    @property
    def redirected(self):
        return self.response and self.response.geturl() != self.request.get_full_url()

    @property
    def failed(self):
        return self.ready and self._respcode != 200

    _respcode = -1
    @property
    def ready(self):
        return self._respcode > -1

    @property
    def code(self):
        self.wait()
        return self._respcode

    _closed = False
    @property
    def closed(self):
        return self.response is None or self._closed

    @property
    def headers(self):
        if self.response:
            return self.response.headers
        return {}

    _rurl = None
    @property
    def response_url(self):
        if self._rurl is None:
            self._rurl = self.response.geturl()
        return self._rurl

    _url = None
    @property
    def url(self):
        return self._url

    @classmethod
    def close_all_connections(cls):
        for wref in cls._all_instances:
            wref.close()

    @classmethod
    def faster_url(cls, *url_lists, **kwargs):
        '''
        Get faster url for each url list in params in 0.5 seconds.
        If no url responds in max_time, last url is returned.

        If more than one list is given as argument, result will ge returned
        as list.

        Returns:
            faster url in list or, if more than url_list is given, list of
            faster urls of each url given.
        '''
        retries = kwargs.pop("retries", 10)
        wait_time = kwargs.pop("wait_time", 0.05)
        checkers = [[cls(url) for url in url_list] for url_list in url_lists]
        results = [url_list[-1] for url_list in url_lists]
        numlists = len(url_lists)
        done = 0
        for i in xrange(retries):
            for n, checker_list in enumerate(checkers):
                for checker in checker_list:
                    if checker.ready and (not checker.failed) and (not checker.redirected):
                        results[n] = checker.url
                        checkers[n] = ()
                        done += 1
                        break
            if done == numlists: break
            time.sleep(wait_time)
        if numlists == 1:
            return results[0]
        return results

    def get_error_message(self):
        return self._error_message

    def __init__(self, url, args=None, useragent=None, autoclose=True, method="HEAD"):
        self.__class__._all_instances.add(self)
        self._url = url

        if not url:
            traceback.print_stack()

        data = None

        headers = {}
        if useragent:
            headers["User-Agent"] = useragent

        if args:
            if method == "GET":
                url = "%s?%s" % (url, urllib.urlencode(args))
            elif method == "POST":
                data = urllib.urlencode(args)

        self._data = data
        self.request = urllib2.Request(url, data, headers)
        self.response = None
        self.autoclose = autoclose
        self.cthread = None
        self.retry()

    def close(self):
        if not self.closed:
            if self.response:
                self.response.close()
            self._closed = True

    def retry(self):
        if self.cthread is None or not self.cthread.is_alive():
            self._rurl = None
            self._error_message = None
            self._respcode = -1
            self.cthread = threading.Thread(target=self._connect)
            self.cthread.start()

    def wait(self, timeout=None):
        if self.cthread and self.cthread.is_alive():
            self.cthread.join(timeout)

    def _connect(self):
        try:
            self.response = urllib2.urlopen(self.request, self._data)
        except urllib2.HTTPError as e:
            self._respcode = e.code
            self._error_message = "Server returned code %d." % e.code
        except urllib2.URLError as e:
            logging.exception(e)
            self._error_message = "Cannot connect to remote host."
            self.response = None
            self._respcode = 0
        else:
            self._respcode = self.response.getcode()
            if self.autoclose:
                self.response.close()

    def __del__(self):
        self.close()


class GetURL(CheckURL):
    @property
    def lines(self):
        '''
        Return line iterator
        '''
        return IteratorCallback(self.response, self.close)

    @property
    def failed(self):
        '''
        If download failed or response code other than 200 or 206
        '''
        if self._download_failed:
            return True
        if self.ready:
            # URL error
            code = self.code
            if self._partial:
                return code != 206
            return not code in (200, 202)
        return False

    @property
    def size(self):
        '''
        Content-Length
        '''
        return int(self.headers.get("Content-Length", 0))

    @property
    def finished(self):
        '''
        Request body data EOF reached
        '''
        return self._eof

    def __init__(self, url, args=None, buffsize=4096, useragent=None, method="GET"):
        CheckURL.__init__(self, url, args, useragent=useragent, autoclose=False, method=method)
        self.buffsize = buffsize
        self.reserved = False
        self._partial = False # True if we seeked to some position
        self._offset = 0

    def __iter__(self):
        return self

    def retry(self):
        '''

        '''
        self._eof = False
        self._offset = 0
        self._download_failed = False
        CheckURL.retry(self)

    def _discard_response(self):
        try:
            self.wait()
            if self.code == 200:
                self.response.read()
        except BaseException:
            pass

    def discard(self):
        if not self.closed:
            threading.Thread(target=self._discard_response).start()

    def _getnbytes(self, numbytes):
        self.wait()
        if not self.failed:
            while numbytes > 0:
                r = self.response.read(numbytes)
                rn = len(r)
                if rn == 0: # Means EOF
                    self._eof = True
                    self.close()
                    break
                yield r
                self._offset += rn
                numbytes -= rn

    def save(self, path, ):
        '''
        Save request body to path
        '''
        self.wait()
        fileobj = None
        try:
            checksum = self.headers.get("Content-MD5", None)
            if self.reserved and self.size and os.path.isfile(path) and os.stat(path).st_size == self.size:
                # Fixed disk size mode
                fileobj = open(path, "r+b")
                fileobj.seek(self._offset)
            elif self._offset == 0:
                # Write to empty file mode
                fileobj = open(path, "wb")
                if self.reserved and self.size:
                    # Reserve disk space
                    fileobj.seek(self.size-1)
                    fileobj.write("\0")
                    fileobj.seek(0)
            elif os.path.isfile(path):
                # File exists, we test offset
                fsize = os.stat(path).st_size
                if fsize > self._offset:
                    # File is bigger than offset, we truncate to offset
                    fileobj = open(path, "rw+b")
                    fileobj.truncate(self._offset)
                    fileobj.seek(self._offset)
                elif fsize == self._offset:
                    # File size is exactly offset, resuming
                    fileobj = open(path, "ab")
                else:
                    # Unhandled case, seek to zero an retry
                    self.seek(0)
                    self.save(path)
                    return
            else:
                # Unhandled case, seek to zero an retry
                self.seek(0)
                self.save(path)
                return

            # Download and, if checksum is available, md5 feed
            if checksum:
                md5sum = hashlib.md5()
                for chunk in self:
                    md5sum.update(chunk)
                    fileobj.write(chunk)
            else:
                for chunk in self:
                    fileobj.write(chunk)
            # File sync and close
            fileobj.flush()
            os.fsync(fileobj.fileno())
            fileobj.close()
            fileobj = None # Prevents reclosing on error
            # Response close
            if self.response and hasattr(self.response, "closed") and not self.response.closed:
                self.response.close()
            # EOF not reached
            if not self.finished:
                raise RuntimeError, "Download failed, end of file not reached."
            # Connection fail
            if self.failed:
                raise RuntimeError, "Download failed, code %s" % self.code
            # File checksum
            if checksum:
                if base64.b64encode(md5sum.digest()) != checksum:
                    raise ValueError, "Integrity check failed with server checksum."
            # File size check
            elif self.size and self.size != os.stat(path).st_size:
                raise ValueError, "Size check failed."
        except BaseException as e:
            self._download_failed = True
            if hasattr(e, "message") and e.message:
                self._error_message = e.message
            elif hasattr(e, "errno"):
                self._error_message = errno_message(e.errno)
            logging.debug(e)
            # Closing fileobj
            if fileobj:
                fileobj.close()
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logging.debug("File %s removed." % path)
            except BaseException as e:
                logging.debug(e)

    def seek(self, v, whence=os.SEEK_SET):
        '''
        You should check for error code 416 after seek.
        '''
        if self.response:
            self.response.close()
        if v > 0:
            self._partial = True
            self._offset = v
            self.request.add_header("Range", "bytes=%d-" % v)
        elif self._partial:
            self._partial = False
            self._offset = 0
            del self.request.headers["Range"]
        self.retry()

    def tell(self):
        return self._offset

    def next(self):
        self.wait()
        if not self.closed:
            return "".join(self._getnbytes(self.buffsize))
        raise StopIteration

    def read_all(self):
        return "".join(self)

    def read(self, n=None):
        self.wait()
        if not self.failed:
            r = self.response.read(n)
            self._offset += len(r)
            return r
        return ""


class GeneratorFile(object):
    def __init__(self, generator):
        self._iterator = iter(generator)
        self._memory = ""
        self._position = 0
        self._exhausted = False

    def read(self, k=sys.maxint):
        nextpos = self._position + k

        if not self._exhausted:
            try:
                while len(self._memory) < nextpos:
                    self._memory += self._iterator.next()
            except StopIteration:
                self._exhausted = True

        old_pos = self._position
        self._position = min(self._position, nextpos)
        return self._memory[old_pos:k]

    def tell(self):
        return self._position

    def seek(self, pos, since=-1):
        pass

    def __iter__(self):
        self._position = 0
        lastline = self._memory

        while "\n" in lastline:
            r, lastline = lastline.split("\n", 1)
            self._position += len(r) + 1
            yield r + "\n"

        if not self._exhausted:
            for i in self._iterator:
                lastline += i
                while "\n" in lastline:
                    r, lastline = lastline.split("\n", 1)
                    self._position += len(r) + 1
                    yield r + "\n"
            self._exhausted = True
        yield lastline


class JSONEncoder_extra(json.JSONEncoder):
    """
    Like JSONEncoder but also serializes modules and all the rest (as "repr").
    """

    @classmethod
    def relativize_module_path(cls, path):
        "/usr/lib/python2.7/mymodule -> mymodule"
        for i in sys.path:
            if i and path.startswith(i+os.sep):  # found it!
                return path[len(i)+len(os.sep):]
        return path  # well, no luck relitivizing path, so return the full thing

    def default(self, o):
        try:
            return json.JSONEncoder.default(self, o)  # normal serialization
        except TypeError:  # serialize modules, and send a "repr" for the rest
            if isinstance(o, types.ModuleType) and hasattr(o, "__file__"):
                path = self.relativize_module_path(o.__file__)
                return u"<module '%s' from '%s'>" % (o.__name__, path)
            return repr(o)


class LoggerHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)

    def emit(self, record):
        exc = record.exc_info
        if exc: # exc defaults to (None, None, None)
            traceback.print_exception(*exc)
        #if record.msg:
        #    print >> sys.stderr, record.msg


class TaskPool(object):
    _emptydict = {}
    _value_unset = type("ValueUnsetType", (), {})
    _polling = 0.001
    _all_pools = []
    def __init__(self):
        '''
        Threadpool implementation using threads
        '''
        #
        self._all_pools.append(self) # We collect all pools for convenience

        self._event_pool = collections.deque()
        self._pool = []
        self._lock = threading.Lock()

    def parallelize(self, *tasks):
        '''
        Run given tasks as args (a task  should be a callable or tuple as
        (callable, args, kwargs)) parallelized (using threads).

        It's a good idea to put the (usually) longer task in first
        place, it will run in the main thread and will minimize idle
        time.

        Args:
            *tasks: tasks given as callable or tuple parameters as
                    as (callable, args, kwargs).

        Returns:
            list of returned values. If exception is raised, it will
            placed on this list instead of return value.
        '''
        # No tasks given test
        if not tasks:
            return ()

        # Recycle event object or create new one for result notification
        event = self._event_pool.popleft() if self._event_pool else threading.Event()

        # Result list initialization
        results = [self._value_unset for task in tasks]

        # Run tasks
        for n in xrange(1, len(tasks)):
            self._add_task(tasks[n], n, results, event)
        self._run_task(tasks[0], 0, results, event)

        # Wait for all values
        while self._value_unset in results:
            event.wait() # Wait for new result
            event.clear()

        self._event_pool.append(event) # Return event object

        return results

    def parallelize_iter(self, iterable):
        return self.parallelize(*iterable)

    @classmethod
    def _async_inner(cls, callback, args, kwargs, success, error):
        try:
            r = callback(*args, **kwargs)
            if callable(success):
                success(r)
        except BaseException as e:
            if callable(error):
                error(e)

    def async(self, callback, args=(), kwargs={}, success=None, error=None):
        task = (self._async_inner, (callback, args, kwargs, success, error))
        self._add_task(task)

    def _add_task(self, task, n=0, results=None, event=None):
        for t in self._pool:
            # Worker picking and run task
            if t.worker_task is None:
                with self._lock: # Double-check lock
                    if t.worker_task is None: # Double-check
                        t.worker_task = (task, n, results, event)
                        t.worker_semaphore.release() # hup worker
                        break
        else:
            # New worker initialization with task
            t = threading.Thread(target=self._worker)
            t.worker_semaphore = threading.Semaphore(0) # block on first acquire
            t.worker_loop = True
            t.worker_task = (task, n, results, event)
            t.start()
            self._pool.append(t)

    @classmethod
    def _worker(cls):
        t = threading.current_thread()
        while t.worker_loop:
            cls._run_task(*t.worker_task)
            t.worker_task = None
            t.worker_semaphore.acquire() # Hang loop until new task

    @classmethod
    def _run_task(cls, task, n, results, event):
        task = (task,) if callable(task) else task
        args = task[1] if len(task) > 1 else ()
        kwargs = task[2] if len(task) > 2 else cls._emptydict
        if results:
            try:
                results[n] = task[0](*args, **kwargs)
            except BaseException as e:
                results[n] = e
        else:
            try:
                task[0](*args, **kwargs)
            except BaseException as e:
                logging.exception(e)
        if event:
            event.set()

    @classmethod
    def clean_all(self):
        for pool in self._all_pools:
            for t in pool._pool:
                t.worker_loop = False
                t.worker_semaphore.release()
        for pool in self._all_pools:
            for t in pool._pool:
                t.join()
            pool._pool[:] = ()

    def clean(self, join=True):
        '''
        Clean all workers.
        '''
        for t in self._pool:
            t.worker_loop = False
            t.worker_semaphore.release()
        for t in self._pool:
            t.join()
        self._pool[:] = ()


class FileEater(threading.Thread):
    def __init__(self, f):
        threading.Thread.__init__(self)
        self._f = f
        self._b = ""
        self._v = collections.deque()
        self._l = threading.Lock()
        self._r = True
        self.daemon = True
        self.start()

    @property
    def value(self):
        with self._l:
            if self._v:
                self._b += "".join(self._v)
                self._v.clear()
        return self._b

    def __len__(self):
        return len(self._b) + len(self._v)

    def finish(self):
        self._r = False

    def run(self):
        try:
            s = self._f.read(1)
            while self._r and s:
                with self._l:
                    self._v.append(s)
                s = self._f.read(1)
        except:
            pass


class EventHandler(object):
    '''
    Object which allows registering and triggering events.

    This object allows to specify some events
    '''
    __handlers_cache = None
    @property
    def __handlers(self):
        ''' Event handlers dict, initialized ondemand '''
        if self.__handlers_cache is None:
            self.__handlers_cache = {}
        return self.__handlers_cache

    __reemits_cache = None
    @property
    def __reemits(self):
        '''
        Stored emits as dictionary of event names given to enable_reemit and
        its related emits as list or direct value (if last where False or True
        respectively).
        '''
        if self.__reemits_cache is None:
            self.__reemits_cache = {}
        return self.__reemits_cache

    def _blocked_enable_reemit(self, *args, **kwargs):
        '''
        enable_reemit is not longer available
        '''
        raise NotImplementedError, "Cannot call set_reemit_on before handler registering"

    __default_reemit = False
    __default_reemit_multi = False
    def enable_reemit(self, event_name=None, enable=True, lastonly=False):
        '''
        Last emit (or all of them if 'last' parameter is False) for given
        event_name is/are sent to related handler once registered if 'enable'
        parameter is True.

        If not event_name is given, reemit is enabled for all event names.

        This method is disabled once first handler is registered, so its a good
        idea use this functionality on __init__ of inherited classes.

        Params:
            event_name: optional, whose emits will be resent for new registers
                        If not given, configuration assumed for all events.
            enable: optional, boolean, enable or disable reemit behavior.
                    Defaults to True.
            lastonly: optional, reemit all emits if default, reemit only last
                      emit if True.
                      Defaults to False.
        '''
        if event_name is None:
            self.__default_reemit = enable
            self.__default_reemit_multi = not lastonly
        elif event_name in self.__reemits:
            if not enable:
                del self.__reemits[event_name]
        elif enable:
            self.__reemits[event_name] = (not lastonly, [])

    def cancel_reemit(self, event_name, *args):
        '''
        Given event name and arguments, remove matching stored emits.

        Params:
            event_name: event name
            *args: emit arguments
        '''
        if event_name in self.__reemits:
            multi, emits = self.__reemits[event_name]
            if args in emits:
                emits.remove(args)

    def on(self, event_name, handler=None):
        '''
        Register handler for given 'event_name'. If enable_reemit has been
        set for 'event_name', handler will be called immediatly with last or
        all past emits (depending in enable_reemit configuration).

        Note: enable_reemit is disabled before this method's first call.

        Params:
            event_name: event name or mapping with event name and handlers.
            handler: callable handler will be executed once event_name is
                     emited. If event_name is mapping, this is ignored.

        '''
        if not self.enable_reemit is self._blocked_enable_reemit:
            self.enable_reemit = self._blocked_enable_reemit

        if isinstance(event_name, collections.Mapping):
            for event_name, handler in event_name.iteritems():
                self.on(event_name, handler)
            return

        assert callable(handler), "Handler must be callable"

        # Save handler
        if event_name in self.__handlers:
            self.__handlers[event_name].append(handler)
        else:
            self.__handlers[event_name] = [handler]

        # Run old emits
        if event_name in self.__reemits:
            for args in self.__reemits[event_name][1]:
                handler(*args)

    def emit(self, event_name, *args):
        '''
        Call registered handlers for 'event_name' with given arguments.
        '''
        # Run handlers
        for handler in self.__handlers.get(event_name, ()):
            try:
                handler(*args)
            except BaseException as e:
                logging.exception(e)

        # Save emit
        if event_name in self.__reemits:
            is_multi, emits = self.__reemits[event_name]
            if is_multi or not emits:
                emits.append(args)
            else:
                emits[0] = args
        elif self.__default_reemit:
            self.__reemits[event_name] = (self.__default_reemit_multi, [args])


def make_hash_obj(obj):
    if hasattr(obj, "__hash__"):
        try:
            hash(obj) # hashing test
        except TypeError:
            if hasattr(obj, "__iter__"):
                return tuple(make_hash_obj(v) for v in obj)
            else:
                return repr(obj)
        return obj
    elif isinstance(obj, dict):
        return tuple((k, make_hash_obj(v)) for k, v in obj.iteritems())
    elif isinstance(obj, list):
        return tuple(make_hash_obj(i) for i in obj)
    elif isinstance(obj, set):
        return frozenset(obj)
    return repr(obj)

def hash_obj(obj):
    return hash(make_hash_obj(obj))

_taskpool = TaskPool()
def parallelize(*tasks):
    return _taskpool.parallelize(*tasks)

def parallelize_iter(tasks):
    return _taskpool.parallelize_iter(tasks)

def async(*args, **kwargs):
    _taskpool.async(*args, **kwargs)

def unix_to_win_version(version):
    if not "-" in version:
        return version
    major, minor = version.split("-", 1)
    if not "." in minor:
        minor_len = len(minor)
        prefix = ""
        if minor_len == 8:
            minor = minor[:4] + "." + minor[4:]
        else:
            minor = prefix + ".".join(minor[i:i+2] for i in xrange(0, minor_len, 2))
    return "%s.%s" % (major, minor)

def optimport(importable):
    try:
        return __import__(importable)
    except ImportError as e:
        logging.exception(e)
    return None


def sizeof_fmt(number, b1024=False, fmt="%.1f %s"):
    "sizeof_fmt(25331, b1024=True)  ->  '24.7 KiB'"

    if b1024:
        mult = 1024.0  # see https://en.wikipedia.org/wiki/Binary_prefix
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
    else:
        mult = 1000.0
        units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if number < 1000:  # so we have a maximum of 3 digits after the comma
            break
        number /= mult

    return locale.format_string(fmt, (number, unit))


def size_in(number, unit):
    "size_in(25331, 'KiB')  ->  24.7373046875"

    b1024_units = ["B", "KiB", "MiB", "GiB", "TiB"]
    units = ["B", "KB", "MB", "GB", "TB"]

    if unit in units:
        return float(number) / 1000**units.index(unit)
    else:
        return float(number) / 1024**b1024_units.index(unit)


used_ports = [None]
def choose_port():
    port = None
    while port in used_ports:
        testsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        testsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        testsocket.bind(('127.0.0.1', 0))
        port = testsocket.getsockname()[1]
        #testsocket.shutdown(socket.SHUT_RDWR) # unnecessary
        testsocket.close()
    used_ports.append(port)
    return port


def get_resource_data(path):
    try:
        if my_env.is_linux or my_env.is_frozen:
            with open(os.path.join(config.RESOURCESDIR, path), "rb") as res:
                data = res.read()
        else:
            data = pkg_resources.resource_string(__name__, path)
        return data
    except IOError as e:
        logging.exception(e)
    return None

def get_resource_stream(path):
    try:
        if my_env.is_linux or my_env.is_frozen:
            data = open(os.path.join(config.RESOURCESDIR, path), "rb")
        else:
            data = pkg_resources.resource_stream(__name__, path)
        return data
    except IOError  as e:
        logging.exception(e)
    return None

def get_resource_exists(path):
    if my_env.is_linux or my_env.is_frozen:
        return os.path.exists(os.path.join(config.RESOURCESDIR, path))
    return pkg_resources.resource_exists(__name__, path)

def get_resource_isdir(path):
    if my_env.is_linux or my_env.is_frozen:
        return os.path.isdir(os.path.join(config.RESOURCESDIR, path))
    return pkg_resources.resource_isdir(__name__, path)

if my_env.is_frozen:
    path = os.path.abspath(sys.path[0]) if sys.path else None

    # uses sys.executable if sys.path is not valid
    if not path or not os.path.exists(path):
        path = os.path.abspath(sys.executable)

    frozen_mtime = os.stat(path).st_mtime
else:
    frozen_mtime = 0

def get_resource_mtime(path):
    if frozen_mtime:
        return frozen_mtime
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    return os.stat(path).st_mtime


errno_dict = {
    "EPERM": "Operation not permitted",
    "ENOENT": "No such file or directory",
    "ESRCH": "No such process",
    "EINTR": "Interrupted system call",
    "EIO": "I/O error",
    "ENXIO": "No such device or address",
    "E2BIG": "Arg list too long",
    "ENOEXEC": "Exec format error",
    "EBADF": "Bad file number",
    "ECHILD": "No child processes",
    "EAGAIN": "Try again",
    "ENOMEM": "Out of memory",
    "EACCES": "Permission denied",
    "EFAULT": "Bad address",
    "ENOTBLK": "Block device required",
    "EBUSY": "Device or resource busy",
    "EEXIST": "File exists",
    "EXDEV": "Cross-device link",
    "ENODEV": "No such device",
    "ENOTDIR": "Not a directory",
    "EISDIR": "Is a directory",
    "EINVAL": "Invalid argument",
    "ENFILE": "File table overflow",
    "EMFILE": "Too many open files",
    "ENOTTY": "Not a typewriter",
    "ETXTBSY": "Text file busy",
    "EFBIG": "File too large",
    "ENOSPC": "No space left on device",
    "ESPIPE": "Illegal seek",
    "EROFS": "Read-only file system",
    "EMLINK": "Too many links",
    "EPIPE": "Broken pipe",
    "EDOM": "Math argument out of domain of func",
    "ERANGE": "Math result not representable",
    "EDEADLK": "Resource deadlock would occur",
    "ENAMETOOLONG": "File name too long",
    "ENOLCK": "No record locks available",
    "ENOSYS": "Function not implemented",
    "ENOTEMPTY": "Directory not empty",
    "ELOOP": "Too many symbolic links encountered",
    "EWOULDBLOCK": "Operation would block",
    "ENOMSG": "No message of desired type",
    "EIDRM": "Identifier removed",
    "ECHRNG": "Channel number out of range",
    "EL2NSYNC": "Level 2 not synchronized",
    "EL3HLT": "Level 3 halted",
    "EL3RST": "Level 3 reset",
    "ELNRNG": "Link number out of range",
    "EUNATCH": "Protocol driver not attached",
    "ENOCSI": "No CSI structure available",
    "EL2HLT": "Level 2 halted",
    "EBADE": "Invalid exchange",
    "EBADR": "Invalid request descriptor",
    "EXFULL": "Exchange full",
    "ENOANO": "No anode",
    "EBADRQC": "Invalid request code",
    "EBADSLT": "Invalid slot",
    "EDEADLOCK": "File locking deadlock error",
    "EBFONT": "Bad font file format",
    "ENOSTR": "Device not a stream",
    "ENODATA": "No data available",
    "ETIME": "Timer expired",
    "ENOSR": "Out of streams resources",
    "ENONET": "Machine is not on the network",
    "ENOPKG": "Package not installed",
    "EREMOTE": "Object is remote",
    "ENOLINK": "Link has been severed",
    "EADV": "Advertise error",
    "ESRMNT": "Srmount error",
    "ECOMM": "Communication error on send",
    "EPROTO": "Protocol error",
    "EMULTIHOP": "Multihop attempted",
    "EDOTDOT": "RFS specific error",
    "EBADMSG": "Not a data message",
    "EOVERFLOW": "Value too large for defined data type",
    "ENOTUNIQ": "Name not unique on network",
    "EBADFD": "File descriptor in bad state",
    "EREMCHG": "Remote address changed",
    "ELIBACC": "Can not access a needed shared library",
    "ELIBBAD": "Accessing a corrupted shared library",
    "ELIBSCN": ".lib section in a.out corrupted",
    "ELIBMAX": "Attempting to link in too many shared libraries",
    "ELIBEXEC": "Cannot exec a shared library directly",
    "EILSEQ": "Illegal byte sequence",
    "ERESTART": "Interrupted system call should be restarted",
    "ESTRPIPE": "Streams pipe error",
    "EUSERS": "Too many users",
    "ENOTSOCK": "Socket operation on non-socket",
    "EDESTADDRREQ": "Destination address required",
    "EMSGSIZE": "Message too long",
    "EPROTOTYPE": "Protocol wrong type for socket",
    "ENOPROTOOPT": "Protocol not available",
    "EPROTONOSUPPORT": "Protocol not supported",
    "ESOCKTNOSUPPORT": "Socket type not supported",
    "EOPNOTSUPP": "Operation not supported on transport endpoint",
    "EPFNOSUPPORT": "Protocol family not supported",
    "EAFNOSUPPORT": "Address family not supported by protocol",
    "EADDRINUSE": "Address already in use",
    "EADDRNOTAVAIL": "Cannot assign requested address",
    "ENETDOWN": "Network is down",
    "ENETUNREACH": "Network is unreachable",
    "ENETRESET": "Network dropped connection because of reset",
    "ECONNABORTED": "Software caused connection abort",
    "ECONNRESET": "Connection reset by peer",
    "ENOBUFS": "No buffer space available",
    "EISCONN": "Transport endpoint is already connected",
    "ENOTCONN": "Transport endpoint is not connected",
    "ESHUTDOWN": "Cannot send after transport endpoint shutdown",
    "ETOOMANYREFS": "Too many references: cannot splice",
    "ETIMEDOUT": "Connection timed out",
    "ECONNREFUSED": "Connection refused",
    "EHOSTDOWN": "Host is down",
    "EHOSTUNREACH": "No route to host",
    "EALREADY": "Operation already in progress",
    "EINPROGRESS": "Operation now in progress",
    "ESTALE": "Stale NFS file handle",
    "EUCLEAN": "Structure needs cleaning",
    "ENOTNAM": "Not a XENIX named type file",
    "ENAVAIL": "No XENIX semaphores available",
    "EISNAM": "Is a named type file",
    "EREMOTEIO": "Remote I/O error",
    "EDQUOT": "Quota exceeded",
    }
def errno_message(errno_code):
    "Return a descriptive message of the error errno_code"
    try:
        return errno_dict[errno.errorcode[errno_code]]
    except KeyError:
        return "Error code %s" % errno_code


_ = lambda x: x  # so xgettext gets the units
time_fmt_steps = [
    (60, _("second"), _("seconds")),
    (60, _("minute"), _("minutes")),
    (24, _("hour"), _("hours")),
    (30.4, _("day"), _("days")),
    (12, _("month"), _("months")),
    (10, _("year"), _("years")),
    (10, _("decade"), _("decades")),
    (1000, _("century"), _("centuries"))]
def time_fmt(t):
    "234  ->  [(3, 'minutes'), (54, 'seconds')]"
    result = []
    for div,singular,plural in time_fmt_steps:
        if t < div:
            result.append( (int(t), (plural if int(t) != 1 else singular)) )
            break
        remaining = int(t % div)
        result.append( (remaining, (plural if remaining != 1 else singular)) )
        t /= div
    return result[::-1]

def time_fmt_hms(seconds, components=2):
    "234344  ->  '65:05:44'"
    seconds = int(seconds)
    r = []
    while seconds and len(r) < 2:
        r.append(seconds % 60)
        seconds = seconds/60
    if seconds:
        r.append(seconds)
    r.extend(0 for i in xrange(len(r), components))
    r = ":".join("%02d" % i for i in reversed(r))
    if r[0] == "0":
        return r[1:]
    return r


_last_output_memory = {}
_last_output_memory_size = 0
_omlogger = logging.getLogger("%s.output_memory" % __name__)
def output_memory():
    global _last_output_memory, _last_output_memory_size
    d = collections.defaultdict(int)
    size = 0
    dead_objs = collections.defaultdict(int)

    for o in gc.get_objects():
        if isinstance(o, wx._core._wxPyDeadObject):
            for ref in gc.get_referrers():
                dead_objs[type(ref).__name__] += 1
        d[type(o).__name__] += 1
        size += sys.getsizeof(o)
    items = "\n    ".join(
        "%s: %s" % (
            k, "%s%d" % (
                "+" if v > _last_output_memory[k] else "-",
                abs(v - _last_output_memory[k])
                ) if k in _last_output_memory else v)
        for k, v in itertools.islice(sorted(d.iteritems(), key=operator.itemgetter(1), reverse=True), 0, 25)
        if _last_output_memory.get(k, 0) != v
        )
    if items:
        if not _last_output_memory:
            items += "\n    ..."
        items += "\nGC count %d / %d / %d" % gc.get_count()
        _omlogger.debug("%s are being used. Incremental changed on most "
                        "frequent objects:\n    %s" % (sizeof_fmt(size), items))
        _last_output_memory.update(d)
    elif size != _last_output_memory_size:
        _omlogger.debug("%s bytes are being used." % (size, ))
    _last_output_memory_size = size

def filter_exceptions(exception_or_exceptions, exception_return, call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except exception_or_exceptions:
        return exception_return

def image_format(data):
    if data.startswith("\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"): return "png"
    elif data.startswith("\x49\x49\x2A"): return "tiff"
    elif data.startswith("\x42\x4D"): return "bmp"
    elif data.startswith("\x47\x49\x46"): return "gif"
    elif data.startswith("\x00\x00\x00\x0C\x6A\x50\x20\x20\0D\x0A"): return "jp2"
    elif data.startswith("\xFF\xD8\xFF"): return "jpg"
    return None

image_format_to_bitmap_type = {
    "png": wx.BITMAP_TYPE_PNG,
    "tiff": wx.BITMAP_TYPE_TIFF,
    "bmp": wx.BITMAP_TYPE_BMP,
    "gif": wx.BITMAP_TYPE_GIF,
    "jp2": wx.BITMAP_TYPE_JPEG,
    "jpg": wx.BITMAP_TYPE_JPEG,
    }
def image_type(data):
    return image_format_to_bitmap_type[image_format(data)]

def image_size(data):
    try:
        strio = StringIO.StringIO(data)
        image = wx.ImageFromStream(strio, type=image_type(data), index=-1)
        size = tuple(image.GetSize())
        image.Destroy()
        return size
    except IndexError:  # could not find image type
        return (0, 0)
    except BaseException as e:
        logging.debug(e)
    return (0, 0)

'''
import cProfile
def profileit(name):
    def inner(func):
        def wrapper(*args, **kwargs):
            prof = cProfile.Profile()
            retval = prof.runcall(func, *args, **kwargs)
            prof.dump_stats(name)
            return retval
        return wrapper
    return inner
'''

if __name__ == "__main__":
    import doctest
    doctest.testmod()

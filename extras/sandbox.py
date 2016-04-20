#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''

Sandbox

Restrictions:
    - Cannot modify foreign objects.
    - Cannot access __double-underscored__ attributes (except __name__ and
      __doc__)
    - Cannot access _underscored_ attributes of non-sandbox objects.
    - Modules with less symbols:
        sys, os
        simplejson
    - Full modules:
        math, random
    - Old style python classes read-only (by RestrictedPython)
    -

'''
import os
import sys
import types
import logging
import functools
import zipfile
import __builtin__

from RestrictedPython import compile_restricted
from RestrictedPython.Guards import safe_builtins
from RestrictedPython.PrintCollector import PrintCollector
from RestrictedPython.RestrictionMutator import RestrictionMutator

import my_env

# mokeypatch checkName amd checkAttrName
old_check_name = RestrictionMutator.checkName
old_check_attr = RestrictionMutator.checkAttrName

underscore_whitelist = {"__name__", "__doc__", "__import__"}
underscore_blacklist = {"__module__"}

def new_check_name(self, node, name):
    if name in underscore_blacklist:
        old_check_name(self, node, name)
def new_check_attr(self, node):
    name = node.attrname
    if name in underscore_blacklist:
        old_check_attr(self, node)
RestrictionMutator.checkName = new_check_name
RestrictionMutator.checkAttrName = new_check_attr

logger = logging.getLogger(__name__)

def wrapped_getattribute(self, base, exceptions, k):
    if k in exceptions:
        return dict.__getattribute__(self, k)
    return getattr(base, k)

def wrapped_function(fnc, before=None, after=None):
    @functools.wraps(fnc)
    def wrapped(*args, **kwargs):
        if before:
            before()
        r = fnc(*args, **kwargs)
        if after:
            after()
        return r
    return wrapped

class LocalObject(object):
    pass


class ForeignObject(object):
    pass


class SandboxError(RuntimeError):
    pass


class ModuleGuard(object):
    def __init__(self, base_module):
        if not isinstance(base_module, basestring):
            base_module = base_module.__name__
        self._base = base_module
        self._prefix = base_module + "."

    def _analyze(self, obj):
        cls = obj if isinstance(obj, (type, types.ClassType)) else getattr(obj, "__class__", None)
        obj = None if cls is obj else obj
        return cls, obj

    def _check_local(self, cls, obj):
        if isinstance(obj, (ForeignObject, LocalObject)):
            # ForeignObject instances (see RestrictedModule)
            return True
        if hasattr(cls, "__mro__") and any(i is LocalObject for i in cls.__mro__):
            # New style classes created inside sandbox inherite from LocalObject
            return True
        if hasattr(cls, "__module__") and (cls.__module__ == self._base or cls.__module__.startswith(self._prefix)):
            # Classes declared inside sandbox has __module__ to sandbox __name__
            return True
        return False


class WriteGuard(ModuleGuard):
    def __call__(self, o):
        cls, obj = self._analyze(o)
        if self._check_local(cls, obj):
            return o
        if isinstance(o, (dict, list, set, slice)):
            return o
        raise AttributeError, "cannot set attributes in object %r" % cls


class GetAttrGuard(ModuleGuard):
    def __call__(self, o, k):
        if k in underscore_blacklist:
            raise SandboxError, "%r property access is blocked on sandboxed mode" % k
        if not k.startswith("_") or k in underscore_whitelist:
            return getattr(o, k)
        cls, obj = self._analyze(o)
        if self._check_local(cls, obj):
            return getattr(o, k)
        raise AttributeError, "%r object has no attribute %r" % (cls, k)


class RestrictedModule(object):
    '''
    Base restricted module
    '''
    __module_cache = {}

    def __init__(self):
        raise NotImplemented

    @staticmethod
    def _wrap(obj):
        try:
            if isinstance(obj, types.ClassType):
                return type(obj.__name__, (obj, ForeignObject), {"__doc__": obj.__doc__})
            if isinstance(obj, types.TypeType) and object in obj.__bases__:
                return type(obj.__name__, (obj, ForeignObject), {"__doc__": obj.__doc__})
        except BaseException as e:
            logging.debug(e)
        try:
            if callable(obj):
                @functools.wraps(obj)
                def wrapped(self, *args, **kwargs):
                    return obj(*args, **kwargs)
        except BaseException as e:
            logging.debug(e)
        return obj

    @staticmethod
    def _init(self):
        types.ModuleType.__init__(self, self.__class__.__name__, self.__class__.__doc__)

    @classmethod
    def empty(cls, module_name):
        return types.ModuleType(module_name, "%s module" % module_name)

    @classmethod
    def create(cls, module_name, symbols=None):
        if module_name in cls.__module_cache:
            return cls.__module_cache[module_name]

        # Symbols dict means virtual module
        if isinstance(symbols, dict):
            # Initialization
            restricted_module = types.ModuleType(module_name, "%s module" % module_name)
            restricted_module.__dict__.update((k, cls._wrap(v)) for k, v in symbols.iteritems())
            return restricted_module

        # Get module
        if not module_name in sys.modules:
            __import__(module_name)
        module = sys.modules[module_name]

        # Default symbols
        if symbols is None:
            symbols = [i for i in dir(module) if not i.startswith("_")]

        # Create new module object
        restricted_module = types.ModuleType(module.__name__, module.__doc__)
        restricted_module.__dict__.update(
            (symbol, cls._wrap(getattr(module, symbol)))
            for symbol in symbols
            if hasattr(module, symbol)
            )
        if hasattr(module, "__file__"):
            restricted_module.__file__ = module.__file__
        if hasattr(module, "__path__"):
            restricted_module.__path__ = module.__path__
        if hasattr(module, "__package__"):
            restricted_module.__package__ = module.__package__
        cls.__module_cache[module_name] = restricted_module
        return restricted_module

    @classmethod
    def factory(cls, module, symbols=None):
        '''
        Get a function which returns a restricted module when called with
        no arguments.

        Args:
            module: module name or module object where symbols are located
            symbols: iterable of whitelisted symbols will be proxied to module

        Returns:
            factory function which returns a restricted module object

        '''
        module_name = module if isinstance(module, basestring) else module.__name__

        # Save symbols for deferred initialization
        wrapper = functools.partial(cls.create, module_name, symbols)
        wrapper.__name__ = module_name
        wrapper.__doc__ = "%r import wrapper for %r" % (cls, module_name)
        return wrapper


class Sandbox(object):
    '''
    Untrusted code sandbox
    '''
    _default = type("DefaultValue", (), {})
    _builtins = dict(safe_builtins)
    _builtins.update(
        (i, getattr(__builtin__, i)) for i in (
            'bytearray', 'all', 'set', 'help', 'vars', 'reduce', 'coerce',
            'intern', 'enumerate', 'memoryview', 'apply', 'any', 'locals',
            'quit', 'slice', 'copyright', 'min', 'sum', 'next', 'list',
            'getattr', 'exit', 'hasattr', 'dict', 'type', 'NotImplemented',
            'bin', 'map', 'format', 'buffer', 'max', 'reversed', 'credits',
            'frozenset', 'sorted', 'super', 'license', 'classmethod',
            'bytes', 'iter', 'filter', 'staticmethod', 'property', 'dir',
            'Ellipsis'
            )
        if hasattr(__builtin__, i)
        )

    _modules = [
        # Safe modules
        "math",
        "random",

        # Import modules with restricted keys
        ("sys", (
            "api_version", "copyright", "exc_clear", "exc_info", "exc_type",
            "excepthook", "exec_prefix", "getdefaultencoding", "getfilesystemencoding",
            "getrecursionlimit", "getrefcount", "getsizeof", "getwindowsversion",
            "hexversion", "long_info", "maxint", "maxsize", "maxunicode", "path",
            "platform", "prefix", "subversion", "version", "version_info", "winver")
            ),
        ("os", ("name", "devnull", "sep", "linesep")),
        ("simplejson", ("dumps", "loads")),

        # Test
        ("sandbox_test", {
            "NewClass": type("NewClass", (object,), {}),
            "OldClass": type("OldClass", (), {}),
            "instance": type("InstanceClass", (object,), {})(),
            }),

        # TODO(felipe): Logging
        ]
    _module_importers = dict(
        (i, RestrictedModule.factory(i)) if isinstance(i, basestring) else (i[0], RestrictedModule.factory(*i))
        for i in _modules
        )
    @classmethod
    def pyfiles_on_tree(self, path):
        '''
        Get all .py files recursively on given directory path

        Yields:
            Tuple pair with slash separated relative path and source as basestring.
        '''
        psize = len(path)+1
        walked = {path}
        pending = [path]
        while pending:
            folder = pending.pop()
            for path in os.listdir(folder):
                path = os.path.join(folder, path)
                rpath = os.path.realpath(path)
                if os.path.isdir(rpath):
                    if not rpath in walked:
                        pending.append(path)
                        walked.add(rpath)
                    continue
                elif path.endswith(".py"):
                    with open(path, "r") as f:
                        data = f.read()
                        yield path[psize:].replace(os.sep, "/"), data


    @classmethod
    def pyfiles_on_zipfile(self, path):
        '''
        Get all .py files recursively on given zipfile path

        Yields:
            Tuple pair with slash separated relative path and source as basestring.
        '''
        with zipfile.ZipFile(path) as zp:
            for info in zp.infolist():
                if info.filename.endswith(".py"):
                    yield info.filename.replace(os.sep, "/"), zp.read(info)

    @classmethod
    def _getitem_(cls, obj, k):
        return obj.__getitem__(k)

    @classmethod
    def _banned_fnc(cls, name, *args, **kwargs):
        '''
        Sometimes we need unusable but importable callables. This is a dummy
        object which raises SandboxError if called.
        Callable name must be provided for propper error description (you can
        use lambda or functools.partial).

        Arguments:
            name: function name
            *args
            **kargs
        '''
        raise SandboxError, "function %r is disabled on sandboxed mode" % name

    @classmethod
    def _import(cls, logger, base, cache, *args, **kwargs):
        '''
        Sandbox import functionality

        '''
        module = args[0]
        if module:
            if module[0] == ".":
                if base is None:
                    raise ImportError, "ValueError: Attempted relative import in non-package"
                module = base if module == "." else base + module
        elif base is None:
            raise ImportError, "ValueError: Attempted relative import in non-package"
        else:
            module = base

        if module in cache:
            obj = cache[module]
            if isinstance(obj, basestring):
                cache[module] = RestrictedModule.empty(module)
                symbols = cls.run(source=obj, logger=logger, base=module, reraise=True, import_cache=cache)
                obj = cache[module]
                obj.__dict__.update(symbols)
        elif module in cls._module_importers:
            obj = cls._module_importers[module]()
            cache[module] = obj
        else:
            raise ImportError, "No module named %r" % args[0]

        if "." in module:
            # Return grandpa module (it's __import__ behavior)
            parent = cls._import(logger, base, cache, module[:module.rfind(".")])
            setattr(parent, module[module.rfind(".")+1:], obj)
            return parent
        return obj


    @classmethod
    def load(cls, module, path, logger=_default, reraise=False, import_cache=None):
        '''
        Load python module in sandboxed mode.

        Args:
            module:  module name
            path:    module path
            logger:  optional logger for logging messages. Defaults to module
                     logger if reraise is False.
            reraise: optional, raise sandbox exceptions outside sandbox,
                     defaults to False.
            import_cache: cache of module objects as dictionary. You can use
                          RestrictedModule methods for creating safe module
                          objects or basestrings (will be evaluated on demand).

        Returns:
            Public global variables as dict (those in __all__ or all globals).
        '''
        if logger is cls._default:
            logger = None if reraise else globals()["logger"]

        try:
            if os.path.isfile(path):
                files = cls.pyfiles_on_zipfile(path)
            else:
                files = cls.pyfiles_on_tree(path)
        except (OSError, IOError, zipfile.BadZipfile):
            raise ValueError, "Given path must refer to valid zipfile or directory"

        # {name: source} module dictionary
        sources = {
            filename[:-11 if filename.endswith("__init__.py") else -3] \
                .strip("/").replace("/", "."): source
            for filename, source in files
            }

        # No sources found error
        if not module in sources:
            return {}

        # Import cache update
        if import_cache:
            cache = dict(import_cache)
            cache.update(sources)
        else:
            cache = sources

        # Source sandoxed execution
        try:
            return cls.run(sources[module], logger=None, base=module, reraise=reraise or bool(logger), import_cache=cache)
        except BaseException as e:
            if logger:
                logger.exception(e)
            if reraise:
                raise
        return {}


    _env_cache = None
    @classmethod
    def run(cls, source=None, code=None, logger=_default, base="__sandbox__", reraise=False, import_cache=None):
        '''
        Run source str or compiled code in sandbox.

        Args:
            source:  optional source code as string.
            code:    optional python code as code object, this overrides source.
            logger:  optional logger for logging messages. Defaults to module
                     logger if reraise is False.
            base:    optional __name__ variable value, defaults to __sandbox__.
            reraise: optional, raise sandbox exceptions outside sandbox,
                     defaults to False
            import_cache: cache of module objects as dictionary. You can use
                          RestrictedModule methods for creating safe module
                          objects or basestrings (will be evaluated on demand).

        Returns:
            Public global variables as dict (those in __all__ or all globals).
        '''
        if logger is cls._default:
            logger = None if reraise else globals()["logger"]

        error = None
        try:
            # Initialize sandbox scope
            if cls._env_cache is None:
                cls._builtins.update((
                    ("__import__", None),
                    ("__name__", base),
                    ("__package__", None),
                    ("__doc__", None),
                    ("globals", globals),
                    ("locals", locals),
                    ("compile", wrapped_function(compile, cls._banned_fnc)),
                    ("file", wrapped_function(file, cls._banned_fnc)),
                    ("open", wrapped_function(open, cls._banned_fnc)),
                    ("execfile", wrapped_function(execfile, cls._banned_fnc)),
                    ("eval",  wrapped_function(eval, cls._banned_fnc)),
                    ("input",  wrapped_function(input, cls._banned_fnc)),
                    ("raw_input",  wrapped_function(raw_input, cls._banned_fnc)),
                    ("reload",  wrapped_function(reload, cls._banned_fnc)),
                    ("object", LocalObject),
                    ("_", None),
                    ))
                cls._env_cache = {
                    "_print_": None,
                    "_write_": None,
                    "_getattr_": None,
                    "_getitem_": cls._getitem_,
                    "__builtins__": cls._builtins
                    }

            print_collector = PrintCollector()
            import_cache = {} if import_cache is None else import_cache
            import_fnc = functools.partial(cls._import, logger, None if base == "__sandbox__" else base, import_cache)

            # Local env values
            env = dict(cls._env_cache)
            env["__builtins__"] = dict(env["__builtins__"])
            env["__builtins__"]["__import__"] = import_fnc

            import_cache["__builtin__"] = RestrictedModule.create("__builtin__", env["__builtins__"])

            env["_print_"] = lambda: print_collector
            env["_write_"] = WriteGuard(base)
            env["_getattr_"] = GetAttrGuard(base)

            # Compile source if not code is given
            if code is None:
                code = compile_restricted(source, '<string>', 'exec')

            # Run code in sandbox
            try:
                exec code in env
            except SystemExit as e:
                if logger:
                    logger.debug("Exited with return code %d" % (e.args[0] if e.args else 0, ))
                error = e
            except (BaseException, RuntimeError) as e:
                if logger:
                    logger.exception(e)
                error = e
            # Print as debug
            out = print_collector()
            if out and logger:
                logger.debug("printed %r" % out)
        except BaseException as e:
            if logger:
                logger.exception(e)
            error = e

        # Reraise
        if error and reraise:
            raise error

        # Return globals
        if "__all__" in env:
            return {k: env[k] for k in env["__all__"]}
        return {k: v for k, v in env.iteritems() if not k in cls._env_cache}


if __name__ == "__main__":
    # Sandbox testing
    test_list = [
        ("restrict modules",
            '''
            # coding: rot_13
            # Obfuscated code
            vzcbeg flf
            cevag flf
            cevag flf.fgqbhg
            ''', False),
        ("block old class edits",
            '''
            class A:
                pass
            A.b = 1
            ''', False),
        ("block foreign modification",
            '''
            import sandbox_test
            sandbox_test.instance.a = 1
            ''', False),
        ("block exec statement",
            '''
            exec "print hello"
            ''', False),
        ("block relative import on non-package",
            '''
            from . import *
            ''', False),
        ("allow new class edits",
            '''
            class A(object):
                pass
            A.b = 1
            ''', True),
        ("allow instance edits",
            '''
            class A:
                pass
            a = A()
            a.b = 1
            ''', True),
        ("allow instance of foreign class edits",
            '''
            import sandbox_test

            instance = sandbox_test.NewClass()
            instance.a = 1
            ''', True),
        ("assert sandbox's hacked os is restricted os",
            '''
            import os
            assert __builtins__['X19pbXBvcnRfXw=='.decode('base64')]('b3M='.decode('base64')) is os
            ''', True),
        ("assert builtin module works",
            '''
            import __builtin__
            assert __builtin__.dir is dir, "Mangled dir"
            assert __builtin__.__import__ is __import__, "Mangled __import__"
            ''', True),
        ("assert absolute and relative imports works", {
            "test/__init__.py": '''
                import test.imported
                assert test.imported.brb, "Failed"

                from . import imported
                assert imported is test.imported, "Failed asserting relative is the same that absolute import"
                ''',
            "test/imported/__init__.py": '''
                brb = True
                '''
            }, True),
        ("assert ImportError is not propagated", {
            "test/__init__.py": '''
                import notexisting.module
                ''',
            }, False),
        ]

    import tempfile, shutil, traceback

    def fix_indent(src):
        indent = min(
            len(line) - len(line.lstrip())
            for line in src.strip("\n").splitlines()
            if line.strip() and not line.lstrip()[0] == "#"
            )
        return src.replace("\n" + " " * indent, "\n")

    if my_env.is_windows:
        import ctypes, struct

        # Constants from the Windows API
        STD_OUTPUT_HANDLE = -11
        FOREGROUND_GREEN  = 0x0002
        FOREGROUND_RED    = 0x0004 # text color contains red

        # Based on IPython's winconsole.py, written by Alexander Belchenko
        handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        csbi = ctypes.create_string_buffer(22)
        res = ctypes.windll.kernel32.GetConsoleScreenBufferInfo(handle, csbi)
        assert res, "ctypes.windll.kernel32.GetConsoleScreenBufferInfo failed"
        reset = struct.unpack("hhhhHhhhhhh", csbi.raw)[4]

        def console_color(ok, text):
            ctypes.windll.kernel32.SetConsoleTextAttribute(handle, FOREGROUND_GREEN if ok else FOREGROUND_RED)
            sys.stdout.write(text)
            sys.stdout.flush()
            ctypes.windll.kernel32.SetConsoleTextAttribute(handle, reset)

    else:
        FOREGROUND_GREEN = "\x1b[32;01m"
        FOREGROUND_RED = "\x1b[31;01m"
        FOREGROUND_RESET = "\x1b[0m"

        def console_color(ok, text):
            sys.stdout.write(FOREGROUND_GREEN if ok else FOREGROUND_RED)
            sys.stdout.write(text)
            sys.stdout.write(FOREGROUND_RESET)

    logger = logging.getLogger()
    logging.basicConfig(
        format = "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt = "%Y.%m.%d %H.%M.%S"
        )

    print "Unit test"
    ok_message     = "  OK  "
    failed_message = "FAILED"
    testdir = tempfile.mkdtemp()
    for name, src, should_work in test_list:
        if isinstance(src, basestring):
            # Test basic script
            try:
                Sandbox.run(fix_indent(src), reraise=True)
            except (BaseException, RuntimeError) as e:
                msg = failed_message if should_work else ok_message
            else:
                msg = ok_message if should_work else failed_message
        else:
            # Test basic module hierarchy
            starting_point = None
            for path, source in src.iteritems():
                path = os.path.join(testdir, path)
                if starting_point is None or len(path) < len(starting_point):
                    starting_point = path
                dirname = os.path.dirname(path)
                if not os.path.exists(dirname):
                    os.makedirs(dirname)
                with open(path, "w") as f:
                    f.write(fix_indent(source))

            if starting_point.endswith("__init__.py"):
                starting_point = os.path.dirname(starting_point)

            import_name = os.path.basename(starting_point[:-3] if starting_point.endswith(".py") else starting_point)
            sys_path = os.path.dirname(starting_point)

            try:
                Sandbox.load(import_name, sys_path, reraise=True)
            except (BaseException, RuntimeError) as e:
                msg = failed_message if should_work else ok_message
            else:
                msg = ok_message if should_work else failed_message
            shutil.rmtree(sys_path)

        print "    {0: <64s} [ ".format(name),
        console_color(msg == ok_message, msg)
        print " ]"
        if msg == failed_message:
            if should_work:
                traceback.print_exc()
            else:
                print "No exception raised"

    assert not os.path.isdir(testdir), "testdir leaved"


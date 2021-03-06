import os
import sys
import inspect
import tempfile
import shutil
import functools

if sys.version_info >= (3, 4):
    from importlib import import_module, reload
else:
    from importlib import import_module


class SerializableFunc:
    """Makes a function independent from its source file.

    This decorator alters the serialization hook so that unpickling the
    pickled function will import a back-up of the original source code.

    .. warning::
        This is a hackish solution where only the source file
        containing the function is saved, regenerated and reloaded.
        Use with care.
    """
    def __init__(self, func):
        if isinstance(func, SerializableFunc):
            self.name = func.name
            self.source = func.source
            self.func = func.func
        else:
            self.name = func.__name__
            with open(inspect.getsourcefile(func)) as dump_file:
                self.source = dump_file.read()
            self.func = func
            functools.update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    def __getstate__(self):
        return self.source, self.name

    def __setstate__(self, state):
        self.source, self.name = state

        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "module.py"), 'w') as dump_file:
                dump_file.write(self.source)

            sys.path.insert(0, tmpdir)
            module = import_module("module")
            module = reload(module)
            self.func = getattr(module, self.name)
            sys.path.pop(0)

        finally:
            shutil.rmtree(tmpdir)

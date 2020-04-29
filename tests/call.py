from pathlib import Path
from collections.abc import Iterable

import os
import random
import re
import subprocess
import sys
import time


SUBPROCESS_CALL = subprocess.call
DEFAULT = object()


def one_arg(args, kwargs):
    return not kwargs and len(args) == 1 and callable(args[0])


# apply decorator_factory if cond is True on args
def _make_conditional_d(decorator_factory):
    def df(*df_args, cond=None, inverse=False, **df_kwargs):
        if cond is None:
            cond = lambda x: True  # noqa E731

        def decorator(prog):
            def f(args):
                if cond(args) != inverse:
                    return decorator_factory(*df_args, **df_kwargs)(prog)(args)
                else:
                    return prog(args)
            return f
        return decorator
    return df


def _decorator_add_factory_d(decorator):
    def df(*df_args, **df_kwargs):
        if one_arg(df_args, df_kwargs):
            return decorator(df_args[0])
        else:
            def d(f):
                return decorator(f)
            return d
    return df


def _factory_add_decorator_df(*dff_args, **dff_kwargs):
    def dff(decorator_factory):
        def df(*df_args, **df_kwargs):
            if one_arg(df_args, df_kwargs):
                return decorator_factory(*dff_args, **dff_kwargs)(df_args[0])
            else:
                def df1(d):
                    if df_args:
                        args = df_args
                    else:
                        args = dff_args
                    kwargs = dff_kwargs.copy()
                    kwargs.update(df_kwargs)
                    return decorator_factory(*args, **kwargs)(d)
                return df1
        return df
    return dff


@_factory_add_decorator_df()
@_make_conditional_d
@_decorator_add_factory_d
def print_d(func):
    def f(*args, **kwargs):
        sargs = list(args)
        sargs.extend(f'{k}={v}' for k, v in kwargs.items())
        print(f'{func.__name__}({sargs})', file=sys.stdout)
        return func(*args)
    return f


@_factory_add_decorator_df()
@_make_conditional_d
@_decorator_add_factory_d
def nop_d(func):
    def f(*args, **kwargs):
        pass
    return f


@_make_conditional_d
def before_d(func_before, *fb_args, **fb_kwargs):
    def d(func):
        def f(*args, **kwargs):
            func_before(*fb_args, **fb_kwargs)
            return func(*args, **kwargs)
        return f
    return d


@_make_conditional_d
def after_d(func_after, *fa_args, save_rc=True, **fa_kwargs):
    def d(func):
        def f(*args, **kwargs):
            old_rc = func(*args, **kwargs)
            new_rc = func_after(*fa_args, **fa_kwargs)
            if save_rc:
                return old_rc
            else:
                return new_rc
        return f
    return d


@_factory_add_decorator_df(1)
@_make_conditional_d
def sleep_d(s):
    def d(func):
        def f(*args, **kwargs):
            time.sleep(s)
            return func(*args, **kwargs)
        return f
    return d


@_factory_add_decorator_df(1)
@_make_conditional_d
def return_d(rc):
    def d(func):
        def f(*args, **kwargs):
            func(*args, **kwargs)
            return rc
        return f
    return d


def error_call(args):
    raise Exception(f'Not implemened call for `{args}`')


def git(args):
    if args[1] == 'clone':
        target = Path(args[3])
        os.makedirs(target)
        if target.name == 'mkimage-profiles':
            os.makedirs(target / 'conf.d')
            os.makedirs(target / 'features.in/build-ve/image-scripts.d')
    else:
        error_call(args)
    return 0


def make(args):
    for arg in args:
        if arg.startswith('IMAGE_OUTDIR='):
            out_dir = Path(arg.lstrip('IMAGE_OUTDIR='))
        if arg.startswith('ARCH='):
            arch = Path(arg.lstrip('ARCH='))

    match = re.match(r'.*/([-\w]*)\.(.*)', args[-1])
    target, kind = match.groups()
    image = out_dir / f'{target}-{arch}.{kind}'
    image.write_bytes(
        bytes(random.randint(0, 255) for x in range(random.randint(32, 128)))
    )

    return 0


def gpg(args):
    Path(f'{args[-1]}.asc').touch()
    return 0


def rsync(args):
    return SUBPROCESS_CALL(args, stdout=subprocess.DEVNULL)


def decorate(decorators, func):
    for decorator in reversed(decorators):
        func = decorator(func)
    return func


class Call():
    def __init__(self, progs=None, decorators=None):
        self.progs = {
            'git': git,
            'make': make,
            'gpg2': gpg,
            'rsync': rsync,
            DEFAULT: error_call,
        }

        if progs is not None:
            self.progs.update(progs)

        if decorators is None:
            decorators = {}
        self.decorators = decorators

    def __call__(self, args):
        rc = None
        prog = args[0]
        func = self.progs.get(prog, DEFAULT)
        decorators = self.decorators.get(prog, [])
        if not isinstance(decorators, Iterable):
            decorators = [decorators]
        rc = decorate(decorators, func)(args)
        return rc

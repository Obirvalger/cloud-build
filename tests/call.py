from pathlib import Path

import datetime
import os
import random
import re
import subprocess


SUBPROCESS_CALL = subprocess.call
DEFAULT = object()


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
    date = datetime.date.today().strftime('%Y%m%d')
    image = out_dir / f'{target}-{date}-{arch}.{kind}'
    image.write_bytes(
        bytes(random.randint(0, 255) for x in range(random.randint(32, 128)))
    )

    return 0


def gpg(args):
    Path(f'{args[-1]}.asc').touch()
    return 0


def rsync(args):
    return SUBPROCESS_CALL(args, stdout=subprocess.DEVNULL)


class Call():
    def __init__(self, progs=None):
        self.progs = {
            'git': git,
            'make': make,
            'gpg2': gpg,
            'rsync': rsync,
            DEFAULT: error_call,
        }

        if progs is not None:
            self.progs.update(progs)

    def __call__(self, args):
        rc = None
        prog = args[0]
        if prog in self.progs:
            rc = self.progs[prog](args)
        else:
            rc = self.progs[DEFAULT](args)
        return rc

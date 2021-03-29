import contextlib
import os
import shutil
import subprocess
import re
import tempfile

from .lxd import test_lxd
from .docker import test_docker


@contextlib.contextmanager
def pushtmpd():
    previous_dir = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    try:
        os.chdir(tmpdir)
        yield tmpdir
    finally:
        os.chdir(previous_dir)
        shutil.rmtree(tmpdir)


def test(method, image, branch, arch):
    result = True

    if arch not in ['x86_64', 'i586']:
        return True

    with pushtmpd() as tmpdir:
        image = shutil.copy(image, tmpdir)
        image_name = os.path.basename(image)
        if method == 'lxd':
            commands = test_lxd(image)
        elif method == 'docker':
            commands = test_docker(image_name)
        elif match := re.match(r'prog\(([-.\w]+)\)', method):
            commands = [f"{match[1]} {image}"]
        else:
            raise Exception(f'Undefined test method {method}')

        for command in commands:
            rc = subprocess.call(command, shell=True)
            if rc:
                result = False

    return result

from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest import mock

import os
import shutil

from cloud_build import CB
from tests.call import Call


def renamer(directory):
    renamer = directory / 'renamer.py'
    renamer.touch()
    renamer.write_text('''\
#!/usr/bin/python3

print("lxd.tar.xz")
''')
    renamer.chmod(0o700)


class TestRename(TestCase):
    def setUp(self):
        self.images = self.__class__.images

    @classmethod
    def setUpClass(cls):
        cls.work_dir = Path('/tmp/cloud-build')
        os.makedirs(cls.work_dir, exist_ok=True)
        renamer(cls.work_dir)

        with ExitStack() as stack:
            stack.enter_context(mock.patch('subprocess.call', Call()))

            cloud_build = CB(
                config='tests/test_rename.yaml',
                data_dir=(cls.work_dir / 'cloud_build').as_posix(),
            )
            cloud_build.create_images(no_tests=True)
            cloud_build.sync(create_remote_dirs=True)

        images_dir = cls.work_dir / 'images'
        cls.images = os.listdir(images_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)

    def test_simple_rename(self):
        self.assertIn('docker.tar.xz', self.images)

    def test_prog_rename(self):
        self.assertIn('lxd.tar.xz', self.images)

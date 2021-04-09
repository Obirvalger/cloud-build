from pathlib import Path
from unittest import TestCase
from unittest import mock

import shutil
import tempfile

from cloud_build import CB

import tests.call as call


class TestNoDelete(TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix='cloud_build'))
        self.images_dir = Path('/tmp/cloud-build-test_no_delete/')
        self.images_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.data_dir)
        shutil.rmtree(self.images_dir)

    @mock.patch('subprocess.call', call.Call())
    def test_no_delete_false(self):
        cb = CB(
            config='tests/test_no_delete_false.yaml',
            data_dir=self.data_dir,
        )
        other_file = self.images_dir / 'other_file.txt'
        other_file.write_text('Some text')
        cb.create_images(no_tests=True)
        cb.sync(create_remote_dirs=True)
        del cb
        msg = 'Other files shoud be deleted if not no_delete'
        if other_file.exists():
            self.fail(msg)

    @mock.patch('subprocess.call', call.Call())
    def test_no_delete_true(self):
        cb = CB(
            config='tests/test_no_delete_true.yaml',
            data_dir=self.data_dir,
        )
        other_file = self.images_dir / 'other_file.txt'
        other_file.write_text('Some text')
        cb.create_images(no_tests=True)
        cb.sync(create_remote_dirs=True)
        del cb
        msg = 'Other files shoud not be deleted if no_delete'
        if not other_file.exists():
            self.fail(msg)

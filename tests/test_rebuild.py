from pathlib import Path
from unittest import TestCase
from unittest import mock

import os
import shutil
import tempfile
import time

from cloud_build import CB
from cloud_build import BuildError

import tests.call as call


DS = {'make': [call.return_d(0), call.nop_d]}


class TestErrors(TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix='cloud_build'))
        self.cb = CB(
            config='tests/test_rebuild.yaml',
            data_dir=self.data_dir,
            no_tests=True,
            create_remote_dirs=True,
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_do_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        two_hours_ago = time.time() - 2*60*60
        os.utime(tarball, times=(two_hours_ago, two_hours_ago))
        msg = 'Do not try to rebuild with outdated cache'
        with self.assertRaises(BuildError, msg=msg):
            self.cb.create_images()

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_dont_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        msg = 'Try to rebuild with valid cache'
        try:
            self.cb.create_images()
        except BuildError:
            self.fail(msg)

    @mock.patch('subprocess.call', call.Call())
    def test_dont_create_image_when_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        self.cb.create_images()
        image = (
            self.data_dir
            / 'images'
            / 'Sisyphus'
            / 'alt-sisyphus-rootfs-minimal-x86_64.tar.xz'
        )
        msg = 'Do not create image when rebuild'
        if not image.exists():
            self.fail(msg)

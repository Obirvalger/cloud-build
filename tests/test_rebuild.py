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


class TestRebuild(TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix='cloud_build'))
        self.cb = CB(
            config='tests/test_rebuild.yaml',
            data_dir=self.data_dir,
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
            self.cb.create_images(no_tests=True)

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_do_force_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        del self.cb
        cb = CB(
            config='tests/test_rebuild.yaml',
            data_dir=self.data_dir,
            force_rebuild=True,
        )
        msg = 'Do not try to rebuild when force_rebuild'
        with self.assertRaises(BuildError, msg=msg):
            cb.create_images(no_tests=True)

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_dont_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        msg = 'Try to rebuild with valid cache'
        try:
            self.cb.create_images(no_tests=True)
        except BuildError:
            self.fail(msg)

    @mock.patch('subprocess.call', call.Call())
    def test_dont_create_image_when_rebuild(self):
        tarball = self.data_dir / 'out/docker_Sisyphus-x86_64.tar.xz'
        tarball.touch()
        self.cb.create_images(no_tests=True)
        image = (
            self.data_dir
            / 'images'
            / 'alt-sisyphus-rootfs-minimal-x86_64.tar.xz'
        )
        msg = 'Do not create image when rebuild'
        if not image.exists():
            self.fail(msg)

#!/usr/bin/python3

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import os
import shutil
import unittest

from cloud_build.cloud_build import CB
from tests.call import Call


class TestCommon(unittest.TestCase):
    def setUp(self):
        self.images = TestCommon.images

    @classmethod
    def setUpClass(cls):
        cls.work_dir = Path('/tmp/cloud-build')
        os.makedirs(cls.work_dir / 'external_files/p9', exist_ok=True)
        (cls.work_dir / 'external_files/p9/README').write_text('README')

        with ExitStack() as stack:
            stack.enter_context(mock.patch('subprocess.call', Call()))
            stack.enter_context(mock.patch.dict(
                'os.environ',
                {'XDG_DATA_HOME': cls.work_dir.as_posix()}
            ))

            cloud_build = CB(SimpleNamespace(
                config='tests/test_integration_images.yaml',
                no_tests=True,
                create_remote_dirs=True,
            ))
            cloud_build.create_images()
            cloud_build.copy_external_files()
            cloud_build.sign()
            cloud_build.sync()

        images_dir = cls.work_dir / 'images'
        cls.images = {}
        for branch in os.listdir(images_dir):
            cls.images[branch] = os.listdir(images_dir / branch / 'cloud')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)

    def test_arch_ppc64le(self):
        self.assertIn('alt-p9-rootfs-minimal-ppc64le.tar.xz',
                      self.images['p9'])

    def test_branches(self):
        self.assertCountEqual(self.images.keys(), ['Sisyphus', 'p9', 'p8'])

    def test_build_cloud(self):
        self.assertIn('alt-p9-cloud-x86_64.qcow2', self.images['p9'])

    def test_exclude_arches(self):
        self.assertNotIn('alt-p8-cloud-x86_64.qcow2', self.images['p8'])

    def test_exclude_branches(self):
        self.assertNotIn('alt-p9-cloud-ppc64le.qcow2', self.images['p9'])

    def test_external_files(self):
        self.assertIn('README', self.images['p9'])

    def test_number_of_images(self):
        number_of_images = sum(len(self.images[b]) for b in self.images.keys())
        self.assertEqual(number_of_images, 58)

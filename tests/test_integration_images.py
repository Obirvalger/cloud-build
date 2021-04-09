from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest import mock

import os
import shutil

from cloud_build import CB
from tests.call import Call


class TestIntegrationImages(TestCase):
    def setUp(self):
        self.images = self.__class__.images

    @classmethod
    def setUpClass(cls):
        cls.work_dir = Path('/tmp/cloud-build')
        os.makedirs(cls.work_dir / 'external_files/p9', exist_ok=True)
        (cls.work_dir / 'external_files/p9/README').write_text('README')

        with ExitStack() as stack:
            stack.enter_context(mock.patch('subprocess.call', Call()))

            cloud_build = CB(
                config='tests/test_integration_images.yaml',
                data_dir=(cls.work_dir / 'cloud_build').as_posix(),
                create_remote_dirs=True,
            )
            cloud_build.create_images(no_tests=True)
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

    def test_verification_files(self):
        for images in self.images.values():
            self.assertIn('SHA256SUMS', images)
            self.assertIn('SHA256SUMS.gpg', images)

    def test_number_of_images(self):
        number_of_images = sum(len(self.images[b]) for b in self.images.keys())
        self.assertEqual(number_of_images, 64)

from unittest import TestCase
from unittest import mock

import shutil
import tempfile

from cloud_build import CB
from tests.call import Call


class TestPackages(TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix='cloud_build')
        self.conf_mk = 'mkimage-profiles/conf.d/cloud-build.mk'
        self.package_lines = [
            '\t@$(call add,BASE_PACKAGES,vim-console)',
            '\t@$(call add,BASE_PACKAGES,gosu)'
        ]

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    def test_packages_all(self):
        with mock.patch('subprocess.call', Call()):
            cb = CB(
                data_dir=self.data_dir,
                config='tests/packages_all.yaml'
            )
            cb.ensure_mkimage_profiles()

            conf = cb.work_dir / self.conf_mk
            lines = conf.read_text().splitlines()

            for package_line in self.package_lines:
                self.assertIn(package_line, lines)

    def test_packages_external(self):
        with mock.patch('subprocess.call', Call()):
            cb = CB(
                data_dir=self.data_dir,
                config='tests/packages_external.yaml'
            )
            cb.ensure_mkimage_profiles()

            conf = cb.work_dir / self.conf_mk
            lines = conf.read_text().splitlines()

            for package_line in self.package_lines:
                self.assertIn(package_line, lines)

    def test_packages_images(self):
        with mock.patch('subprocess.call', Call()):
            cb = CB(
                data_dir=self.data_dir,
                config='tests/packages_image.yaml'
            )
            cb.ensure_mkimage_profiles()

            conf = cb.work_dir / self.conf_mk
            lines = conf.read_text().splitlines()

            for package_line in self.package_lines:
                self.assertIn(package_line, lines)

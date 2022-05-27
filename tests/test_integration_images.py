from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest import mock

import json
import os
import shutil

from parameterized import parameterized, parameterized_class  # type: ignore

import yaml

from cloud_build import CB
from tests.call import Call


def change(origin, new, key, value):
    with open(origin) as f:
        cfg = yaml.safe_load(f)

    with open(new, 'w') as f:
        yaml.safe_dump(cfg | {key: value}, f)


def get_class_name(cls, num, params_dict):
    result = cls.__name__
    if branch := params_dict['branch']:
        result = f'{result}_{parameterized.to_safe_name(branch)}'
    if arch := params_dict['arch']:
        result = f'{result}_{parameterized.to_safe_name(arch)}'
    return f'{result}_{num}'


@parameterized_class([
    {'branch': 'branch', 'arch': ''},
    {'branch': 'branch', 'arch': 'arch'},
    {'branch': '', 'arch': 'arch'},
    {'branch': '', 'arch': ''},
], class_name_func=get_class_name)
class TestIntegrationImages(TestCase):
    def setUp(self):
        self._images = self.__class__._images
        self.images_dir = self.__class__.images_dir

    @classmethod
    def setUpClass(cls):
        cls.work_dir = Path('/tmp/cloud-build')
        os.makedirs(cls.work_dir / 'external_files/p9/x86_64', exist_ok=True)
        (cls.work_dir / 'external_files/p9/x86_64/README').write_text('README')
        config = cls.work_dir / 'config.yaml'
        branch = cls.branch
        arch = cls.arch
        remote = Path('/tmp/cloud-build/images')
        if branch:
            remote = remote / '{branch}'
        if arch:
            remote = remote / '{arch}'
        remote = (remote / 'cloud').as_posix()
        change(
            'tests/test_integration_images.yaml',
            config,
            'remote',
            remote,
        )

        with ExitStack() as stack:
            stack.enter_context(mock.patch('subprocess.call', Call()))

            cloud_build = CB(
                config=config,
                data_dir=(cls.work_dir / 'cloud_build').as_posix(),
            )
            cloud_build.create_images(no_tests=True)
            cloud_build.copy_external_files()
            cloud_build.sign()
            cloud_build.sync(create_remote_dirs=True)

        images_dir = cls.work_dir / 'images'
        cls.images_dir = images_dir
        images = defaultdict(lambda: defaultdict(list))

        if branch:
            for branch in os.listdir(images_dir):
                if arch:
                    for arch in os.listdir(images_dir / branch):
                        images[branch][arch] = os.listdir(
                            images_dir / branch / arch / 'cloud'
                        )
                else:
                    images[branch]['arch'] = os.listdir(
                        images_dir / branch / 'cloud'
                    )
        elif arch:
            for arch in os.listdir(images_dir):
                images['branch'][arch] = os.listdir(
                    images_dir / arch / 'cloud'
                )
        else:
            images['branch']['arch'] = os.listdir(
                images_dir / 'cloud'
            )
        cls._images = images

    def image_path(self, branch, arch, image) -> Path:
        images_dir = self.images_dir
        if self.branch:  # type: ignore
            images_dir = images_dir / branch
        if self.arch:  # type: ignore
            images_dir = images_dir / arch

        return images_dir / 'cloud' / image

    def images(self, branch, arch) -> list:
        if not self.branch:  # type: ignore
            branch = 'branch'
        if not self.arch:  # type: ignore
            arch = 'arch'

        return self._images[branch][arch]

    def images_lists(self) -> list:
        result = []
        for branch_value in self._images.values():
            for arch_value in branch_value.values():
                result.append(arch_value)
        return result

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)

    def test_arch_ppc64le(self):
        self.assertIn('alt-p9-rootfs-minimal-ppc64le.tar.xz',
                      self.images('p9', 'ppc64le'))

    def test_branches(self):
        if self.branch:
            self.assertCountEqual(self._images.keys(),
                                  ['Sisyphus', 'p9', 'p8'])
        else:
            self.assertCountEqual(self._images.keys(), ['branch'])

    def test_build_cloud_img(self):
        self.assertIn('alt-p9-cloud-x86_64.img', self.images('p9', 'x86_64'))

    def test_rename_regex_cloud(self):
        self.assertIn('alt-p9-cloud-x86_64.qcow2', self.images('p9', 'x86_64'))

    def test_exclude_arches(self):
        self.assertNotIn('alt-p8-cloud-x86_64.qcow2',
                         self.images('p8', 'x86_64'))

    def test_exclude_branches(self):
        self.assertNotIn('alt-p9-cloud-ppc64le.qcow2',
                         self.images('p9', 'ppc64le'))

    def get_make_args(self, branch, arch, image):
        image = self.image_path(branch, arch, image)
        return json.loads(image.read_text())

    def test_branding_present_p9_rootfs_minimal(self):
        self.assertIn(
            "BRANDING=alt-starterkit",
            self.get_make_args(
                'p9',
                'x86_64',
                'alt-p9-rootfs-minimal-x86_64.tar.xz',
            ),
        )

    def test_branding_present_p9_cloud(self):
        self.assertIn(
            "BRANDING=alt-starterkit",
            self.get_make_args('p9', 'x86_64', 'alt-p9-cloud-x86_64.qcow2'),
        )

    def test_branding_absent_p9_workstation_cloud(self):
        self.assertNotRegex(
            ' '.join(self.get_make_args(
                'p9',
                'x86_64',
                'alt-p9-workstation-cloud-x86_64.qcow2',
            )),
            'BRANDING'
        )

    def test_branding_absent_sisyphus_cloud(self):
        self.assertNotRegex(
            ' '.join(self.get_make_args(
                'Sisyphus',
                'x86_64',
                'alt-sisyphus-cloud-x86_64.qcow2',
            )),
            'BRANDING'
        )

    def test_external_files(self):
        self.assertIn('README', self.images('p9', 'x86_64'))

    def test_verification_files(self):
        for images_list in self.images_lists():
            self.assertIn('SHA256SUMS', images_list)
            self.assertIn('SHA256SUMS.gpg', images_list)

        number_of_images = len(self.image_path(
            'p9',
            'x86_64',
            'SHA256SUMS',
        ).read_text().splitlines())
        index = bool(self.branch) * 2 + bool(self.arch)
        expected_numbers = [58, 19, 24, 8]
        self.assertEqual(number_of_images, expected_numbers[index])

    def test_number_of_images(self):
        number_of_images = sum(len(lst) for lst in self.images_lists())
        index = bool(self.branch) * 2 + bool(self.arch)
        expected_numbers = [62, 78, 70, 102]
        self.assertEqual(number_of_images, expected_numbers[index])

from unittest import TestCase
from unittest import mock

import shutil
import tempfile

import yaml

from cloud_build import CB
from cloud_build import Error, BuildError, MultipleBuildErrors

import tests.call as call


def update(old_dict, kwargs):
    new_dict = old_dict.copy()
    for key, value in kwargs.items():
        if value is None:
            del new_dict[key]
        else:
            new_dict[key] = value
    return new_dict


class TestErrors(TestCase):
    def setUp(self):
        kwargs = {}
        kwargs['data_dir'] = tempfile.mkdtemp(prefix='cloud_build')
        self.kwargs = kwargs

    def tearDown(self):
        shutil.rmtree(self.kwargs['data_dir'])

    def test_read_config_not_found(self):
        regex = 'config file.*No such file or directory'
        self.kwargs.update(config='/var/empty/cb_conf.yaml')
        self.assertRaisesRegex(Error, regex, CB, **self.kwargs)

    def test_read_config_permission_denied(self):
        regex = 'config file.*Permission denied'
        self.kwargs.update(config='/root/cb_conf.yaml')
        self.assertRaisesRegex(Error, regex, CB, **self.kwargs)

    def test_required_parameters_in_config(self):
        config = tempfile.mktemp(prefix='cb_conf')
        with open('tests/minimal_config.yaml') as f:
            cfg = yaml.safe_load(f)

        parameter = 'key'
        for parameter in ['remote', 'key', 'images', 'branches']:
            with open(config, 'w') as f:
                yaml.safe_dump(update(cfg, {parameter: None}), f)

            regex = f'parameter.*{parameter}'
            self.kwargs.update(config=config)
            self.assertRaisesRegex(Error, regex, CB, **self.kwargs)

    def test_run_already_running(self):
        self.kwargs.update(config='tests/minimal_config.yaml')
        cb = CB(**self.kwargs)  # noqa F841
        regex = 'already running'
        self.assertRaisesRegex(Error, regex, CB, **self.kwargs)

    def test_try_build_all_zero_rc(self):
        def cond(args):
            return args[1].endswith('aarch64')
        ds = {'make': [call.return_d(0, cond=cond), call.nop_d(cond=cond)]}
        with mock.patch('subprocess.call', call.Call(decorators=ds)):
            cloud_build = CB(
                config='tests/test_try_build_all.yaml',
                data_dir=self.kwargs['data_dir'],
                no_tests=True,
                create_remote_dirs=True,
            )
            regex = r'build.*:'
            self.assertRaisesRegex(
                MultipleBuildErrors,
                regex,
                cloud_build.create_images
            )

    def test_try_build_all_non_zero_rc(self):
        def cond(args):
            return args[1].endswith('aarch64')
        ds = {'make': [call.return_d(2, cond=cond), call.nop_d(cond=cond)]}
        with mock.patch('subprocess.call', call.Call(decorators=ds)):
            cloud_build = CB(
                config='tests/test_try_build_all.yaml',
                data_dir=self.kwargs['data_dir'],
                no_tests=True,
                create_remote_dirs=True,
            )
            regex = r'build.*:'
            self.assertRaisesRegex(
                MultipleBuildErrors,
                regex,
                cloud_build.create_images
            )

    def test_not_try_build_all(self):
        def cond(args):
            return args[1].endswith('aarch64')
        ds = {'make': [call.return_d(0, cond=cond), call.nop_d(cond=cond)]}
        with mock.patch('subprocess.call', call.Call(decorators=ds)):
            cloud_build = CB(
                config='tests/test_not_try_build_all.yaml',
                data_dir=self.kwargs['data_dir'],
                no_tests=True,
                create_remote_dirs=True,
            )
            regex = r'build.*aarch64'
            self.assertRaisesRegex(
                BuildError,
                regex,
                cloud_build.create_images
            )

    def test_rebuild_after_format(self):
        regex = 'years.*rebuild_after'
        self.kwargs.update(config='tests/test_rebuild_after_format.yaml')
        self.assertRaisesRegex(Error, regex, CB, **self.kwargs)

from unittest import TestCase

import shutil
import tempfile

import yaml

from cloud_build import CB
from cloud_build import Error


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

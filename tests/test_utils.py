from unittest import TestCase

import shutil
import tempfile

from cloud_build import CB


class TestUtils(TestCase):
    def setUp(self):
        kwargs = {
            'data_dir': tempfile.mkdtemp(prefix='cloud_build'),
            'config': 'tests/minimal_config.yaml',
        }
        self.kwargs = kwargs
        self.cb = CB(**kwargs)

    def tearDown(self):
        shutil.rmtree(self.kwargs['data_dir'])

    def test_conver_size_lower_case(self):
        self.assertEqual(self.cb.convert_size('200k'), '204800')

    def test_conver_size_upper_case(self):
        self.assertEqual(self.cb.convert_size('1M'), '1048576')

    def test_conver_size_real(self):
        self.assertEqual(self.cb.convert_size('0.1G'), '107374182')

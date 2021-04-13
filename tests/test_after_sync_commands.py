from pathlib import Path
from unittest import TestCase
from unittest import mock

import tempfile
import shutil

from cloud_build import CB

import tests.call as call


DS = {'rsync': [call.return_d(0), call.nop_d]}


class TestAfterSyncCommands(TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix='cloud_build'))

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_run_after_sync_remote_commands(self):
        cb = CB(
            config='tests/test_run_after_sync_remote_commands.yaml',
            data_dir=self.data_dir,
        )
        cb.create_images(no_tests=True)
        regex = r'ssh.*kick'
        self.assertRaisesRegex(
            Exception,
            regex,
            cb.sync,
            create_remote_dirs=True
        )

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_run_after_sync_local_commands(self):
        cb = CB(
            config='tests/test_run_after_sync_local_commands.yaml',
            data_dir=self.data_dir,
        )
        cb.create_images(no_tests=True)
        regex = r'\[\'kick'
        self.assertRaisesRegex(
            Exception,
            regex,
            cb.sync,
            create_remote_dirs=True
        )

    @mock.patch('subprocess.call', call.Call(decorators=DS))
    def test_dont_run_after_sync_local_commands(self):
        cb = CB(
            config='tests/minimal_config.yaml',
            data_dir=self.data_dir,
        )
        cb.create_images(no_tests=True)
        cb.sync(create_remote_dirs=False)

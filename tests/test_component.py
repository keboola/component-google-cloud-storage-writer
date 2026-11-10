'''
Created on 12. 11. 2018

@author: esner
'''
import json
import shutil
import tempfile
import unittest
import mock
import os
from freezegun import freeze_time
from google.api_core.exceptions import Forbidden, NotFound, ServerError

from component import Component, UserException

BUCKET_NAME = 'test-bucket'


class TestComponent(unittest.TestCase):

    # set global time to 2010-10-10 - affects functions like datetime.now()
    @freeze_time("2010-10-10")
    # set KBC_DATADIR env to non-existing dir
    @mock.patch.dict(os.environ, {'KBC_DATADIR': './non-existing-dir'})
    def test_run_no_cfg_fails(self):
        with self.assertRaises(ValueError):
            comp = Component()
            comp.run()


class TestUploadFileErrorHandling(unittest.TestCase):
    """
    Google Cloud Storage API errors raised while uploading a blob must surface as user errors
    (exit code 1) instead of an unhandled internal error (exit code 2).
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.data_dir, 'in', 'tables'))
        os.makedirs(os.path.join(self.data_dir, 'in', 'files'))
        os.makedirs(os.path.join(self.data_dir, 'out'))
        with open(os.path.join(self.data_dir, 'config.json'), 'w') as config_file:
            json.dump({'parameters': {'bucket_name': BUCKET_NAME, 'append_date': False}}, config_file)
        with open(os.path.join(self.data_dir, 'in', 'tables', 'test.csv'), 'w') as source_file:
            source_file.write('id\n1\n')

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _get_component_and_input_table(self):
        with mock.patch.dict(os.environ, {'KBC_DATADIR': self.data_dir}):
            component = Component()
        return component, component.get_input_tables_definitions()[0]

    def _upload_with_client_error(self, error):
        component, input_table = self._get_component_and_input_table()
        storage_client = mock.MagicMock()
        storage_client.upload_blob.side_effect = error
        component.upload_file(storage_client, BUCKET_NAME, '', input_table, False)

    def test_upload_forbidden_raises_user_exception(self):
        error = Forbidden('POST https://storage.googleapis.com/upload/storage/v1/b/test-bucket/o: '
                          'service-account@example.iam.gserviceaccount.com does not have '
                          'storage.objects.delete access to the Google Cloud Storage object.')
        with self.assertRaises(UserException) as raised:
            self._upload_with_client_error(error)
        message = str(raised.exception)
        self.assertIn('denied', message)
        self.assertIn('storage.objects.delete', message)

    def test_upload_not_found_still_raises_its_own_user_exception(self):
        with self.assertRaises(UserException) as raised:
            self._upload_with_client_error(NotFound('no such bucket'))
        self.assertIn('Not Found error occurred', str(raised.exception))

    def test_upload_server_error_still_raises_its_own_user_exception(self):
        with self.assertRaises(UserException) as raised:
            self._upload_with_client_error(ServerError('backend error'))
        self.assertIn('internal server error', str(raised.exception))

    def test_successful_upload_is_unaffected(self):
        component, input_table = self._get_component_and_input_table()
        storage_client = mock.MagicMock()
        component.upload_file(storage_client, BUCKET_NAME, '', input_table, False)
        storage_client.upload_blob.assert_called_once_with(BUCKET_NAME, input_table.full_path, 'test.csv')


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()

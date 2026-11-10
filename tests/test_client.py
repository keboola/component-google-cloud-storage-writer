import json
import os
import tempfile
import unittest

import mock
import requests
from google.auth.credentials import AnonymousCredentials

from google_cloud_storage.client import StorageClient

SESSION_URL = "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?uploadType=resumable&upload_id=abc"


def _response(status, headers=None, body=b""):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = body
    response.request = requests.Request("PUT", SESSION_URL).prepare()
    return response


class FakeSession:
    """Starts a resumable session per POST, and fails the first chunk PUT with a 503."""

    is_mtls = False

    def __init__(self, file_size):
        self.file_size = file_size
        self.initiated_sessions = 0
        self.chunk_puts = 0
        self.content_ranges = []

    def request(self, method, url, data=None, headers=None, timeout=None, **kwargs):
        if method == "POST":
            self.initiated_sessions += 1
            return _response(200, {"location": SESSION_URL})
        self.chunk_puts += 1
        self.content_ranges.append(headers.get("content-range"))
        if self.chunk_puts == 1:
            return _response(503, body=b"We encountered an internal error. Please try again.")
        body = {"name": "out.csv", "bucket": "bucket", "size": str(self.file_size)}
        return _response(200, {"content-type": "application/json"}, json.dumps(body).encode())


class TestUploadRetry(unittest.TestCase):

    def setUp(self):
        self.file_size = 9 * 1024 * 1024  # above the 8 MiB threshold, so the upload is resumable
        handle, self.path = tempfile.mkstemp()
        with os.fdopen(handle, "wb") as f:
            f.write(b"a" * self.file_size)

    def tearDown(self):
        os.remove(self.path)

    @mock.patch("time.sleep")
    @mock.patch.object(StorageClient, "_get_storage_credentials", return_value=(AnonymousCredentials(), "project"))
    def test_chunk_503_is_retried_in_the_same_upload_session(self, _credentials, _sleep):
        client = StorageClient("bucket", service_account_json_key={})
        session = FakeSession(self.file_size)
        client._http_internal = session

        client.upload_blob("bucket", self.path, "out.csv")

        self.assertEqual(session.initiated_sessions, 1)
        self.assertEqual(session.chunk_puts, 2)
        self.assertEqual(session.content_ranges[0], session.content_ranges[1])


if __name__ == "__main__":
    unittest.main()

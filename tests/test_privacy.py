"""Canary secrets must never reach either log sink or review files."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from api import privacy, review
from api.logger import logger


class PrivacyTest(unittest.TestCase):
    def test_console_and_file_sinks_redact_fields_urls_and_exceptions(self):
        secret = "synthetic-canary-auth-value"
        privacy.register_secret(secret)
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "run.log")
            console_sink = logger.add(console, format="{message}")
            file_sink = logger.add(str(path), format="{message}")
            try:
                logger.info("Cookie: {} | password='{}' | https://notify.invalid/{}/push?uid=123", secret, secret, secret)
                try:
                    raise ValueError("unlabeled " + secret)
                except ValueError:
                    logger.exception("request failed")
            finally:
                logger.remove(console_sink)
                logger.remove(file_sink)
            for output in (console.getvalue(), path.read_text()):
                self.assertNotIn(secret, output)
                self.assertNotIn("/push?uid=123", output)
                self.assertIn("redacted", output)

    def test_cookiejar_and_identity_fields_are_redacted(self):
        text = privacy.redact("<RequestsCookieJar[<Cookie session=synthetic-secret for x/>]> username=13912345678 dtoken='synthetic-token' Authorization: Bearer synthetic-bearer")
        for value in ("synthetic-secret", "13912345678", "synthetic-token", "synthetic-bearer"):
            self.assertNotIn(value, text)

    def test_unregistered_cookie_headers_and_containers(self):
        for value in ('Cookie: synthetic_sid=alpha-demo; synthetic_auth=beta-demo',
                      'cookies={"synthetic_sid":"alpha-demo"}',
                      'Set-Cookie: synthetic_sid=alpha-demo; Path=/'):
            self.assertNotIn("alpha-demo", privacy.redact(value))
            self.assertNotIn("beta-demo", privacy.redact(value))
        for value in ('payload={"token": ["alpha-demo", "beta-demo"]}',
                      'payload={"authorization": {"primary": "alpha-demo", "secondary": "beta-demo"}}'):
            self.assertNotIn("alpha-demo", privacy.redact(value))
            self.assertNotIn("beta-demo", privacy.redact(value))
        value = '{"token": [\n "alpha-demo",\n "beta-demo"\n]}'
        self.assertNotIn("alpha-demo", privacy.redact(value))
        self.assertNotIn("beta-demo", privacy.redact(value))
        record = {"message": "safe", "extra": {"request": {"cookies": {"sid": "alpha-demo"}}}}
        privacy.patch_record(record)
        self.assertNotIn("alpha-demo", str(record))

    def test_review_is_private_durable_and_uses_last_status(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"CX_DATA_HOME": directory}):
            item = review.record(review.KIND_DISCUSSION, "正文 password=synthetic-private", extra={"cookie": "must-not-persist"})
            self.assertIsNotNone(item)
            review.update(item, "用户取消，未提交")
            records = review.load()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "用户取消，未提交")
            for path in (Path(review.index_path()), Path(review.markdown_path())):
                self.assertNotIn("synthetic-private", path.read_text())
                self.assertNotIn("must-not-persist", path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

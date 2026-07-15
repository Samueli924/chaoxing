import unittest
from unittest.mock import Mock, patch

from api.notification import REQUEST_TIMEOUT, ServerChan


class NotificationTests(unittest.TestCase):
    @patch("api.notification.requests.post")
    def test_notification_requests_have_a_timeout(self, post):
        response = Mock()
        response.json.return_value = {"code": 0}
        post.return_value = response
        service = ServerChan()
        service.config_set({"url": "https://example.invalid/secret-token"})
        service.init_notification()

        service.send("done")

        self.assertEqual(post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()

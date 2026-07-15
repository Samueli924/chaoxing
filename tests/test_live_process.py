import unittest
from unittest.mock import patch

from api.live_process import LiveProcessor


class LiveProcessorTests(unittest.TestCase):
    @patch("api.live_process.time.sleep")
    def test_second_failed_submission_returns_false(self, sleep):
        class FakeLive:
            name = "Replay"

            def get_status(self):
                return {"temp": {"data": {"duration": 60}}}

            def do_finish(self):
                return False

        self.assertFalse(LiveProcessor.run_live(FakeLive(), speed=1.0))


if __name__ == "__main__":
    unittest.main()

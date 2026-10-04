"""公开建模的限额与并发控制不依赖客户提交的计数。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import public_service


class PublicServiceTests(unittest.TestCase):
    def test_daily_cap_blocks_and_exception_releases_worker(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "AICAD_PUBLIC_USAGE_DB": str(Path(directory) / "usage.sqlite"),
            "AICAD_PUBLIC_DAILY_LIMIT": "2",
        }):
            def fail():
                raise ValueError("private")
            result = public_service.run_public("hello", fail)
            self.assertEqual(result["status"], "error")
            second = public_service.run_public("hello", lambda: {"status": "success"})
            self.assertEqual(second["status"], "success")
            third = public_service.run_public("hello", lambda: self.fail("额度不足仍执行"))
            self.assertEqual(third["status"], "error")
            self.assertIn("上限", third["error_message"])

    def test_busy_or_oversized_requests_do_not_execute(self):
        lock = public_service.WORKER
        lock.acquire()
        try:
            result = public_service.run_public("hello", lambda: self.fail("并发时仍执行"))
            self.assertIn("忙", result["error_message"])
        finally:
            lock.release()
        result = public_service.run_public("x" * 2001, lambda: self.fail("超长请求仍执行"))
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()

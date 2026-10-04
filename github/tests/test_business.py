"""验证账户隔离、按次结算、退款和重复请求，不使用真实支付或模型 API。"""
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from business import BusinessStore, BusinessError, run_service


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = BusinessStore(Path(self.directory.name) / "test.sqlite")
        self.user = self.store.register("customer", "a-long-password")
        self.admin = self.store.create_admin("owner", "an-admin-password")

    def tearDown(self):
        self.directory.cleanup()

    def test_auth_and_admin_permissions(self):
        self.assertIsNone(self.store.authenticate("customer", "wrong-password"))
        self.assertEqual(self.store.authenticate("customer", "a-long-password")["id"], self.user["id"])
        with self.assertRaises(BusinessError):
            self.store.set_price(self.user["id"], 200)
        self.store.set_price(self.admin["id"], 200)
        self.assertEqual(self.store.price_fen(), 200)
        with self.assertRaises(BusinessError):
            self.store.register("customer", "another-password")

    def test_success_charges_once_and_duplicate_does_not_call_model(self):
        calls = []
        def generate():
            calls.append(1)
            return {"status": "success", "output_file": "sample.step"}
        first = run_service(self.store, self.user["id"], "unique", "create", generate)
        second = run_service(self.store, self.user["id"], "unique", "create", generate)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.user(self.user["id"])["balance_fen"], 900)
        stats = self.store.statistics(self.admin["id"])
        self.assertEqual(stats["successful_orders"], 1)
        self.assertEqual(stats["demo_service_fen"], 100)
        self.assertEqual(stats["real_received_fen"], 0)

    def test_failure_refunds_and_customer_cannot_see_others_orders(self):
        result = run_service(self.store, self.user["id"], "failure", "bad", lambda: {"status": "error", "error_message": "invalid"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.store.user(self.user["id"])["balance_fen"], 1000)
        other = self.store.register("another", "another-password")
        self.assertEqual(self.store.orders(other["id"]), [])
        self.assertEqual(self.store.orders(self.user["id"])[0]["status"], "failed")
        self.assertEqual(self.store.statistics(self.admin["id"])["demo_service_fen"], 0)

    def test_reservations_are_atomic_and_prevent_overspending(self):
        self.store.set_price(self.admin["id"], 600)
        def reserve(number):
            try:
                return self.store.reserve(self.user["id"], str(number), "request", 600)
            except BusinessError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservations = list(pool.map(reserve, [1, 2]))
        self.assertEqual(sum(r is not None for r in reservations), 1)
        self.assertEqual(self.store.user(self.user["id"])["balance_fen"], 400)

    def test_exception_refunds_and_changed_quote_blocks_generation(self):
        def explode():
            raise RuntimeError("private error")
        result = run_service(self.store, self.user["id"], "error", "request", explode)
        self.assertNotIn("private error", str(result))
        self.assertEqual(self.store.user(self.user["id"])["balance_fen"], 1000)
        self.store.set_price(self.admin["id"], 200)
        with self.assertRaises(BusinessError):
            self.store.reserve(self.user["id"], "stale", "request", 100)

    def test_daily_limit_blocks_before_model_and_pending_duplicate_is_not_reexecuted(self):
        self.store.reserve(self.user["id"], "pending", "request", 100)
        calls = []
        with self.assertRaises(BusinessError):
            run_service(self.store, self.user["id"], "pending", "request", lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.store.set_daily_limit(self.admin["id"], 1)
        with self.assertRaises(BusinessError):
            self.store.reserve(self.user["id"], "too-many", "request", 100)


if __name__ == "__main__":
    unittest.main()

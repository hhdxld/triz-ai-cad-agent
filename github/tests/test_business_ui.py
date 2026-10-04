"""真实 CAD 与演示计费完整会话，隔离测试数据库。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from business import BusinessStore
from business_ui import csv_report

APP = Path(__file__).resolve().parents[1] / "app.py"


class BusinessUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = str(Path(self.temp.name) / "business.sqlite")
        self.store = BusinessStore(path)
        self.customer = self.store.register("customer", "password-for-test")
        environment = patch.dict("os.environ", {"AICAD_BILLING_MODE": "demo", "AICAD_DATABASE_PATH": path,
                                "OPENAI_API_KEY": "secret-never-show", "OPENAI_MODEL": "demo-test-model",
                                "AICAD_ALLOW_DEMO_API": "false"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_login_charge_refund_logout_isolation_and_server_key_not_shown(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        app.button(key="preset_standard").click().run()
        self.assertIsNone(app.session_state["latest_result"])
        app.text_input(key="login_username").set_value("customer")
        app.text_input(key="login_password").set_value("password-for-test")
        app.button(key="FormSubmitter:login-登录账户").click().run()
        self.assertEqual(len(app.exception), 0)
        consent = next(box for box in app.checkbox if box.key.startswith("fee_consent_"))
        consent.check().run()
        app.button(key="preset_standard").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.user(self.customer["id"])["balance_fen"], 900)
        self.assertEqual(self.store.orders(self.customer["id"])[0]["status"], "success")
        app.chat_input[0].set_value("长度改为20").run()
        self.assertEqual(self.store.user(self.customer["id"])["balance_fen"], 900)
        self.assertTrue(any(row["status"] == "failed" for row in self.store.orders(self.customer["id"])))
        app.radio[0].set_value("在线模型 API").run()
        self.assertFalse(any(item.label == "API 密钥" for item in app.text_input))
        self.assertNotIn("secret-never-show", str([item.value for item in app.markdown]))
        previous = len(self.store.orders(self.customer["id"]))
        app.chat_input[0].set_value("长度改为140").run()
        self.assertEqual(len(self.store.orders(self.customer["id"])), previous)
        app.button(key="logout").click().run()
        self.assertIsNone(app.session_state["latest_result"])
        self.assertNotIn("站长经营统计", [element.value for element in app.subheader])

    def test_csv_does_not_execute_customer_formula(self):
        data = csv_report([{"id": "id", "username": "customer", "prompt": "=1+1", "fee_fen": 100,
                           "status": "failed", "created_at": "now"}]).decode("utf-8-sig")
        self.assertIn("'=1+1", data)
        self.assertIn("0.00", data)

    def test_admin_can_change_price_and_view_statistics(self):
        admin = self.store.create_admin("owner", "owner-password-test")
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        app.text_input(key="login_username").set_value("owner")
        app.text_input(key="login_password").set_value("owner-password-test")
        app.button(key="FormSubmitter:login-登录账户").click().run()
        self.assertIn("站长经营统计", [element.value for element in app.subheader])
        app.number_input(key="admin_price").set_value(250)
        app.button(key="FormSubmitter:pricing-保存服务价格与限额").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.price_fen(), 250)
        self.assertFalse(next(box for box in app.checkbox if box.key.startswith("fee_consent_")).value)
        self.assertEqual(self.store.statistics(admin["id"])["real_received_fen"], 0)


if __name__ == "__main__":
    unittest.main()

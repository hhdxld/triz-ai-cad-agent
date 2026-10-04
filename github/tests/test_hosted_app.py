"""检查正式站点入口的登录门禁与后台权限，不调用支付平台。"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from business import BusinessStore


class HostedAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = str(Path(self.temp.name) / "business.sqlite")
        self.store = BusinessStore(path)
        self.customer = self.store.register("customer", "customer-password")
        self.admin = self.store.create_admin("owner", "owner-password-test")
        env = patch.dict("os.environ", {"AICAD_BILLING_MODE": "demo", "AICAD_DATABASE_PATH": path})
        env.start()
        self.addCleanup(env.stop)
        self.entry = str(Path(__file__).resolve().parents[1] / "hosted_app.py")

    def test_guest_must_login_before_workbench(self):
        app = AppTest.from_file(self.entry).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.chat_input), 0)
        self.assertFalse(any(button.key == "preset_standard" for button in app.button))
        app.text_input(key="login_username").set_value("customer")
        app.text_input(key="login_password").set_value("customer-password")
        app.button(key="FormSubmitter:login-登录账户").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.chat_input), 1)
        app.button(key="logout").click().run()
        self.assertEqual(len(app.chat_input), 0)

    def test_customer_cannot_enter_admin_even_with_direct_url(self):
        app = AppTest.from_file(self.entry)
        app.query_params["page"] = "admin"
        app.session_state["account_id"] = self.customer["id"]
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("管理员" in item.value for item in app.error))
        self.assertFalse(any(item.key == "admin_price" for item in app.number_input))

    def test_admin_has_separate_dashboard_and_price_controls(self):
        app = AppTest.from_file(self.entry)
        app.query_params["page"] = "admin"
        app.session_state["account_id"] = self.admin["id"]
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.chat_input), 0)
        app.number_input(key="admin_price").set_value(250)
        app.button(key="FormSubmitter:pricing-保存服务价格与限额").click().run()
        self.assertEqual(self.store.price_fen(), 250)

    def test_free_mode_cannot_bypass_hosted_login_gate(self):
        with patch.dict("os.environ", {"AICAD_BILLING_MODE": "off"}):
            app = AppTest.from_file(self.entry).run()
        self.assertEqual(len(app.chat_input), 0)
        self.assertTrue(len(app.error))

    def test_idle_session_expires_and_hides_previous_model(self):
        app = AppTest.from_file(self.entry)
        app.session_state["account_id"] = self.customer["id"]
        app.session_state["last_active"] = time.monotonic() - 1801
        app.session_state["latest_result"] = {"status": "success", "output_file": "private.step"}
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.chat_input), 0)
        self.assertNotIn("latest_result", app.session_state)

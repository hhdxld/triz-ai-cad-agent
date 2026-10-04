"""公开入口必须免登录、不收费、不能调用站长的付费 API。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class PublicAppTests(unittest.TestCase):
    def test_guest_build_modify_download_and_no_payment_or_secret_fields(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "AICAD_PUBLIC_USAGE_DB": str(Path(directory) / "usage.sqlite"),
            "OPENAI_API_KEY": "private-owner-key",
        }):
            self.assertTrue((ROOT / "public_app.py").is_file(), "公开入口尚未创建")
            app = AppTest.from_file(str(ROOT / "public_app.py"), default_timeout=30).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.text_input), 0)
            self.assertNotIn("在线模型 API", app.radio[0].options)
            app.button(key="preset_standard").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["latest_result"]["status"], "success")
            labels={item.label for item in app.get('download_button')}
            self.assertTrue({'下载 STEP 工业模型','下载 STL 模型','下载参数 JSON','下载设计报告'}<=labels)
            app.chat_input[0].set_value("长度改为140").run()
            self.assertEqual(app.session_state["last_params"]["length"], 140)
            self.assertNotIn("private-owner-key", str([m.value for m in app.markdown]))


if __name__ == "__main__":
    unittest.main()

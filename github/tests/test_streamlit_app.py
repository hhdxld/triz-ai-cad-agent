"""使用 Streamlit 官方 AppTest 验证完整会话与渲染组件接入。"""

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class StreamlitAppTests(unittest.TestCase):
    def test_chat_build_modify_and_failure_preserves_success(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "TRIZ AI CAD Agent")
        self.assertEqual(app.radio[0].value, "本地参数识别")
        app.radio[0].set_value("本地参数识别").run()
        app.chat_input[0].set_value("长100宽45厚5孔距50孔径16.5").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 3)
        first = app.session_state["latest_result"]
        self.assertEqual(first["status"], "success")
        self.assertTrue(Path(first["stl_file"]).is_file())
        # 失败不能把尺寸参数或右侧下载模型换成无效版本。
        app.chat_input[0].set_value("长度改成20").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["latest_result"]["output_file"], first["output_file"])
        self.assertEqual(app.session_state["last_params"]["length"], 100)
        app.chat_input[0].set_value("长度改为140").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["last_params"]["length"], 140)
        self.assertEqual(app.session_state["last_params"]["probe_distance"], 50)
        self.assertNotEqual(app.session_state["latest_result"]["output_file"], first["output_file"])
        self.assertEqual(len(app.get("download_button")), 2)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIsNone(app.session_state["latest_result"])


if __name__ == "__main__":
    unittest.main()

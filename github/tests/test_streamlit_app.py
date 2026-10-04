"""使用 Streamlit 官方 AppTest 验证完整会话与渲染组件接入。"""

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class StreamlitAppTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"AICAD_BILLING_MODE": "off"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_preset_and_parameter_editor_generate_real_models(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertIn("preset_standard", [b.key for b in app.button])
        app.button(key="preset_standard").click().run()
        self.assertEqual(len(app.exception), 0)
        first = app.session_state["latest_result"]
        self.assertTrue(Path(first["output_file"]).is_file())
        # 表单字段在提交时一起发送，不为单个字段触发独立重跑。
        app.number_input(key="edit_length").set_value(150)
        app.button(key="FormSubmitter:dimensions-应用尺寸并生成").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["last_params"]["length"], 150,
                         app.session_state["messages"][-2:])
        self.assertEqual(app.session_state["last_params"]["probe_distance"], 50)
        second = app.session_state["latest_result"]
        self.assertNotEqual(first["output_file"], second["output_file"])
        app.chat_input[0].set_value("宽度改为60").run()
        self.assertEqual(app.number_input(key="edit_width").value, 60)
        app.number_input(key="edit_length").set_value(20)
        app.button(key="FormSubmitter:dimensions-应用尺寸并生成").click().run()
        self.assertEqual(app.session_state["last_params"]["length"], 150)
        self.assertEqual(app.session_state["last_params"]["width"], 60)

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
        self.assertTrue({'下载 STEP 工业模型','下载 STL 模型','下载参数 JSON','下载设计报告'}<=
            {item.label for item in app.get('download_button')})
        app.button(key="new_design").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIsNone(app.session_state["latest_result"])


if __name__ == "__main__":
    unittest.main()

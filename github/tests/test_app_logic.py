"""网页关键行为测试，不调用付费 API。"""

import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path

AVAILABLE = importlib.util.find_spec("app") is not None
if AVAILABLE:
    from app import parse_local_request, process_request, DEFAULT_PARAMS


class AppLogicTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(AVAILABLE, "尚未实现 Streamlit app.py")

    def test_chinese_dimensions_and_units(self):
        params = parse_local_request("做一个长10厘米、宽45mm、厚5毫米，孔距50mm，孔径16.5mm的支架")
        self.assertEqual(params["length"], 100)
        self.assertEqual(params["width"], 45)
        self.assertEqual(params["thickness"], 5)
        self.assertEqual(params["probe_distance"], 50)

    def test_incremental_change_preserves_previous_dimensions(self):
        old = dict(DEFAULT_PARAMS, width=60, probe_distance=70)
        params = parse_local_request("长度改为140毫米，关闭减重，取消倒角", old)
        self.assertEqual(params["length"], 140)
        self.assertEqual(params["width"], 60)
        self.assertEqual(params["probe_distance"], 70)
        self.assertIs(params["enable_triz_lightening"], False)
        self.assertIs(params["enable_stress_relief"], False)
        self.assertEqual(old["length"], 100)

    def test_compact_dimensions_and_unknown_prompt(self):
        params = parse_local_request("做100×45×5 mm的支架，孔距50")
        self.assertEqual([params[k] for k in ("length", "width", "thickness")], [100, 45, 5])
        with self.assertRaises(ValueError):
            parse_local_request("你好")
        params = parse_local_request("长度改成-20")
        self.assertEqual(params["length"], -20)  # 由 CAD 校验阻止非法几何。

    def test_local_flow_calls_existing_cad_function(self):
        result = process_request("长100宽45厚5孔距50", None, mode="本地参数识别")
        self.assertEqual(result["status"], "success", result)
        self.assertTrue(Path(result["output_file"]).is_file())
        self.assertTrue(Path(result["stl_file"]).is_file())
        self.assertGreater(result["reduction_percent"], 0)

    def test_online_missing_settings_and_api_failure_preserve_error(self):
        result = process_request("长度140", None, mode="在线模型 API")
        self.assertEqual(result["status"], "error")
        with patch("app.extract_api_parameters", side_effect=RuntimeError("连接失败")):
            result = process_request("长度140", None, mode="在线模型 API",
                                     api_key="test-only", base_url="https://example.invalid/v1", model="test")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("test-only", result["error_message"])

    def test_unsupported_shape_must_not_be_replaced_with_sensor_plate(self):
        for text in ('做一个圆柱，直径20长度100', '做一个L形支架，长100宽45厚5',
                     '做一个无孔的长100宽45厚5板', '做齿轮，直径50厚5', '长100宽45厚5的外壳'):
            with self.subTest(text=text), patch('app.cad_tool.generate_sensor_bracket') as generate:
                result = process_request(text, None, mode='本地参数识别')
                self.assertEqual(result['status'], 'error')
                generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()

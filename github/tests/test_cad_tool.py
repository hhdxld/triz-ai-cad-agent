"""验证真实几何、参数边界和 Agent 调用契约。"""

import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = importlib.util.find_spec("cad_tool") is not None
if AVAILABLE:
    from cad_tool import CADTool, dispatch_tool_call


class CADToolTests(unittest.TestCase):
    """以独立解析 STEP 和解析几何计算验证建模结果。"""

    def setUp(self):
        self.assertTrue(AVAILABLE, "尚未实现 cad_tool 工具模块")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = CADTool(output_dir=self.tmp.name)
        self.params = dict(length=100.0, width=45.0, thickness=5.0,
                           probe_distance=50.0, probe_dia=16.5)

    def generate(self, **changes):
        """合并参数并调用真实工具。"""
        return self.tool.generate_sensor_bracket(**(self.params | changes))

    def test_plain_plate_analytical_volume_and_step_roundtrip(self):
        result = self.generate(enable_triz_lightening=False, enable_stress_relief=False)
        self.assertEqual(result["status"], "success", result)
        expected = (100 * 45 - 2 * math.pi * (16.5 / 2) ** 2) * 5
        physical = result["physical_properties"]
        self.assertAlmostEqual(physical["volume_mm3"], expected, places=5)
        self.assertAlmostEqual(physical["weight_g"], expected * 0.0027, places=5)
        shape = cq.importers.importStep(result["output_file"]).val()
        stl_file = Path(result["stl_file"])
        self.assertEqual(stl_file.stem, Path(result["output_file"]).stem)
        self.assertGreater(stl_file.stat().st_size, 84)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids()), 1)
        self.assertAlmostEqual(shape.Volume(), expected, places=5)
        self.assertAlmostEqual(shape.BoundingBox().xlen, 100, places=5)
        self.assertAlmostEqual(shape.BoundingBox().zlen, 5, places=5)
        # 两个孔内应无材料，外侧连接部位应有材料。
        self.assertFalse(shape.isInside(cq.Vector(25, 0, 2.5)))
        self.assertTrue(shape.isInside(cq.Vector(45, 0, 2.5)))
        json.dumps(result, allow_nan=False)

    def test_each_feature_combination_keeps_connected_valid_solid(self):
        baseline = self.generate(enable_triz_lightening=False, enable_stress_relief=False)
        for lightening, relief in [(True, False), (False, True), (True, True)]:
            with self.subTest(lightening=lightening, relief=relief):
                result = self.generate(enable_triz_lightening=lightening,
                                       enable_stress_relief=relief)
                self.assertEqual(result["status"], "success", result)
                shape = cq.importers.importStep(result["output_file"]).val()
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids()), 1)
                self.assertLess(shape.Volume(), baseline["physical_properties"]["volume_mm3"])
                self.assertFalse(result["validation"]["strength_verified"])
                numbers = [entry["principle_number"] for entry in result["triz_logs"]]
                self.assertNotIn(15, numbers)
                self.assertEqual(2 in numbers, lightening)
                self.assertEqual(3 in numbers, relief)

    def test_invalid_parameters_return_json_error_without_artifacts(self):
        cases = [dict(length=-1), dict(width=10), dict(probe_distance=14),
                 dict(probe_distance=90), dict(length=float("nan")),
                 dict(width=float("inf")), dict(length=True),
                 dict(enable_triz_lightening="false"), dict(thickness=0),
                 dict(length=10000)]
        for case in cases:
            with self.subTest(case=case):
                result = self.generate(**case)
                self.assertEqual(result["status"], "error", result)
                self.assertIsNone(result["output_file"])
                self.assertTrue(result["error_message"])
                json.dumps(result, allow_nan=False)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_agent_dispatch_uses_whitelist_and_rejects_bad_json(self):
        for name, args in [("unknown_tool", {}), ("generate_sensor_bracket", "{"),
                           ("generate_sensor_bracket", []),
                           ("generate_sensor_bracket", self.params | {"output_dir": "elsewhere"})]:
            result = dispatch_tool_call(name, args, tool=self.tool)
            self.assertEqual(result["status"], "error")
        result = dispatch_tool_call("generate_sensor_bracket", json.dumps(self.params), tool=self.tool)
        self.assertEqual(result["status"], "success", result)

    def test_output_files_are_unique_and_export_failure_is_structured(self):
        first, second = self.generate(), self.generate()
        self.assertEqual(first["status"], "success", first)
        self.assertNotEqual(first["output_file"], second["output_file"])
        blocked = Path(self.tmp.name) / "file_instead_of_directory"
        blocked.write_text("保留已有文件", encoding="utf-8")
        result = CADTool(output_dir=blocked).generate_sensor_bracket(**self.params)
        self.assertEqual(result["status"], "error")
        self.assertEqual(blocked.read_text(encoding="utf-8"), "保留已有文件")

    def test_schema_matches_public_signature(self):
        import inspect
        definition = json.loads((ROOT / "tool_definition.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(definition["type"], "function")
        self.assertTrue(definition["strict"])
        schema = definition["parameters"]
        self.assertFalse(schema["additionalProperties"])
        names = set(inspect.signature(self.tool.generate_sensor_bracket).parameters)
        self.assertEqual(names, set(schema["properties"]))
        self.assertEqual(names, set(schema["required"]))


if __name__ == "__main__":
    unittest.main()

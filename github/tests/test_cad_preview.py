"""验证真实网格直接内嵌，预览不需要临时模型请求和显卡加速。"""
from pathlib import Path
import tempfile
import unittest
from cad_tool import CADTool
from cad_preview import preview_html


class PreviewTests(unittest.TestCase):
    def test_real_cad_mesh_is_embedded_with_fixed_height_and_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            result = CADTool(directory).generate_sensor_bracket(100,45,5,50)
            self.assertEqual(result['status'], 'success')
            html = preview_html(result['stl_file'])
        self.assertIn('height:380px', html)
        self.assertIn("canvas.getContext('2d')", html)
        self.assertIn('pointermove', html)
        self.assertNotIn('__CONFIG__', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('fetch(', html)

    def test_invalid_mesh_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.stl'
            path.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                preview_html(path)

"""以用户实际需求验收盒体，检查尺寸、壁厚、两个实体与盖子干涉。"""
import tempfile
import unittest
from unittest.mock import patch
import cadquery as cq
from box_tool import generate_box_with_lid
from app import process_request, parse_box_request
from streamlit.testing.v1 import AppTest
from pathlib import Path
import os


class BoxTests(unittest.TestCase):
    def test_user_description_routes_to_box_not_bracket(self):
        with patch('app.cad_tool.generate_sensor_bracket') as bracket:
            result=process_request('一个长150mm宽140mm，高100mm的长方体厚度为2mm，有盖子',None,mode='本地参数识别')
        self.assertEqual(result['status'],'success',result)
        self.assertEqual(result['model_type'],'box_with_lid')
        self.assertEqual(result['input_parameters']['height'],100)
        bracket.assert_not_called()

    def test_assembled_dimensions_walls_lid_fit_and_step_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            result=generate_box_with_lid(150,140,100,2,output_dir=directory)
            self.assertEqual(result['status'],'success',result)
            shape=cq.importers.importStep(result['output_file']).val()
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids()),2)
            bbox=shape.BoundingBox()
            for actual,expected in zip((bbox.xlen,bbox.ylen,bbox.zlen),(150,140,100)):
                self.assertAlmostEqual(actual,expected,places=5)
            body=cq.importers.importStep(result['parts'][0]['output_file']).val()
            # 盒体外高98，内腔146×136×96，壁/底厚2。
            self.assertAlmostEqual(body.Volume(),150*140*98-146*136*96,places=4)
            self.assertLess(result['validation']['interference_volume_mm3'],1e-5)

    def test_missing_dimensions_ask_instead_of_inventing(self):
        with self.assertRaisesRegex(ValueError,'缺少'):
            parse_box_request('做一个有盖子的盒子')
        old={'length':150.,'width':140.,'height':100.,'thickness':2.,'lid_clearance':.3}
        updated=parse_box_request('高度改为120',old)
        self.assertEqual(updated['height'],120)
        self.assertEqual(updated['width'],140)

    def test_invalid_wall_returns_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            result=generate_box_with_lid(10,10,10,8,output_dir=directory)
            self.assertEqual(result['status'],'error')

    def test_workbench_box_editing_and_switch_back_to_plate(self):
        with patch.dict(os.environ,{'AICAD_BILLING_MODE':'off'}):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
            app.chat_input[0].set_value('一个长150mm宽140mm，高100mm的长方体厚度为2mm，有盖子').run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.session_state['latest_result']['model_type'],'box_with_lid')
            self.assertEqual(app.number_input(key='edit_height').value,100.)
            app.number_input(key='edit_height').set_value(120.)
            app.button(key='FormSubmitter:dimensions-应用尺寸并生成').click().run()
            self.assertEqual(app.session_state['last_params']['height'],120.)
            app.button(key='preset_standard').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertNotIn('height',app.session_state['last_params'])

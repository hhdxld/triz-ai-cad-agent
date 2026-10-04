"""附件解析、视图确认和模型接口测试；不会调用真实付费 API。"""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
from streamlit.testing.v1 import AppTest

from app import DEFAULT_PARAMS, parse_local_request
from attachment_input import MAX_BYTES, confirmed_prompt, read_attachment, recognize_image


class AttachmentTests(unittest.TestCase):
    def test_partial_json_and_units_do_not_invent_missing_dimensions(self):
        result = read_attachment('part.json', b'{"length":"14cm","probe_dia":16.5}')
        self.assertEqual(result['observed'], {'length': 140., 'probe_dia': 16.5})
        self.assertNotIn('thickness', result['observed'])
        self.assertEqual(parse_local_request(confirmed_prompt(DEFAULT_PARAMS)), DEFAULT_PARAMS)

    def test_csv_and_text_extract_actual_values(self):
        result = read_attachment('part.csv', b'parameter,value\nlength,140\nenable_triz_lightening,false')
        self.assertEqual(result['observed'], {'length': 140., 'enable_triz_lightening': False})
        result = read_attachment('part.txt', '长度100毫米，宽45毫米'.encode())
        self.assertEqual(result['observed'], {'length': 100., 'width': 45.})

    def test_box_document_and_confirmation_keep_box_shape(self):
        result=read_attachment('box.txt','长150mm宽140mm高100mm，壁厚2mm，有盖子'.encode())
        self.assertEqual(result['model_type'],'box_with_lid')
        self.assertEqual(result['observed']['height'],100.)
        self.assertNotIn('probe_dia',result['observed'])

    def test_untrusted_file_limits_and_parameter_types(self):
        for name, data in [('x.json', b'{"length":NaN}'), ('x.json', b'{"length":true}'),
                           ('x.json', b'{"length":100,"length":140}'), ('x.json', b'{"code":"evil"}'),
                           ('x.json', b'{"thickness":200}'), ('x.exe', b'evil'),
                           ('x.txt', b'x' * (MAX_BYTES + 1)), ('x.png', b'not a picture')]:
            with self.subTest(name=name, data=data[:60]):
                with self.assertRaises(ValueError):
                    read_attachment(name, data)

    def test_image_and_scanned_pdf_are_not_silently_treated_as_dimensions(self):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 40), 'white').save(buffer, 'PNG')
        image = read_attachment('drawing.png', buffer.getvalue())
        self.assertEqual(image['kind'], 'image')
        self.assertEqual(image['observed'], {})
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        pdf = io.BytesIO()
        writer.write(pdf)
        with self.assertRaisesRegex(ValueError, '没有可提取'):
            read_attachment('scan.pdf', pdf.getvalue())

    def test_text_pdf_dimension_extraction(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=600)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 20 500 Td (length100 width45 thickness5 probe_distance50 probe_dia16.5) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        output = io.BytesIO()
        writer.write(output)
        observed = read_attachment('drawing.pdf', output.getvalue())['observed']
        self.assertEqual(observed, {key: DEFAULT_PARAMS[key] for key in ('length', 'width', 'thickness', 'probe_distance', 'probe_dia')})

    def test_vision_protocols_and_null_dimensions(self):
        for protocol in ('Responses', 'Chat Completions'):
            with self.subTest(protocol=protocol), patch('openai.OpenAI') as factory:
                client = factory.return_value.__enter__.return_value
                content = json.dumps({'supported': True, 'parameters': {'length': 140, 'thickness': None}, 'notes': '厚度未标注'})
                client.responses.create.return_value.output_text = content
                client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content=content))]
                result = recognize_image(b'image', api_key='test-secret', base_url='https://example.invalid/v1', model='vision', protocol=protocol)
                self.assertEqual(result['observed'], {'length': 140.})
                if protocol == 'Responses':
                    payload = client.responses.create.call_args.kwargs['input'][0]['content'][1]
                    self.assertEqual(payload['type'], 'input_image')
                else:
                    payload = client.chat.completions.create.call_args.kwargs['messages'][1]['content'][1]
                    self.assertEqual(payload['type'], 'image_url')

    def test_attachment_form_requires_confirmation_before_real_cad(self):
        upload = MagicMock(name='uploaded-file')
        upload.name = 'dimensions.json'
        upload.getvalue.return_value = json.dumps(DEFAULT_PARAMS).encode()
        script = '''
import streamlit as st
from attachment_ui import render_attachment
from app import process_request
def submit(prompt, local=False):
    st.session_state['result'] = process_request(prompt, None, mode='本地参数识别')
render_attachment(submit, user=None, login_required=False, public=True)
'''
        with patch('streamlit.file_uploader', return_value=upload):
            app = AppTest.from_string(script, default_timeout=30).run()
            self.assertEqual(len(app.exception), 0)
            button = next(x for x in app.button if x.label == '确认参数并生成 CAD')
            button.click().run()
            self.assertNotIn('result', app.session_state)
            next(x for x in app.checkbox if x.key.startswith('attachment_confirmed_')).check()
            next(x for x in app.button if x.label == '确认参数并生成 CAD').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['result']['status'], 'success')

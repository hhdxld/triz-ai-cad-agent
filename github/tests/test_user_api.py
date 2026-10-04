"""自带 API 的密钥隔离、退出清理、账本与充值占位测试；不发送真实请求。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from business import BusinessStore
from app import process_request

ROOT=Path(__file__).resolve().parents[1]


class UserAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'site.sqlite'
        self.store=BusinessStore(self.path)
        self.user=self.store.register('customer','customer-password-test')
        self.store.set_api_provider(self.store.create_admin('owner','owner-password-test')['id'],'openai')
        env=patch.dict('os.environ',{'AICAD_DATABASE_PATH':str(self.path),'AICAD_BILLING_MODE':'demo',
            'OPENAI_API_KEY':'site-key-not-for-customer','OPENAI_MODEL':'site-model','AICAD_ALLOW_DEMO_API':'false'})
        env.start()
        self.addCleanup(env.stop)

    def app(self):
        app=AppTest.from_file(str(ROOT/'hosted_app.py'),default_timeout=30)
        app.session_state['account_id']=self.user['id']
        return app.run()

    def test_user_key_is_used_instead_of_site_key_and_not_stored_in_ledger(self):
        app=self.app()
        self.assertTrue(app.button(key='recharge_pending').disabled)
        app.radio[0].set_value('在线模型 API').run()
        app.radio(key='ai_source').set_value('使用自己的 API').run()
        app.selectbox(key='personal_api_provider').set_value('deepseek').run()
        app.text_input(key='personal_api_model_deepseek').set_value('my-model').run()
        app.text_input(key='personal_api_key_deepseek').set_value('user-only-test-secret').run()
        app.checkbox(key='personal_api_consent').check().run()
        next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
        result=process_request('长150宽140高100厚2，有盖子',None,mode='本地参数识别')
        with patch('app.process_request',return_value=result) as mock:
            app.chat_input[0].set_value('做长150宽140高100厚2的带盖盒子').run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(mock.call_args.kwargs['api_key'],'user-only-test-secret')
        self.assertEqual(mock.call_args.kwargs['model'],'my-model')
        self.assertIn('api.deepseek.com',mock.call_args.kwargs['base_url'])
        self.assertNotIn('user-only-test-secret',str(self.store.orders(self.user['id'])))
        self.assertNotIn('user-only-test-secret',str(app.session_state['messages']))
        self.assertEqual(self.store.user(self.user['id'])['balance_fen'],900)
        app.button(key='logout').click().run()
        for key in ('personal_api_key_deepseek','personal_api_model_deepseek','personal_api_consent'):
            self.assertNotIn(key,app.session_state)

    def test_switch_to_site_clears_user_key_and_does_not_unlock_site_credit(self):
        app=self.app()
        app.radio[0].set_value('在线模型 API').run()
        app.radio(key='ai_source').set_value('使用自己的 API').run()
        app.text_input(key='personal_api_key_openai').set_value('private-test-only').run()
        app.radio(key='ai_source').set_value('使用站内 API').run()
        for key in ('personal_api_key_openai','personal_api_model_openai','personal_api_consent'):
            self.assertNotIn(key,app.session_state)
        next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
        with patch('app.process_request') as generate:
            app.chat_input[0].set_value('做带盖盒子长150宽140高100厚2').run()
            generate.assert_not_called()
        self.assertEqual(self.store.orders(self.user['id']),[])

    def test_no_user_consent_never_falls_back_to_owner_key(self):
        app=self.app()
        app.radio[0].set_value('在线模型 API').run()
        app.radio(key='ai_source').set_value('使用自己的 API').run()
        app.text_input(key='personal_api_model_openai').set_value('test-model').run()
        app.text_input(key='personal_api_key_openai').set_value('private-key-test').run()
        next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
        with patch('app.process_request') as generate:
            app.chat_input[0].set_value('长100宽45厚5孔距50').run()
            generate.assert_not_called()
        self.assertEqual(self.store.orders(self.user['id']),[])

    def test_clear_button_resets_password_widget(self):
        app=self.app()
        app.radio[0].set_value('在线模型 API').run()
        app.radio(key='ai_source').set_value('使用自己的 API').run()
        app.text_input(key='personal_api_key_openai').set_value('private-key-test').run()
        app.button(key='personal_api_clear').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.text_input(key='personal_api_key_openai').value,'')

    def test_site_model_choice_uses_selected_provider_without_showing_key(self):
        with patch.dict('os.environ',{'KIMI_API_KEY':'kimi-site-test-private','KIMI_MODEL':'kimi-k2.6'}):
            app=self.app()
            app.radio[0].set_value('在线模型 API').run()
            self.assertTrue(any('Kimi' in item for item in app.selectbox(key='site_api_provider').options))
            app.selectbox(key='site_api_provider').set_value('kimi').run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any('kimi-k2.6' in item.value for item in app.caption))
            self.assertFalse(any('kimi-site-test-private' in item.value for item in app.text_input))
            # 选择新厂商也不能绕过普通用户的站内额度开关。
            next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
            with patch('app.process_request') as generate:
                app.chat_input[0].set_value('做一个带盖盒子长150宽140高100厚2').run()
                generate.assert_not_called()
            admin=self.store.authenticate('owner','owner-password-test')
            app.session_state['account_id']=admin['id']
            app.run()
            next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
            result=process_request('长150宽140高100厚2，有盖子',None,mode='本地参数识别')
            with patch('app.process_request',return_value=result) as generate:
                app.chat_input[0].set_value('做一个带盖盒子长150宽140高100厚2').run()
                self.assertEqual(generate.call_args.kwargs['api_key'],'kimi-site-test-private')
                self.assertEqual(generate.call_args.kwargs['model'],'kimi-k2.6')

"""验证厂商隔离、管理员切换与盒子工具调用；不访问真实模型服务。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from api_providers import PROVIDERS, provider_settings
from business import BusinessStore, BusinessError
from app import extract_api_parameters
from box_tool import BOX_DEFAULTS


class ProviderTests(unittest.TestCase):
    def test_keys_are_never_reused_across_providers(self):
        values={'OPENAI_API_KEY':'owner-openai-secret','OPENAI_MODEL':'original',
                'DEEPSEEK_API_KEY':'separate-deepseek-secret','DEEPSEEK_MODEL':'deepseek-model'}
        setting=lambda key,default='':values.get(key,default)
        self.assertEqual(provider_settings('deepseek',setting)['api_key'],'separate-deepseek-secret')
        self.assertEqual(provider_settings('deepseek',setting)['protocol'],'Chat Completions')
        self.assertEqual(provider_settings('qwen',setting)['api_key'],'')
        self.assertEqual(provider_settings('qwen',setting)['model'],'')

    def test_url_validation_and_all_presets(self):
        for provider in PROVIDERS:
            result=provider_settings(provider,lambda key,default='':default)
            self.assertEqual(result['provider'],provider)
        with self.assertRaises(ValueError):
            provider_settings('custom',lambda key,default='':'http://localhost:1234' if key.endswith('BASE_URL') else default)

    def test_kimi_uses_its_own_key_and_official_endpoint(self):
        values={'KIMI_API_KEY':'kimi-test-only','KIMI_MODEL':'kimi-k2.6',
                'DEEPSEEK_API_KEY':'different-secret'}
        result=provider_settings('kimi',lambda key,default='':values.get(key,default))
        self.assertEqual(result['api_key'],'kimi-test-only')
        self.assertEqual(result['base_url'],'https://api.moonshot.cn/v1')
        self.assertEqual(result['model'],'kimi-k2.6')

    def test_only_admin_can_switch_provider_and_selection_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'site.sqlite'
            store=BusinessStore(path)
            customer=store.register('customer','a-customer-password')
            admin=store.create_admin('owner','owner-password-test')
            with self.assertRaises(BusinessError):
                store.set_api_provider(customer['id'],'deepseek')
            store.set_api_provider(admin['id'],'deepseek')
            self.assertEqual(BusinessStore(path).api_provider(),'deepseek')
            with self.assertRaises(BusinessError):
                store.set_api_provider(admin['id'],'unknown')

    def test_compatible_api_can_select_box_tool_with_strict_removed(self):
        with patch('openai.OpenAI') as factory:
            client=factory.return_value.__enter__.return_value
            call=MagicMock()
            call.function.name='generate_box_with_lid'
            call.function.arguments=json.dumps(BOX_DEFAULTS)
            client.chat.completions.create.return_value.choices=[MagicMock(message=MagicMock(tool_calls=[call]))]
            params=extract_api_parameters('做一个150x140x100厚2mm带盖盒子',None,api_key='test-secret',
                base_url='https://api.deepseek.com/v1',model='test-model')
            self.assertEqual(params,BOX_DEFAULTS)
            payload=client.chat.completions.create.call_args.kwargs
            self.assertEqual(len(payload['tools']),2)
            self.assertNotIn('strict',payload['tools'][0]['function'])

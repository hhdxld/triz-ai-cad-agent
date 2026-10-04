"""验证跨会话项目、账户隔离、密码变更与会话失效；不调用付费 API。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from business import BusinessStore, BusinessError, run_service
from app import process_request
from attachment_input import read_attachment

ROOT=Path(__file__).resolve().parents[1]


class ProjectAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'site.sqlite'
        self.store=BusinessStore(self.path)
        self.user=self.store.register('customer','customer-password')
        self.other=self.store.register('different','different-password')
        env=patch.dict('os.environ',{'AICAD_DATABASE_PATH':str(self.path),'AICAD_BILLING_MODE':'demo'})
        env.start();self.addCleanup(env.stop)

    def order(self):
        return run_service(self.store,self.user['id'],'box-order','长150宽140高100厚2，有盖子',
            lambda:process_request('长150宽140高100厚2，有盖子',None,mode='本地参数识别'))

    def test_save_reopen_and_delete_are_owned_and_do_not_charge(self):
        result=self.order()
        project=self.store.save_project(self.user['id'],result['service_order_id'],'我的盒子')
        balance=self.store.user(self.user['id'])['balance_fen']
        reopened=BusinessStore(self.path).load_project(self.user['id'],project)
        self.assertEqual(reopened['input_parameters']['height'],100)
        self.assertEqual(len(self.store.projects(self.user['id'])),1)
        self.assertEqual(self.store.projects(self.other['id']),[])
        for operation in (lambda:self.store.load_project(self.other['id'],project),
                          lambda:self.store.delete_project(self.other['id'],project),
                          lambda:self.store.save_project(self.other['id'],result['service_order_id'],'窃取')):
            with self.assertRaises(BusinessError):operation()
        self.store.delete_project(self.user['id'],project)
        self.assertEqual(self.store.projects(self.user['id']),[])
        self.assertTrue(Path(result['output_file']).is_file())
        self.assertEqual(self.store.user(self.user['id'])['balance_fen'],balance)

    def test_failed_orders_cannot_be_saved(self):
        result=run_service(self.store,self.user['id'],'failure','invalid',lambda:{'status':'error','error_message':'invalid'})
        with self.assertRaises(BusinessError):
            self.store.save_project(self.user['id'],result['service_order_id'],'失败')

    def test_saving_same_order_updates_name_instead_of_duplicate(self):
        result=self.order()
        first=self.store.save_project(self.user['id'],result['service_order_id'],'第一版')
        second=self.store.save_project(self.user['id'],result['service_order_id'],'第二版')
        self.assertEqual(first,second)
        self.assertEqual(self.store.projects(self.user['id'])[0]['name'],'第二版')

    def test_password_requires_old_password_and_invalidates_previous_version(self):
        with self.assertRaises(BusinessError):
            self.store.change_password(self.user['id'],'wrong-password','new-password-test')
        self.assertIsNotNone(self.store.authenticate('customer','customer-password'))
        version=self.store.user(self.user['id'])['auth_version']
        changed=self.store.change_password(self.user['id'],'customer-password','new-password-test')
        self.assertEqual(changed['auth_version'],version+1)
        self.assertIsNone(self.store.authenticate('customer','customer-password'))
        self.assertIsNotNone(self.store.authenticate('customer','new-password-test'))

    def test_admin_user_search_does_not_expose_password_hashes(self):
        admin=self.store.create_admin('owner','owner-password-test')
        with self.assertRaises(BusinessError):self.store.users(self.user['id'])
        rows=self.store.users(admin['id'],'customer')
        self.assertEqual(len(rows),1)
        self.assertNotIn('password_hash',rows[0])
        self.assertNotIn('salt',rows[0])

    def test_site_api_trial_access_must_be_granted_by_admin(self):
        admin=self.store.create_admin('owner','owner-password-test')
        self.assertFalse(self.store.user(self.user['id'])['site_api_access'])
        with self.assertRaises(BusinessError):
            self.store.set_site_api_access(self.other['id'],self.user['id'],True)
        self.store.set_site_api_access(admin['id'],self.user['id'],True)
        self.assertTrue(self.store.user(self.user['id'])['site_api_access'])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'owner-trial-test','OPENAI_MODEL':'test-model','AICAD_ALLOW_DEMO_API':'false'}):
            self.store.set_api_provider(admin['id'],'openai')
            app=AppTest.from_file(str(ROOT/'hosted_app.py'),default_timeout=30)
            app.session_state['account_id']=self.user['id']
            app.run()
            app.radio[0].set_value('在线模型 API').run()
            next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
            result=process_request('长100宽45厚5孔距50',None,mode='本地参数识别')
            with patch('app.process_request',return_value=result) as generate:
                app.chat_input[0].set_value('做一个双探头安装板').run()
                self.assertEqual(generate.call_args.kwargs['api_key'],'owner-trial-test')
            self.store.set_site_api_access(admin['id'],self.user['id'],False)
            app.run()
            with patch('app.process_request') as generate:
                app.chat_input[0].set_value('长度改为140').run()
                generate.assert_not_called()

    def test_projects_ui_restores_without_new_order(self):
        result=self.order()
        project=self.store.save_project(self.user['id'],result['service_order_id'],'盒子验收')
        app=AppTest.from_file(str(ROOT/'hosted_app.py'),default_timeout=30)
        app.session_state['account_id']=self.user['id']
        app.run()
        app.selectbox(key='project_selected').set_value(project).run()
        with patch('app.process_request') as generate:
            app.button(key='project_open').click().run()
            generate.assert_not_called()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['last_params']['height'],100)
        self.assertEqual(len(self.store.orders(self.user['id'])),1)
        self.assertTrue(any(x.label=='下载参数 JSON' for x in app.get('download_button')))
        app.checkbox(key='project_delete_confirm').check().run()
        app.button(key='project_delete').click().run()
        self.assertEqual(self.store.projects(self.user['id']),[])

    def test_box_preset_can_be_saved_from_ui_and_parameters_reimported(self):
        app=AppTest.from_file(str(ROOT/'hosted_app.py'),default_timeout=30)
        app.session_state['account_id']=self.user['id']
        app.run()
        next(x for x in app.checkbox if x.key.startswith('fee_consent_')).check().run()
        app.button(key='preset_box').click().run()
        app.text_input(key='project_name').set_value('我的带盖盒子')
        app.button(key='FormSubmitter:project_save-保存当前设计').click().run()
        self.assertEqual(len(app.exception),0)
        projects=self.store.projects(self.user['id'])
        self.assertEqual(len(projects),1)
        parameters=self.store.load_project(self.user['id'],projects[0]['id'])['input_parameters']
        parsed=read_attachment('cad-parameters.json',json.dumps(parameters).encode())
        self.assertEqual(parsed['model_type'],'box_with_lid')
        self.assertEqual(parsed['observed'],parameters)
        self.assertEqual(self.store.user(self.user['id'])['balance_fen'],900)

    def test_password_change_logs_out_other_session_on_next_interaction(self):
        app=AppTest.from_file(str(ROOT/'hosted_app.py'))
        app.session_state['account_id']=self.user['id']
        app.run()
        self.store.change_password(self.user['id'],'customer-password','new-password-test')
        app.run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.chat_input),0)
        self.assertNotIn('account_id',app.session_state)

    def test_password_form_clears_secrets_after_success(self):
        app=AppTest.from_file(str(ROOT/'hosted_app.py'))
        app.session_state['account_id']=self.user['id']
        app.run()
        app.text_input(key='change_old_password').set_value('customer-password')
        app.text_input(key='change_new_password').set_value('new-password-test')
        app.text_input(key='change_confirm_password').set_value('new-password-test')
        app.button(key='FormSubmitter:change_password-修改密码').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.text_input(key='change_new_password').value,'')
        self.assertIsNotNone(self.store.authenticate('customer','new-password-test'))

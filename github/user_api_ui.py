"""访客自带 API：只保存在当前会话，使用预设官方地址，绝不回退站长密钥。"""
import streamlit as st
from api_providers import PROVIDERS, provider_settings
from business_ui import server_api_settings, configured_site_providers


def render_api_choice(user: dict | None, login_required: bool) -> tuple[dict, bool]:
    """返回本次选择的配置与是否使用自带密钥；不会发送测试请求。"""
    source=st.radio('AI 费用来源',['使用站内 API','使用自己的 API'],key='ai_source')
    personal=source=='使用自己的 API'
    if not personal:
        settings=server_api_settings()
        available=configured_site_providers()
        if available:
            # 只显示服务端已配置的厂商，选择值仍经白名单读取配置。
            default=settings['provider'] if settings['provider'] in available else available[0]
            if st.session_state.get('site_api_provider',default) not in available:
                st.session_state.pop('site_api_provider',None)
            selected=st.selectbox('站内 AI 模型',available,index=available.index(default),
                format_func=lambda name:PROVIDERS[name]['label'],key='site_api_provider')
            settings=server_api_settings(selected)
        st.caption('站内服务商：'+settings['provider_label'])
        if settings['model']:
            st.caption('模型：'+settings['model'])
        if settings['api_key'] and settings['model']:
            st.success('站内模型已配置')
        else:
            st.info('站内模型尚未配置，可以使用自己的 API。')
        if login_required and user and user['role'] != 'admin' and not user.get('site_api_access') and not settings['allow_demo_api']:
            st.info('站内 API 暂未对普通演示账户开放；充值待开发，可选择自己的 API。')
        elif user and user.get('site_api_access'):
            st.caption('管理员已授予站内模型试用权限；服务费仍为演示记账，模型费用由站长承担。')
        return settings,False
    if login_required and not user:
        st.info('请先登录，再填写自己的 API。')
        return {'api_key':'','base_url':'','model':'','protocol':'Chat Completions','allow_demo_api':False},True
    # 访客只能选预设官方服务商，不向网站后端提交任意网络地址。
    choices=[name for name in PROVIDERS if name!='custom']
    provider=st.selectbox('你的 API 服务商',choices,format_func=lambda name:PROVIDERS[name]['label'],key='personal_api_provider')
    st.caption('模型费用由你的供应商账户承担；本站 CAD 服务仍按页面报价计费，目前为演示。')
    model=st.text_input('你的模型名称',key='personal_api_model_'+provider,max_chars=200)
    key=st.text_input('你的 API Key',type='password',key='personal_api_key_'+provider,max_chars=512)
    consent=st.checkbox('同意由本站服务器使用我的密钥向所选服务商发送需求',key='personal_api_consent')
    st.caption('密钥仅在当前会话使用，不保存到网站配置、订单或日志；退出登录、登录超时或切回站内 API 后清除。')
    if st.button('清除我的 API 配置',key='personal_api_clear'):
        for name in list(st.session_state):
            if name.startswith('personal_api_'):
                st.session_state.pop(name,None)
        st.rerun()
    prefix=PROVIDERS[provider]['prefix']
    values={prefix+'_API_KEY':key.strip() if consent else '',prefix+'_MODEL':model.strip()}
    settings=provider_settings(provider,lambda name,default='':values.get(name,default))
    settings['user_consent']=consent
    return settings,True

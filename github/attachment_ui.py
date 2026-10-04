"""附件导入界面：预览与参数确认后才进入现有计费/建模流程。"""
import hashlib
import json

import streamlit as st

from attachment_input import NUMERIC, confirmed_prompt, read_attachment, recognize_image
from app import DEFAULT_PARAMS, LABELS
from box_tool import BOX_DEFAULTS
from business import BusinessError
from business_ui import server_api_settings
from public_service import run_public


def render_attachment(submit, *, user: dict | None, login_required: bool, public: bool,
                      api_settings: dict | None = None, personal_api: bool = False) -> None:
    """附件只保留于当前会话；图片传出前须获得用户明确勾选同意。"""
    with st.expander("📎 从图片或文件创建设计", expanded=False):
        st.caption("支持尺寸图 PNG/JPG、PDF、TXT、JSON、CSV。先检查尺寸，再确认生成。单文件最多 5 MB。")
        st.download_button("下载参数 JSON 示例", json.dumps(DEFAULT_PARAMS, ensure_ascii=False, indent=2),
                           'bracket-parameters.json', 'application/json', key='attachment_template')
        st.download_button('下载带盖盒子参数示例',json.dumps(BOX_DEFAULTS,ensure_ascii=False,indent=2),
            'box-parameters.json','application/json',key='attachment_box_template')
        file = st.file_uploader("上传图纸、照片或参数文件", type=['png', 'jpg', 'jpeg', 'pdf', 'txt', 'json', 'csv'],
                                key='attachment_upload')
        if file is None:
            st.session_state.pop('attachment_draft', None)
            return
        data = file.getvalue()
        fingerprint = hashlib.sha256(file.name.encode() + data).hexdigest()[:20]
        if fingerprint != st.session_state.get('attachment_fingerprint'):
            st.session_state.attachment_fingerprint = fingerprint
            st.session_state.pop('attachment_draft', None)
        try:
            parsed = read_attachment(file.name, data)
        except (ValueError, ImportError) as exc:
            st.error(str(exc) if isinstance(exc, ValueError) else "PDF 解析组件尚未安装，请更新项目依赖。")
            return
        if parsed['kind'] == 'image':
            st.image(parsed['image'], caption='上传的参考图片')
            st.caption("普通照片不能确定绝对尺寸。请优先上传带尺寸、单位和厚度标注的工程图。")
            settings = api_settings or server_api_settings()
            allowed = not public and (not login_required or bool(user)) and (
                personal_api or settings['allow_demo_api'] or (user and (user['role'] == 'admin' or user.get('site_api_access'))))
            consent = st.checkbox("同意将这张图片发送给本站模型服务商进行识别", key=f'attachment_send_{fingerprint}')
            if not allowed or not settings['api_key'] or not settings['model']:
                st.info("请先填写自带 API 配置并勾选授权；所选模型需支持图片。" if personal_api else "图片自动识别尚未启用，需要站长配置支持图片的 API；仍可参考图片手动补齐下方参数。")
            if st.button("识别图片中的尺寸", key='attachment_recognize',
                         disabled=not (allowed and consent and settings['api_key'] and settings['model'])):
                try:
                    used = st.session_state.get('attachment_api_requests', 0)
                    if used >= 5:
                        raise ValueError("当前会话已达 5 次图片识别上限。")
                    st.session_state.attachment_api_requests = used + 1
                    with st.spinner("正在识别标注尺寸…"):
                        result = run_public('attachment vision preview', lambda: {
                            'status': 'success', 'draft': recognize_image(parsed['image'], api_key=settings['api_key'],
                                base_url=settings['base_url'], model=settings['model'], protocol=settings['protocol'])})
                    if result.get('status') != 'success':
                        raise ValueError("图片识别失败，请检查 API 配置或手动补齐尺寸。")
                    st.session_state.attachment_draft = result['draft']
                    st.rerun()
                except (ValueError, BusinessError) as exc:
                    st.error(str(exc))
            draft = st.session_state.get('attachment_draft', {'observed': {}, 'notes': ''})
            st.caption("图片识别消耗"+('你的 API 额度' if personal_api else '站长 API 额度')+"，当前不扣用户演示余额；确认生成才按现有服务费结算。")
        else:
            draft = {'observed': parsed['observed'], 'notes': '', 'model_type': parsed.get('model_type')}
            if parsed.get('text'):
                with st.expander('查看提取内容'):
                    st.text(parsed['text'][:12000])
        observed = draft['observed']
        detected_box = draft.get('model_type') == 'box_with_lid' or 'height' in observed
        kind=st.radio('资料对应的零件类型',['双探头安装板','带盖空心盒'],index=1 if detected_box else 0,
            key='attachment_type_'+fingerprint+'_'+str(draft.get('model_type','manual')),horizontal=True)
        box=kind=='带盖空心盒'
        defaults = BOX_DEFAULTS if box else DEFAULT_PARAMS
        if set(observed)-set(defaults):
            st.warning('资料含有当前零件类型不使用的参数，请确认类型选择正确；未使用的参数不会进入模型。')
        if draft.get('notes'):
            st.write(draft['notes'])
        st.table([{'参数': LABELS[key], '值': observed.get(key, defaults[key]),
                   '来源': '资料识别 · 请核对' if key in observed else '推荐值 · 资料未提供'} for key in defaults])
        st.warning("资料未提供的尺寸不会按图片比例猜测。请核对推荐值，填写实际尺寸后再生成。当前支持双探头安装板和带盖空心盒。")
        # 识别草稿变化时换表单键，使最新识别尺寸同步显示，不沿用旧上传内容。
        revision = hashlib.sha256((kind+json.dumps(observed, sort_keys=True)).encode()).hexdigest()[:8]
        with st.form(f'attachment_confirm_{fingerprint}_{revision}'):
            params = {}
            for key in (tuple(BOX_DEFAULTS) if box else NUMERIC):
                minimum = .05 if key == 'lid_clearance' else .5 if key == 'thickness' else .1 if key == 'probe_dia' else 1.
                params[key] = st.number_input(LABELS[key] + ' / mm', min_value=minimum, max_value=2. if key == 'lid_clearance' else 100. if key == 'thickness' else 1000.,
                    value=float(observed.get(key, defaults[key])), key=f'attachment_value_{fingerprint}_{revision}_{key}')
            for key in (() if box else ('enable_triz_lightening', 'enable_stress_relief')):
                params[key] = st.checkbox(LABELS[key], value=observed.get(key, DEFAULT_PARAMS[key]),
                                         key=f'attachment_value_{fingerprint}_{revision}_{key}')
            confirmed = st.checkbox("已核对图纸、单位和全部尺寸，同意按本站当前价格生成",
                                    key=f'attachment_confirmed_{fingerprint}_{revision}')
            if st.form_submit_button('确认参数并生成 CAD', type='primary'):
                if not confirmed:
                    st.error('请先核对并确认参数。')
                else:
                    submit(confirmed_prompt(params), local=True)

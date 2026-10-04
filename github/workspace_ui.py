"""本地 CAD 网站的操作工作台；界面不依赖 CDN 或在线模型服务。"""

from pathlib import Path
from typing import Callable
from uuid import uuid4

import streamlit as st
from cad_preview import render_preview
from business import BusinessError, run_service
from business_ui import get_store, server_api_settings, render_account, render_orders, clear_design
from public_service import run_public
from attachment_ui import render_attachment
from box_tool import BOX_DEFAULTS
from user_api_ui import render_api_choice
from project_ui import render_projects, render_project_exports


STYLE = """
<style>
.stApp {background:#f5f7fb;}
.block-container {padding-top:2rem; padding-bottom:2rem; max-width:1600px;}
[data-testid="stSidebar"] {background:#fff; border-right:1px solid #e4e9f1;}
h1,h2,h3 {color:#15233b; letter-spacing:-.035em;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius:16px;}
[data-testid="stMetric"] {background:#fff; border:1px solid #e5eaf3;
 padding:14px 16px; border-radius:12px;}
[data-testid="stChatMessage"] {background:#fff; border:1px solid #e9edf5; border-radius:12px;}
.eyebrow {font-size:12px; font-weight:700; letter-spacing:2px; color:#5274a9; margin:0 0 8px;}
.steps {display:flex; gap:10px; flex-wrap:wrap; margin:16px 0 26px;}
.steps span {font-size:12px; color:#546680; background:#fff; border:1px solid #e3e9f3;
 padding:7px 13px; border-radius:20px;}
.empty-preview {height:320px; background:linear-gradient(135deg,#edf3ff,#fff);
 border:1px dashed #ccd8eb; border-radius:14px; display:flex; flex-direction:column;
 align-items:center; justify-content:center; color:#61738e; text-align:center;}
.empty-preview svg {width:min(85%,360px); height:160px; margin-bottom:22px;}
.empty-preview strong {color:#263e61; font-size:18px; margin-bottom:8px;}
.empty-preview small {font-size:13px;}
@media (max-width:768px) {.block-container {padding:1rem;} .steps {margin-bottom:15px;}}
</style>
"""

EMPTY_PREVIEW = """
<div class="empty-preview">
<svg viewBox="0 0 380 160" role="img" aria-label="双探头安装板结构示意图">
 <defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
 <path d="M20 0H0V20" fill="none" stroke="#dce6f5" stroke-width=".6"/></pattern></defs>
 <rect width="380" height="160" fill="url(#grid)"/>
 <path d="M50 70L275 32L332 85L107 123Z" fill="#c7dafa" stroke="#668ac2" stroke-width="2"/>
 <path d="M107 123L332 85V97L107 135L50 82V70Z" fill="#8facd7" stroke="#668ac2" stroke-width="2"/>
 <ellipse cx="123" cy="84" rx="22" ry="13" fill="#f5f8fd" stroke="#668ac2" stroke-width="2"/>
 <ellipse cx="255" cy="62" rx="22" ry="13" fill="#f5f8fd" stroke="#668ac2" stroke-width="2"/>
 <path d="M172 81L204 76" stroke="#668ac2" stroke-width="18" stroke-linecap="round"/>
 <path d="M172 81L204 76" stroke="#f5f8fd" stroke-width="14" stroke-linecap="round"/>
</svg>
<strong>你的下一件零件，从一句描述开始</strong>
<small>左侧选择示例或输入尺寸 · 上图为结构示意</small>
</div>
"""


def render_workspace(process_request: Callable, format_report: Callable,
                     defaults: dict, labels: dict, *, public: bool = False) -> None:
    """呈现对话、示例、尺寸编辑、真实三维预览与设计报告。"""
    st.set_page_config(page_title="TRIZ AI CAD Agent", page_icon="⚙️", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    for key, value in {
        "messages": [{"role": "assistant", "content":
            "当前支持双探头安装板和带盖空心盒。未连接模型 API 时使用本地参数工具，不是 AI 对话。\n\n"
            "试试：**长100、宽45、厚5、孔距50、孔径16.5毫米，开启减重。**\n\n"
            "之后可以说“长度改为140”，其他参数会保留。未填写的初始尺寸采用推荐值。"}],
        "last_params": None, "latest_result": None, "editor_sync": True,
        "last_error": "",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value
    try:
        store = None if public else get_store()
    except BusinessError as exc:
        st.error(str(exc))
        return

    # 对话修改或切换示例后，在创建输入框之前同步尺寸，避免表单显示旧值。
    if st.session_state.editor_sync:
        current = st.session_state.last_params or defaults
        for key, value in current.items():
            st.session_state[f"edit_{key}"] = float(value) if not isinstance(value, bool) else value
        st.session_state.editor_sync = False

    with st.sidebar:
        st.markdown("### ⚙ TRIZ CAD")
        st.caption("参数化机械设计工作台")
        st.divider()
        user, fee_consent, quoted_fen = render_account(store)
        mode = st.radio("需求理解方式", ["本地参数识别"] if public else ["本地参数识别", "在线模型 API"])
        personal_api = False
        configuration = None
        api_key, base_url, model, protocol = "", "", "", "Chat Completions"
        if mode == "本地参数识别":
            st.success("本地可用 · 无需 API 密钥")
            st.caption("支持明确尺寸、厘米/毫米与功能开关。复杂自然语言可切换在线模型。")
        else:
            configuration, personal_api = render_api_choice(user,store is not None)
            api_key, base_url = configuration["api_key"], configuration["base_url"]
            model, protocol = configuration["model"], configuration["protocol"]
        if not personal_api:
            for state_key in list(st.session_state):
                if state_key.startswith('personal_api_'):
                    st.session_state.pop(state_key,None)
        if public:
            st.success("公开体验 · 免费 · 免登录")
            st.caption("本地规则理解明确尺寸，不调用付费模型 API。单个浏览器会话最多 10 次建模请求。")
        st.divider()
        st.caption("预览设置")
        color = st.color_picker("模型颜色", "#4F8BFF")
        auto_rotate = st.toggle("自动旋转", False)
        if st.button("开始新设计", key="new_design", use_container_width=True):
            clear_design()
            st.rerun()
        st.divider()
        st.caption("当前零件：" + ("带盖空心盒" if st.session_state.last_params and 'height' in st.session_state.last_params else "双探头平面安装板") + "\n\n材料：6061 铝（重量估算）\n\n输出：STEP / STL")
        with st.expander("怎么使用？"):
            st.markdown("1. 选择安装板或带盖盒子示例，也可上传尺寸资料。\n2. 输入修改需求，或打开尺寸编辑。\n3. 旋转预览，下载 STEP、参数和报告。\n4. 在“我的项目”保存成果，下次登录继续修改。")
            st.caption("支持：双探头平面板、减重槽、倒角，以及带独立盖子的空心盒。其他零件类型会提示能力范围。")

    st.markdown('<p class="eyebrow">DESCRIBE · DESIGN · BUILD</p>', unsafe_allow_html=True)
    st.title("TRIZ AI CAD Agent")
    connection = configuration or server_api_settings()
    if not connection['api_key'] or not connection['model']:
        st.warning("AI 尚未连接：当前使用本地参数建模，支持双探头安装板、带盖空心盒；不具备任意零件理解能力。")
    st.caption("把尺寸描述变成可修改的三维零件，边设计，边查看减重与工程参数。")
    st.markdown('<div class="steps"><span>01 描述需求</span><span>02 参数化建模</span>'
                '<span>03 TRIZ 优化</span><span>04 下载 CAD</span></div>', unsafe_allow_html=True)

    def submit(text: str, *, local: bool = False) -> None:
        """所有入口共用一个建模流程；失败保留上一成功模型和参数。"""
        try:
            if store and not user:
                raise BusinessError("请先在左侧注册或登录，再生成模型。")
            if store and not fee_consent:
                raise BusinessError("请先在左侧确认每次服务的演示价格。")
            if not local and mode == "在线模型 API":
                if not api_key or not model:
                    raise BusinessError("请填写自己的模型名称和 API Key，并勾选使用授权。" if personal_api else "站点尚未配置在线 AI，暂时请选择本地参数识别。")
                if store and not personal_api and not configuration["allow_demo_api"] and user['role'] != 'admin' and not store.user(user['id'])['site_api_access']:
                    raise BusinessError("演示计费下的付费 API 调用尚未开启，请使用本地建模。")
            with st.spinner("正在计算几何并导出 STEP / STL…"):
                def generate():
                    return process_request(text, st.session_state.last_params,
                        mode="本地参数识别" if local else mode, api_key=api_key,
                        base_url=base_url, model=model, protocol=protocol)
                if store:
                    # 服务器保存请求编号；账本对同一编号幂等，预占发生在调用模型之前。
                    request_key = st.session_state.setdefault("service_request_key", uuid4().hex)
                    result = run_service(store, user["id"], request_key, text, generate,
                                         quoted_fen=quoted_fen)
                    st.session_state.pop("service_request_key", None)
                else:
                    if public:
                        used = st.session_state.get("public_requests", 0)
                        if used >= 10:
                            raise BusinessError("当前浏览器会话已达 10 次公开体验上限。")
                        st.session_state.public_requests = used + 1
                        result = run_public(text, generate)
                    else:
                        result = generate()
        except BusinessError as exc:
            st.session_state.pop("service_request_key", None)
            result = {"status": "error", "error_message": str(exc)}
        st.session_state.messages.append({"role": "user", "content": text})
        if result["status"] == "success":
            st.session_state.last_params = result["input_parameters"]
            st.session_state.latest_result = result
            st.session_state.editor_sync = True
            st.session_state.last_error = ""
            report = format_report(result)
            if store:
                report += f"\n\n演示服务订单：{result['service_order_id'][:12]} · 本次结算 ¥{result['demo_service_fee_fen']/100:.2f}（非真实收款）。"
        else:
            st.session_state.last_error = result["error_message"]
            report = result["error_message"] + "\n\n请调整尺寸后重试，上一成功模型已保留。"
        st.session_state.messages.append({"role": "assistant", "content": report})
        st.rerun()

    left, right = st.columns([1, 1.45], gap="large")
    with left:
        st.subheader("设计助手")
        st.caption("选择一个起点，再用对话或尺寸面板修改。")
        presets = st.columns(4)
        examples = [
            ("标准支架", "standard", "长100宽45厚5孔距50孔径16.5，开启减重，开启倒角"),
            ("加长支架", "long", "长140宽50厚6孔距70孔径16.5，开启减重，开启倒角"),
            ("完整板件", "solid", "长100宽45厚5孔距50孔径16.5，关闭减重，开启倒角"),
            ("带盖盒子", "box", "长150宽140高100厚2毫米，有盖子"),
        ]
        for column, (name, key, text) in zip(presets, examples):
            if column.button(name, key=f"preset_{key}", use_container_width=True):
                submit(('带盖盒子，' if key=='box' else '双探头安装板，')+text, local=True)
        render_attachment(submit, user=user, login_required=store is not None, public=public,
                          api_settings=configuration, personal_api=personal_api)
        with st.container(height=550, border=True):
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        prompt = st.chat_input("描述尺寸，例如：长度改为140，关闭减重")
        if prompt:
            submit(prompt)
        st.caption("首个模型缺省推荐：100 × 45 × 5 mm，孔距 50 mm，孔径 16.5 mm。")

    with right:
        st.subheader("模型工作台")
        tabs = st.tabs(["三维预览", "尺寸编辑", "TRIZ 与检查"] + (["我的项目", "服务订单"] if store else []))
        preview_tab, parameters_tab, triz_tab = tabs[:3]
        latest = st.session_state.latest_result
        with preview_tab:
            if latest is None:
                st.markdown(EMPTY_PREVIEW, unsafe_allow_html=True)
                st.info("点击“标准支架”即可生成第一个可旋转的三维模型。")
            else:
                stl = Path(latest["stl_file"])
                step = Path(latest["output_file"])
                with st.container(border=True):
                    if stl.is_file():
                        try:
                            # 浏览器在本机渲染 STL，CadQuery 的精确几何通过 STEP 交付。
                            render_preview(stl, color=color, auto_rotate=auto_rotate)
                        except Exception:
                            st.warning("三维预览加载失败，仍可下载已生成的 STEP。")
                    else:
                        st.warning("预览文件已不存在，请重新生成。")
                st.caption("拖拽旋转 · 滚轮缩放 · 点击重置视角")
                physical = latest["physical_properties"]
                a, b, c = st.columns(3)
                a.metric("体积 / mm³", f"{physical['volume_mm3']:,.1f}")
                b.metric("估算重量 / g", f"{physical['weight_g']:.2f}")
                if latest.get('model_type') == 'box_with_lid':
                    c.metric("独立零件", "2 · 盒体与盖子")
                    st.info("预览将盖子抬高以展示空腔；装配 STEP 保持你要求的闭合外尺寸。")
                else:
                    c.metric("减重率", f"{latest['reduction_percent']:.2f}%")
                a, b = st.columns([1.5, 1])
                if step.is_file():
                    a.download_button("下载 STEP 工业模型", step.read_bytes(), step.name,
                        mime="application/octet-stream", type="primary", use_container_width=True)
                if stl.is_file():
                    b.download_button("下载 STL 模型", stl.read_bytes(), stl.name,
                        mime="application/octet-stream", use_container_width=True)
                for part in latest.get('parts', []):
                    part_file = Path(part['output_file'])
                    if part_file.is_file():
                        st.download_button('单独下载'+part['name']+' STEP', part_file.read_bytes(), part_file.name,
                            mime='application/octet-stream', key='part_'+part_file.stem)
                with st.expander('参数与设计报告'):
                    render_project_exports(latest,format_report)
                if not step.is_file():
                    st.warning('原始 STEP 文件已不存在。仍可下载参数；重新生成将创建新订单。')
        with parameters_tab:
            st.caption("所有尺寸单位均为毫米。未生成模型时显示推荐参数。")
            if st.session_state.last_error:
                st.error(st.session_state.last_error)
            with st.form("dimensions"):
                numeric = {}
                box_mode = bool(st.session_state.last_params and 'height' in st.session_state.last_params)
                dimensions = [('length',1.,1000.),('width',1.,1000.),('height',1.,1000.),('thickness',.5,50.),('lid_clearance',.05,2.)] if box_mode else [
                    ("length", 1., 1000.), ("width", 1., 1000.), ("thickness", .5, 100.),
                    ("probe_distance", 1., 1000.), ("probe_dia", .1, 1000.),
                ]
                for key, minimum, maximum in dimensions:
                    numeric[key] = st.number_input(labels[key] + " / mm", min_value=minimum,
                        max_value=maximum, step=.05 if key == 'lid_clearance' else .5, key=f"edit_{key}")
                if not box_mode:
                    light = st.checkbox("启用中央减重槽 · TRIZ 抽取原理", key="edit_enable_triz_lightening")
                    chamfer = st.checkbox("启用边缘倒角 · TRIZ 局部质量", key="edit_enable_stress_relief")
                if st.form_submit_button("应用尺寸并生成", type="primary", use_container_width=True):
                    text = "，".join(f"{labels[key]}{value:g}毫米" for key, value in numeric.items())
                    if box_mode:
                        text = '带盖盒子，'+text
                    else:
                        text += "，" + ("开启" if light else "关闭") + "减重"
                        text += "，" + ("开启" if chamfer else "关闭") + "倒角"
                    # 表单已给出明确参数，无需调用付费模型 API。
                    submit(text, local=True)
        with triz_tab:
            if latest is None:
                st.info("生成模型后查看真实减重数据、TRIZ 触发日志与几何检查结果。")
            else:
                for entry in latest["triz_logs"]:
                    st.markdown(f"**第 {entry['principle_number']} 号 · {entry['principle_name']}**")
                    st.write(entry["description"])
                if not latest["triz_logs"]:
                    st.caption("本次未启用减重或倒角。")
                st.divider()
                if latest.get('model_type') == 'box_with_lid':
                    st.success("盒体和盖子均为有效实体；装配尺寸与几何干涉检查已通过。")
                    for note in latest['design_notes']:
                        st.caption(note)
                else:
                    st.success("几何已生成，STEP / STL 已导出；孔边距与连接区域通过建模约束。")
                    st.caption("减重率以同尺寸、同探头孔的无槽无倒角板件为基准，包含槽和倒角的共同影响。")
                st.caption("重量按 6061 铝推荐密度估算。应力、承载和疲劳性能尚未验证。")
                with st.expander("当前模型参数"):
                    st.table([{"参数": labels[k], "值": "开启" if v is True else "关闭" if v is False
                               else f"{v:g} mm"} for k, v in latest["input_parameters"].items()])
        if store:
            with tabs[3]:
                render_projects(store,user,latest,format_report)
            with tabs[4]:
                render_orders(store, user)
    st.divider()
    st.caption("TRIZ CAD · 当前支持双探头平面安装板与带盖空心盒。未配置模型 API 时不调用 AI。")
    if public:
        st.caption("公开体验不永久保存项目，请及时下载成果。失败请求也计入体验次数。")

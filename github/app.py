"""TRIZ AI CAD Agent：聊天参数提取、三维预览与 STEP 下载。

启动：python -m streamlit run app.py
默认离线规则识别，无需互联网或API密钥；可选在线模式使用兼容
OpenAI 工具调用协议的 API。所有 CAD 运算在服务器本地执行。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

import streamlit as st
from streamlit_stl import stl_from_file

import cad_tool

ROOT = Path(__file__).resolve().parent
DEFAULT_PARAMS = {
    "length": 100.0, "width": 45.0, "thickness": 5.0,
    "probe_distance": 50.0, "probe_dia": 16.5,
    "enable_triz_lightening": True, "enable_stress_relief": True,
}
LABELS = {
    "length": "长度", "width": "宽度", "thickness": "厚度",
    "probe_distance": "探头孔距", "probe_dia": "探头孔径",
    "enable_triz_lightening": "减重槽", "enable_stress_relief": "边缘倒角",
}


def parse_local_request(text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """识别明确标注的尺寸和开关；保留上一成功模型的其他参数。

    支持“长100宽45厚5孔距50”、100×45×5 mm、cm 与中文毫米/厘米。
    本地规则不猜测复杂语义，无法识别时要求用户补充，不制造 AI 成功假象。
    """
    params = dict(previous or DEFAULT_PARAMS)
    updates: dict[str, Any] = {}
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    unit = r"(?:毫米|厘米|mm|cm)"

    def mm(value: str, suffix: str | None) -> float:
        """把明确标注的厘米换算为毫米；无单位默认为毫米。"""
        return float(value) * (10 if suffix and suffix.lower() in ("cm", "厘米") else 1)

    compact = re.search(
        rf"({number})\s*[×xX*]\s*({number})\s*[×xX*]\s*({number})\s*({unit})?", text,
        flags=re.IGNORECASE,
    )
    if compact:
        for key, value in zip(("length", "width", "thickness"), compact.groups()[:3]):
            updates[key] = mm(value, compact.group(4))

    names = {
        "length": r"总长度|长度|长|length",
        "width": r"总宽度|宽度|宽|width",
        "thickness": r"基础厚度|厚度|厚|thickness",
        "probe_distance": r"探头中心间距|探头间距|中心间距|探头孔距|孔距|间距|probe_distance",
        "probe_dia": r"探头安装孔直径|探头孔径|安装孔直径|孔直径|孔径|直径|probe_dia",
    }
    for key, aliases in names.items():
        matches = list(re.finditer(
            rf"(?:{aliases})\s*(?:改为|改成|修改为|设为|设置为|调整为|增加到|减少到|为|是)?"
            rf"\s*[:：=]?\s*({number})\s*({unit})?", text, re.IGNORECASE,
        ))
        if matches:
            match = matches[-1]
            updates[key] = mm(match.group(1), match.group(2))

    # 开关必须带有明确操作词；只提及“减重”不等于启用该功能。
    for key, feature in [("enable_triz_lightening", r"减重(?:槽)?|中间切口"),
                         ("enable_stress_relief", r"倒角|边缘处理")]:
        switches = list(re.finditer(
            rf"(关闭|取消|不要|禁用|不开|开启|启用|打开|增加|添加)\s*(?:{feature})", text,
        ))
        if switches:
            updates[key] = switches[-1].group(1) in ("开启", "启用", "打开", "增加", "添加")
    if not updates:
        raise ValueError("请明确描述尺寸，例如：长100、宽45、厚5、孔距50、孔径16.5 mm；也可以说“长度改为140，关闭减重”。")
    params.update(updates)
    return params


def extract_api_parameters(text: str, previous: dict[str, Any] | None, *,
                           api_key: str, base_url: str, model: str,
                           protocol: str = "Chat Completions") -> dict[str, Any]:
    """用真实模型 API 提取参数；只接受指定函数的单次工具调用。

    API 密钥仅传给 SDK，不写入对话、项目文件或建模日志。
    支持原生 Responses 和兼容厂商常用的 Chat Completions 两种协议。
    """
    from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

    definitions = json.loads((ROOT / "tool_definition.json").read_text(encoding="utf-8"))
    context = {
        "上一成功模型参数": previous,
        "未指定时推荐参数": DEFAULT_PARAMS,
    }
    instructions = (
        "你是双探头平面安装板设计助手。只支持指定工具的七个参数。所有尺寸换算为mm。"
        "修改请求必须保留上一成功模型中未被用户修改的参数。首个模型缺失的参数使用推荐参数。"
        "不得擅自修改用户明确给定的值来绕过几何错误。禁止生成或执行Python代码。"
        "只有用户要求创建或修改受支持零件时才调用generate_sensor_bracket，且每次只调用一次。"
        "如果请求超出平面安装板能力、含不支持的结构，或无法明确用户意图，直接说明并询问，不能伪装完成。"
        "第2号是抽取，第3号是局部质量，第15号是动态化。倒角不代表强度已验证。"
        + json.dumps(context, ensure_ascii=False, allow_nan=False)
    )
    try:
        with OpenAI(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=1) as client:
            if protocol == "Responses":
                response = client.responses.create(
                    model=model, instructions=instructions, input=text,
                    tools=definitions, parallel_tool_calls=False,
                )
                calls = [item for item in response.output if item.type == "function_call"]
                if len(calls) != 1:
                    raise ValueError(response.output_text or "模型没有返回唯一的建模请求，请补充尺寸或功能。")
                name, arguments = calls[0].name, calls[0].arguments
            else:
                tools = [{"type": "function", "function": {
                    key: value for key, value in item.items() if key != "type"
                }} for item in definitions]
                response = client.chat.completions.create(
                    model=model, messages=[{"role": "system", "content": instructions},
                                           {"role": "user", "content": text}],
                    tools=tools, tool_choice="auto",
                )
                message = response.choices[0].message
                calls = message.tool_calls or []
                if len(calls) != 1:
                    raise ValueError(message.content or "模型没有返回唯一的建模请求，请补充尺寸或功能。")
                name, arguments = calls[0].function.name, calls[0].function.arguments
    except AuthenticationError:
        raise RuntimeError("API 鉴权失败，请检查密钥和接口地址。") from None
    except RateLimitError:
        raise RuntimeError("API 额度不足或请求受限，请检查账户额度后重试。") from None
    except APIConnectionError:
        raise RuntimeError("API 连接失败或超时，请检查网络和接口地址。") from None
    except APIStatusError as exc:
        raise RuntimeError(f"API 返回 HTTP {exc.status_code}，请检查模型名称、协议和服务状态。") from None
    if name != "generate_sensor_bracket":
        raise ValueError("模型返回了不支持的工具。")
    params = json.loads(arguments)
    if not isinstance(params, dict) or set(params) != set(DEFAULT_PARAMS):
        raise ValueError("模型参数不完整或存在额外字段，请重试。")
    return params


def process_request(text: str, previous: dict[str, Any] | None, *,
                    mode: str, api_key: str = "", base_url: str = "", model: str = "",
                    protocol: str = "Chat Completions") -> dict[str, Any]:
    """完成参数解析与真实 CAD 调用；失败结果由界面处理，不覆盖上一模型。"""
    try:
        if mode == "在线模型 API":
            if not api_key.strip() or not base_url.strip() or not model.strip():
                raise ValueError("请先在左侧填写 API 地址、模型名称和密钥，或切换到本地参数识别体验。")
            params = extract_api_parameters(text, previous, api_key=api_key,
                                            base_url=base_url, model=model, protocol=protocol)
        else:
            params = parse_local_request(text, previous)
        # 在线输出也通过严格白名单，禁止把模型额外字段当作Python参数执行。
        if set(params) != set(DEFAULT_PARAMS):
            raise ValueError("参数字段与当前建模能力不一致。")
        result = cad_tool.generate_sensor_bracket(**params)
        if result["status"] == "success":
            result["input_parameters"] = params
            result["reduction_percent"] = result["physical_properties"]["weight_reduction_percent"]
        return result
    except (ValueError, RuntimeError) as exc:
        return {"status": "error", "error_message": str(exc)[:1200]}
    except Exception:
        # 不直接显示 SDK 异常对象，避免请求头、密钥或服务端详细内容进入聊天记录。
        return {"status": "error", "error_message": "请求处理失败。请检查 API 配置、网络、依赖和输入格式后重试；上一模型已保留。"}


def format_report(result: dict[str, Any]) -> str:
    """用 CAD 计算结果编写报告，避免让模型编造体积、重量或减重数据。"""
    physical = result["physical_properties"]
    params = result["input_parameters"]
    lines = [
        "模型已生成，可以在右侧旋转查看或下载。",
        "",
        f"- 尺寸：**{params['length']:g} × {params['width']:g} × {params['thickness']:g} mm**",
        f"- 探头孔距 / 孔径：**{params['probe_distance']:g} / {params['probe_dia']:g} mm**",
        f"- 体积：**{physical['volume_mm3']:,.2f} mm³**",
        f"- 估算重量：**{physical['weight_g']:.2f} g**（Aluminum 6061）",
        f"- 减重率：**{result['reduction_percent']:.2f}%**",
        "",
        "减重基准为同尺寸、同探头孔的无槽无倒角板件，统计槽和倒角的共同影响。",
        "",
        "**TRIZ 触发日志**",
        "",
    ]
    for entry in result["triz_logs"]:
        lines.append(f"- 第 {entry['principle_number']} 号 · {entry['principle_name']}：{entry['description']}")
    if not result["triz_logs"]:
        lines.append("- 本次未启用减重或倒角。")
    lines.extend(["", "重量按推荐密度估算；应力、承载与疲劳性能尚未验证。"])
    return "\n".join(lines)


def main() -> None:
    """构建宽屏双栏界面；用 session_state 保留对话和上一成功模型。"""
    # 页面配置是首个界面调用；导入app模块不会启动界面，便于独立测试函数。
    st.set_page_config(page_title="TRIZ AI CAD Agent", page_icon="⚙️", layout="wide")
    st.title("TRIZ AI CAD Agent")
    st.caption("离线可用 · 描述双探头安装支架，预览三维模型并下载 STEP 文件。")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": (
            "告诉我支架长度、宽度、厚度、探头孔距和孔径。\n\n"
            "例如：长100、宽45、厚5、孔距50、孔径16.5毫米，开启减重。\n\n"
            "未指定的初始参数采用推荐值：100×45×5 mm，孔距50 mm，孔径16.5 mm，减重和倒角开启。"
        )}]
    for key in ("last_params", "latest_result"):
        if key not in st.session_state:
            st.session_state[key] = None

    # 环境变量让部署者能够预配置API；终端用户也能在侧栏自行填写。
    with st.sidebar:
        st.header("设计与显示")
        mode = st.radio("需求理解方式", ["本地参数识别", "在线模型 API"])
        if mode == "本地参数识别":
            st.success("离线模式 · 无需密钥")
            st.caption("识别明确尺寸与开关，例如“长100宽45厚5孔距50”或“长度改为140”。尺寸单位默认为毫米。")
        else:
            st.caption("在线模式需要网络和密钥，支持更灵活的自然语言。")
        api_key, base_url, model, protocol = "", "", "", "Chat Completions"
        if mode == "在线模型 API":
            base_url = st.text_input("API 地址", value=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
            model = st.text_input("模型名称", value=os.getenv("OPENAI_MODEL", ""), placeholder="填写服务商提供的模型名称")
            # 公共网站不得把部署者的环境密钥发给浏览器；在线模式由访客自行填写。
            api_key = st.text_input("API 密钥", value="", type="password")
            protocol = st.selectbox("接口协议", ["Chat Completions", "Responses"])
            st.caption("在线模式使用你填写的密钥和服务商额度。密钥不会写入模型文件或聊天记录。")
        color = st.color_picker("模型颜色", "#4F8BFF")
        auto_rotate = st.toggle("自动旋转", value=False)
        if st.button("开始新设计", use_container_width=True):
            # 只清除当前会话，不删除服务器上的已导出成果。
            for key in ("messages", "last_params", "latest_result"):
                st.session_state.pop(key, None)
            st.rerun()

    left, right = st.columns([1, 1.25], gap="large")
    with left:
        st.subheader("设计对话")
        # 固定高度让长对话滚动，右侧模型保持易于查看。
        conversation = st.container(height=570)
        with conversation:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        prompt = st.chat_input("例如：长度改为140毫米，其他尺寸保持不变")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with conversation:
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("正在理解需求并生成模型…"):
                        result = process_request(
                            prompt, st.session_state.last_params, mode=mode,
                            api_key=api_key, base_url=base_url, model=model, protocol=protocol,
                        )
                    if result["status"] == "success":
                        # 只有成功生成STEP与STL后，才更新当前模型与后续修改的参数。
                        st.session_state.last_params = result["input_parameters"]
                        st.session_state.latest_result = result
                        report = format_report(result)
                        st.markdown(report)
                    else:
                        report = result["error_message"] + "\n\n请调整需求后重试，右侧保留上一成功模型。"
                        st.error(result["error_message"])
            st.session_state.messages.append({"role": "assistant", "content": report})

    with right:
        st.subheader("三维模型")
        latest = st.session_state.latest_result
        if latest is None:
            st.info("生成模型后，这里将显示可拖拽旋转的三维预览。")
            st.caption("当前支持平面双探头支架、圆头减重通槽和边缘倒角。")
        else:
            step_path = Path(latest["output_file"])
            stl_path = Path(latest["stl_file"])
            if stl_path.is_file():
                try:
                    # streamlit-stl将STL交给浏览器Three.js组件，支持拖拽、缩放与旋转。
                    # 同名UUID作为key，新模型会刷新，颜色更改时保留当前组件身份。
                    success = stl_from_file(
                        file_path=str(stl_path), color=color, material="material",
                        auto_rotate=auto_rotate, opacity=1.0, height=470,
                        cam_v_angle=55, cam_h_angle=-45,
                        key=f"preview_{stl_path.stem}",
                    )
                    if success is False:
                        st.warning("预览组件读取失败，仍可下载 STEP 文件。")
                except Exception:
                    st.warning("三维预览加载失败，仍可下载 STEP 文件。")
            else:
                st.warning("STL 预览文件已不存在，请重新生成。")
            st.caption("鼠标拖拽旋转 · 滚轮缩放 · 右键拖拽平移")
            physical = latest["physical_properties"]
            a, b, c = st.columns(3)
            a.metric("体积 / mm³", f"{physical['volume_mm3']:,.1f}")
            b.metric("估算重量 / g", f"{physical['weight_g']:.2f}")
            c.metric("减重率", f"{latest['reduction_percent']:.2f}%")
            # 下载原始字节，浏览器无需访问服务器文件系统路径。
            if step_path.is_file():
                st.download_button(
                    "下载 STEP 工业模型", data=step_path.read_bytes(),
                    file_name=step_path.name, mime="application/octet-stream",
                    type="primary", use_container_width=True,
                )
            else:
                st.warning("STEP 文件已不存在，请重新生成。")
            if stl_path.is_file():
                st.download_button("下载 STL 预览模型", data=stl_path.read_bytes(),
                                   file_name=stl_path.name, mime="application/octet-stream",
                                   use_container_width=True)
            with st.expander("查看当前尺寸与功能"):
                st.table([
                    {"参数": LABELS[name], "当前值": (
                        "开启" if value is True else "关闭" if value is False else f"{value:g} mm"
                    )} for name, value in latest["input_parameters"].items()
                ])


if __name__ == "__main__":
    main()

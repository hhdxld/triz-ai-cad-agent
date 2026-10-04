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

import cad_tool
from box_tool import BOX_DEFAULTS, generate_box_with_lid

ROOT = Path(__file__).resolve().parent
DEFAULT_PARAMS = {
    "length": 100.0, "width": 45.0, "thickness": 5.0,
    "probe_distance": 50.0, "probe_dia": 16.5,
    "enable_triz_lightening": True, "enable_stress_relief": True,
}
LABELS = {
    "height": "高度", "lid_clearance": "盖子每侧配合间隙",
    "length": "长度", "width": "宽度", "thickness": "厚度",
    "probe_distance": "探头孔距", "probe_dia": "探头孔径",
    "enable_triz_lightening": "减重槽", "enable_stress_relief": "边缘倒角",
}


def parse_box_request(text: str, previous: dict | None = None) -> dict:
    """盒体核心尺寸缺失时要求补充；不擅自添加探头孔或替换零件类型。"""
    if re.search(r'圆柱|齿轮|圆形|球体|螺纹|卡扣|铰链|开孔|钻孔|孔径|孔距|分隔|圆角|倒角',text):
        raise ValueError('盒子需求包含当前工具未实现的结构，已停止建模，不能用基础带盖盒子冒充完成。')
    params = {k: v for k,v in (previous or {}).items() if k in BOX_DEFAULTS}
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    for key,aliases in {'length':'长度|长|length','width':'宽度|宽|width','height':'高度|高|height',
                        'thickness':'壁厚|厚度|厚|thickness','lid_clearance':'每侧配合间隙|配合间隙|lid_clearance'}.items():
        matches = list(re.finditer(rf'(?:{aliases})\s*(?:改为|修改为|改成|设为|为|是)?\s*[:：=]?\s*({number})\s*(mm|cm|毫米|厘米)?',text,re.I))
        if matches:
            match=matches[-1]
            params[key]=float(match[1])*(10 if (match[2] or '').lower() in ('cm','厘米') else 1)
    missing = {'length','width','height','thickness'}-set(params)
    if missing:
        raise ValueError('带盖盒子还缺少：'+ '、'.join(LABELS[k] for k in sorted(missing))+'。请补充实际尺寸。')
    params.setdefault('lid_clearance',.3)
    return params


def is_box_request(text: str, previous: dict | None) -> bool:
    """选择独立盒体工具；明确支架请求可以切回原工具。"""
    return bool(re.search(r'盒|箱|有盖|带盖|盖子',text)) or (
        bool(previous and 'height' in previous) and not re.search(r'支架|探头|安装板',text))


def parse_local_request(text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """识别明确标注的尺寸和开关；保留上一成功模型的其他参数。

    支持“长100宽45厚5孔距50”、100×45×5 mm、cm 与中文毫米/厘米。
    本地规则不猜测复杂语义，无法识别时要求用户补充，不制造 AI 成功假象。
    """
    if re.search(r'长方体|圆柱|齿轮|法兰|外壳|壳体|无孔|不要孔|不打孔|单孔|[三四五六]孔|[34]个?孔|[LU][形型]|L-shaped|螺纹|折弯|台阶|圆管|球体|侧面.*孔', text, re.I):
        raise ValueError('该需求不能用双探头平面安装板实现，已停止建模，避免生成不符合描述的零件。')
    params = dict(previous if previous and 'height' not in previous else DEFAULT_PARAMS)
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
        "你是机械设计助手，支持双探头平面安装板和带盖空心长方体盒子两个工具。所有尺寸换算为mm。"
        "用户要求盒子、箱体或带盖长方体时只能调用generate_box_with_lid，不能套用双孔安装板。"
        "盒子长宽高为闭合装配外尺寸，总高度含盖板，壁底盖厚度一致，缺少核心尺寸先询问，不调用工具。"
        "修改请求必须保留上一成功模型中未被用户修改的参数。首个模型缺失的参数使用推荐参数。"
        "不得擅自修改用户明确给定的值来绕过几何错误。禁止生成或执行Python代码。"
        "只有用户要求创建或修改受支持零件时才选择对应工具，且每次只调用一次。"
        "如果请求超出这两种工具能力、含不支持的结构，或无法明确用户意图，直接说明并询问，不能伪装完成。"
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
                # 部分兼容厂商不支持 OpenAI strict 开关；仍由服务端白名单验证结果。
                if 'api.openai.com' not in base_url:
                    for tool in tools:
                        tool['function'].pop('strict',None)
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
    if name not in ("generate_sensor_bracket", "generate_box_with_lid"):
        raise ValueError("模型返回了不支持的工具。")
    params = json.loads(arguments)
    if not isinstance(params, dict) or set(params) != set(BOX_DEFAULTS if name == 'generate_box_with_lid' else DEFAULT_PARAMS):
        raise ValueError("模型参数不完整或存在额外字段，请重试。")
    return params


def process_request(text: str, previous: dict[str, Any] | None, *,
                    mode: str, api_key: str = "", base_url: str = "", model: str = "",
                    protocol: str = "Chat Completions") -> dict[str, Any]:
    """完成参数解析与真实 CAD 调用；失败结果由界面处理，不覆盖上一模型。"""
    try:
        if mode == "在线模型 API":
            if not api_key.strip() or not base_url.strip() or not model.strip():
                raise ValueError("站长尚未配置模型 API，当前没有调用 AI。请先配置服务端 API，或使用明确标注能力范围的本地参数工具。")
            params = extract_api_parameters(text, previous, api_key=api_key,
                                            base_url=base_url, model=model, protocol=protocol)
        else:
            params = parse_box_request(text, previous) if is_box_request(text, previous) else parse_local_request(text, previous)
        # 在线输出也通过严格白名单，禁止把模型额外字段当作Python参数执行。
        if set(params) not in (set(DEFAULT_PARAMS),set(BOX_DEFAULTS)):
            raise ValueError("参数字段与当前建模能力不一致。")
        result = generate_box_with_lid(**params) if 'height' in params else cad_tool.generate_sensor_bracket(**params)
        if result["status"] == "success":
            result["input_parameters"] = params
            if 'height' not in params:
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
    if result.get('model_type') == 'box_with_lid':
        return '\n\n'.join(['已生成带盖空心盒：独立盒体和盖子，共两个零件。',
            f"装配外尺寸：**{params['length']:g} × {params['width']:g} × {params['height']:g} mm**；壁、底、盖厚 **{params['thickness']:g} mm**。",
            f"体积 {physical['volume_mm3']:,.2f} mm³，6061 铝估算重量 {physical['weight_g']:.2f} g。",
            *result['design_notes'], '本地工具按明确尺寸生成；只有配置并选择模型 API 后才会调用 AI。'])
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
    """打开本地 CAD 工作台，复用同一参数解析与建模接口。"""
    from workspace_ui import render_workspace
    render_workspace(process_request, format_report, DEFAULT_PARAMS, LABELS)


if __name__ == "__main__":
    main()

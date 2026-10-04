# TRIZ AI CAD Agent

第一版为可被 Agent 调用的双探头安装板工具，使用真实 CadQuery 实体建模与同名 STEP/STL 导出；提供 Streamlit 对话和三维预览界面。

## 文件

- `cad_tool.py`：`CADTool` 类、`generate_sensor_bracket()` 公共入口和白名单工具分发器。
- `tool_definition.json`：可直接作为 OpenAI Responses API 的 `tools` 参数，采用严格函数定义格式。
- `test_agent_runner.py`：模拟 Agent 调用和参数纠错，执行真实建模、重量计算及 STEP 回读校验。
- `tests/test_cad_tool.py`：独立解析体积、四种功能组合、错误处理、定义与签名一致性的测试。
- `requirements.txt`：已在本机验证的 CadQuery 版本。
- `app.py`：宽屏双栏聊天、在线API/本地规则解析、连续修改、STL预览与STEP下载。

## 网页应用运行（PowerShell）

新用户先在项目目录中使用 Python 3.12 创建环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Linux/macOS 使用 `.venv/bin/python` 替换上述解释器路径。首次安装需要网络；默认规则模式在依赖安装后可离线运行。

默认离线运行：链接为 http://127.0.0.1:8501 ，无需互联网和API密钥。
STL查看器的Three.js、OrbitControls与STLLoader随已安装组件在本机提供，没有外部CDN脚本。
离线理解由规则识别实现，不是离线大模型；支持明确尺寸与开关。在线模型API是可选功能。

日常使用可双击项目内的 `启动网站.cmd`，它会启动或复用后台服务并打开浏览器。
服务已经启动时，可以直接点上述链接或双击 `TRIZ AI CAD.url`。
重启电脑后先双击启动入口一次。链接仅适用于安装本应用的当前电脑，不是公共互联网地址。
CadQuery依赖本机Python服务，不能把HTML文件单独拷到其他电脑就执行建模。

本项目已经创建 `.venv` 并安装网页依赖，复用本机 `aicad_env` 中的 CadQuery：

```powershell
Set-Location -LiteralPath '你的项目目录'
& '.\.venv\Scripts\python.exe' -m streamlit run app.py --server.address 127.0.0.1
```

浏览器打开 http://127.0.0.1:8501 。默认本地参数识别，无需密钥；需要在线理解时，可选择在线模型API并填写API地址、模型名称和密钥。
部署者可通过 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 环境变量预配置服务地址与模型；API密钥由使用者在界面自行输入，不从服务器环境变量回填到浏览器，密钥不要提交到仓库。
原生OpenAI可选择Responses协议，其他服务商按其工具调用接口选择Chat Completions或Responses；在线调用会产生所选服务商的费用。

快速体验：本地模式输入“长100宽45厚5孔距50孔径16.5”；生成后输入“长度改为140，关闭减重”。右侧可旋转和缩放模型，并下载STEP与STL。
本地规则只识别明确尺寸和开关，复杂自然语言需要在线API。当前建模能力为平面双探头安装板，不支持自动增加任意结构。
未输入的新设计参数采用界面明确列出的推荐值；修改请求继承上一成功模型的未修改参数。失败时保留上一成功模型。
减重基准为相同外形、相同探头孔的无减重槽无倒角板件，重量按近似密度估算，包含槽与倒角共同影响，不表示强度验证。

网页测试和CAD测试都用网页环境运行：

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -s tests -v
```

已使用Streamlit AppTest验证聊天生成、尺寸修改、错误保留、下载按钮和新设计重置。该验证不等同于真实浏览器WebGL旋转测试。真实在线API未验证，因为未提供密钥。

## 本机运行（PowerShell）

仅运行CAD演示时，本机已有 `aicad_env`，无需网页依赖。首先进入项目：

```powershell
Set-Location -LiteralPath '你的项目目录'
conda activate aicad_env
python test_agent_runner.py
python -m unittest discover -s tests -p test_cad_tool.py -v
```

若当前终端未初始化 conda，可以直接调用现有解释器：

```powershell
& '.\.venv\Scripts\python.exe' test_agent_runner.py
```

新机器建议使用 Python 3.10～3.12 的独立环境后执行 `python -m pip install -r requirements.txt`。不要假定最新 Python 的 CadQuery 二进制依赖已经兼容。
在只有Python的环境中可先运行 `python -m venv .venv`，然后使用该虚拟环境安装requirements，再启动Streamlit。

## Python 调用

```python
from cad_tool import generate_sensor_bracket

result = generate_sensor_bracket(
    length=100, width=45, thickness=5, probe_distance=50,
    probe_dia=16.5, enable_triz_lightening=True, enable_stress_relief=True,
)
print(result)
```

宿主指定输出目录时使用 `CADTool(output_dir=...)`；该目录不属于模型可调用参数。

## 对接 Agent

加载 `tool_definition.json` 后将列表作为 Responses API 的 `tools` 参数。
模型返回 `type="function_call"` 项时，由宿主执行下面的分发逻辑：

```python
import json
from cad_tool import dispatch_tool_call

# call 是模型返回的函数调用对象。只分发 function_call 项。
result = dispatch_tool_call(call.name, call.arguments)
tool_output = {
    "type": "function_call_output",
    "call_id": call.call_id,
    "output": json.dumps(result, ensure_ascii=False, allow_nan=False),
}
# 宿主将 tool_output 连同必要的会话上下文发回模型，供模型解释或重试。
```

严格模式要求七个字段都在模型参数中出现。Python 原生调用仍允许省略后三个默认参数。
如果宿主使用 Chat Completions API，把每项改为
`{"type": "function", "function": {k: v for k, v in item.items() if k != "type"}}`。

该 JSON 是函数调用定义，不是 MCP 服务，也不是 Codex 的 `SKILL.md`。
通过 Python 宿主的 dispatcher 可立即调用；若以后接入 MCP，需另建服务器并注册函数，不能仅把本 JSON 改名当作 MCP 服务。
演示脚本不连接在线模型、不需要密钥、不产生 API 费用。真实模型决策与自愈尚未通过在线 API 验证。

## 几何约定与可制造性边界

- 默认构型为矩形平面双探头安装板；用户没有指定折弯高度，因此不猜测 L 形结构。
- X 长、Y 宽、底面 Z=0；两个孔中心为 `(±probe_distance/2, 0)`，均为贯穿孔。
- 中部减重为圆头贯穿槽。连接区域规则推荐取 `max(2 mm, thickness/2)`，另留倒角余量；这不是载荷强度标准。
- 倒角尺寸自动取 `min(0.5 mm, thickness/4, 连接区域推荐值/4)`，作用于上下表面边缘，包括孔口与槽口。
- 加工可采用板材 CNC；实际刀径、夹持、孔配合公差和表面处理需要工艺人员确认。
- 不会自动增加设备安装螺丝孔；设备侧的固定方式尚未作为本函数参数定义。
- 导出的 STEP 保存几何。参数化编辑依靠再次调用函数与保存参数，STEP 不承诺包含原生 CAD 特征历史。

## 物性与 TRIZ 说明

`weight_g = volume_mm3 × 0.0027`。Aluminum 6061 密度以推荐近似值 2.70 g/cm³ 估算，仅包含板件，不包括探头、螺丝和涂层。未进行有限元应力、疲劳或承载试验。

减重采用第 2 号抽取原理。倒角仅以第 3 号局部质量作结构设计解释；第 15 号是动态化原理，静态倒角不据此记录为动态化。`enable_stress_relief` 名称保留用户要求的接口，但不意味着应力改善已经证明。错误结果中的 TRIZ 日志若存在，只表示失败前执行过的步骤，不能当作交付成果。

所有尺寸须为有限正数。长度、宽度、孔距和孔径最大 1000 mm，厚度为 0.5～100 mm；额外几何约束由错误消息明确说明。输出文件使用唯一名称，失败不覆盖以前的成果。

## 格式与建模参考

公网试用部署步骤与费用边界见 `DEPLOY.md`。GitHub用于保存源码，运行本应用需要支持Python的托管服务。

- [OpenAI 官方 Function Calling 文档](https://developers.openai.com/api/docs/guides/function-calling)
- [CadQuery 官方类参考](https://cadquery.readthedocs.io/en/stable/classreference.html)
- [CadQuery 官方安装文档](https://cadquery.readthedocs.io/en/stable/installation.html)

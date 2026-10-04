"""无需 API 密钥的 Agent 工具调用演示：参数、建模、校验和重试。

此脚本模拟模型输出的 function_call，不声称调用了真实大模型。
"""

import json
import math
from pathlib import Path
import sys

from cad_tool import dispatch_tool_call


def main() -> int:
    """执行真实 CAD 建模与 STEP 回读；失败时返回非零退出码。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    definitions = json.loads(Path(__file__).with_name("tool_definition.json").read_text(encoding="utf-8"))
    tool_name = definitions[0]["name"]
    parameters = dict(length=100.0, width=45.0, thickness=5.0,
                      probe_distance=50.0, probe_dia=16.5,
                      enable_triz_lightening=True, enable_stress_relief=True)
    print("模式：模拟 Agent 工具调用，执行真实 CadQuery 建模；无需 API 密钥。")

    # 首先构造一次非法调用，演示宿主获得错误后修改参数。
    invalid = dispatch_tool_call(tool_name, json.dumps(parameters | {"length": 20}))
    if invalid["status"] != "error" or invalid["output_file"] is not None:
        print("错误分支验证失败。")
        return 1
    print("首次调用：", invalid["error_message"])
    print("模拟重试：将 length 修正为 100 mm。")

    baseline = dispatch_tool_call(tool_name, parameters | {
        "enable_triz_lightening": False, "enable_stress_relief": False,
    })
    result = dispatch_tool_call(tool_name, json.dumps(parameters))
    if baseline["status"] != "success" or result["status"] != "success":
        print(json.dumps({"baseline": baseline, "optimized": result}, ensure_ascii=False, indent=2))
        return 1
    import cadquery as cq
    shape = cq.importers.importStep(result["output_file"]).val()
    reported = result["physical_properties"]
    baseline_volume = baseline["physical_properties"]["volume_mm3"]
    expected_baseline = (100 * 45 - 2 * math.pi * (16.5 / 2) ** 2) * 5
    principle_numbers = [entry["principle_number"] for entry in result["triz_logs"]]
    checks = {
        "baseline_matches_analytical_volume": math.isclose(baseline_volume, expected_baseline, abs_tol=1e-5),
        "step_roundtrip_valid": shape.isValid() and len(shape.Solids()) == 1,
        "roundtrip_volume_matches": math.isclose(shape.Volume(), reported["volume_mm3"], abs_tol=1e-5),
        "weight_matches_assumed_density": math.isclose(reported["weight_g"], reported["volume_mm3"] * 0.0027, abs_tol=1e-6),
        "lightening_reduces_volume": 0 < reported["volume_mm3"] < baseline_volume,
        "triz_principles_correct": principle_numbers == [2, 3],
        "strength_not_claimed": result["validation"]["strength_verified"] is False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    print("验证结果：", json.dumps(checks, ensure_ascii=False, indent=2))
    reduction = (1 - reported["volume_mm3"] / baseline_volume) * 100
    print(f"相对无槽、无倒角基准减重：{reduction:.2f}%（包含槽和倒角的共同影响）。")
    print("承载能力与应力改善未验证。基准文件：", baseline["output_file"])
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

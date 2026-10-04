"""可供 Agent 调用的参数化 CAD 工具；所有尺寸单位为 mm。

默认构型是平面双探头安装板，而非含折弯的 L 形支架。
坐标：X 为长度，Y 为宽度，底面 Z=0，孔中心为 (±间距/2, 0)。
物性只按均匀材料密度计算，不执行有限元分析或承载能力认证。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

MATERIAL = "Aluminum 6061"
DENSITY_G_PER_MM3 = 0.0027  # 推荐估算密度：2.70 g/cm³，未计入表面处理。
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def _error(message: str, code: str = "INVALID_PARAMETERS",
           logs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """返回可 JSON 序列化的错误；失败时不给出有效文件或物性。"""
    return {
        "status": "error", "output_file": None, "stl_file": None, "physical_properties": None,
        "triz_logs": logs or [], "error_message": message, "error_code": code,
        "validation": {"geometry_valid": False, "strength_verified": False},
    }


class CADTool:
    """封装建模与导出；输出目录由宿主配置，不暴露给模型。

    Args:
        output_dir: 导出目录。省略时使用项目的 outputs 目录。
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR

    def generate_sensor_bracket(
        self, length: float, width: float, thickness: float,
        probe_distance: float, probe_dia: float = 16.5,
        enable_triz_lightening: bool = True,
        enable_stress_relief: bool = True,
    ) -> dict[str, Any]:
        """生成双探头安装板、可选中间减重通槽与边缘倒角。

        Args:
            length: 安装板 X 向长度，范围 1～1000 mm。
            width: 安装板 Y 向宽度，范围 1～1000 mm。
            thickness: 安装板厚度，范围 0.5～100 mm。
            probe_distance: 两孔中心 X 向间距，必须满足连接区域约束。
            probe_dia: 两个探头通孔直径，默认 16.5 mm。
            enable_triz_lightening: 是否用第 2 号抽取原理移除两孔间材料。
            enable_stress_relief: 是否进行推荐倒角；按第 3 号局部质量记录。
                名称为兼容上层接口保留，不能据此断言应力已经降低。

        Returns:
            含 status、output_file、physical_properties、triz_logs、
            error_message 的字典；额外返回参数布局和验证边界。
            所有可预期的参数、依赖、建模和导出错误都以 error 状态返回。
        """
        numeric = dict(length=length, width=width, thickness=thickness,
                       probe_distance=probe_distance, probe_dia=probe_dia)
        for name, value in numeric.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return _error(f"{name} 必须是数值，不能是布尔值或字符串。")
            try:
                finite = math.isfinite(value)
            except (OverflowError, ValueError):
                finite = False
            if not finite or value <= 0 or value > 1000:
                return _error(f"{name} 必须是大于 0、不超过 1000 的有限数值（mm）。")
        if not 0.5 <= thickness <= 100:
            return _error("thickness 必须在 0.5～100 mm 之间。")
        for name, value in [("enable_triz_lightening", enable_triz_lightening),
                            ("enable_stress_relief", enable_stress_relief)]:
            if not isinstance(value, bool):
                return _error(f"{name} 必须是 true/false 布尔值。")

        # 连接区域尺寸为推荐几何规则，不是特定载荷下的强度计算结果。
        nominal_web = max(2.0, thickness / 2.0)
        chamfer = min(0.5, thickness / 4.0, nominal_web / 4.0) if enable_stress_relief else 0.0
        # 留出倒角扩孔和外缘去除余量，保证最终表面仍有 nominal_web。
        clearance = nominal_web + 2 * chamfer
        if length < probe_distance + probe_dia + 2 * clearance:
            return _error(
                f"孔距和孔径超出长度或孔边距不足：length 至少需要 "
                f"{probe_distance + probe_dia + 2 * clearance:.3f} mm。"
            )
        if width < probe_dia + 2 * clearance:
            return _error(f"孔到侧边距离不足：width 至少需要 {probe_dia + 2 * clearance:.3f} mm。")
        gap = probe_distance - probe_dia
        if gap < clearance:
            return _error(f"探头孔相交或两孔连接区域不足：probe_distance 至少需要 {probe_dia + clearance:.3f} mm。")
        slot_length = gap - 2 * clearance if enable_triz_lightening else 0.0
        if enable_triz_lightening and slot_length < 2.0:
            return _error(
                f"两孔之间没有足够空间开减重槽：probe_distance 至少需要 "
                f"{probe_dia + 2 * clearance + 2:.3f} mm；"
                "也可将 enable_triz_lightening 设为 false。"
            )
        slot_width = min(width * 0.5, width - 2 * clearance, slot_length * 0.5) if enable_triz_lightening else 0.0

        try:
            import cadquery as cq
        except ImportError as exc:
            return _error(f"CadQuery 或其依赖不可用：{exc}。请在推荐环境执行 pip install -r requirements.txt。",
                          "DEPENDENCY_ERROR")

        logs: list[dict[str, Any]] = []
        temp_path: Path | None = None
        temp_stl_path: Path | None = None
        created_files: list[Path] = []
        export_complete = False
        try:
            model = cq.Workplane("XY").box(length, width, thickness, centered=(True, True, False))
            model = model.faces(">Z").workplane().pushPoints(
                [(-probe_distance / 2, 0), (probe_distance / 2, 0)]
            ).hole(probe_dia)
            # 基准使用相同外形与探头孔，但不包含减重槽和倒角。
            reference_volume = float(model.val().Volume())
            if enable_triz_lightening:
                model = model.faces(">Z").workplane().slot2D(slot_length, slot_width).cutThruAll()
                logs.append({
                    "principle_number": 2, "principle_name": "抽取原理",
                    "description": "在两探头孔之间移除材料，使用圆头通槽并保留连接区域；减重效果由最终实体体积计算。",
                    "feature": "central_lightening_slot", "status": "applied",
                })
            if enable_stress_relief:
                model = model.faces(">Z or <Z").edges().chamfer(chamfer)
                logs.append({
                    "principle_number": 3, "principle_name": "局部质量原理",
                    "description": "局部修改上下表面边缘，包含孔口与槽口倒角。此对应关系为设计解释；应力改善须进一步验证。第15号动态化原理未应用。",
                    "feature": "edge_chamfer", "chamfer_mm": chamfer, "status": "applied",
                })
            solid = model.val()
            if not solid.isValid() or len(solid.Solids()) != 1:
                return _error("模型无效或被切割为多个实体，请增加连接区域或关闭减重。", "GEOMETRY_ERROR", logs)
            volume = float(solid.Volume())
            if not math.isfinite(volume) or volume <= 0:
                return _error("实体体积无效。", "GEOMETRY_ERROR", logs)
            bbox = solid.BoundingBox()
            for actual, expected in [(bbox.xlen, length), (bbox.ylen, width), (bbox.zlen, thickness)]:
                if not math.isclose(actual, expected, abs_tol=1e-5):
                    return _error("建模结果的外形尺寸与输入不一致。", "GEOMETRY_ERROR", logs)

            output_dir = self.output_dir.resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            token = uuid4().hex
            output_file = output_dir / f"sensor_bracket_{token}.step"
            stl_file = output_file.with_suffix(".stl")
            temp_path = output_dir / f".sensor_bracket_{token}.tmp.step"
            temp_stl_path = output_dir / f".sensor_bracket_{token}.tmp.stl"
            cq.exporters.export(model, str(temp_path), exportType="STEP")
            # STL 与 STEP 来自同一实体；网格用于预览，STEP 用于工业 CAD 交换。
            cq.exporters.export(model, str(temp_stl_path), exportType="STL",
                                tolerance=0.05, angularTolerance=0.1)
            if any(not path.is_file() or path.stat().st_size == 0
                   for path in (temp_path, temp_stl_path)):
                return _error("STEP/STL 导出没有产生有效文件。", "EXPORT_ERROR", logs)
            temp_path.replace(output_file)
            created_files.append(output_file)
            temp_stl_path.replace(stl_file)
            created_files.append(stl_file)
            export_complete = True
            return {
                "status": "success", "output_file": str(output_file), "stl_file": str(stl_file),
                "physical_properties": {
                    "volume_mm3": volume, "weight_g": volume * DENSITY_G_PER_MM3,
                    "material": MATERIAL, "density_g_per_mm3": DENSITY_G_PER_MM3,
                    "weight_basis": "几何体积 × 推荐均匀密度；未计入探头、紧固件与涂层",
                    "reference_volume_mm3": reference_volume,
                    "weight_reduction_percent": (1 - volume / reference_volume) * 100,
                },
                "triz_logs": logs, "error_message": None,
                "design_parameters": numeric | {
                    "enable_triz_lightening": enable_triz_lightening,
                    "enable_stress_relief": enable_stress_relief,
                    "probe_centers_mm": [[-probe_distance / 2, 0], [probe_distance / 2, 0]],
                    "slot_length_mm": slot_length, "slot_width_mm": slot_width,
                    "chamfer_mm": chamfer, "minimum_web_rule_mm": nominal_web,
                },
                "validation": {
                    "geometry_valid": True, "solid_count": 1,
                    "dimensions_match": True, "edge_clearance_checked": True,
                    "strength_verified": False,
                    "notes": ["未执行有限元应力分析、疲劳计算或载荷试验。",
                              "探头孔为输入直径的通孔，不自动假设螺纹、公差或紧固方式。"],
                },
            }
        except (OSError, PermissionError) as exc:
            return _error(f"STEP/STL 文件导出失败：{type(exc).__name__}: {exc}", "EXPORT_ERROR", logs)
        except Exception as exc:
            return _error(f"几何建模失败：{type(exc).__name__}: {exc}；请检查尺寸或关闭倒角后重试。",
                          "GEOMETRY_ERROR", logs)
        finally:
            # 只清理本次 UUID 对应的文件，不删除以前生成的模型。
            cleanup = [temp_path, temp_stl_path]
            if not export_complete:
                cleanup.extend(created_files)
            for path in cleanup:
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass


def generate_sensor_bracket(
    length: float, width: float, thickness: float, probe_distance: float,
    probe_dia: float = 16.5, enable_triz_lightening: bool = True,
    enable_stress_relief: bool = True,
) -> dict[str, Any]:
    """公共函数入口；参数语义见 CADTool.generate_sensor_bracket。

    导出文件写入本模块旁的 outputs 目录，返回 JSON 可序列化字典。
    """
    return CADTool().generate_sensor_bracket(
        length, width, thickness, probe_distance, probe_dia,
        enable_triz_lightening, enable_stress_relief,
    )


def dispatch_tool_call(name: str, arguments: str | dict[str, Any],
                       *, tool: CADTool | None = None) -> dict[str, Any]:
    """将 Agent 工具调用分发到白名单；不 eval 或执行模型生成代码。

    Args:
        name: 必须为 generate_sensor_bracket。
        arguments: JSON 对象字符串或字典。Python 可选参数沿用默认值。
        tool: 可由宿主注入固定输出目录的工具实例。
    """
    if name != "generate_sensor_bracket":
        return _error(f"不支持的工具：{name}", "UNKNOWN_TOOL")
    try:
        data = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(data, dict):
            return _error("工具参数必须是 JSON 对象。")
        allowed = {"length", "width", "thickness", "probe_distance", "probe_dia",
                   "enable_triz_lightening", "enable_stress_relief"}
        required = {"length", "width", "thickness", "probe_distance"}
        if set(data) - allowed:
            return _error("存在不支持的参数；只允许尺寸与两个功能开关。")
        if required - set(data):
            return _error(f"缺少必需参数：{', '.join(sorted(required - set(data)))}")
        return (tool or CADTool()).generate_sensor_bracket(**data)
    except (ValueError, TypeError, RecursionError) as exc:
        return _error(f"工具参数无法解析：{exc}")

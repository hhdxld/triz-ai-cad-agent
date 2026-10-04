"""参数化带盖空心盒；总高度含盖板，盖子独立零件，预览采用分解位置。"""
import math
from pathlib import Path
from uuid import uuid4

from cad_tool import DEFAULT_OUTPUT_DIR, DENSITY_G_PER_MM3, MATERIAL

BOX_DEFAULTS = {'length': 150., 'width': 140., 'height': 100., 'thickness': 2., 'lid_clearance': .3}


def generate_box_with_lid(length: float, width: float, height: float, thickness: float,
                          lid_clearance: float = .3, *, output_dir=None) -> dict:
    """导出装配 STEP、分解 STL、盒体和盖子 STEP；不自动添加用户未要求的孔。

    解释：length/width/height 为装配外尺寸，壁/底/盖厚均为 thickness。
    推荐定位唇高 3 mm、壁厚 1.5 mm（随薄壁约束缩小），每侧间隙默认 .3 mm。
    """
    params = dict(length=length, width=width, height=height, thickness=thickness, lid_clearance=lid_clearance)
    artifacts = []
    try:
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in params.values()):
            raise ValueError('盒体尺寸必须是有限数值。')
        if any(not 1 <= v <= 1000 for v in (length,width,height)) or not .5 <= thickness <= 50 or not .05 <= lid_clearance <= 2:
            raise ValueError('长宽高需为 1～1000 mm，壁厚 .5～50 mm，每侧配合间隙 .05～2 mm。')
        if min(length,width) <= 2*thickness + 2*lid_clearance + 4 or height <= 3*thickness+2:
            raise ValueError('尺寸无法容纳空腔、底板和盖子定位唇，请增大外尺寸或减小壁厚。')
        import cadquery as cq
        body_height = height-thickness
        inner_l, inner_w = length-2*thickness, width-2*thickness
        body = cq.Workplane('XY').box(length,width,body_height,centered=(True,True,False))
        cavity = cq.Workplane('XY').box(inner_l,inner_w,body_height,centered=(True,True,False)).translate((0,0,thickness))
        body = body.cut(cavity)
        lid = cq.Workplane('XY').box(length,width,thickness,centered=(True,True,False)).translate((0,0,body_height))
        lip_h = min(3., (body_height-thickness)/2)
        lip_t = min(1.5, thickness)
        lip_l, lip_w = inner_l-2*lid_clearance, inner_w-2*lid_clearance
        lip_outer = cq.Workplane('XY').box(lip_l,lip_w,lip_h,centered=(True,True,False)).translate((0,0,body_height-lip_h))
        lip_inner = cq.Workplane('XY').box(lip_l-2*lip_t,lip_w-2*lip_t,lip_h,centered=(True,True,False)).translate((0,0,body_height-lip_h))
        lid = lid.union(lip_outer.cut(lip_inner))
        if any(not part.val().isValid() or len(part.val().Solids()) != 1 for part in (body,lid)):
            raise ValueError('盒体或盖子几何无效。')
        interference = body.val().intersect(lid.val()).Volume()
        if interference > 1e-5:
            raise ValueError('盒体与盖子发生几何干涉。')
        assembled = cq.Compound.makeCompound([body.val(),lid.val()])
        directory = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
        directory.mkdir(parents=True,exist_ok=True)
        stem = directory/('box_'+uuid4().hex)
        step,stl = stem.with_suffix('.step'),stem.with_suffix('.stl')
        body_file, lid_file = directory/(stem.name+'_body.step'), directory/(stem.name+'_lid.step')
        # 精确 STEP 保持装配高度；可旋转 STL 抬高盖子，让用户能看见空腔。
        exploded = cq.Compound.makeCompound([body.val(),lid.val().translate((0,0,max(20.,height*.3)))])
        for shape,path in ((assembled,step),(exploded,stl),(body.val(),body_file),(lid.val(),lid_file)):
            artifacts.append(path)
            cq.exporters.export(shape,str(path))
        volume = assembled.Volume()
        return {'status':'success','model_type':'box_with_lid','output_file':str(step.resolve()),'stl_file':str(stl.resolve()),
            'input_parameters':params,'reduction_percent':0.,
            'physical_properties':{'volume_mm3':volume,'weight_g':volume*DENSITY_G_PER_MM3,'material':MATERIAL},
            'parts':[{'name':'盒体','output_file':str(body_file.resolve())},{'name':'盖子','output_file':str(lid_file.resolve())}],
            'triz_logs':[{'principle_number':1,'principle_name':'分割原理','description':'盒体与盖子分为两个可制造、可拆装零件。'},
                         {'principle_number':7,'principle_name':'嵌套原理','description':'盖子下方定位唇嵌入盒体空腔，每侧保留配合间隙。'}],
            'validation':{'geometry_valid':True,'solid_count':2,'dimensions_match':True,'strength_verified':False,'interference_volume_mm3':interference},
            'design_notes':['总高度包含盖板；壁、底和盖板厚度相同。',
                f'推荐定位唇高 {lip_h:g} mm、壁厚 {lip_t:g} mm，每侧间隙 {lid_clearance:g} mm。',
                'STL 为抬高盖子的分解预览，STEP 为闭合装配位置。未添加螺丝、卡扣或安装孔。',
                '材料按6061铝估算，制造方法尚未指定；配合间隙需按加工工艺调整。']}
    except Exception as exc:
        for path in artifacts:
            path.unlink(missing_ok=True)
        return {'status':'error','error_message':str(exc)[:800]}

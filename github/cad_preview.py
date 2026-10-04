"""内嵌 STL 三维预览：直接传输网格，无临时文件 URL、CDN 或 WebGL 依赖。"""
import base64
import json
import math
from pathlib import Path
import re
import struct

import streamlit as st


def preview_html(path: str | Path, color: str = '#4F8BFF', auto_rotate: bool = False) -> str:
    """验证 CadQuery 二进制 STL，生成带鼠标旋转、缩放和重置的 Canvas 预览。"""
    data = Path(path).read_bytes()
    if len(data) < 84 or len(data) > 16 * 1024 * 1024:
        raise ValueError('模型预览文件为空或过大。')
    count = struct.unpack_from('<I', data, 80)[0]
    if not 0 < count <= 100000 or len(data) != 84 + count * 50:
        raise ValueError('预览需要有效的二进制 STL 文件。')
    for offset in range(84, len(data), 50):
        if not all(math.isfinite(v) for v in struct.unpack_from('<12f', data, offset)):
            raise ValueError('模型网格包含无效坐标。')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('预览颜色无效。')
    config = json.dumps({'data': base64.b64encode(data).decode(), 'color': color, 'rotate': bool(auto_rotate)})
    return HTML.replace('__CONFIG__', config)


def render_preview(path: str | Path, *, color: str, auto_rotate: bool) -> None:
    """固定高度且离线可用；前端错误明确显示，不留下无提示空白。"""
    st.iframe(preview_html(path, color, auto_rotate), height=390, alt='可旋转的三维 CAD 模型预览')


HTML = '''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:100%;height:380px;font:13px sans-serif;color:#52647e}
#view{position:relative;width:100%;height:380px;background:#f3f6fc;border-radius:12px;overflow:hidden}
canvas{display:block;width:100%;height:380px;touch-action:none;cursor:grab}
button{position:absolute;right:12px;top:12px;padding:6px 12px;background:white;border:1px solid #cbd6e7;border-radius:6px;cursor:pointer}
#status{position:absolute;left:12px;bottom:10px;pointer-events:none}
</style></head><body><div id="view"><canvas id="mesh"></canvas><button id="reset">重置视角</button><span id="status">正在加载模型…</span></div>
<script>
const cfg=__CONFIG__, canvas=document.getElementById('mesh'), status=document.getElementById('status');
try {
const context=canvas.getContext('2d'); if(!context)throw Error('浏览器无法创建画布');
const bytes=Uint8Array.from(atob(cfg.data), c=>c.charCodeAt(0)), data=new DataView(bytes.buffer), count=data.getUint32(80,true);
const faces=[], lower=[Infinity,Infinity,Infinity], upper=[-Infinity,-Infinity,-Infinity];
for(let i=0;i<count;i++){const points=[];for(let j=0;j<3;j++){const p=[];for(let k=0;k<3;k++){const v=data.getFloat32(84+i*50+12+j*12+k*4,true);p.push(v);lower[k]=Math.min(lower[k],v);upper[k]=Math.max(upper[k],v);}points.push(p);}faces.push(points);}
const center=lower.map((v,k)=>(v+upper[k])/2), extent=Math.max(...upper.map((v,k)=>v-lower[k]));
if(!(extent>0))throw Error('模型尺寸无效');
for(const face of faces)for(const p of face)for(let k=0;k<3;k++)p[k]=(p[k]-center[k])/extent;
const rgb=[1,3,5].map(i=>parseInt(cfg.color.slice(i,i+2),16));
let yaw=-.6,pitch=.65,zoom=1,drag=false,lastX=0,lastY=0,width=0,height=380;
function transform(p){const x=p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw), y=p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw);return [x,y*Math.cos(pitch)-p[2]*Math.sin(pitch),y*Math.sin(pitch)+p[2]*Math.cos(pitch)];}
function draw(){if(!width)return;context.clearRect(0,0,width,height);const scale=Math.min(width,height)*.78*zoom;
const projected=faces.map(f=>f.map(transform)).sort((a,b)=>a.reduce((s,p)=>s+p[1],0)-b.reduce((s,p)=>s+p[1],0));
for(const f of projected){const a=f[0],b=f[1],c=f[2],u=b.map((v,i)=>v-a[i]),v=c.map((n,i)=>n-a[i]);const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]], len=Math.hypot(...n)||1;
const light=.55+.4*Math.abs((n[0]*.3-n[1]*.7+n[2]*.6)/len);context.fillStyle='rgb('+rgb.map(x=>Math.min(255,Math.round(x*light))).join(',')+')';context.strokeStyle=context.fillStyle;context.lineWidth=.35;context.beginPath();f.forEach((p,i)=>{const x=width/2+p[0]*scale,y=height/2-p[2]*scale;i?context.lineTo(x,y):context.moveTo(x,y);});context.closePath();context.fill();context.stroke();}}
function resize(){width=canvas.clientWidth;const ratio=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(width*ratio);canvas.height=height*ratio;context.setTransform(ratio,0,0,ratio,0,0);draw();}
new ResizeObserver(resize).observe(document.getElementById('view'));resize();
canvas.addEventListener('pointerdown',e=>{drag=true;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-lastX)*.008;pitch=Math.max(-1.5,Math.min(1.5,pitch+(e.clientY-lastY)*.008));lastX=e.clientX;lastY=e.clientY;draw();});
for(const event of ['pointerup','pointercancel'])canvas.addEventListener(event,()=>drag=false);
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.3,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
document.getElementById('reset').onclick=()=>{yaw=-.6;pitch=.65;zoom=1;draw();};
let last=0;function tick(t){if(cfg.rotate&&!drag&&t-last>50){yaw+=.01;draw();last=t;}if(cfg.rotate)requestAnimationFrame(tick);}if(cfg.rotate)requestAnimationFrame(tick);
status.textContent='拖拽旋转 · 滚轮缩放 · '+count+' 个网格面';
}catch(error){status.textContent='预览加载失败：'+error.message+'。可下载 STEP/STL。';status.style.color='#b42318';}
</script></body></html>'''

"""本机交互配置各厂商 API：密钥不回显，不写日志，也不加入公开源码。"""
from getpass import getpass
from pathlib import Path
import os
import toml
from api_providers import PROVIDERS, provider_settings


def main() -> int:
    """每次配置一个厂商，保留其他配置；管理员在网站后台选择启用。"""
    choices=list(PROVIDERS)
    for index,name in enumerate(choices,1):
        print(f"{index}. {PROVIDERS[name]['label']}")
    try:
        number=int(input('选择服务商编号：'))
        if not 1 <= number <= len(choices):
            raise ValueError('编号无效。')
        provider=choices[number-1]
        profile=PROVIDERS[provider]
        model=input('模型名称（请使用该平台实际开通的模型ID）：').strip()
        url=input('接口根地址（直接回车使用官方预设；地区/专用套餐可能不同）：').strip() or profile['url']
        key=getpass('API Key（输入不回显）：').strip()
        if not model or not key:
            raise ValueError('模型名称和 API Key 均不能为空。')
        prefix=profile['prefix']
        updates={prefix+'_API_KEY':key,prefix+'_MODEL':model,prefix+'_BASE_URL':url,
                 prefix+'_PROTOCOL':'Chat Completions'}
        provider_settings(provider,lambda name,default='':updates.get(name,default))
        target=Path(__file__).resolve().parent/'.streamlit/secrets.toml'
        target.parent.mkdir(exist_ok=True)
        values=toml.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
        values.update(updates)
        values.setdefault('AICAD_API_PROVIDER',provider)
        values.setdefault('AICAD_ALLOW_DEMO_API','false')
        temporary=target.with_name('secrets.toml.tmp')
        try:
            with temporary.open('w',encoding='utf-8') as output:
                output.write(toml.dumps(values))
            temporary.chmod(0o600)
            os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)
        print('配置已保存。请在管理员后台选择该服务商，并在工作台切换在线模型 API。')
        print('尚未发送真实 API 请求；先用一条小需求验证工具调用，图片需单独验证。')
        return 0
    except (ValueError,OSError,toml.TomlDecodeError) as exc:
        print('配置失败，请检查输入或文件权限；未发出 API 请求。')
        return 1


if __name__=='__main__':
    raise SystemExit(main())

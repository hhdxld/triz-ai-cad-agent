"""多厂商 OpenAI 兼容接口配置；密钥由服务端读取，不提供给访客。"""
from urllib.parse import urlparse

PROVIDERS = {
    'openai': {'label':'OpenAI', 'prefix':'OPENAI','url':'https://api.openai.com/v1'},
    'deepseek': {'label':'DeepSeek','prefix':'DEEPSEEK','url':'https://api.deepseek.com/v1'},
    'kimi': {'label':'Kimi / 月之暗面','prefix':'KIMI','url':'https://api.moonshot.cn/v1'},
    'qwen': {'label':'阿里百炼 / 千问','prefix':'QWEN','url':'https://dashscope.aliyuncs.com/compatible-mode/v1'},
    'gemini': {'label':'Google Gemini','prefix':'GEMINI','url':'https://generativelanguage.googleapis.com/v1beta/openai/'},
    'doubao': {'label':'火山方舟 / 豆包','prefix':'DOUBAO','url':'https://ark.cn-beijing.volces.com/api/v3'},
    'siliconflow': {'label':'硅基流动','prefix':'SILICONFLOW','url':'https://api.siliconflow.cn/v1'},
    'custom': {'label':'其他 OpenAI 兼容接口','prefix':'CUSTOM_AI','url':''},
}


def provider_settings(provider: str, setting) -> dict:
    """选定供应商只读取自己的密钥，不能跨厂商回退发送凭证。"""
    if provider not in PROVIDERS:
        raise ValueError('不支持的 API 服务商。')
    profile = PROVIDERS[provider]
    prefix = profile['prefix']
    url = setting(prefix+'_BASE_URL',profile['url']).strip()
    if url:
        parsed=urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('模型 API 地址必须是无账号信息的 HTTPS 接口根地址。')
    protocol = setting(prefix+'_PROTOCOL', setting('AICAD_API_PROTOCOL','Chat Completions') if provider == 'openai' else 'Chat Completions')
    if protocol not in ('Responses','Chat Completions'):
        raise ValueError('不支持的 API 协议。')
    return {'provider':provider,'provider_label':profile['label'], 'api_key':setting(prefix+'_API_KEY'),
            'base_url':url, 'model':setting(prefix+'_MODEL'), 'protocol':protocol,
            'allow_demo_api':setting('AICAD_ALLOW_DEMO_API','false').lower() == 'true'}

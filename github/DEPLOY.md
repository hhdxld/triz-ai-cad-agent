# GitHub 与公网试用发布

## 免费试用方案

GitHub 保存源码，Streamlit Community Cloud 运行 Python 应用并提供公开 HTTPS 链接。
GitHub Pages 是静态托管，不能直接运行 Streamlit/CadQuery 服务。

规则识别、CAD 生成和下载不调用模型 API。应用本身没有收费功能，访客可免费体验。
托管免费不等于无限并发或永久在线；CAD 工作负载须以实际云端安装、启动及建模验证结果为准。
后续使用其他服务器、域名或付费 API 时，费用取决于服务商和账户配置。

## 要上传的内容

上传源码、requirements.txt、packages.txt、tool_definition.json、.streamlit/config.toml、测试和文档。
不要上传 .venv、API 密钥、secrets.toml、生成模型、日志或 .git 目录。
这些本地内容已通过 .gitignore 排除。

## Streamlit Community Cloud 部署步骤

1. 将当前项目推送到你的 GitHub 仓库。
2. 登录 https://share.streamlit.io ，连接具有仓库管理权限的 GitHub 账号。
3. 选择 Create app，指定仓库、实际分支和入口 app.py。
4. Advanced settings 中选择 Python 3.12。requirements.txt 用于 Python 依赖，packages.txt 用于 Debian 图形库依赖。
5. 不配置共享 OPENAI_API_KEY；默认规则识别无需密钥。在线模式由访客填写自己的密钥。
6. 设置公开访问，部署后从平台取得实际分配的 *.streamlit.app 链接。
7. 用未登录的浏览器测试访问，生成“长100宽45厚5孔距50孔径16.5”，确认STL加载和STEP下载；再测试修改与非法尺寸。

不要把本机 127.0.0.1 链接当作公网地址。只有平台实际部署成功并验证后，才能宣称已上线。

## 平台资源与后续经营

现阶段适合比赛展示和小规模试用，不能承诺无限使用。云容器的本地文件不作为永久项目存储；用户应下载成果。
如果实际试用出现内存不足或并发排队问题，可转为配置明确的服务器，并增加任务队列、使用额度和成果存储。
用户收费与平台收费是两件事：你可以保持规则试用免费，以团队功能或设计服务收费；当前应用尚未实现支付或订阅。

## 官方参考

- https://docs.streamlit.io/deploy/streamlit-community-cloud
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site

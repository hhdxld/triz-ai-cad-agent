# GitHub 与公网试用发布

需要必须登录、独立后台和长期运行时，请使用 `hosted_app.py` 与 [正式网站部署说明](正式网站部署说明.md)。下方 Community Cloud 内容用于试用；不得直接用临时容器数据库经营真实收费业务。

## 免费试用方案

GitHub 保存源码，Streamlit Community Cloud 运行 Python 应用并提供公开 HTTPS 链接。
GitHub Pages 是静态托管，不能直接运行 Streamlit/CadQuery 服务。

规则识别、CAD 生成和下载不调用模型 API。应用已有演示按次计费与订单，但未接入真实支付，不收取真实款项。
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
5. 默认规则识别无需密钥。站长 API 只能放在服务器 Secrets，不能上传源码；在线模式不会向访客显示密钥。演示计费下默认关闭真实 API，公开演示不要开启真实 API。
6. 设置公开访问，部署后从平台取得实际分配的 *.streamlit.app 链接。
7. 用未登录的浏览器测试访问，生成“长100宽45厚5孔距50孔径16.5”，确认STL加载和STEP下载；再测试修改与非法尺寸。

不要把本机 127.0.0.1 链接当作公网地址。只有平台实际部署成功并验证后，才能宣称已上线。

## 平台资源与后续经营

现阶段适合比赛展示和小规模试用，不能承诺无限使用。云容器的本地文件不作为永久项目存储；用户应下载成果。
如果实际试用出现内存不足或并发排队问题，可转为配置明确的服务器，并增加任务队列、使用额度和成果存储。
用户收费与平台收费是两件事。当前已实现演示服务订单，真实支付和订阅尚未接入。账户与账本使用本机 SQLite；公开收费前必须使用持久化数据存储、支付验证、对账和退款流程，不要将云端临时容器当作真实资金账本。

## 官方参考

- https://docs.streamlit.io/deploy/streamlit-community-cloud
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site

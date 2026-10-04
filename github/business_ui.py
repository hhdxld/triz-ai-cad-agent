"""账户、演示账单与站长统计 UI；不提供伪造支付成功的按钮。"""
import csv
import io
import os
from pathlib import Path

import streamlit as st

from business import BusinessStore, BusinessError
from api_providers import PROVIDERS, provider_settings

ROOT = Path(__file__).resolve().parent


def get_store() -> BusinessStore | None:
    """演示计费默认开启；关闭仅由服务器环境变量控制，访客不能切换。"""
    mode = os.getenv("AICAD_BILLING_MODE", "demo")
    if mode == "off":
        return None
    if mode != "demo":
        raise BusinessError("真实收款尚未接入。当前仅支持 demo 演示或 off 本地免费模式。")
    return BusinessStore(os.getenv("AICAD_DATABASE_PATH", str(ROOT / "outputs" / "business.sqlite")))


def server_api_settings(selected_provider: str | None = None) -> dict:
    """只在服务器读取站长 API 配置，返回值不得用于浏览器输入框或日志。"""
    def setting(name: str, default: str = "") -> str:
        value = os.getenv(name)
        if value is not None:
            return value
        try:
            return str(st.secrets.get(name, default))
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            return default
    store=get_store()
    provider=selected_provider or (store.api_provider() if store else None) or setting('AICAD_API_PROVIDER','openai')
    try:
        return provider_settings(provider,setting)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None


def configured_site_providers() -> list[str]:
    """仅返回已配密钥与模型的厂商编号，不把凭证传到选择组件。"""
    available=[]
    for provider in PROVIDERS:
        try:
            config=server_api_settings(provider)
            if config['api_key'] and config['model'] and config['base_url']:
                available.append(provider)
        except BusinessError:
            continue
    return available


def clear_design() -> None:
    """切换账户时清除模型、聊天和尺寸，防止同一浏览器看到前一账户成果。"""
    for key in ("messages", "last_params", "latest_result", "last_error"):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith('attachment_') and key != 'attachment_api_requests':
            st.session_state.pop(key, None)
    st.session_state.editor_sync = True


def session_user(store: BusinessStore) -> dict | None:
    """每次交互核验会话版本；密码变更使其他会话在下次访问时退出。"""
    account_id=st.session_state.get('account_id')
    if not account_id:
        return None
    try:
        user=store.user(account_id)
    except BusinessError:
        user=None
    if user and st.session_state.get('account_version',user['auth_version'])==user['auth_version']:
        st.session_state.account_version=user['auth_version']
        return user
    st.session_state.pop('account_id',None)
    st.session_state.pop('account_version',None)
    st.session_state.auth_clear_pending=True
    clear_design()
    st.info('账户登录状态已更新，请重新登录。')
    return None


def render_password_change(store: BusinessStore, user: dict) -> None:
    """修改密码需旧密码校验，提交完成后清空所有密码组件。"""
    if st.session_state.pop('password_clear_pending',False):
        for name in ('change_old_password','change_new_password','change_confirm_password'):
            st.session_state.pop(name,None)
    if st.session_state.pop('password_changed_notice',False):
        st.success('密码已修改；其他会话将在下一次交互时退出。')
    with st.expander('账户安全 · 修改密码'):
        with st.form('change_password'):
            old=st.text_input('当前密码',type='password',key='change_old_password',max_chars=128)
            new=st.text_input('新密码',type='password',key='change_new_password',max_chars=128)
            confirm=st.text_input('再次输入新密码',type='password',key='change_confirm_password',max_chars=128)
            st.caption('新密码至少 10 个字符。忘记密码的邮件恢复暂未接入。')
            if st.form_submit_button('修改密码'):
                try:
                    if new!=confirm:
                        raise BusinessError('两次新密码不一致。')
                    updated=store.change_password(user['id'],old,new)
                    st.session_state.account_version=updated['auth_version']
                    st.session_state.password_changed_notice=True
                except BusinessError as exc:
                    st.session_state.password_change_error=str(exc)
                st.session_state.password_clear_pending=True
                st.rerun()
        error=st.session_state.pop('password_change_error','')
        if error:
            st.error(error)


def render_account(store: BusinessStore | None) -> tuple[dict | None, bool, int]:
    """在侧栏呈现登录与价格，返回服务器验证的当前用户和价格快照。"""
    if store is None:
        return None, True, 0
    if st.session_state.pop("auth_clear_pending", False):
        for key in ("login_password", "register_password", "register_confirm"):
            st.session_state.pop(key, None)
        for key in list(st.session_state):
            if key.startswith(('personal_api_','project_','change_','password_')):
                st.session_state.pop(key,None)
    account_id = st.session_state.get("account_id")
    user = session_user(store) if account_id else None
    price = store.price_fen()
    st.markdown("#### 账户与服务费")
    st.warning("演示计费 · 不收取真实款项")
    st.caption(f"每次成功生成 ¥{price / 100:.2f}（演示）；修改重新生成计一次。失败退回，重复下载免费。")
    if user:
        st.write(f"当前账户：**{user['username']}**")
        st.write(f"演示余额：**¥{user['balance_fen'] / 100:.2f}**")
        with st.expander('充值中心 · 待开发'):
            st.info('充值和真实支付正在开发，当前不能付款或增加真实余额。')
            st.button('充值余额（暂未开放）',disabled=True,key='recharge_pending',use_container_width=True)
        render_password_change(store,user)
        consent = st.checkbox(f"同意每次成功生成扣 ¥{price / 100:.2f} 演示额度",
                              key=f"fee_consent_{user['id']}_{price}")
        if st.button("退出登录", key="logout", use_container_width=True):
            st.session_state.pop("account_id", None)
            st.session_state.pop('account_version',None)
            st.session_state.auth_clear_pending = True
            for key in list(st.session_state):
                if key.startswith("fee_consent_"):
                    st.session_state.pop(key, None)
            clear_design()
            st.rerun()
        return user, consent, price
    st.caption("请先注册或登录，再体验按次计费。新账户获得 ¥10 演示额度。")
    login, register = st.tabs(["登录", "注册"])
    with login:
        with st.form("login"):
            username = st.text_input("用户名", key="login_username")
            password = st.text_input("密码", type="password", key="login_password")
            if st.form_submit_button("登录账户", use_container_width=True):
                account = store.authenticate(username, password)
                if account:
                    st.session_state.account_id = account["id"]
                    st.session_state.account_version=account['auth_version']
                    st.session_state.auth_clear_pending = True
                    clear_design()
                    st.rerun()
                st.error("用户名或密码错误，或账户暂时锁定。")
    with register:
        with st.form("register"):
            username = st.text_input("新用户名", key="register_username", help="3～32 位英文字母、数字或下划线")
            password = st.text_input("新密码", type="password", key="register_password", help="至少 10 个字符")
            confirmation = st.text_input("确认密码", type="password", key="register_confirm")
            if st.form_submit_button("注册并登录", use_container_width=True):
                try:
                    if password != confirmation:
                        raise BusinessError("两次密码不一致。")
                    account = store.register(username, password)
                    st.session_state.account_id = account["id"]
                    st.session_state.account_version=account['auth_version']
                    st.session_state.auth_clear_pending = True
                    clear_design()
                    st.rerun()
                except BusinessError as exc:
                    st.error(str(exc))
    return None, False, price


def csv_report(rows: list[dict]) -> bytes:
    """导出 UTF-8 BOM CSV；阻止用户描述在 Excel 中作为公式执行。"""
    buffer = io.StringIO()
    columns = ["订单号", "用户", "需求", "状态", "报价_元_演示", "结算_元_演示", "创建时间_UTC"]
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        prompt = row["prompt"]
        if prompt.lstrip().startswith(("=", "+", "-", "@")):
            prompt = "'" + prompt
        writer.writerow([row["id"], row["username"], prompt, row["status"],
                         f"{row['fee_fen']/100:.2f}", f"{row['fee_fen']/100:.2f}" if row["status"] == "success" else "0.00",
                         row["created_at"]])
    return buffer.getvalue().encode("utf-8-sig")


def render_orders(store: BusinessStore, user: dict | None) -> None:
    """个人账单和全站仪表盘；未登录者与普通用户看不到全站数据。"""
    st.subheader("我的服务订单")
    if not user:
        st.info("登录后查看自己的订单、服务费和退款状态。")
        return
    rows = store.orders(user["id"])
    statuses = {"success": "成功 · 已结算", "failed": "失败 · 已退回", "reserved": "处理中 · 已预占"}
    if rows:
        display = [{"订单": r["id"][:12], "需求": r["prompt"], "状态": statuses[r["status"]],
                    "报价（演示）": f"¥{r['fee_fen']/100:.2f}",
                    "结算（演示）": f"¥{r['fee_fen']/100:.2f}" if r["status"] == "success" else "¥0.00",
                    "时间（UTC）": r["created_at"]} for r in rows]
        st.dataframe(display, hide_index=True, width="stretch")
        st.download_button("导出我的订单 CSV", csv_report(rows), "my-service-orders.csv", "text/csv")
    else:
        st.caption("还没有订单。成功或失败的建模请求都会留下记录。")
    st.caption("最多显示最近 500 笔。处理中金额为预占，未计入成功服务费。所有金额均为演示，不代表真实支付。")
    if user["role"] != "admin":
        return
    st.divider()
    render_admin(store, user)


def render_admin(store: BusinessStore, user: dict) -> None:
    """独立管理面板；先从数据库验证权限，再输出任何全站信息。"""
    statistics = store.statistics(user["id"])
    st.subheader("AI 接入状态")
    rows=[]
    for provider in PROVIDERS:
        try:
            configured=server_api_settings(provider)
            rows.append({'厂商':PROVIDERS[provider]['label'],'模型':configured['model'] or '未填写',
                '配置状态':'已配置 · 不代表调用验证' if configured['api_key'] and configured['model'] else '未完整配置'})
        except BusinessError:
            rows.append({'厂商':PROVIDERS[provider]['label'],'模型':'—','配置状态':'配置无效'})
    st.dataframe(rows,hide_index=True,width='stretch')
    api = server_api_settings()
    choices=list(PROVIDERS)
    with st.form('ai_provider'):
        chosen=st.selectbox('本站使用的 AI 服务商',choices,index=choices.index(api['provider']),
                            format_func=lambda name:PROVIDERS[name]['label'],key='admin_api_provider')
        st.caption('切换只改变供应商，需先在服务端配置该厂商的独立密钥和模型；不会自动测试或产生 API 费用。')
        if st.form_submit_button('切换 AI 服务商'):
            store.set_api_provider(user['id'],chosen)
            st.rerun()
    st.caption('当前服务商：'+api['provider_label'])
    if api['api_key'] and api['model']:
        st.info("已配置 API 密钥和模型名称，但配置存在不代表接口调用已验证成功。")
    else:
        st.error("AI 未连接：当前只运行本地参数工具，没有调用模型 API。")
        st.caption("请在服务端环境变量或 .streamlit/secrets.toml 配置 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL。不要公开密钥。")
    st.subheader("站长经营统计")
    a, b, c, d = st.columns(4)
    a.metric("注册客户", statistics["users"])
    b.metric("成功订单", statistics["successful_orders"])
    c.metric("演示服务费 · 非收入", f"¥{statistics['demo_service_fen']/100:.2f}")
    d.metric("真实到账收入", "¥0.00")
    st.caption(f"失败 {statistics['failed_orders']} 笔 · 处理中 {statistics['pending_orders']} 笔 · 共 {statistics['total_orders']} 笔。"
               "支付平台未接入，无法统计真实利润；API、托管、手续费和税费也需计入成本。")
    with st.form("pricing"):
        price = st.number_input("每次服务费（分，演示）", min_value=1, max_value=100000,
                                value=store.price_fen(), step=1, key="admin_price")
        daily_limit = st.number_input("每人每天最多请求次数", 1, 100, store.daily_limit(), key="admin_daily_limit")
        if st.form_submit_button("保存服务价格与限额"):
            store.set_price(user["id"], int(price))
            store.set_daily_limit(user["id"], int(daily_limit))
            st.rerun()
    all_rows = store.orders(user["id"], all_users=True)
    if all_rows:
        st.dataframe(all_rows, hide_index=True, width="stretch")
        st.download_button("导出全站订单 CSV", csv_report(all_rows), "all-service-orders.csv", "text/csv")
    st.subheader('用户查询')
    search=st.text_input('按用户名查找',key='admin_user_search',max_chars=32)
    accounts=store.users(user['id'],search)
    st.dataframe([{'用户名':r['username'],'角色':r['role'],'站内 API 试用':'已开启' if r['site_api_access'] else '未开启','演示余额 / 元':r['balance_fen']/100,
        '注册时间（UTC）':r['created_at']} for r in accounts],hide_index=True,width='stretch')
    st.caption('最多显示 200 个账户；不显示密码或密钥，不提供手工伪造充值。')
    if accounts:
        choices={r['id']:r for r in accounts}
        if st.session_state.get('admin_trial_user') not in choices:
            st.session_state.pop('admin_trial_user',None)
        with st.form('admin_trial_access'):
            target=st.selectbox('试用权限账户',list(choices),format_func=lambda key:choices[key]['username'],key='admin_trial_user')
            action=st.radio('站内 API 试用权限',['关闭','开启'],key='admin_trial_action',horizontal=True)
            st.caption('开启后该用户的站内文字和图片调用消耗站长真实 API 额度；仍受每日请求限制，充值尚未接入。')
            if st.form_submit_button('保存试用权限'):
                store.set_site_api_access(user['id'],target,action=='开启')
                st.rerun()
    st.caption("管理员通过本机“设置管理员.cmd”创建。真实收款需支付网关验签、到账核对和持久化部署，当前未启用。")

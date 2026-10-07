"""云端主入口：所有工作台页面要求登录，管理员使用独立入口。

启动：streamlit run hosted_app.py
后台：网站地址/?page=admin。入口地址公开，数据权限由数据库角色验证。
当前账本仍为演示；未接入支付平台时绝不标记为真实收款。
"""
import time

import streamlit as st

from app import DEFAULT_PARAMS, LABELS, format_report, process_request
from business import BusinessError
from business_ui import clear_design, get_store, render_account, render_admin, session_user
from workspace_ui import STYLE, render_workspace


def main() -> None:
    """登录状态只在服务器会话保存，管理员权限在每次访问时重新查询。"""
    st.set_page_config(page_title="Green beans AI CAD", page_icon="⚙️", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    try:
        store = get_store()
        if store is None:
            raise BusinessError("云端入口必须启用账户与账单，不能使用 off 免费绕过模式。")
        account_id = st.session_state.get("account_id")
        user = session_user(store) if account_id else None
        # 闲置 30 分钟后，在下一次页面交互时重新登录；不将密码存到浏览器。
        now = time.monotonic()
        last_active = st.session_state.get("last_active", now)
        if user and now - last_active > 1800:
            st.session_state.pop("account_id", None)
            st.session_state.auth_clear_pending = True
            clear_design()
            user = None
            st.info("登录已超时，请重新登录。")
        st.session_state.last_active = now
        if not user:
            # 未登录时只呈现认证表单，不创建建模、下载或后台组件。
            st.title("欢迎使用 Green beans AI CAD")
            st.write("登录后描述尺寸、生成三维零件，并在个人订单中查看服务记录。")
            st.caption("目前处于演示计费阶段，尚未开放真实收款。")
            render_account(store)
            return
        if st.query_params.get("page") == "admin":
            with st.sidebar:
                st.title("网站管理")
                render_account(store)
                st.link_button("返回建模工作台", "?")
            if user["role"] != "admin":
                st.error("此页面仅限管理员访问。")
                return
            st.title("管理员控制台")
            render_admin(store, user)
            return
        render_workspace(process_request, format_report, DEFAULT_PARAMS, LABELS)
        if user["role"] == "admin":
            with st.sidebar:
                st.link_button("管理员入口", "?page=admin")
    except BusinessError as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()

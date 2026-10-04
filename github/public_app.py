"""免登录公开体验入口；不调用站长 API、不打开计费和管理界面。"""
from app import process_request, format_report, DEFAULT_PARAMS, LABELS
from workspace_ui import render_workspace


if __name__ == "__main__":
    render_workspace(process_request, format_report, DEFAULT_PARAMS, LABELS, public=True)

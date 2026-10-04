"""启动或复用本机离线网站；服务在后台运行，启动器可以退出。

由启动网站.cmd调用。--no-browser适合验证和只启动服务的场景。
不安装系统服务、不修改开机启动项；重启电脑后再次运行启动入口即可。
"""

import argparse
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8501"


def is_running() -> bool:
    """只检查本机健康接口，不连接互联网；禁用代理避免绕过本地地址。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read().decode().strip() == "ok"
    except (OSError, ValueError):
        return False


def main() -> int:
    """必要时启动后台服务，确认可用后打开本机链接。"""
    parser = argparse.ArgumentParser(description="TRIZ AI CAD 离线网站启动器")
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不打开浏览器")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not is_running():
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            print("未找到项目Python环境。请按README安装依赖后重试。")
            return 1
        log = ROOT / "outputs" / "offline_server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as output:
            service = subprocess.Popen(
                [str(python), "-m", "streamlit", "run", str(ROOT / "app.py"),
                 "--server.address", "127.0.0.1", "--server.port", "8501",
                 "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        for _ in range(30):
            if is_running():
                break
            if service.poll() is not None:
                print(f"网站启动失败，请查看日志：{log}")
                return 1
            time.sleep(0.5)
        else:
            print(f"网站尚未就绪，请查看日志：{log}")
            return 1
    print(f"离线网站已就绪：{URL}")
    if not args.no_browser:
        webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

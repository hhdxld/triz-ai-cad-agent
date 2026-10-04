"""发布或关闭本机免费体验入口的临时 HTTPS 链接，不配置系统服务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
CLIENT = ROOT / ".local-tools" / "cloudflare" / "cloudflared.exe"
STATE = ROOT / "outputs" / "public_tunnel.json"
LOG = ROOT / "outputs" / "public_tunnel.log"
ORIGIN = "http://127.0.0.1:8502"
EXPECTED_SHA256 = "f096265ec2fcbe9bb6e2d64268db167ced3fcbb83d894bdb9e2fcdb26f2ea7e2"


def owned_process(pid: int) -> bool:
    """停止/复用前核验 PID 对应本项目客户端及公开端口，避免 PID 重用误操作。"""
    if type(pid) is not int or pid <= 0:
        return False
    safe_path = str(CLIENT.resolve()).replace("'", "''")
    command = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if ($p.ExecutablePath -eq '{safe_path}' -and $p.CommandLine -like '*--url {ORIGIN}*') {{ 'MATCH' }}"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0 and result.stdout.strip() == "MATCH"


def ready(url: str) -> bool:
    try:
        request = urllib.request.Request(url + "/_stcore/health", headers={"User-Agent": "TRIZ-CAD-healthcheck"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200 and response.read().strip() == b"ok"
    except (OSError, ValueError):
        return False


def main() -> int:
    """创建公网链接；--stop 只关闭本项目通道，网站和管理员本地入口保留。"""
    global STATE, LOG, ORIGIN
    parser = argparse.ArgumentParser(description="TRIZ AI CAD 公网链接")
    parser.add_argument("--hosted", action="store_true", help="发布需要登录的完整网站，端口8503")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.hosted:
        STATE = ROOT / "outputs" / "hosted_tunnel.json"
        LOG = ROOT / "outputs" / "hosted_tunnel.log"
        ORIGIN = "http://127.0.0.1:8503"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    active = owned_process(state.get("pid", 0))
    if args.stop:
        if active:
            os.kill(state["pid"], signal.SIGTERM)
        STATE.write_text("{}", encoding="utf-8")
        print("公网通道已关闭。本机网站仍可使用。")
        return 0
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    subprocess.run([str(python), str(ROOT / "start_offline.py"), "--hosted" if args.hosted else "--public", "--no-browser"], check=True)
    if not active:
        if not CLIENT.is_file():
            print("缺少 Cloudflare 官方客户端，请参阅公网体验说明。")
            return 1
        if hashlib.sha256(CLIENT.read_bytes()).hexdigest() != EXPECTED_SHA256:
            print("公网客户端校验失败，未执行程序。")
            return 1
        with LOG.open("wb") as output:
            process = subprocess.Popen([str(CLIENT), "tunnel", "--url", ORIGIN, "--protocol", "http2"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        state = {"pid": process.pid, "url": ""}
        STATE.write_text(json.dumps(state), encoding="utf-8")
    url = state.get("url", "")
    for _ in range(45):
        content = LOG.read_text(encoding="utf-8", errors="replace") if LOG.is_file() else ""
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", content)
        if match:
            url = match.group(0)
            state["url"] = url
            STATE.write_text(json.dumps(state), encoding="utf-8")
            if ready(url):
                print(f"{'登录网站' if args.hosted else '公开体验'}链接已通过健康检查：{url}")
                print("请保持电脑联网、网站和通道运行。重启通道可能生成新链接。")
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
        time.sleep(1)
    print(f"公网连接尚未就绪，请查看 {LOG}")
    if url:
        print(f"平台分配链接（尚未通过健康检查）：{url}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""容器启动器：运行需登录的站点，并定期备份数据库。

进程异常退出会将退出码传给托管平台，由平台执行自动重启。
"""
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from site_backup import backup_database

ROOT = Path(__file__).resolve().parent


def main() -> int:
    """PORT 来自托管平台；只运行一个实例，共享同一持久化磁盘。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output = Path(os.getenv("AICAD_OUTPUT_DIR", str(ROOT / "outputs")))
    output.mkdir(parents=True, exist_ok=True)
    database = Path(os.getenv("AICAD_DATABASE_PATH", str(output / "business.sqlite")))
    directory = Path(os.getenv("AICAD_BACKUP_DIR", str(output / "backups")))
    # 统一传给子进程，避免模型与账本写到容器临时层。
    os.environ["AICAD_OUTPUT_DIR"] = str(output)
    os.environ["AICAD_DATABASE_PATH"] = str(database)
    os.environ.setdefault("AICAD_BILLING_MODE", "demo")
    interval = int(os.getenv("AICAD_BACKUP_INTERVAL_SECONDS", "21600"))
    if interval < 60:
        raise ValueError("备份间隔至少为 60 秒。")
    stopped = threading.Event()

    def backups() -> None:
        while not stopped.is_set():
            try:
                result = backup_database(database, directory, keep=14)
                if result:
                    logging.info("数据库备份完成")
            except Exception:
                # 不输出账户信息、密钥或数据库内容；服务继续运行，日志可触发平台告警。
                logging.error("数据库备份失败，请检查持久化磁盘与权限")
            stopped.wait(interval)

    threading.Thread(target=backups, name="database-backup", daemon=True).start()
    port = int(os.getenv("PORT", "8501"))
    if not 1 <= port <= 65535:
        raise ValueError("端口应在 1 到 65535 之间。")
    child = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", str(ROOT / "hosted_app.py"),
        "--server.address=0.0.0.0", f"--server.port={port}", "--server.headless=true",
        "--server.enableXsrfProtection=true", "--server.enableCORS=true",
        "--browser.gatherUsageStats=false",
    ])

    def shutdown(*_args) -> None:
        stopped.set()
        child.terminate()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        return child.wait()
    finally:
        stopped.set()


if __name__ == "__main__":
    raise SystemExit(main())

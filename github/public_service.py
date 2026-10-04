"""公开体验入口的单进程并发保护和每日全站限额，不存储访客描述。"""
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from threading import BoundedSemaphore

WORKER = BoundedSemaphore(1)
ROOT = Path(__file__).resolve().parent


def error(message: str) -> dict:
    return {"status": "error", "error_message": message}


def run_public(prompt: str, generate) -> dict:
    """限额内执行本地 CAD；额度不足、并发忙、超长输入均不调用生成器。"""
    if not prompt.strip() or len(prompt) > 2000:
        return error("请将需求控制在 1～2000 字以内。")
    if not WORKER.acquire(blocking=False):
        return error("建模服务正忙，请稍后重试，上一模型已保留。")
    connection = None
    try:
        path = Path(os.getenv("AICAD_PUBLIC_USAGE_DB", str(ROOT / "outputs" / "public_usage.sqlite")))
        path.parent.mkdir(parents=True, exist_ok=True)
        limit = int(os.getenv("AICAD_PUBLIC_DAILY_LIMIT", "100"))
        connection = sqlite3.connect(path, timeout=10)
        connection.execute("CREATE TABLE IF NOT EXISTS daily_usage(day TEXT PRIMARY KEY,requests INTEGER NOT NULL)")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        day = datetime.now(timezone.utc).date().isoformat()
        connection.execute("INSERT OR IGNORE INTO daily_usage VALUES (?,0)", (day,))
        count = connection.execute("SELECT requests FROM daily_usage WHERE day=?", (day,)).fetchone()[0]
        if count >= limit:
            connection.rollback()
            return error("公开体验今日请求已达上限，请明天再试。")
        connection.execute("UPDATE daily_usage SET requests=requests+1 WHERE day=?", (day,))
        connection.commit()
        return generate()
    except Exception:
        return error("公开建模服务暂时不可用，请稍后重试。")
    finally:
        if connection is not None:
            connection.close()
        WORKER.release()

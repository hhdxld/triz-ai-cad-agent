"""通过 SQLite 在线备份 API 保存一致账本；只清理本工具创建的历史副本。"""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
from uuid import uuid4


def backup_database(source: str | Path, directory: str | Path, *, keep: int = 14) -> Path | None:
    """返回已验证副本；数据库尚未创建时返回 None，不伪造空数据库。

    注意：副本包含密码哈希及订单，应保存在受保护的服务端目录。
    同一磁盘备份用于防止误操作，不能替代异地备份。
    """
    if keep < 1:
        raise ValueError("备份保留数量必须大于零。")
    source, directory = Path(source).resolve(), Path(directory).resolve()
    if not source.is_file():
        return None
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = directory / f"aicad-db-{stamp}-{uuid4().hex[:8]}.sqlite"
    temporary = output.with_suffix(".partial")
    try:
        # 使用只读 URI 打开原库；backup() 与并发事务兼容，避免直接拷贝 WAL 文件。
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=15)) as original:
            with closing(sqlite3.connect(temporary)) as copy:
                original.backup(copy, pages=256, sleep=0.05)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("备份完整性校验失败。")
        temporary.chmod(0o600)
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    # 时间戳排序与 UUID 防止同秒覆盖；只处理固定命名且位于目标目录的文件。
    owned = sorted(directory.glob("aicad-db-*.sqlite"), reverse=True)
    for old in owned[keep:]:
        if old.is_file() and not old.is_symlink() and old.resolve().parent == directory:
            old.unlink()
    return output

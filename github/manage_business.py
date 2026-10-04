"""服务器本机管理命令：创建管理员，密码交互输入且不回显。"""
import argparse
from getpass import getpass
import os
from pathlib import Path

from business import BusinessStore, BusinessError


def main() -> int:
    parser = argparse.ArgumentParser(description="设置 TRIZ CAD 站长账号")
    parser.add_argument("command", choices=["init-admin"])
    args = parser.parse_args()
    store = BusinessStore(os.getenv("AICAD_DATABASE_PATH", str(Path(__file__).parent / "outputs" / "business.sqlite")))
    username = input("管理员用户名（英文字母/数字/下划线）：").strip()
    password = getpass("密码（至少10位，输入不显示）：")
    confirmation = getpass("再次输入密码：")
    try:
        if password != confirmation:
            raise BusinessError("两次密码不一致。")
        store.create_admin(username, password)
    except BusinessError as exc:
        print(str(exc))
        return 1
    print("管理员已创建。打开登录网站并登录后，点击管理员入口；也可访问网站地址/?page=admin。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

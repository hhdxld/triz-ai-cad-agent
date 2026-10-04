"""本地账户与演示计费账本：金额用整数分，成功结算，失败退款。

本模块没有支付网关，不接收银行卡/支付密钥，不把演示额度当作真实收入。
SQLite 事务负责并发预占与幂等；商用部署需持久化数据库和真实支付接入。
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Callable
from uuid import uuid4


class BusinessError(ValueError):
    """可安全向用户展示的业务错误。"""


def utc_now() -> str:
    """统一用 UTC 记录订单时间，页面明确标注时区。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BusinessStore:
    """持久化用户、演示余额、价格快照和服务订单，不保存模型 API 密钥。"""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('customer','admin')),
                    balance_fen INTEGER NOT NULL CHECK(balance_fen>=0),
                    failed_logins INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS site_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    prompt TEXT NOT NULL, fee_fen INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved','success','failed')),
                    result_json TEXT, created_at TEXT NOT NULL, finished_at TEXT,
                    UNIQUE(user_id,request_key));
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL,
                    action TEXT NOT NULL, value INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    order_id TEXT NOT NULL REFERENCES orders(id), name TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(user_id,order_id));
            """)
            if 'auth_version' not in {r['name'] for r in db.execute('PRAGMA table_info(users)')}:
                db.execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
            if 'site_api_access' not in {r['name'] for r in db.execute('PRAGMA table_info(users)')}:
                db.execute('ALTER TABLE users ADD COLUMN site_api_access INTEGER NOT NULL DEFAULT 0 CHECK(site_api_access IN (0,1))')
            db.executemany("INSERT OR IGNORE INTO settings VALUES (?,?)",
                           [("price_fen", 100), ("daily_limit", 20), ("global_daily_limit", 100)])

    @contextmanager
    def db(self, *, write: bool = False):
        """每次操作独立连接；预占使用写事务，避免先查余额后扣款的竞态。"""
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _create_user(self, username: str, password: str, role: str) -> dict:
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
            raise BusinessError("用户名需为 3～32 位英文字母、数字或下划线。")
        if not 10 <= len(password) <= 128:
            raise BusinessError("密码需为 10～128 个字符。")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()
        user_id = uuid4().hex
        try:
            with self.db(write=True) as db:
                db.execute("INSERT INTO users(id,username,salt,password_hash,role,balance_fen,created_at) VALUES (?,?,?,?,?,?,?)",
                           (user_id, username, salt, digest, role, 1000, utc_now()))
        except sqlite3.IntegrityError:
            raise BusinessError("这个用户名已存在。") from None
        return self.user(user_id)

    def register(self, username: str, password: str) -> dict:
        """公开注册只能创建普通账户；赠送 ¥10 演示额度，不是真实资金。"""
        return self._create_user(username, password, "customer")

    def create_admin(self, username: str, password: str) -> dict:
        """仅供服务器本机管理命令使用，不暴露在注册界面。"""
        return self._create_user(username, password, "admin")

    def api_provider(self) -> str | None:
        """站点使用哪个供应商；账本只保存名称，不保存密钥。"""
        with self.db() as db:
            row=db.execute("SELECT value FROM site_config WHERE key='api_provider'").fetchone()
            return row['value'] if row else None

    def set_api_provider(self, admin_id: str, provider: str) -> None:
        """管理员修改供应商并记录审计，普通账户无法切换站长 API。"""
        from api_providers import PROVIDERS
        with self.db(write=True) as db:
            self._admin(db,admin_id)
            if provider not in PROVIDERS:
                raise BusinessError('不支持的 API 服务商。')
            db.execute("INSERT INTO site_config VALUES ('api_provider',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(provider,))
            db.execute('INSERT INTO audit(actor_id,action,value,created_at) VALUES (?,?,?,?)',
                       (admin_id,'api_provider:'+provider,0,utc_now()))

    def authenticate(self, username: str, password: str) -> dict | None:
        """校验加盐哈希；连续 5 次错误锁定 5 分钟，不返回密码字段。"""
        if len(password) > 128:
            return None
        with self.db(write=True) as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
            # 不存在的用户名也做同等哈希计算，减少响应时间上的账号枚举差异。
            salt = row["salt"] if row else "00" * 16
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()
            if not row or row["locked_until"] > time.time():
                return None
            if not hmac.compare_digest(actual, row["password_hash"]):
                attempts = row["failed_logins"] + 1
                db.execute("UPDATE users SET failed_logins=?,locked_until=? WHERE id=?",
                           (attempts, time.time() + 300 if attempts >= 5 else 0, row["id"]))
                return None
            db.execute("UPDATE users SET failed_logins=0,locked_until=0 WHERE id=?", (row["id"],))
            user_id = row["id"]
        return self.user(user_id)

    def user(self, user_id: str) -> dict:
        """返回页面需要的公开账户资料；密钥与密码哈希不会发送到浏览器。"""
        with self.db() as db:
            row = db.execute("SELECT id,username,role,balance_fen,created_at,auth_version,site_api_access FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise BusinessError("请重新登录。")
            return dict(row)

    def change_password(self, user_id: str, old_password: str, new_password: str) -> dict:
        """校验旧密码，更新独立盐并增加会话版本；错误尝试沿用锁定策略。"""
        if not 10 <= len(new_password) <= 128 or len(old_password)>128:
            raise BusinessError('新密码需为 10～128 个字符。')
        invalid=False
        with self.db(write=True) as db:
            row=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not row:
                raise BusinessError('请重新登录。')
            actual=hashlib.pbkdf2_hmac('sha256',old_password.encode(),bytes.fromhex(row['salt']),600000).hex()
            if row['locked_until']>time.time():
                invalid=True
            elif not hmac.compare_digest(actual,row['password_hash']):
                attempts=row['failed_logins']+1
                db.execute('UPDATE users SET failed_logins=?,locked_until=? WHERE id=?',
                    (attempts,time.time()+300 if attempts>=5 else 0,user_id))
                invalid=True
            else:
                salt=secrets.token_hex(16)
                digest=hashlib.pbkdf2_hmac('sha256',new_password.encode(),bytes.fromhex(salt),600000).hex()
                db.execute('UPDATE users SET salt=?,password_hash=?,auth_version=auth_version+1,failed_logins=0,locked_until=0 WHERE id=?',
                    (salt,digest,user_id))
                db.execute('INSERT INTO audit(actor_id,action,value,created_at) VALUES (?,?,?,?)',
                    (user_id,'password_changed',0,utc_now()))
        if invalid:
            raise BusinessError('旧密码错误或账户暂时锁定。')
        return self.user(user_id)

    def users(self, admin_id: str, search: str = '') -> list[dict]:
        """管理员查询公开账户资料，绝不返回密码哈希、盐或 API 配置。"""
        with self.db() as db:
            self._admin(db,admin_id)
            query=search.strip().lower()[:32].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            return [dict(r) for r in db.execute("SELECT id,username,role,balance_fen,created_at,site_api_access FROM users WHERE username LIKE ? ESCAPE '\\' ORDER BY created_at DESC,id LIMIT 200",('%'+query+'%',))]

    def set_site_api_access(self, admin_id: str, user_id: str, enabled: bool) -> None:
        """管理员为指定账户开放站长 API 试用，默认关闭且每次变更记审计。"""
        if type(enabled) is not bool:
            raise BusinessError('试用权限必须为开或关。')
        with self.db(write=True) as db:
            self._admin(db,admin_id)
            if db.execute('UPDATE users SET site_api_access=? WHERE id=?',(int(enabled),user_id)).rowcount!=1:
                raise BusinessError('账户不存在。')
            db.execute('INSERT INTO audit(actor_id,action,value,created_at) VALUES (?,?,?,?)',
                (admin_id,'site_api_access:'+user_id,int(enabled),utc_now()))

    def save_project(self, user_id: str, order_id: str, name: str) -> str:
        """项目只引用本人成功订单；保存和重命名不调用模型、不扣余额。"""
        name=name.strip()
        if not 1<=len(name)<=80 or any(ord(c)<32 for c in name):
            raise BusinessError('项目名称需为 1～80 个字符，不能包含控制字符。')
        with self.db(write=True) as db:
            row=db.execute("SELECT id FROM orders WHERE id=? AND user_id=? AND status='success'",(order_id,user_id)).fetchone()
            if not row:
                raise BusinessError('只能保存自己的成功设计订单。')
            previous=db.execute('SELECT id FROM projects WHERE user_id=? AND order_id=?',(user_id,order_id)).fetchone()
            if previous:
                project_id=previous['id']
                db.execute('UPDATE projects SET name=?,updated_at=? WHERE id=?',(name,utc_now(),project_id))
            else:
                if db.execute('SELECT COUNT(*) FROM projects WHERE user_id=?',(user_id,)).fetchone()[0]>=50:
                    raise BusinessError('每个账户最多保存 50 个项目，请先删除不需要的记录。')
                project_id=uuid4().hex
                now=utc_now()
                db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',(project_id,user_id,order_id,name,now,now))
            return project_id

    def projects(self, user_id: str) -> list[dict]:
        """仅列出本人项目，刷新或重新登录后仍可查询。"""
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT id,name,order_id,created_at,updated_at FROM projects WHERE user_id=? ORDER BY updated_at DESC,id',(user_id,))]

    def load_project(self, user_id: str, project_id: str) -> dict:
        """服务器按所有权取回已结算结果，不接受浏览器提交的文件路径。"""
        with self.db() as db:
            row=db.execute("SELECT o.result_json FROM projects p JOIN orders o ON o.id=p.order_id AND o.user_id=p.user_id WHERE p.id=? AND p.user_id=? AND o.status='success'",(project_id,user_id)).fetchone()
            if not row:
                raise BusinessError('项目不存在或不属于当前账户。')
            return json.loads(row['result_json'])

    def delete_project(self, user_id: str, project_id: str) -> None:
        """只删除本人项目条目，保留订单及其原始模型文件供追溯。"""
        with self.db(write=True) as db:
            if db.execute('DELETE FROM projects WHERE id=? AND user_id=?',(project_id,user_id)).rowcount!=1:
                raise BusinessError('项目不存在或不属于当前账户。')

    def price_fen(self) -> int:
        with self.db() as db:
            return db.execute("SELECT value FROM settings WHERE key='price_fen'").fetchone()[0]

    def daily_limit(self) -> int:
        with self.db() as db:
            return db.execute("SELECT value FROM settings WHERE key='daily_limit'").fetchone()[0]

    @staticmethod
    def _admin(db, actor_id: str) -> None:
        row = db.execute("SELECT role FROM users WHERE id=?", (actor_id,)).fetchone()
        if not row or row[0] != "admin":
            raise BusinessError("此操作仅限管理员。")

    def _set(self, actor_id: str, key: str, value: int, maximum: int) -> None:
        if type(value) is not int or not 1 <= value <= maximum:
            raise BusinessError("设置值超出允许范围。")
        with self.db(write=True) as db:
            self._admin(db, actor_id)
            db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
            db.execute("INSERT INTO audit(actor_id,action,value,created_at) VALUES (?,?,?,?)",
                       (actor_id, key, value, utc_now()))

    def set_price(self, actor_id: str, price_fen: int) -> None:
        """调整未来订单价格；历史订单金额始终使用原价格快照。"""
        self._set(actor_id, "price_fen", price_fen, 100000)

    def set_daily_limit(self, actor_id: str, limit: int) -> None:
        self._set(actor_id, "daily_limit", limit, 100)

    def reserve(self, user_id: str, request_key: str, prompt: str, quoted_fen: int) -> dict:
        """调用模型前预占演示额度；重复请求只返回原订单，不重复预占。"""
        if not request_key or len(request_key) > 128 or not prompt.strip() or len(prompt) > 2000:
            raise BusinessError("请求为空或过长，请缩短到 2000 字以内。")
        request_hash = hashlib.sha256(prompt.encode()).hexdigest()
        with self.db(write=True) as db:
            existing = db.execute("SELECT * FROM orders WHERE user_id=? AND request_key=?", (user_id, request_key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise BusinessError("请求编号已被另一项设计使用。")
                return dict(existing, new_reservation=False)
            price = db.execute("SELECT value FROM settings WHERE key='price_fen'").fetchone()[0]
            if type(quoted_fen) is not int or price != quoted_fen:
                raise BusinessError("服务价格已更新，请刷新后确认新价格。")
            user = db.execute("SELECT balance_fen FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise BusinessError("请先登录。")
            limits = dict(db.execute("SELECT key,value FROM settings"))
            today = utc_now()[:10] + "%"
            count = db.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at LIKE ?", (user_id, today)).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM orders WHERE created_at LIKE ?", (today,)).fetchone()[0]
            if count >= limits["daily_limit"] or total >= limits["global_daily_limit"]:
                raise BusinessError("今日服务请求已达上限，请明天再试。失败请求也计入调用限额。")
            if user[0] < price:
                raise BusinessError("演示额度不足。真实充值尚未开通，不会向你收取真实款项。")
            db.execute("UPDATE users SET balance_fen=balance_fen-? WHERE id=?", (price, user_id))
            order_id = uuid4().hex
            db.execute("INSERT INTO orders(id,user_id,request_key,request_hash,prompt,fee_fen,status,created_at) VALUES (?,?,?,?,?,?,'reserved',?)",
                       (order_id, user_id, request_key, request_hash, prompt, price, utc_now()))
            return dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone(),
                        new_reservation=True)

    def settle(self, user_id: str, order_id: str, result: dict) -> dict:
        """幂等结算：只有成功订单计服务费，失败只退款一次。"""
        with self.db(write=True) as db:
            order = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
            if order is None:
                raise BusinessError("无权查看或结算该订单。")
            if order["status"] != "reserved":
                return json.loads(order["result_json"])
            success = result.get("status") == "success"
            result = dict(result, service_order_id=order_id,
                          demo_service_fee_fen=order["fee_fen"] if success else 0)
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if not success:
                db.execute("UPDATE users SET balance_fen=balance_fen+? WHERE id=?", (order["fee_fen"], user_id))
            db.execute("UPDATE orders SET status=?,result_json=?,finished_at=? WHERE id=?",
                       ("success" if success else "failed", serialized, utc_now(), order_id))
            return result

    def orders(self, user_id: str, *, all_users: bool = False) -> list[dict]:
        """普通用户仅看自己的账单；全站统计必须再次在数据库核验管理员角色。"""
        with self.db() as db:
            if all_users:
                self._admin(db, user_id)
            query = "SELECT o.id,u.username,o.prompt,o.fee_fen,o.status,o.created_at,o.finished_at FROM orders o JOIN users u ON u.id=o.user_id"
            args = () if all_users else (user_id,)
            if not all_users:
                query += " WHERE o.user_id=?"
            return [dict(r) for r in db.execute(query + " ORDER BY o.created_at DESC,o.id LIMIT 500", args)]

    def statistics(self, actor_id: str) -> dict:
        """对全量订单聚合；演示服务费与真实到账收入分开，不能用余额推算收入。"""
        with self.db() as db:
            self._admin(db, actor_id)
            row = db.execute("SELECT COUNT(*) total_orders,COALESCE(SUM(status='success'),0) successful_orders,COALESCE(SUM(status='failed'),0) failed_orders,COALESCE(SUM(status='reserved'),0) pending_orders,COALESCE(SUM(CASE WHEN status='success' THEN fee_fen ELSE 0 END),0) demo_service_fen FROM orders").fetchone()
            result = dict(row)
            result["users"] = db.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0]
            result["real_received_fen"] = 0
            return result


def run_service(store: BusinessStore, user_id: str, request_key: str,
                prompt: str, generate: Callable, *, quoted_fen: int | None = None) -> dict:
    """先预占后建模；成功结果可幂等读取，未完成请求不重执行付费 API。"""
    order = store.reserve(user_id, request_key, prompt,
                          store.price_fen() if quoted_fen is None else quoted_fen)
    if order["result_json"]:
        return json.loads(order["result_json"])
    # reserve 在写事务中标记是否首次创建，跨进程也只有一个调用者可以建模。
    if not order["new_reservation"]:
        raise BusinessError("该订单正在处理，请勿重复提交。")
    try:
        result = generate()
        if not isinstance(result, dict) or result.get("status") not in ("success", "error"):
            raise ValueError("invalid service result")
        json.dumps(result, allow_nan=False)
    except Exception:
        result = {"status": "error", "error_message": "服务处理失败，本次演示额度已退回。"}
    return store.settle(user_id, order["id"], result)

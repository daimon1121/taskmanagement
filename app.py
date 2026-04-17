from dotenv import load_dotenv; load_dotenv()

import os
import re
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

import json as _json
import ssl as _ssl
import urllib3 as _urllib3
import stripe
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_mail import Mail, Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

# ─── App & Config ─────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

app.config.update(
    MAIL_SERVER        = os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT          = int(os.environ.get("MAIL_PORT", 587)),
    MAIL_USE_TLS       = True,
    MAIL_USERNAME      = os.environ.get("MAIL_USERNAME", ""),
    MAIL_PASSWORD      = os.environ.get("MAIL_PASSWORD", ""),
    MAIL_DEFAULT_SENDER= os.environ.get("MAIL_USERNAME", ""),
)
mail = Mail(app)

stripe.api_key         = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID        = os.environ.get("STRIPE_PRICE_ID", "")
WEBMASTER_EMAIL        = "daimon1121@gmail.com"

FREE_TASK_LIMIT = 10
TOOLS_VER       = 2

# ─── Database (Neon HTTP API) ─────────────────────────────────────────────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)

try:
    import truststore as _truststore
    _ssl_ctx = _truststore.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
except ImportError:
    _ssl_ctx = _ssl.create_default_context()

_http_pool = _urllib3.PoolManager(ssl_context=_ssl_ctx)
_m = re.match(r'postgresql://[^@]+@([^/?]+)', _DATABASE_URL)
_NEON_HOST = _m.group(1) if _m else ''

def _sql_to_pg(query, params):
    """psycopg2 の %s → PostgreSQL $1,$2,... に変換、%% → % もエスケープ解除"""
    if not params:
        return query, []
    n = [0]
    def repl(m):
        if m.group(0) == '%%':
            return '%'
        n[0] += 1
        return f'${n[0]}'
    return re.sub(r'%%|%s', repl, query), list(params)

class _Cursor:
    def __init__(self):
        self._rows = []
        self._pos  = 0
        self.rowcount   = -1
        self.description = None

    def execute(self, query, params=None):
        q, p = _sql_to_pg(query, params)
        resp = _http_pool.request(
            "POST", f"https://{_NEON_HOST}/sql",
            headers={"Neon-Connection-String": _DATABASE_URL,
                     "Content-Type": "application/json"},
            body=_json.dumps({"query": q, "params": p}).encode()
        )
        data = _json.loads(resp.data)
        if resp.status >= 400:
            raise Exception(f"DB Error: {data.get('message', resp.status)}")
        self._rows = data.get("rows", [])
        self._pos  = 0
        self.rowcount = data.get("rowCount", len(self._rows))

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def close(self): pass

class _Conn:
    def cursor(self):  return _Cursor()
    def commit(self):  pass
    def close(self):   pass

@contextmanager
def get_db():
    conn = _Conn()
    cur  = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    finally:
        cur.close()
        conn.close()

# ─── Seed Data ────────────────────────────────────────────────────────────────
_SAMPLE_ASSIGNEES = [
    ("田中 太郎",   "t.tanaka@nexwave.co.jp"),
    ("鈴木 花子",   "h.suzuki@nexwave.co.jp"),
    ("佐藤 一郎",   "i.sato@nexwave.co.jp"),
    ("高橋 美香",   "m.takahashi@nexwave.co.jp"),
    ("伊藤 健二",   "k.ito@nexwave.co.jp"),
    ("渡辺 祐子",   "y.watanabe@nexwave.co.jp"),
    ("山田 修",     "o.yamada@nexwave.co.jp"),
    ("中村 理恵",   "r.nakamura@nexwave.co.jp"),
    ("小林 拓也",   "t.kobayashi@dev.nexwave.co.jp"),
    ("加藤 奈々",   "n.kato@dev.nexwave.co.jp"),
    ("吉田 大輔",   "d.yoshida@dev.nexwave.co.jp"),
    ("山口 恵子",   "k.yamaguchi@design.nexwave.co.jp"),
    ("松本 健",     "k.matsumoto@infra.nexwave.co.jp"),
    ("井上 さくら", "s.inoue@infra.nexwave.co.jp"),
    ("木村 誠",     "m.kimura@qa.nexwave.co.jp"),
    ("林 美穂",     "m.hayashi@qa.nexwave.co.jp"),
    ("清水 隆",     "t.shimizu@biz.nexwave.co.jp"),
    ("山崎 由美",   "y.yamazaki@biz.nexwave.co.jp"),
    ("池田 直樹",   "n.ikeda@pm.nexwave.co.jp"),
    ("橋本 陽子",   "y.hashimoto@pm.nexwave.co.jp"),
]

_TOOL_BASE = [
    "GitHub","GitLab","Bitbucket","Jira","Confluence",
    "Trello","Asana","Notion","Monday.com","ClickUp",
    "Slack","Teams","Zoom","Google Meet","Figma",
    "Adobe XD","Sketch","InVision","Zeplin","Miro",
    "VS Code","IntelliJ IDEA","Eclipse","PyCharm","WebStorm",
    "Docker","Kubernetes","Terraform","Ansible","Jenkins",
    "CircleCI","GitHub Actions","AWS Console","GCP Console","Azure Portal",
    "Heroku","Vercel","Netlify","PostgreSQL","MySQL",
    "MongoDB","Redis","Elasticsearch","DynamoDB","Firestore",
    "Tableau","Power BI","Looker","Grafana","Kibana",
    "Datadog","NewRelic","Sentry","PagerDuty","Splunk",
    "Postman","Swagger","Insomnia","SoapUI","Salesforce",
    "SAP","ServiceNow","Zendesk","HubSpot","Marketo",
    "Python","Node.js","Java Spring","ASP.NET","Ruby on Rails",
    "Go","Rust","React","Vue.js","Angular",
    "Next.js","Nuxt.js","Svelte","Nginx","Apache",
    "HAProxy","Varnish","Prometheus","Alertmanager","Jaeger",
    "Zipkin","Kafka","RabbitMQ","ActiveMQ","NATS",
    "Vault","Keycloak","Auth0","Okta","Sonarqube",
    "Snyk","OWASP ZAP","Trivy","Excel","Word",
    "PowerPoint","Google Sheets","Google Docs",
]

# ─── DB Init ──────────────────────────────────────────────────────────────────
def init_db():
    with get_db() as (conn, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                     VARCHAR(36)  PRIMARY KEY,
                email                  VARCHAR(255) UNIQUE NOT NULL,
                password               VARCHAR(255) NOT NULL,
                plan                   VARCHAR(20)  DEFAULT 'free',
                stripe_customer_id     VARCHAR(255),
                stripe_subscription_id VARCHAR(255),
                display_name           VARCHAR(200)
            )
        """)
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(200)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id                  SERIAL PRIMARY KEY,
                name                VARCHAR(500),
                request_date        VARCHAR(20),
                start_date          VARCHAR(20),
                distribution_date   VARCHAR(20),
                end_date            VARCHAR(20),
                status              VARCHAR(50),
                priority            VARCHAR(20),
                tool                VARCHAR(200),
                assignee            VARCHAR(200),
                description         TEXT,
                implementation_date VARCHAR(20)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS assignees (
                id    SERIAL PRIMARY KEY,
                name  VARCHAR(200) NOT NULL,
                email VARCHAR(255)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tools (
                id   SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id         SERIAL PRIMARY KEY,
                user_id    VARCHAR(36),
                rating     INTEGER,
                message    TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("SELECT COUNT(*) FROM assignees")
        if cur.fetchone()["count"] == 0:
            for name, email in _SAMPLE_ASSIGNEES:
                cur.execute("INSERT INTO assignees (name, email) VALUES (%s, %s)", (name, email))

        cur.execute("SELECT COUNT(*) FROM tools")
        if cur.fetchone()["count"] == 0:
            tool_names = [f"{i:03d}_{b}" for i, b in enumerate(_TOOL_BASE, 1)]
            for i in range(len(_TOOL_BASE) + 1, 301):
                tool_names.append(f"{i:03d}_ツール")
            for name in tool_names:
                cur.execute("INSERT INTO tools (name) VALUES (%s)", (name,))

        cur.execute("SELECT COUNT(*) FROM tasks")
        if cur.fetchone()["count"] == 0:
            today = datetime.now()
            def d(n): return (today + timedelta(days=n)).strftime("%Y-%m-%d")
            rows = [
                ("要件定義・仕様策定",d(-23),d(-20),d(-13),d(-11),"完了",  "高","005_Confluence","田中 太郎","ステークホルダーへのヒアリング完了。"),
                ("UI/UXデザイン",     d(-17),d(-14),d(-5), d(-3), "完了",  "高","015_Figma",     "鈴木 花子","ワイヤーフレーム・プロトタイプを作成。"),
                ("データベース設計",  d(-12),d(-10),d(-4), d(-2), "完了",  "中","039_PostgreSQL","佐藤 一郎","ER図・テーブル定義書を作成。"),
                ("バックエンド開発",  d(-8), d(-5), d(9),  d(12), "進行中","高","001_GitHub",    "伊藤 健二","REST API実装中。"),
                ("フロントエンド開発",d(-5), d(-2), d(12), d(15), "進行中","高","073_React",     "渡辺 祐子","コンポーネント実装中。"),
                ("単体テスト",        d(5),  d(8),  d(15), d(18), "未着手","中","095_Sonarqube", "山田 修",  "ユニットテストを実施予定。"),
                ("結合テスト",        d(13), d(16), d(22), d(25), "未着手","高","056_Postman",   "高橋 美香","API連携・画面遷移の総合確認。"),
                ("パフォーマンス改善",d(7),  d(10), d(17), d(20), "未着手","低","051_Datadog",   "佐藤 一郎","ボトルネック分析後に対応。"),
                ("ドキュメント整備",  d(15), d(18), d(25), d(28), "未着手","低","005_Confluence","中村 理恵","APIドキュメント・運用手順書の作成。"),
                ("本番リリース準備",  d(21), d(24), d(27), d(30), "未着手","高","028_Terraform", "田中 太郎","インフラ構築・監視設定。"),
            ]
            for name,rq,s,di,e,status,pri,tool,assignee,desc in rows:
                cur.execute("""
                    INSERT INTO tasks (name,request_date,start_date,distribution_date,end_date,
                                       status,priority,tool,assignee,description)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (name,rq,s,di,e,status,pri,tool,assignee,desc))

with app.app_context():
    if _DATABASE_URL:
        init_db()

# ─── Auth Helpers ─────────────────────────────────────────────────────────────
def _make_reset_token(email):
    return URLSafeTimedSerializer(app.secret_key).dumps(email, salt="pw-reset")

def _verify_reset_token(token, max_age=3600):
    try:
        return URLSafeTimedSerializer(app.secret_key).loads(token, salt="pw-reset", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None

def find_user_by_email(email):
    with get_db() as (_, cur):
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
    return dict(row) if row else None

def find_user_by_id(uid):
    with get_db() as (_, cur):
        cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
        row = cur.fetchone()
    return dict(row) if row else None

def current_user():
    uid = session.get("user_id")
    return find_user_by_id(uid) if uid else None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def is_pro():
    u = current_user()
    return u and u.get("plan") == "pro"

# ─── Admin Stats Helper ───────────────────────────────────────────────────────
def _get_site_stats():
    with get_db() as (_, cur):
        cur.execute("SELECT * FROM users ORDER BY email")
        users = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = cur.fetchone()["count"]
        cur.execute("""
            SELECT f.id, f.rating, f.message, f.created_at, u.email AS user_email
            FROM feedback f
            LEFT JOIN users u ON u.id = f.user_id
            ORDER BY f.created_at DESC
        """)
        feedback = [dict(r) for r in cur.fetchall()]
    stats = {
        "total_users": len(users),
        "pro_users":   sum(1 for u in users if u.get("plan") == "pro"),
        "free_users":  sum(1 for u in users if u.get("plan") != "pro"),
        "total_tasks": total_tasks,
    }
    return users, stats, feedback

# ─── Data Access ──────────────────────────────────────────────────────────────
def _load_table(table):
    with get_db() as (_, cur):
        cur.execute(f"SELECT * FROM {table} ORDER BY id")
        rows = [dict(r) for r in cur.fetchall()]
    next_id = (max(r["id"] for r in rows) + 1) if rows else 1
    return rows, next_id

def load_data():
    tasks, next_id = _load_table("tasks")
    return {"tasks": tasks, "next_id": next_id}

def load_tools():
    tools, next_id = _load_table("tools")
    return {"version": TOOLS_VER, "tools": tools, "next_id": next_id}

def load_assignees():
    assignees, next_id = _load_table("assignees")
    return {"assignees": assignees, "next_id": next_id}

def _composite_key(t):
    return (t.get("assignee",""), t.get("tool",""), t.get("name",""), t.get("implementation_date",""))

_TASK_FIELDS = (
    "name", "request_date", "start_date", "distribution_date", "end_date",
    "status", "priority", "tool", "assignee", "description", "implementation_date",
)

def _task_params(task):
    return tuple(task.get(f) for f in _TASK_FIELDS)

# ─── Auth Routes ──────────────────────────────────────────────────────────────
@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not email or not password:
            flash("メールアドレスとパスワードを入力してください")
            return render_template("signup.html")
        if find_user_by_email(email):
            flash("このメールアドレスはすでに登録されています")
            return render_template("signup.html")
        uid = str(uuid.uuid4())
        with get_db() as (_, cur):
            cur.execute(
                "INSERT INTO users (id,email,password,plan) VALUES (%s,%s,%s,'free')",
                (uid, email, generate_password_hash(password))
            )
        session["user_id"] = uid
        return redirect(url_for("index"))
    return render_template("signup.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        user = find_user_by_email(email)
        if not user or not check_password_hash(user["password"], password):
            flash("メールアドレスまたはパスワードが正しくありません")
            return render_template("login.html")
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET","POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        user  = find_user_by_email(email)
        if user:
            token     = _make_reset_token(email)
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                msg = Message("パスワードリセット - NAGARE", recipients=[email])
                msg.body = (
                    f"以下のリンクからパスワードをリセットしてください（有効期限：1時間）\n\n"
                    f"{reset_url}\n\n"
                    f"このメールに心当たりがない場合は無視してください。"
                )
                mail.send(msg)
            except Exception:
                flash("メール送信に失敗しました。しばらく後でお試しください。")
                return render_template("forgot_password.html")
        flash("登録済みのメールアドレスであれば、リセットリンクを送信しました。")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET","POST"])
def reset_password(token):
    email = _verify_reset_token(token)
    if not email:
        flash("リセットリンクが無効または期限切れです（1時間以内にお使いください）。")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password","")
        confirm  = request.form.get("confirm","")
        if len(password) < 6:
            flash("パスワードは6文字以上で入力してください。")
            return render_template("reset_password.html", token=token)
        if password != confirm:
            flash("パスワードが一致しません。")
            return render_template("reset_password.html", token=token)
        with get_db() as (_, cur):
            cur.execute("UPDATE users SET password=%s WHERE email=%s",
                        (generate_password_hash(password), email))
        flash("パスワードをリセットしました。新しいパスワードでログインしてください。")
        return redirect(url_for("login"))
    return render_template("reset_password.html", token=token)

# ─── Stripe / Pricing Routes ──────────────────────────────────────────────────
@app.route("/pricing")
@login_required
def pricing():
    return render_template("pricing.html", user=current_user(), stripe_key=STRIPE_PUBLISHABLE_KEY)

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    u        = current_user()
    base_url = request.host_url.rstrip("/")
    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=u["email"],
            success_url=base_url + url_for("payment_success") + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base_url + url_for("pricing"),
            metadata={"user_id": u["id"]},
        )
        return redirect(checkout.url, code=303)
    except Exception as e:
        flash(f"決済セッションの作成に失敗しました: {e}")
        return redirect(url_for("pricing"))

@app.route("/payment-success")
@login_required
def payment_success():
    session_id = request.args.get("session_id")
    if session_id:
        try:
            checkout = stripe.checkout.Session.retrieve(session_id)
            _upgrade_user(checkout.metadata.get("user_id"),
                          checkout.customer, checkout.subscription)
        except Exception:
            pass
    return render_template("success.html")

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature","")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "", 400
    if event["type"] == "customer.subscription.deleted":
        _downgrade_by_subscription(event["data"]["object"]["id"])
    elif event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        _upgrade_user(obj.get("metadata",{}).get("user_id"),
                      obj.get("customer"), obj.get("subscription"))
    return "", 200

def _upgrade_user(user_id, customer_id, subscription_id):
    if not user_id:
        return
    with get_db() as (_, cur):
        cur.execute("""
            UPDATE users SET plan='pro', stripe_customer_id=%s, stripe_subscription_id=%s
            WHERE id=%s
        """, (customer_id, subscription_id, user_id))

def _downgrade_by_subscription(subscription_id):
    with get_db() as (_, cur):
        cur.execute("""
            UPDATE users SET plan='free', stripe_subscription_id=NULL
            WHERE stripe_subscription_id=%s
        """, (subscription_id,))

# ─── API: Tools ───────────────────────────────────────────────────────────────
@app.route("/api/tools", methods=["GET"])
@login_required
def get_tools():
    return jsonify(load_tools())

@app.route("/api/tools", methods=["POST"])
@login_required
def add_tool():
    name = (request.json or {}).get("name","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as (_, cur):
        cur.execute("INSERT INTO tools (name) VALUES (%s) RETURNING id", (name,))
        tool_id = cur.fetchone()["id"]
    return jsonify({"id": tool_id, "name": name}), 201

@app.route("/api/tools/<int:tool_id>", methods=["PUT"])
@login_required
def update_tool(tool_id):
    name = (request.json or {}).get("name","").strip()
    with get_db() as (_, cur):
        cur.execute("UPDATE tools SET name=%s WHERE id=%s RETURNING *", (name, tool_id))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))

@app.route("/api/tools/<int:tool_id>", methods=["DELETE"])
@login_required
def delete_tool(tool_id):
    with get_db() as (_, cur):
        cur.execute("DELETE FROM tools WHERE id=%s", (tool_id,))
    return jsonify({"ok": True})

# ─── API: Assignees ───────────────────────────────────────────────────────────
@app.route("/api/assignees", methods=["GET"])
@login_required
def get_assignees():
    return jsonify(load_assignees())

@app.route("/api/assignees", methods=["POST"])
@login_required
def add_assignee():
    body  = request.json or {}
    name  = body.get("name","").strip()
    email = body.get("email","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as (_, cur):
        cur.execute("INSERT INTO assignees (name,email) VALUES (%s,%s) RETURNING id", (name, email))
        aid = cur.fetchone()["id"]
    return jsonify({"id": aid, "name": name, "email": email}), 201

@app.route("/api/assignees/<int:aid>", methods=["PUT"])
@login_required
def update_assignee(aid):
    body  = request.json or {}
    name  = body.get("name","").strip()
    email = body.get("email","").strip()
    with get_db() as (conn, cur):
        cur.execute("SELECT name FROM assignees WHERE id=%s", (aid,))
        existing = cur.fetchone()
        if not existing:
            return jsonify({"error": "not found"}), 404
        old_name = existing["name"]
        cur.execute("UPDATE assignees SET name=%s, email=%s WHERE id=%s RETURNING *",
                    (name, email, aid))
        row = cur.fetchone()
        if old_name != name:
            cur.execute("UPDATE tasks SET assignee=%s WHERE assignee=%s", (name, old_name))
    return jsonify(dict(row))

@app.route("/api/assignees/<int:aid>", methods=["DELETE"])
@login_required
def delete_assignee(aid):
    with get_db() as (_, cur):
        cur.execute("DELETE FROM assignees WHERE id=%s", (aid,))
    return jsonify({"ok": True})

# ─── API: Tasks ───────────────────────────────────────────────────────────────
@app.route("/tokusho")
def tokusho():
    return render_template("tokusho.html")

@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user(), is_pro=is_pro())

@app.route("/account_sample")
def account_sample():
    return render_template("account_sample.html")

@app.route("/feedback_sample")
def feedback_sample():
    return render_template("feedback_sample.html")

@app.route("/account")
@login_required
def account():
    u = current_user()
    display_name = u.get("display_name") or ""
    email = u.get("email", "")
    if display_name:
        initials = "".join(w[0] for w in display_name.split() if w).upper()[:2]
    else:
        initials = email[:2].upper()
    wm_users, wm_stats, wm_feedback = [], {}, []
    if email == WEBMASTER_EMAIL:
        wm_users, wm_stats, wm_feedback = _get_site_stats()
    return render_template("account.html", user=u, is_pro=is_pro(),
                           display_name=display_name, initials=initials,
                           is_webmaster=(email == WEBMASTER_EMAIL),
                           wm_users=wm_users, wm_stats=wm_stats,
                           wm_feedback=wm_feedback)

@app.route("/api/account/profile", methods=["POST"])
@login_required
def update_profile():
    data = request.get_json()
    display_name = (data.get("display_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "メールアドレスを入力してください"}), 400
    u = current_user()
    if email != u["email"] and find_user_by_email(email):
        return jsonify({"error": "このメールアドレスはすでに使用されています"}), 400
    with get_db() as (_, cur):
        cur.execute("UPDATE users SET display_name=%s, email=%s WHERE id=%s",
                    (display_name or None, email, u["id"]))
    return jsonify({"ok": True})

@app.route("/api/account/password", methods=["POST"])
@login_required
def update_password():
    data = request.get_json()
    current_pw = data.get("current_password", "")
    new_pw = data.get("new_password", "")
    if not new_pw or len(new_pw) < 8:
        return jsonify({"error": "新しいパスワードは8文字以上で入力してください"}), 400
    u = current_user()
    if not check_password_hash(u["password"], current_pw):
        return jsonify({"error": "現在のパスワードが正しくありません"}), 400
    with get_db() as (_, cur):
        cur.execute("UPDATE users SET password=%s WHERE id=%s",
                    (generate_password_hash(new_pw), u["id"]))
    return jsonify({"ok": True})

@app.route("/api/account/delete", methods=["POST"])
@login_required
def delete_account():
    u = current_user()
    with get_db() as (_, cur):
        cur.execute("DELETE FROM users WHERE id=%s", (u["id"],))
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/feedback", methods=["POST"])
@login_required
def submit_feedback():
    data = request.get_json()
    rating  = data.get("rating")
    message = (data.get("message") or "").strip()
    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({"error": "評価を選択してください"}), 400
    u = current_user()
    with get_db() as (_, cur):
        cur.execute("INSERT INTO feedback (user_id, rating, message) VALUES (%s, %s, %s)",
                    (u["id"], int(rating), message or None))
    return jsonify({"ok": True})

@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    return jsonify(load_data())

@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    data = load_data()
    if not is_pro() and len(data["tasks"]) >= FREE_TASK_LIMIT:
        return jsonify({"error": "plan_limit",
                        "message": f"無料プランはタスク{FREE_TASK_LIMIT}件までです。Proにアップグレードしてください。"}), 403
    task = request.json
    key  = _composite_key(task)
    if any(_composite_key(t) == key for t in data["tasks"]):
        return jsonify({"error": "duplicate",
                        "message": "同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}), 409
    with get_db() as (_, cur):
        cur.execute("""
            INSERT INTO tasks (name,request_date,start_date,distribution_date,end_date,
                               status,priority,tool,assignee,description,implementation_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, _task_params(task))
        task["id"] = cur.fetchone()["id"]
    return jsonify(task), 201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    data = load_data()
    task = request.json
    key  = _composite_key(task)
    if any(_composite_key(t) == key and t["id"] != task_id for t in data["tasks"]):
        return jsonify({"error": "duplicate",
                        "message": "同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}), 409
    with get_db() as (_, cur):
        cur.execute("""
            UPDATE tasks SET name=%s,request_date=%s,start_date=%s,distribution_date=%s,
                             end_date=%s,status=%s,priority=%s,tool=%s,assignee=%s,
                             description=%s,implementation_date=%s
            WHERE id=%s RETURNING *
        """, _task_params(task) + (task_id,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    with get_db() as (_, cur):
        cur.execute("DELETE FROM tasks WHERE id=%s", (task_id,))
    return jsonify({"ok": True})

@app.route("/api/me")
@login_required
def api_me():
    u = current_user()
    return jsonify({"email": u["email"], "plan": u["plan"]})

# ─── Admin Routes ─────────────────────────────────────────────────────────────
# ─── Admin: Dummy Data ────────────────────────────────────────────────────────
def _webmaster_required():
    u = current_user()
    return u and u.get("email") == WEBMASTER_EMAIL
_DEMO_ASSIGNEE_NAMES = [
    ("デモ 太郎", "demo_taro"), ("デモ 花子", "demo_hanako"), ("デモ 次郎", "demo_jiro"),
    ("デモ 三郎", "demo_saburo"), ("デモ 桃子", "demo_momoko"), ("デモ 健一", "demo_kenichi"),
    ("デモ 由紀", "demo_yuki"), ("デモ 大介", "demo_daisuke"), ("デモ 奈美", "demo_nami"),
    ("デモ 翔太", "demo_shota"),
]
_DEMO_TASK_NAMES = [
    "【DEMO】要件定義書の作成", "【DEMO】UIデザインのレビュー", "【DEMO】バックエンドAPI実装",
    "【DEMO】データベース設計", "【DEMO】単体テスト実施", "【DEMO】結合テスト計画",
    "【DEMO】パフォーマンス改善", "【DEMO】ドキュメント整備", "【DEMO】セキュリティ診断",
    "【DEMO】リリース作業", "【DEMO】監視設定", "【DEMO】コードレビュー",
    "【DEMO】依存ライブラリ更新", "【DEMO】CI/CD環境構築", "【DEMO】ユーザビリティテスト",
    "【DEMO】エラーログ調査", "【DEMO】バグ修正対応", "【DEMO】仕様変更対応",
    "【DEMO】顧客向け資料作成", "【DEMO】進捗報告会準備",
]
_DEMO_STATUSES  = ["未着手", "進行中", "完了", "未着手", "未着手"]
_DEMO_PRIORITIES = ["高", "中", "低", "高", "中"]

@app.route("/api/demo/stats")
@login_required
def api_demo_stats():
    with get_db() as (_, cur):
        cur.execute("SELECT COUNT(*) FROM assignees WHERE email LIKE '%@dummy.test'")
        a_count = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM tasks WHERE name LIKE '【DEMO】%'")
        t_count = cur.fetchone()["count"]
    return jsonify({"assignees": a_count, "tasks": t_count})

@app.route("/api/demo/generate", methods=["POST"])
@login_required
def api_demo_generate():
    import random
    data   = request.json or {}
    n_a    = max(1, min(int(data.get("assignees", 5)), 10))
    n_t    = max(1, min(int(data.get("tasks", 20)), 100))
    today  = datetime.now()
    def d(n): return (today + timedelta(days=n)).strftime("%Y-%m-%d")
    with get_db() as (conn, cur):
        added_names = []
        for name, slug in _DEMO_ASSIGNEE_NAMES[:n_a]:
            email = f"{slug}@dummy.test"
            cur.execute("SELECT id FROM assignees WHERE email=%s", (email,))
            if not cur.fetchone():
                cur.execute("INSERT INTO assignees (name, email) VALUES (%s,%s)", (name, email))
            added_names.append(name)
        task_names = _DEMO_TASK_NAMES * ((n_t // len(_DEMO_TASK_NAMES)) + 1)
        for i in range(n_t):
            name     = task_names[i]
            status   = _DEMO_STATUSES[i % len(_DEMO_STATUSES)]
            priority = _DEMO_PRIORITIES[i % len(_DEMO_PRIORITIES)]
            assignee = added_names[i % len(added_names)]
            offset   = random.randint(-30, 30)
            rq = d(offset - 10); s = d(offset - 7)
            di = d(offset + 3);  e = d(offset + 7)
            cur.execute("""
                INSERT INTO tasks (name,request_date,start_date,distribution_date,end_date,
                                   status,priority,assignee,description)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (name, rq, s, di, e, status, priority, assignee, "DEMOデータです。"))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/demo/delete", methods=["POST"])
@login_required
def api_demo_delete():
    with get_db() as (conn, cur):
        # DEMO担当者の名前一覧を取得
        cur.execute("SELECT name FROM assignees WHERE email LIKE '%@dummy.test'")
        demo_names = [r["name"] for r in cur.fetchall()]
        # DEMOタスクを削除
        cur.execute("DELETE FROM tasks WHERE name LIKE '【DEMO】%'")
        # DEMO担当者が割り当てられている通常タスクの担当者をNULLに
        if demo_names:
            cur.execute(
                "UPDATE tasks SET assignee = NULL WHERE assignee = ANY(%s)",
                (demo_names,)
            )
        # DEMO担当者を削除
        cur.execute("DELETE FROM assignees WHERE email LIKE '%@dummy.test'")
        conn.commit()
    return jsonify({"ok": True})

# ─── AI Routes (ルールベース) ─────────────────────────────────────────────────
_SUBTASK_TEMPLATES = {
    "開発": ["要件定義", "設計", "実装", "単体テスト", "レビュー対応", "結合テスト", "リリース作業"],
    "テスト": ["テスト計画作成", "テストケース作成", "環境構築", "テスト実施", "バグ報告", "修正確認", "完了報告"],
    "設計": ["現状調査", "要件整理", "設計案作成", "レビュー", "修正対応", "ドキュメント仕上げ"],
    "調査": ["情報収集", "現状整理", "問題点抽出", "解決策検討", "レポート作成", "共有・報告"],
    "移行": ["現状調査", "移行計画作成", "テスト環境移行", "動作確認", "本番移行", "事後確認"],
    "構築": ["要件確認", "設計書作成", "環境準備", "構築作業", "動作テスト", "ドキュメント作成"],
    "レビュー": ["対象資料確認", "チェックリスト作成", "レビュー実施", "指摘事項整理", "修正確認", "承認・完了"],
    "リリース": ["リリース計画作成", "事前チェック", "リリース作業", "動作確認", "監視", "完了報告"],
}
_DEFAULT_SUBTASKS = ["要件確認", "計画作成", "作業実施", "進捗確認", "成果物レビュー", "完了報告"]

_NEG_WORDS = {"困難", "問題", "遅延", "障害", "エラー", "失敗", "懸念", "リスク", "不明", "未対応",
              "緊急", "急ぎ", "重大", "クリティカル", "ブロック", "停止", "不具合", "バグ", "炎上"}
_POS_WORDS = {"完了", "達成", "成功", "改善", "解決", "順調", "確認済", "リリース済", "承認", "好調"}

_PRIORITY_KW = {
    "高": ["緊急", "急ぎ", "至急", "重要", "クリティカル", "最優先"],
    "低": ["後回し", "余裕", "暇なとき", "いつか", "低優先"],
}

def _rule_subtasks(name):
    for kw, items in _SUBTASK_TEMPLATES.items():
        if kw in name:
            return [f"{name}の{s}" for s in items]
    return [f"{name}の{s}" for s in _DEFAULT_SUBTASKS]

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

@app.route("/api/ai/decompose", methods=["POST"])
@login_required
def ai_decompose():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify({"subtasks": _rule_subtasks(name)})

@app.route("/api/ai/report", methods=["GET"])
@login_required
def ai_report():
    tasks       = load_data()["tasks"]
    total       = len(tasks)
    done        = sum(1 for t in tasks if t.get("status") == "完了")
    in_progress = sum(1 for t in tasks if t.get("status") == "進行中")
    not_started = sum(1 for t in tasks if t.get("status") == "未着手")
    today       = datetime.now().date()
    rate        = int(done / total * 100) if total else 0
    overdue  = [t for t in tasks if t.get("status") != "完了"
                and _parse_date(t.get("end_date")) and _parse_date(t.get("end_date")) < today]
    high_pri = [t for t in tasks if t.get("priority") == "高" and t.get("status") != "完了"]

    lines = [
        f"【進捗レポート】{today.strftime('%Y年%m月%d日')}時点", "",
        "■ 全体状況",
        f"　総タスク数: {total}件　完了率: {rate}%",
        f"　完了: {done}件　進行中: {in_progress}件　未着手: {not_started}件", "",
        "■ 要注意事項",
    ]
    if overdue:
        lines.append(f"　期限超過タスクが {len(overdue)}件 あります。")
        for t in overdue[:3]:
            lines.append(f"　　・{t['name']}（期限: {t.get('end_date','')}）")
    else:
        lines.append("　期限超過タスクはありません。")
    if high_pri:
        lines.append(f"　高優先度の未完了タスクが {len(high_pri)}件 あります。")
        for t in high_pri[:3]:
            lines.append(f"　　・{t['name']}")
    lines += ["", "■ 所感",
              f"　{'順調に進捗しています。' if rate >= 70 else '進捗が遅れ気味です。優先度の高いタスクに集中することを推奨します。'}"]
    return jsonify({"report": "\n".join(lines)})

@app.route("/api/ai/priority-advice", methods=["GET"])
@login_required
def ai_priority_advice():
    today = datetime.now().date()
    tasks = [t for t in load_data()["tasks"] if t.get("status") != "完了"]
    scored = []
    for t in tasks:
        score = 0
        ed    = _parse_date(t.get("end_date"))
        if ed:
            diff   = (ed - today).days
            score += 100 if diff < 0 else 50 if diff <= 3 else 20 if diff <= 7 else 0
        score += 30 if t.get("priority") == "高" else 10 if t.get("priority") == "中" else 0
        score += 15 if t.get("status") == "未着手" else 0
        scored.append((score, t))
    scored.sort(key=lambda x: -x[0])

    advice = []
    for _, t in scored[:3]:
        ed = _parse_date(t.get("end_date"))
        if ed and ed < today:
            reason = f"期限を{(today - ed).days}日超過しています"
        elif ed and (ed - today).days <= 3:
            reason = f"期限まで{(ed - today).days}日しかありません"
        elif t.get("priority") == "高":
            reason = "高優先度タスクで未完了です"
        else:
            reason = "早期着手を推奨します"
        advice.append({"id": t["id"], "name": t["name"], "reason": reason})
    return jsonify({"advice": advice})

@app.route("/api/ai/workload", methods=["GET"])
@login_required
def ai_workload():
    tasks  = [t for t in load_data()["tasks"] if t.get("status") != "完了"]
    counts = Counter(t.get("assignee", "不明") for t in tasks)
    avg    = len(tasks) / len(counts) if counts else 0
    workload, advice = [], []
    for name, count in counts.most_common():
        workload.append({"name": name, "count": count})
        if count >= avg * 1.5 or count >= 8:
            level, comment = "高", f"{count}件担当しており負荷が高い状態です。タスクの再分配を検討してください。"
        elif count >= avg * 1.1 or count >= 5:
            level, comment = "中", f"{count}件担当。やや負荷がかかっています。"
        else:
            level, comment = "低", f"{count}件担当。適切な負荷です。"
        advice.append({"name": name, "count": count, "level": level, "comment": comment})
    return jsonify({"workload": workload, "advice": advice})

@app.route("/api/ai/parse-task", methods=["POST"])
@login_required
def ai_parse_task():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    today    = datetime.now()
    end_date = ""

    m = re.search(r'(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})日?', text)
    if m:
        end_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m2 = re.search(r'(\d{1,2})[月/](\d{1,2})日?', text)
        if m2:
            end_date = f"{today.year}-{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
        else:
            for kw, days in [("今週", 7), ("来週", 14), ("今月末", 30)]:
                if kw in text:
                    end_date = (today + timedelta(days=days)).strftime("%Y-%m-%d")
                    break

    priority = "中"
    for p, kws in _PRIORITY_KW.items():
        if any(k in text for k in kws):
            priority = p
            break

    m3       = re.search(r'([^\s、。]+)さん', text)
    assignee = m3.group(1) if m3 else ""
    name     = re.sub(r'[。、！？!].*', '', text).strip()[:40]

    return jsonify({"task": {"name": name, "assignee": assignee, "end_date": end_date,
                             "priority": priority, "description": text}})

@app.route("/api/ai/delay-prediction", methods=["GET"])
@login_required
def ai_delay_prediction():
    today       = datetime.now().date()
    predictions = []
    for t in load_data()["tasks"]:
        if t.get("status") == "完了":
            continue
        ed = _parse_date(t.get("end_date"))
        if not ed:
            continue
        diff = (ed - today).days
        if diff < 0:
            predictions.append({"id": t["id"], "name": t["name"],
                                 "delay_days": abs(diff), "risk": "高",
                                 "reason": f"期限を{abs(diff)}日超過しています"})
        elif diff <= 2 and t.get("status") == "未着手":
            predictions.append({"id": t["id"], "name": t["name"],
                                 "delay_days": 0, "risk": "高",
                                 "reason": f"期限まで{diff}日ですが未着手です"})
        elif diff <= 5 and t.get("status") in ("未着手", "保留"):
            predictions.append({"id": t["id"], "name": t["name"],
                                 "delay_days": 0, "risk": "中",
                                 "reason": f"期限まで{diff}日で進捗が不十分です"})
    predictions.sort(key=lambda x: x["delay_days"], reverse=True)
    return jsonify({"predictions": predictions})

@app.route("/api/ai/sentiment", methods=["POST"])
@login_required
def ai_sentiment():
    tasks = (request.json or {}).get("tasks", [])
    if not tasks:
        return jsonify({"sentiments": []})
    results = []
    for t in tasks[:20]:
        text = t.get("description", "") or t.get("name", "")
        neg  = sum(1 for w in _NEG_WORDS if w in text)
        pos  = sum(1 for w in _POS_WORDS if w in text)
        if neg >= 2 or (neg > pos and neg >= 1):
            sentiment, stress = "ネガティブ", "高"
        elif pos >= 1 and neg == 0:
            sentiment, stress = "ポジティブ", "低"
        else:
            sentiment, stress = "普通", "中"
        if t.get("priority") == "高" and stress != "高":
            stress = "中"
        results.append({"id": t["id"], "sentiment": sentiment, "stress": stress})
    return jsonify({"sentiments": results})

# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

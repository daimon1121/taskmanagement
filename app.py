from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import os, uuid, stripe
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

# ─── Mail ────────────────────────────────────────────────────────────────────
app.config["MAIL_SERVER"]         = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"]           = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"]        = True
app.config["MAIL_USERNAME"]       = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"]       = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME", "")
mail = Mail(app)

def _make_reset_token(email):
    return URLSafeTimedSerializer(app.secret_key).dumps(email, salt="pw-reset")

def _verify_reset_token(token, max_age=3600):
    try:
        return URLSafeTimedSerializer(app.secret_key).loads(token, salt="pw-reset", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None

stripe.api_key             = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY     = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET      = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID            = os.environ.get("STRIPE_PRICE_ID", "")

FREE_TASK_LIMIT = 10
TOOLS_VER = 2

# ─── Database ────────────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

def get_conn():
    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

# ─── Tool base names ──────────────────────────────────────────────────────────
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

# ─── DB Init ─────────────────────────────────────────────────────────────────
def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                    VARCHAR(36)  PRIMARY KEY,
            email                 VARCHAR(255) UNIQUE NOT NULL,
            password              VARCHAR(255) NOT NULL,
            plan                  VARCHAR(20)  DEFAULT 'free',
            stripe_customer_id    VARCHAR(255),
            stripe_subscription_id VARCHAR(255)
        )
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

    # Seed assignees
    cur.execute("SELECT COUNT(*) FROM assignees")
    if cur.fetchone()["count"] == 0:
        for name, email in _SAMPLE_ASSIGNEES:
            cur.execute("INSERT INTO assignees (name, email) VALUES (%s, %s)", (name, email))

    # Seed tools
    cur.execute("SELECT COUNT(*) FROM tools")
    if cur.fetchone()["count"] == 0:
        tool_names = [f"{i:03d}_{b}" for i, b in enumerate(_TOOL_BASE, 1)]
        for i in range(len(_TOOL_BASE) + 1, 301):
            tool_names.append(f"{i:03d}_ツール")
        for name in tool_names:
            cur.execute("INSERT INTO tools (name) VALUES (%s)", (name,))

    # Seed tasks
    cur.execute("SELECT COUNT(*) FROM tasks")
    if cur.fetchone()["count"] == 0:
        today = datetime.now()
        def d(n): return (today + timedelta(days=n)).strftime("%Y-%m-%d")
        rows = [
            ("要件定義・仕様策定",    d(-23),d(-20),d(-13),d(-11),"完了",  "高","005_Confluence","田中 太郎","ステークホルダーへのヒアリング完了。"),
            ("UI/UXデザイン",         d(-17),d(-14),d(-5), d(-3), "完了",  "高","015_Figma",     "鈴木 花子","ワイヤーフレーム・プロトタイプを作成。"),
            ("データベース設計",       d(-12),d(-10),d(-4), d(-2), "完了",  "中","039_PostgreSQL","佐藤 一郎","ER図・テーブル定義書を作成。"),
            ("バックエンド開発",       d(-8), d(-5), d(9),  d(12), "進行中","高","001_GitHub",    "伊藤 健二","REST API実装中。"),
            ("フロントエンド開発",     d(-5), d(-2), d(12), d(15), "進行中","高","073_React",     "渡辺 祐子","コンポーネント実装中。"),
            ("単体テスト",             d(5),  d(8),  d(15), d(18), "未着手","中","095_Sonarqube", "山田 修",  "ユニットテストを実施予定。"),
            ("結合テスト",             d(13), d(16), d(22), d(25), "未着手","高","056_Postman",   "高橋 美香","API連携・画面遷移の総合確認。"),
            ("パフォーマンス改善",     d(7),  d(10), d(17), d(20), "未着手","低","051_Datadog",   "佐藤 一郎","ボトルネック分析後に対応。"),
            ("ドキュメント整備",       d(15), d(18), d(25), d(28), "未着手","低","005_Confluence","中村 理恵","APIドキュメント・運用手順書の作成。"),
            ("本番リリース準備",       d(21), d(24), d(27), d(30), "未着手","高","028_Terraform", "田中 太郎","インフラ構築・監視設定。"),
        ]
        for name,rq,s,di,e,status,pri,tool,assignee,desc in rows:
            cur.execute("""
                INSERT INTO tasks (name,request_date,start_date,distribution_date,end_date,
                                   status,priority,tool,assignee,description)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (name,rq,s,di,e,status,pri,tool,assignee,desc))

    conn.commit()
    cur.close()
    conn.close()

with app.app_context():
    if _DATABASE_URL:
        init_db()

# ─── Users ───────────────────────────────────────────────────────────────────
def find_user_by_email(email):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None

def find_user_by_id(uid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    row = cur.fetchone()
    cur.close(); conn.close()
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

# ─── Tools ───────────────────────────────────────────────────────────────────
def load_tools():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM tools ORDER BY id")
    tools = [dict(r) for r in cur.fetchall()]
    next_id = (max(t["id"] for t in tools) + 1) if tools else 1
    cur.close(); conn.close()
    return {"version": TOOLS_VER, "tools": tools, "next_id": next_id}

# ─── Assignees ───────────────────────────────────────────────────────────────
def load_assignees():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM assignees ORDER BY id")
    assignees = [dict(r) for r in cur.fetchall()]
    next_id = (max(a["id"] for a in assignees) + 1) if assignees else 1
    cur.close(); conn.close()
    return {"assignees": assignees, "next_id": next_id}

# ─── Tasks ───────────────────────────────────────────────────────────────────
def load_data():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM tasks ORDER BY id")
    tasks = [dict(r) for r in cur.fetchall()]
    next_id = (max(t["id"] for t in tasks) + 1) if tasks else 1
    cur.close(); conn.close()
    return {"tasks": tasks, "next_id": next_id}

def _composite_key(t):
    return (t.get("assignee",""), t.get("tool",""), t.get("name",""), t.get("implementation_date",""))

# ─── Auth Routes ─────────────────────────────────────────────────────────────
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
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id,email,password,plan) VALUES (%s,%s,%s,'free')",
            (uid, email, generate_password_hash(password))
        )
        conn.commit(); cur.close(); conn.close()
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
                msg = Message("パスワードリセット - タスク管理", recipients=[email])
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
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE users SET password=%s WHERE email=%s",
                    (generate_password_hash(password), email))
        conn.commit(); cur.close(); conn.close()
        flash("パスワードをリセットしました。新しいパスワードでログインしてください。")
        return redirect(url_for("login"))
    return render_template("reset_password.html", token=token)

# ─── Pricing / Stripe Routes ──────────────────────────────────────────────────
@app.route("/pricing")
@login_required
def pricing():
    u = current_user()
    return render_template("pricing.html", user=u, stripe_key=STRIPE_PUBLISHABLE_KEY)

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    u = current_user()
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
                          checkout.customer,
                          checkout.subscription)
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
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        UPDATE users SET plan='pro', stripe_customer_id=%s, stripe_subscription_id=%s
        WHERE id=%s
    """, (customer_id, subscription_id, user_id))
    conn.commit(); cur.close(); conn.close()

def _downgrade_by_subscription(subscription_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        UPDATE users SET plan='free', stripe_subscription_id=NULL
        WHERE stripe_subscription_id=%s
    """, (subscription_id,))
    conn.commit(); cur.close(); conn.close()

# ─── Routes: Tools ───────────────────────────────────────────────────────────
@app.route("/api/tools", methods=["GET"])
@login_required
def get_tools():
    return jsonify(load_tools())

@app.route("/api/tools", methods=["POST"])
@login_required
def add_tool():
    name = (request.json or {}).get("name","").strip()
    if not name: return jsonify({"error":"name required"}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO tools (name) VALUES (%s) RETURNING id", (name,))
    tool_id = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()
    return jsonify({"id": tool_id, "name": name}), 201

@app.route("/api/tools/<int:tool_id>", methods=["PUT"])
@login_required
def update_tool(tool_id):
    name = (request.json or {}).get("name","").strip()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE tools SET name=%s WHERE id=%s RETURNING *", (name, tool_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(dict(row))

@app.route("/api/tools/<int:tool_id>", methods=["DELETE"])
@login_required
def delete_tool(tool_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM tools WHERE id=%s", (tool_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"ok": True})

# ─── Routes: Assignees ────────────────────────────────────────────────────────
@app.route("/api/assignees", methods=["GET"])
@login_required
def get_assignees():
    return jsonify(load_assignees())

@app.route("/api/assignees", methods=["POST"])
@login_required
def add_assignee():
    body = request.json or {}
    name = body.get("name","").strip()
    if not name: return jsonify({"error":"name required"}), 400
    email = body.get("email","").strip()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO assignees (name,email) VALUES (%s,%s) RETURNING id", (name, email))
    aid = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()
    return jsonify({"id": aid, "name": name, "email": email}), 201

@app.route("/api/assignees/<int:aid>", methods=["PUT"])
@login_required
def update_assignee(aid):
    body = request.json or {}
    name  = body.get("name","").strip()
    email = body.get("email","").strip()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE assignees SET name=%s, email=%s WHERE id=%s RETURNING *",
                (name, email, aid))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(dict(row))

@app.route("/api/assignees/<int:aid>", methods=["DELETE"])
@login_required
def delete_assignee(aid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM assignees WHERE id=%s", (aid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"ok": True})

# ─── Routes: Tasks ────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    u = current_user()
    return render_template("index.html", user=u, is_pro=is_pro())

@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    return jsonify(load_data())

@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    data = load_data()
    if not is_pro() and len(data["tasks"]) >= FREE_TASK_LIMIT:
        return jsonify({"error":"plan_limit",
                        "message":f"無料プランはタスク{FREE_TASK_LIMIT}件までです。Proにアップグレードしてください。"}), 403
    task = request.json
    key  = _composite_key(task)
    if any(_composite_key(t) == key for t in data["tasks"]):
        return jsonify({"error":"duplicate","message":"同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}), 409
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO tasks (name,request_date,start_date,distribution_date,end_date,
                           status,priority,tool,assignee,description,implementation_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (
        task.get("name"), task.get("request_date"), task.get("start_date"),
        task.get("distribution_date"), task.get("end_date"), task.get("status"),
        task.get("priority"), task.get("tool"), task.get("assignee"),
        task.get("description"), task.get("implementation_date"),
    ))
    task["id"] = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()
    return jsonify(task), 201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    data = load_data()
    task = request.json
    key  = _composite_key(task)
    if any(_composite_key(t) == key and t["id"] != task_id for t in data["tasks"]):
        return jsonify({"error":"duplicate","message":"同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}), 409
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        UPDATE tasks SET name=%s,request_date=%s,start_date=%s,distribution_date=%s,
                         end_date=%s,status=%s,priority=%s,tool=%s,assignee=%s,
                         description=%s,implementation_date=%s
        WHERE id=%s RETURNING *
    """, (
        task.get("name"), task.get("request_date"), task.get("start_date"),
        task.get("distribution_date"), task.get("end_date"), task.get("status"),
        task.get("priority"), task.get("tool"), task.get("assignee"),
        task.get("description"), task.get("implementation_date"), task_id,
    ))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(dict(row))

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id=%s", (task_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/me")
@login_required
def api_me():
    u = current_user()
    return jsonify({"email": u["email"], "plan": u["plan"]})

# ─── Admin ────────────────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if ADMIN_PASSWORD and pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("パスワードが正しくありません")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY email")
    users = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM tasks")
    total_tasks = cur.fetchone()["count"]
    cur.close(); conn.close()
    stats = {
        "total_users": len(users),
        "pro_users":   sum(1 for u in users if u.get("plan") == "pro"),
        "free_users":  sum(1 for u in users if u.get("plan") != "pro"),
        "total_tasks": total_tasks,
    }
    return render_template("admin_dashboard.html", users=users, stats=stats)

# ─── AI Routes ───────────────────────────────────────────────────────────────
import anthropic as _anthropic
import re as _re
import json as _json
from collections import Counter as _Counter

def _ai_call(prompt, max_tokens=1024):
    client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def _extract_json_array(text):
    match = _re.search(r'\[.*\]', text, _re.DOTALL)
    if not match:
        return []
    try:
        return _json.loads(match.group())
    except Exception:
        return []

def _extract_json_obj(text):
    match = _re.search(r'\{.*\}', text, _re.DOTALL)
    if not match:
        return {}
    try:
        return _json.loads(match.group())
    except Exception:
        return {}

# 1. タスク自動分解
@app.route("/api/ai/decompose", methods=["POST"])
@login_required
def ai_decompose():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    text = _ai_call(
        f"タスク「{name}」を5〜7個の具体的なサブタスクに分解してください。"
        f"JSON配列のみ返してください（説明不要）: [\"サブタスク1\", \"サブタスク2\", ...]"
    )
    return jsonify({"subtasks": _extract_json_array(text)})

# 2. 進捗レポート自動生成
@app.route("/api/ai/report", methods=["GET"])
@login_required
def ai_report():
    data = load_data()
    summary = "\n".join([
        f"- {t['name']} | ステータス:{t.get('status','')} | 優先度:{t.get('priority','')} | 完了日:{t.get('end_date','')}"
        for t in data["tasks"]
    ])
    text = _ai_call(
        f"以下のタスク一覧から今週の進捗レポートを300字程度で作成してください:\n{summary}",
        max_tokens=600
    )
    return jsonify({"report": text})

# 3. 優先度アドバイス
@app.route("/api/ai/priority-advice", methods=["GET"])
@login_required
def ai_priority_advice():
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = [t for t in data["tasks"] if t.get("status") != "完了"]
    summary = "\n".join([
        f"- ID:{t['id']} タスク名:{t['name']} 完了日:{t.get('end_date','')} ステータス:{t.get('status','')}"
        for t in tasks
    ])
    text = _ai_call(
        f"今日は{today}です。以下の未完了タスクから遅延リスクが高いものを3件以内で指摘してください。"
        f"JSON配列のみ返してください: [{{\"id\":1,\"name\":\"タスク名\",\"reason\":\"理由\"}}]\n{summary}"
    )
    return jsonify({"advice": _extract_json_array(text)})

# 4. 担当者負荷検知
@app.route("/api/ai/workload", methods=["GET"])
@login_required
def ai_workload():
    data = load_data()
    tasks = [t for t in data["tasks"] if t.get("status") != "完了"]
    counts = _Counter(t.get("assignee", "不明") for t in tasks)
    workload = [{"name": k, "count": v} for k, v in counts.most_common()]
    summary = "\n".join([f"- {w['name']}: {w['count']}件" for w in workload])
    text = _ai_call(
        f"以下の担当者別タスク件数から負荷が偏っている担当者を指摘してください。"
        f"JSON配列のみ返してください: [{{\"name\":\"担当者名\",\"count\":5,\"level\":\"高\",\"comment\":\"コメント\"}}]\n{summary}"
    )
    return jsonify({"workload": workload, "advice": _extract_json_array(text)})

# 5. 自然言語タスク登録
@app.route("/api/ai/parse-task", methods=["POST"])
@login_required
def ai_parse_task():
    text_input = (request.json or {}).get("text", "").strip()
    if not text_input:
        return jsonify({"error": "text required"}), 400
    today = datetime.now().strftime("%Y-%m-%d")
    result = _ai_call(
        f"今日は{today}です。次の文章からタスク情報を抽出してJSON形式で返してください。"
        f"フィールド: name(タスク名), assignee(担当者名), end_date(完了日 YYYY-MM-DD形式), priority(高/中/低), description(メモ)\n"
        f"文章: 「{text_input}」\n"
        f"JSONオブジェクトのみ返してください: {{\"name\":\"...\",\"assignee\":\"...\",\"end_date\":\"...\",\"priority\":\"...\",\"description\":\"...\"}}"
    )
    return jsonify({"task": _extract_json_obj(result)})

# 6. 遅延予測
@app.route("/api/ai/delay-prediction", methods=["GET"])
@login_required
def ai_delay_prediction():
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = [t for t in data["tasks"] if t.get("status") not in ("完了",)]
    summary = "\n".join([
        f"- ID:{t['id']} {t['name']} 着手日:{t.get('start_date','')} 完了予定:{t.get('end_date','')} ステータス:{t.get('status','')}"
        for t in tasks
    ])
    text = _ai_call(
        f"今日は{today}です。以下のタスクの進捗から遅延が予想されるものを分析してください。"
        f"JSON配列のみ返してください: [{{\"id\":1,\"name\":\"タスク名\",\"delay_days\":3,\"risk\":\"高\",\"reason\":\"理由\"}}]\n{summary}"
    )
    return jsonify({"predictions": _extract_json_array(text)})

# 7. 感情分析
@app.route("/api/ai/sentiment", methods=["POST"])
@login_required
def ai_sentiment():
    tasks = (request.json or {}).get("tasks", [])
    if not tasks:
        return jsonify({"sentiments": []})
    descriptions = "\n".join([
        f"ID:{t['id']} 「{t.get('description', t.get('name',''))}」"
        for t in tasks[:20]
    ])
    text = _ai_call(
        f"以下のタスクの内容から感情・ストレス度を分析してください。"
        f"JSON配列のみ返してください: [{{\"id\":1,\"sentiment\":\"ポジティブ\",\"stress\":\"低\"}}]\n"
        f"sentimentは「ポジティブ/普通/ネガティブ」、stressは「低/中/高」\n{descriptions}"
    )
    return jsonify({"sentiments": _extract_json_array(text)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

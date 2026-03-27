from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import json, os

app = Flask(__name__)

TASKS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json")
TOOLS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.json")
ASSIGNEES_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assignees.json")
TOOLS_VER       = 2

# ─── Tool base names ────────────────────────────────────────────────────────
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

# ─── Assignee sample data ────────────────────────────────────────────────────
_SAMPLE_ASSIGNEES = [
    "田中 太郎","鈴木 花子","佐藤 一郎","高橋 美香",
    "伊藤 健二","渡辺 祐子","山田 修",  "中村 理恵",
    "小林 拓也","加藤 奈々","吉田 大輔","山口 恵子",
    "松本 健",  "井上 さくら","木村 誠","林 美穂",
    "清水 隆",  "山崎 由美", "池田 直樹","橋本 陽子",
]

# ─── Tools ──────────────────────────────────────────────────────────────────

def load_tools():
    if os.path.exists(TOOLS_FILE):
        with open(TOOLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == TOOLS_VER:
            return data
    tools = [{"id": i, "name": f"{i:03d}_{b}"} for i, b in enumerate(_TOOL_BASE, 1)]
    for i in range(len(_TOOL_BASE) + 1, 301):
        tools.append({"id": i, "name": f"{i:03d}_ツール"})
    data = {"version": TOOLS_VER, "tools": tools, "next_id": 301}
    save_tools(data)
    return data

def save_tools(data):
    with open(TOOLS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Assignees ───────────────────────────────────────────────────────────────

def load_assignees():
    if os.path.exists(ASSIGNEES_FILE):
        with open(ASSIGNEES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    assignees = [{"id": i, "name": n} for i, n in enumerate(_SAMPLE_ASSIGNEES, 1)]
    data = {"assignees": assignees, "next_id": len(assignees) + 1}
    save_assignees(data)
    return data

def save_assignees(data):
    with open(ASSIGNEES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Tasks ──────────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    today = datetime.now()
    def d(n): return (today + timedelta(days=n)).strftime("%Y-%m-%d")
    rows = [
        # name,                   request,   start,    dist,     end,    status,   pri, tool,            assignee,     desc
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
        ("ユーザー受け入れテスト", d(23), d(26), d(30), d(33), "保留",  "高","004_Jira",      "高橋 美香","顧客環境での最終確認。"),
        ("リリース・本番切替",     d(29), d(32), d(33), d(35), "未着手","高","030_Jenkins",   "伊藤 健二","段階的ロールアウト予定。"),
    ]
    data = {"tasks": [], "next_id": 1}
    for name,rq,s,di,e,status,pri,tool,assignee,desc in rows:
        data["tasks"].append({"id":data["next_id"],"name":name,
                               "request_date":rq,"start_date":s,
                               "distribution_date":di,"end_date":e,
                               "status":status,"priority":pri,"tool":tool,
                               "assignee":assignee,"description":desc})
        data["next_id"] += 1
    save_data(data)
    return data

def save_data(data):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Routes: Tools ──────────────────────────────────────────────────────────

@app.route("/api/tools", methods=["GET"])
def get_tools():
    return jsonify(load_tools())

@app.route("/api/tools", methods=["POST"])
def add_tool():
    data = load_tools()
    name = (request.json or {}).get("name","").strip()
    if not name: return jsonify({"error":"name required"}),400
    tool = {"id":data["next_id"],"name":name}
    data["next_id"] += 1; data["tools"].append(tool)
    save_tools(data); return jsonify(tool),201

@app.route("/api/tools/<int:tool_id>", methods=["PUT"])
def update_tool(tool_id):
    data = load_tools()
    for i,t in enumerate(data["tools"]):
        if t["id"]==tool_id:
            data["tools"][i]["name"]=(request.json or {}).get("name",t["name"]).strip()
            save_tools(data); return jsonify(data["tools"][i])
    return jsonify({"error":"not found"}),404

@app.route("/api/tools/<int:tool_id>", methods=["DELETE"])
def delete_tool(tool_id):
    data = load_tools()
    data["tools"]=[t for t in data["tools"] if t["id"]!=tool_id]
    save_tools(data); return jsonify({"ok":True})

# ─── Routes: Assignees ───────────────────────────────────────────────────────

@app.route("/api/assignees", methods=["GET"])
def get_assignees():
    return jsonify(load_assignees())

@app.route("/api/assignees", methods=["POST"])
def add_assignee():
    data = load_assignees()
    name = (request.json or {}).get("name","").strip()
    if not name: return jsonify({"error":"name required"}),400
    a = {"id":data["next_id"],"name":name}
    data["next_id"] += 1; data["assignees"].append(a)
    save_assignees(data); return jsonify(a),201

@app.route("/api/assignees/<int:aid>", methods=["PUT"])
def update_assignee(aid):
    data = load_assignees()
    for i,a in enumerate(data["assignees"]):
        if a["id"]==aid:
            data["assignees"][i]["name"]=(request.json or {}).get("name",a["name"]).strip()
            save_assignees(data); return jsonify(data["assignees"][i])
    return jsonify({"error":"not found"}),404

@app.route("/api/assignees/<int:aid>", methods=["DELETE"])
def delete_assignee(aid):
    data = load_assignees()
    data["assignees"]=[a for a in data["assignees"] if a["id"]!=aid]
    save_assignees(data); return jsonify({"ok":True})

# ─── Routes: Tasks ──────────────────────────────────────────────────────────

@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/tasks", methods=["GET"])
def get_tasks(): return jsonify(load_data())

def _composite_key(t):
    return (t.get("assignee",""), t.get("tool",""), t.get("name",""), t.get("implementation_date",""))

@app.route("/api/tasks", methods=["POST"])
def add_task():
    data=load_data(); task=request.json
    key = _composite_key(task)
    if any(_composite_key(t)==key for t in data["tasks"]):
        return jsonify({"error":"duplicate","message":"同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}),409
    task["id"]=data["next_id"]; data["next_id"]+=1
    data["tasks"].append(task); save_data(data)
    return jsonify(task),201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    data=load_data()
    key = _composite_key(request.json)
    if any(_composite_key(t)==key and t["id"]!=task_id for t in data["tasks"]):
        return jsonify({"error":"duplicate","message":"同じ担当者・Tool・タスク名・実施日の組み合わせがすでに存在します"}),409
    for i,t in enumerate(data["tasks"]):
        if t["id"]==task_id:
            updated={**request.json,"id":task_id}
            data["tasks"][i]=updated; save_data(data)
            return jsonify(updated)
    return jsonify({"error":"not found"}),404

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    data=load_data()
    data["tasks"]=[t for t in data["tasks"] if t["id"]!=task_id]
    save_data(data); return jsonify({"ok":True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)

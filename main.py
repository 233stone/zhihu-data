import json
import time
import socket
import sqlite3
import threading
import webbrowser
import requests as http_requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)
DB_PATH = "zhihu_data.db"

# ============================================================
# 数据库初始化
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 文章统计数据表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS article_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_time DATETIME,
            token TEXT,
            title TEXT,
            today_date TEXT,
            today_pv INTEGER,
            today_show INTEGER,
            today_upvote INTEGER,
            today_comment INTEGER,
            today_collect INTEGER,
            today_share INTEGER,
            today_incr_upvote INTEGER,
            today_desc_upvote INTEGER,
            finish_read_percent TEXT,
            positive_interact_percent TEXT,
            follower_translate INTEGER
        )
    ''')

    # 文章配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 系统配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # 初始化默认配置
    default_config = {
        "interval_minutes": "10",
        "request_delay_seconds": "5",
        "cookie": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "x_zse_93": "101_3_3.0",
        "x_zse_96": ""
    }
    for key, value in default_config.items():
        cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()

def get_config_dict():
    """从数据库读取所有配置，返回字典"""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def get_articles_list():
    """从数据库读取文章列表"""
    conn = get_db()
    rows = conn.execute("SELECT token, title FROM articles").fetchall()
    conn.close()
    return [{"token": row["token"], "title": row["title"]} for row in rows]

# ============================================================
# 后台定时抓取线程
# ============================================================
scheduler_running = True

def build_headers(config):
    """根据配置构造请求头"""
    headers = {
        "user-agent": config.get("user_agent", ""),
        "x-zse-93": config.get("x_zse_93", ""),
        "x-zse-96": config.get("x_zse_96", ""),
    }
    cookie = config.get("cookie", "")
    if cookie:
        headers["cookie"] = cookie
    return headers

def fetch_single_article(token, title, headers):
    """抓取单篇文章数据并入库"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.zhihu.com/api/v4/creators/analysis/realtime/content/aggr?type=answer&token={token}&end={end_date}"

    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 正在抓取: {title}")

        response = http_requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            data = response.json()
            today = data.get("today") or {}
            advanced = today.get("advanced") or {}

            fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            conn = get_db()
            conn.execute('''
                INSERT INTO article_stats (
                    fetch_time, token, title,
                    today_date, today_pv, today_show, today_upvote, today_comment, today_collect, today_share,
                    today_incr_upvote, today_desc_upvote, finish_read_percent, positive_interact_percent, follower_translate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                fetch_time, token, title,
                today.get("p_date", ""),
                today.get("pv", 0), today.get("show", 0), today.get("upvote", 0),
                today.get("comment", 0), today.get("collect", 0), today.get("share", 0),
                today.get("incr_upvote_num") or 0, today.get("desc_upvote_num") or 0,
                advanced.get("finish_read_percent", ""),
                advanced.get("positive_interact_percent", ""),
                advanced.get("follower_translate", 0)
            ))
            conn.commit()
            conn.close()

            print(f"  -> 入库成功 | {today.get('p_date','')}: 阅读={today.get('pv',0)}, 赞同={today.get('upvote',0)}, 收藏={today.get('collect',0)}")
            return True
        else:
            print(f"  -> [失败] 状态码: {response.status_code}")
            return False

    except Exception as e:
        print(f"  -> [异常] {type(e).__name__}: {e}")
        return False

def scheduler_loop():
    """后台定时抓取主循环"""
    global scheduler_running
    # 启动后等待 5 秒再开始第一次抓取，让 Flask 先完成启动
    time.sleep(5)

    while scheduler_running:
        try:
            config = get_config_dict()
            articles = get_articles_list()
            headers = build_headers(config)
            delay = int(config.get("request_delay_seconds", "5"))
            interval = int(config.get("interval_minutes", "10"))

            if not articles:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 暂无监控文章，跳过本轮抓取")
            else:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始第 {len(articles)} 篇文章的抓取...")
                for i, article in enumerate(articles):
                    fetch_single_article(article["token"], article["title"], headers)
                    # 文章间延迟（最后一篇不延迟）
                    if i < len(articles) - 1:
                        time.sleep(delay)

            print(f"等待 {interval} 分钟...\n")
            # 用小步 sleep 替代大块 sleep，方便退出时响应
            for _ in range(interval * 60):
                if not scheduler_running:
                    return
                time.sleep(1)

        except Exception as e:
            print(f"[调度异常] {e}")
            time.sleep(60)

# ============================================================
# Flask API 路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")

# --- 数据统计 API ---

@app.route("/api/stats/latest")
def api_stats_latest():
    """获取每篇文章的最新一条统计数据"""
    conn = get_db()
    rows = conn.execute('''
        SELECT s.* FROM article_stats s
        INNER JOIN (
            SELECT token, MAX(fetch_time) as max_time
            FROM article_stats
            GROUP BY token
        ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
        ORDER BY s.today_pv DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route("/api/stats/summary")
def api_stats_summary():
    """获取数据总览（所有文章或单篇文章的今日汇总）"""
    date_filter = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    token = request.args.get("token", "")
    conn = get_db()

    if token:
        # 单篇文章：取该文章在指定日期的最新一条记录
        rows = conn.execute('''
            SELECT s.* FROM article_stats s
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                WHERE today_date = ? AND token = ?
                GROUP BY token
            ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
        ''', (date_filter, token)).fetchall()
    else:
        # 所有文章汇总：取每篇文章在指定日期的最新一条记录
        rows = conn.execute('''
            SELECT s.* FROM article_stats s
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                WHERE today_date = ?
                GROUP BY token
            ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
        ''', (date_filter,)).fetchall()
    conn.close()

    # 汇总
    total_pv = sum(r["today_pv"] or 0 for r in rows)
    total_show = sum(r["today_show"] or 0 for r in rows)
    total_upvote = sum(r["today_upvote"] or 0 for r in rows)
    total_comment = sum(r["today_comment"] or 0 for r in rows)
    total_collect = sum(r["today_collect"] or 0 for r in rows)
    total_share = sum(r["today_share"] or 0 for r in rows)

    # 计算平均完读率
    finish_rates = []
    for r in rows:
        rate_str = r["finish_read_percent"] or ""
        if rate_str and rate_str.endswith("%"):
            try:
                finish_rates.append(float(rate_str.replace("%", "")))
            except ValueError:
                pass
    avg_finish_rate = f"{sum(finish_rates) / len(finish_rates):.2f}%" if finish_rates else "0%"

    # 点击率 = 阅读量 / 展现量
    click_rate = f"{(total_pv / total_show * 100):.2f}%" if total_show > 0 else "0%"

    return jsonify({
        "date": date_filter,
        "total_pv": total_pv,
        "total_show": total_show,
        "total_upvote": total_upvote,
        "total_comment": total_comment,
        "total_collect": total_collect,
        "total_share": total_share,
        "avg_finish_rate": avg_finish_rate,
        "click_rate": click_rate,
        "article_count": len(rows)
    })

@app.route("/api/stats/trend")
def api_stats_trend():
    """获取趋势数据（按时间点），用于折线图"""
    token = request.args.get("token", "")
    days = int(request.args.get("days", "1"))

    conn = get_db()

    if token:
        # 单篇文章的趋势
        rows = conn.execute('''
            SELECT fetch_time, today_date, today_pv, today_upvote, today_collect, today_share, today_show,
                   finish_read_percent, positive_interact_percent
            FROM article_stats
            WHERE token = ?
            ORDER BY fetch_time DESC
            LIMIT ?
        ''', (token, days * 144)).fetchall()
    else:
        # 所有文章汇总趋势：按 fetch_time 分组求和
        rows = conn.execute('''
            SELECT fetch_time, today_date,
                   SUM(today_pv) as today_pv, SUM(today_upvote) as today_upvote,
                   SUM(today_collect) as today_collect, SUM(today_share) as today_share,
                   SUM(today_show) as today_show
            FROM article_stats
            GROUP BY fetch_time
            ORDER BY fetch_time DESC
            LIMIT ?
        ''', (days * 144,)).fetchall()

    conn.close()
    result = [dict(row) for row in rows]
    result.reverse()
    return jsonify(result)

# --- 文章管理 API ---

@app.route("/api/articles", methods=["GET"])
def api_articles_list():
    """获取所有监控文章"""
    conn = get_db()
    articles = conn.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in articles])

@app.route("/api/articles", methods=["POST"])
def api_articles_add():
    """添加文章（支持通过链接自动解析 token）"""
    import re
    data = request.get_json()
    url = data.get("url", "").strip()
    title = data.get("title", "").strip()
    token = data.get("token", "").strip()

    # 如果传了 url，从中解析 token
    if url:
        match = re.search(r'/answer/(\d+)', url)
        if not match:
            return jsonify({"error": "无法从链接中解析 answer ID，请检查链接格式"}), 400
        token = match.group(1)

    if not token:
        return jsonify({"error": "请提供知乎回答链接或 token"}), 400

    # 如果没有标题，尝试从知乎 API 自动获取
    if not title:
        try:
            config = get_config_dict()
            headers = build_headers(config)
            end_date = datetime.now().strftime("%Y-%m-%d")
            api_url = f"https://www.zhihu.com/api/v4/creators/analysis/realtime/content/aggr?type=answer&token={token}&end={end_date}"
            resp = http_requests.get(api_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                resp_data = resp.json()
                title = resp_data.get("answer", {}).get("title", "")
        except Exception:
            pass

    if not title:
        title = f"回答_{token}"

    conn = get_db()
    try:
        conn.execute("INSERT INTO articles (token, title) VALUES (?, ?)", (token, title))
        conn.commit()
        conn.close()
        return jsonify({"message": "添加成功", "token": token, "title": title})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "该文章已存在"}), 409

@app.route("/api/articles/<token>", methods=["DELETE"])
def api_articles_delete(token):
    """删除文章"""
    conn = get_db()
    conn.execute("DELETE FROM articles WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return jsonify({"message": "删除成功"})

# --- 文章数据表格 API（可排序） ---

@app.route("/api/articles/table")
def api_articles_table():
    """获取文章列表 + 每篇文章的最新数据，用于可排序表格"""
    conn = get_db()
    rows = conn.execute('''
        SELECT a.token, a.title,
               s.today_pv, s.today_show, s.today_upvote, s.today_comment,
               s.today_collect, s.today_share, s.finish_read_percent,
               s.positive_interact_percent, s.fetch_time
        FROM articles a
        LEFT JOIN (
            SELECT st.* FROM article_stats st
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                GROUP BY token
            ) latest ON st.token = latest.token AND st.fetch_time = latest.max_time
        ) s ON a.token = s.token
        ORDER BY a.created_at DESC
    ''').fetchall()
    conn.close()

    result = []
    for row in rows:
        item = dict(row)
        # 计算点击率
        pv = item.get("today_pv") or 0
        show = item.get("today_show") or 0
        item["click_rate"] = f"{(pv / show * 100):.2f}%" if show > 0 else "0%"
        result.append(item)

    return jsonify(result)

# --- 系统配置 API ---

@app.route("/api/config", methods=["GET"])
def api_config_get():
    """获取系统配置"""
    return jsonify(get_config_dict())

@app.route("/api/config", methods=["PUT"])
def api_config_update():
    """更新系统配置"""
    data = request.get_json()
    conn = get_db()
    for key, value in data.items():
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
    return jsonify({"message": "配置已更新"})

# ============================================================
# 从旧 config.json 迁移数据
# ============================================================
def migrate_from_config_json():
    """如果存在旧的 config.json，自动导入其数据到数据库"""
    import os
    config_path = "config.json"
    if not os.path.exists(config_path):
        return

    print("[迁移] 检测到 config.json，正在导入到数据库...")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            old_config = json.load(f)

        conn = get_db()

        # 迁移配置
        headers = old_config.get("headers", {})
        config_map = {
            "interval_minutes": str(old_config.get("interval_minutes", 10)),
            "request_delay_seconds": str(old_config.get("request_delay_seconds", 5)),
            "cookie": headers.get("cookie", ""),
            "user_agent": headers.get("user-agent", ""),
            "x_zse_93": headers.get("x-zse-93", ""),
            "x_zse_96": headers.get("x-zse-96", ""),
        }
        for key, value in config_map.items():
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))

        # 迁移文章列表
        for article in old_config.get("articles", []):
            token = article.get("token", "")
            title = article.get("title", "")
            if token:
                conn.execute("INSERT OR IGNORE INTO articles (token, title) VALUES (?, ?)", (token, title))

        conn.commit()
        conn.close()

        # 迁移完成后重命名旧文件
        os.rename(config_path, config_path + ".bak")
        print("[迁移] 完成！旧文件已重命名为 config.json.bak")
    except Exception as e:
        print(f"[迁移] 失败: {e}")

# ============================================================
# 启动入口
# ============================================================
def main():
    print("=============================================")
    print("  知乎数据监控工具 v2.0 (Web 版)")
    print("  访问 http://localhost:5000 打开控制面板")
    print("=============================================\n")

    init_db()
    migrate_from_config_json()

    # 启动后台抓取线程
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

    # 自动打开浏览器
    webbrowser.open("http://localhost:5000")

    # 启动 Flask
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    main()

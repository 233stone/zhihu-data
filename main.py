import os
import sqlite3
import sys
import webbrowser
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from app import repos, services


def get_resource_path(relative_path: str) -> str:
    """获取资源路径，兼容 PyInstaller 打包后的环境"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def get_exe_dir() -> str:
    """获取可执行文件所在目录（打包后为 exe 目录，开发时为项目目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


HOST = "0.0.0.0"
PORT = 5050
LOCAL_URL = f"http://localhost:{PORT}"

app = Flask(
    __name__,
    template_folder=get_resource_path("templates"),
    static_folder=get_resource_path("static"),
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats/latest")
def api_stats_latest():
    """获取每篇文章的最新一条统计数据"""
    return jsonify(repos.get_latest_stats_rows())


@app.route("/api/stats/summary")
def api_stats_summary():
    """获取数据总览（所有文章或单篇文章的今日汇总）"""
    date_filter = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    token = request.args.get("token", "")
    rows = repos.get_summary_rows(date_filter=date_filter, token=token)
    return jsonify(services.calculate_summary(date_filter=date_filter, rows=rows))


@app.route("/api/stats/trend")
def api_stats_trend():
    """获取趋势数据（按时间点），用于折线图"""
    token = request.args.get("token", "")
    try:
        days = int(request.args.get("days", "1"))
    except ValueError:
        days = 1
    return jsonify(repos.get_trend_rows(days=days, token=token))


@app.route("/api/articles", methods=["GET"])
def api_articles_list():
    """获取所有监控文章"""
    return jsonify(repos.list_articles())


@app.route("/api/articles", methods=["POST"])
def api_articles_add():
    """添加文章（支持通过链接自动解析 token）"""
    data = request.get_json() or {}
    raw_input = (data.get("url") or "").strip()
    title = (data.get("title") or "").strip()
    token = (data.get("token") or "").strip()

    if raw_input:
        parsed_token, parsed_title = services.parse_article_input(raw_input)
        if not token and parsed_token:
            token = parsed_token
        if not title and parsed_title:
            title = parsed_title

    if not token:
        return jsonify({"error": "无法解析回答 ID，请粘贴知乎回答链接或分享文本"}), 400

    if not title:
        config = repos.get_config_dict()
        title = services.fetch_article_title(token=token, config=config) or f"回答_{token}"

    try:
        repos.add_article(token=token, title=title)
        return jsonify({"message": "添加成功", "token": token, "title": title})
    except sqlite3.IntegrityError:
        return jsonify({"error": "该文章已存在"}), 409


@app.route("/api/articles/<token>", methods=["DELETE"])
def api_articles_delete(token: str):
    """删除文章"""
    repos.delete_article(token)
    return jsonify({"message": "删除成功"})


@app.route("/api/articles/table")
def api_articles_table():
    """获取文章列表 + 每篇文章的最新数据，用于可排序表格"""
    rows = repos.list_articles_with_latest_stats()
    return jsonify(services.append_click_rate(rows))


@app.route("/api/config", methods=["GET"])
def api_config_get():
    """获取系统配置"""
    return jsonify(repos.get_config_dict())


@app.route("/api/config", methods=["PUT"])
def api_config_update():
    """更新系统配置"""
    data = request.get_json() or {}

    merged_config = repos.get_config_dict()
    for key, value in data.items():
        merged_config[key] = str(value)

    validation = services.validate_auth_config(merged_config)
    if not validation.get("ok") and validation.get("code") in ("missing_auth", "unauthorized"):
        return jsonify({"error": validation.get("message"), "validation": validation}), 400

    repos.upsert_config_values(data)
    return jsonify({"message": "配置已更新", "validation": validation})


def main() -> None:
    print("=============================================")
    print("  知乎数据监控工具 v2.0 (Web 版)")
    print(f"  访问 {LOCAL_URL} 打开控制面板")
    print("=============================================\n")

    repos.init_db()
    repos.migrate_from_config_json()

    scheduler = services.SchedulerRunner()
    scheduler.start()

    webbrowser.open(LOCAL_URL)
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()

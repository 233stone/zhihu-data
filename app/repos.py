import json
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any


def _get_data_dir() -> str:
    """获取数据目录：打包后为 exe 所在目录，开发时为项目目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


DB_PATH = os.path.join(_get_data_dir(), "zhihu_data.db")

DEFAULT_CONFIG = {
    "interval_minutes": "10",
    "request_delay_seconds": "5",
    "cookie": "",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "x_zse_93": "101_3_3.0",
    "x_zse_96": "",
}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
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
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS article_total_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_time DATETIME,
            token TEXT,
            title TEXT,
            total_pv INTEGER,
            total_show INTEGER,
            total_upvote INTEGER,
            total_comment INTEGER,
            total_collect INTEGER,
            total_share INTEGER,
            finish_read_percent TEXT,
            positive_interact_percent TEXT,
            follower_translate INTEGER
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    for key, value in DEFAULT_CONFIG.items():
        cursor.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()
    conn.close()


def migrate_from_config_json(config_path: str = "") -> None:
    """如果存在旧的 config.json，自动导入其数据到数据库"""
    if not config_path:
        config_path = os.path.join(_get_data_dir(), "config.json")
    if not os.path.exists(config_path):
        return

    print("[迁移] 检测到 config.json，正在导入到数据库...")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            old_config: dict[str, Any] = json.load(f)

        conn = get_db_connection()

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
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )

        for article in old_config.get("articles", []):
            token = article.get("token", "")
            title = article.get("title", "")
            if token:
                conn.execute(
                    "INSERT OR IGNORE INTO articles (token, title) VALUES (?, ?)",
                    (token, title),
                )

        conn.commit()
        conn.close()

        os.rename(config_path, config_path + ".bak")
        print("[迁移] 完成！旧文件已重命名为 config.json.bak")
    except Exception as e:
        print(f"[迁移] 失败: {e}")


def get_config_dict() -> dict[str, str]:
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


def upsert_config_values(data: dict[str, str]) -> None:
    conn = get_db_connection()
    for key, value in data.items():
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
    conn.commit()
    conn.close()


def list_articles_basic() -> list[dict[str, str]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT token, title FROM articles").fetchall()
    conn.close()
    return [{"token": row["token"], "title": row["title"]} for row in rows]


def list_articles() -> list[dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_article(token: str, title: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO articles (token, title) VALUES (?, ?)", (token, title))
        conn.commit()
    finally:
        conn.close()


def delete_article(token: str) -> None:
    conn = get_db_connection()
    conn.execute("DELETE FROM articles WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def list_articles_with_latest_stats() -> list[dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        WITH latest_daily_stats AS (
            SELECT st.* FROM article_stats st
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                GROUP BY token
            ) latest ON st.token = latest.token AND st.fetch_time = latest.max_time
        ),
        latest_total_stats AS (
            SELECT st.* FROM article_total_stats st
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_total_stats
                GROUP BY token
            ) latest ON st.token = latest.token AND st.fetch_time = latest.max_time
        ),
        latest_daily_per_date AS (
            SELECT st.* FROM article_stats st
            INNER JOIN (
                SELECT token, today_date, MAX(fetch_time) as max_time
                FROM article_stats
                WHERE today_date <> ''
                GROUP BY token, today_date
            ) latest ON st.token = latest.token
                AND st.today_date = latest.today_date
                AND st.fetch_time = latest.max_time
        ),
        fallback_total_stats AS (
            SELECT token,
                   SUM(today_pv) AS total_pv,
                   SUM(today_show) AS total_show,
                   SUM(today_upvote) AS total_upvote,
                   SUM(today_comment) AS total_comment,
                   SUM(today_collect) AS total_collect,
                   SUM(today_share) AS total_share
            FROM latest_daily_per_date
            GROUP BY token
        )
        SELECT a.token, a.title,
               COALESCE(t.total_pv, f.total_pv, d.today_pv, 0) AS total_pv,
               COALESCE(t.total_show, f.total_show, d.today_show, 0) AS total_show,
               COALESCE(t.total_upvote, f.total_upvote, d.today_upvote, 0) AS total_upvote,
               COALESCE(t.total_comment, f.total_comment, d.today_comment, 0) AS total_comment,
               COALESCE(t.total_collect, f.total_collect, d.today_collect, 0) AS total_collect,
               COALESCE(t.total_share, f.total_share, d.today_share, 0) AS total_share,
               COALESCE(t.finish_read_percent, d.finish_read_percent, '') AS finish_read_percent,
               COALESCE(t.positive_interact_percent, d.positive_interact_percent, '') AS positive_interact_percent,
               COALESCE(t.fetch_time, d.fetch_time) AS fetch_time
        FROM articles a
        LEFT JOIN latest_daily_stats d ON a.token = d.token
        LEFT JOIN latest_total_stats t ON a.token = t.token
        LEFT JOIN fallback_total_stats f ON a.token = f.token
        ORDER BY a.created_at DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def insert_article_stats(record: dict[str, Any]) -> None:
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO article_stats (
            fetch_time, token, title,
            today_date, today_pv, today_show, today_upvote, today_comment, today_collect, today_share,
            today_incr_upvote, today_desc_upvote, finish_read_percent, positive_interact_percent, follower_translate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get("fetch_time"),
            record.get("token"),
            record.get("title"),
            record.get("today_date"),
            record.get("today_pv"),
            record.get("today_show"),
            record.get("today_upvote"),
            record.get("today_comment"),
            record.get("today_collect"),
            record.get("today_share"),
            record.get("today_incr_upvote"),
            record.get("today_desc_upvote"),
            record.get("finish_read_percent"),
            record.get("positive_interact_percent"),
            record.get("follower_translate"),
        ),
    )
    conn.commit()
    conn.close()


def insert_article_total_stats(record: dict[str, Any]) -> None:
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO article_total_stats (
            fetch_time, token, title,
            total_pv, total_show, total_upvote, total_comment, total_collect, total_share,
            finish_read_percent, positive_interact_percent, follower_translate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get("fetch_time"),
            record.get("token"),
            record.get("title"),
            record.get("total_pv"),
            record.get("total_show"),
            record.get("total_upvote"),
            record.get("total_comment"),
            record.get("total_collect"),
            record.get("total_share"),
            record.get("finish_read_percent"),
            record.get("positive_interact_percent"),
            record.get("follower_translate"),
        ),
    )
    conn.commit()
    conn.close()


def get_latest_stats_rows() -> list[dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT s.* FROM article_stats s
        INNER JOIN (
            SELECT token, MAX(fetch_time) as max_time
            FROM article_stats
            GROUP BY token
        ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
        ORDER BY s.today_pv DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_summary_rows(date_filter: str, token: str = "") -> list[dict[str, Any]]:
    conn = get_db_connection()
    if token:
        rows = conn.execute(
            """
            SELECT s.* FROM article_stats s
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                WHERE today_date = ? AND token = ?
                GROUP BY token
            ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
            """,
            (date_filter, token),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT s.* FROM article_stats s
            INNER JOIN (
                SELECT token, MAX(fetch_time) as max_time
                FROM article_stats
                WHERE today_date = ?
                GROUP BY token
            ) latest ON s.token = latest.token AND s.fetch_time = latest.max_time
            """,
            (date_filter,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trend_rows(days: int, token: str = "") -> list[dict[str, Any]]:
    limit = max(days, 1) * 144
    conn = get_db_connection()

    if token:
        rows = conn.execute(
            """
            SELECT fetch_time, today_date, today_pv, today_upvote, today_collect, today_share, today_show,
                   finish_read_percent, positive_interact_percent
            FROM article_stats
            WHERE token = ?
            ORDER BY fetch_time DESC
            LIMIT ?
            """,
            (token, limit),
        ).fetchall()
        conn.close()
        result = [dict(row) for row in rows]
        result.reverse()
        return result

    interval_row = conn.execute(
        "SELECT value FROM config WHERE key = 'interval_minutes'"
    ).fetchone()
    try:
        bucket_minutes = int((interval_row["value"] if interval_row else "10") or 10)
    except ValueError:
        bucket_minutes = 10
    bucket_minutes = max(1, min(60, bucket_minutes))

    raw_limit = limit * 20
    rows = conn.execute(
        """
        SELECT fetch_time, token, today_date, today_pv, today_upvote, today_collect, today_share, today_show
        FROM article_stats
        ORDER BY fetch_time DESC
        LIMIT ?
        """,
        (raw_limit,),
    ).fetchall()
    conn.close()

    # Keep only the newest fetch for each article within each time bucket.
    latest_per_bucket_token: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        try:
            fetch_dt = datetime.strptime(row["fetch_time"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue

        bucket_minute = (fetch_dt.minute // bucket_minutes) * bucket_minutes
        bucket_dt = fetch_dt.replace(minute=bucket_minute, second=0, microsecond=0)
        bucket_key = bucket_dt.strftime("%Y-%m-%d %H:%M")
        token_key = row["token"] or ""
        dedup_key = (bucket_key, token_key)

        if dedup_key in latest_per_bucket_token:
            continue

        latest_per_bucket_token[dedup_key] = {
            "token": token_key,
            "fetch_time": bucket_key,
            "today_date": row["today_date"] or bucket_key.split(" ")[0],
            "today_pv": row["today_pv"] or 0,
            "today_upvote": row["today_upvote"] or 0,
            "today_collect": row["today_collect"] or 0,
            "today_share": row["today_share"] or 0,
            "today_show": row["today_show"] or 0,
        }

    rows_by_bucket: dict[str, list[dict[str, Any]]] = {}
    for row in latest_per_bucket_token.values():
        rows_by_bucket.setdefault(row["fetch_time"], []).append(row)

    result: list[dict[str, Any]] = []
    last_seen_by_token: dict[str, dict[str, Any]] = {}
    current_date = ""

    for bucket_key in sorted(rows_by_bucket.keys()):
        bucket_date = bucket_key.split(" ")[0]
        if bucket_date != current_date:
            current_date = bucket_date
            last_seen_by_token = {}

        for row in rows_by_bucket[bucket_key]:
            if not row["token"]:
                continue
            if row["today_date"] != bucket_date:
                continue
            last_seen_by_token[row["token"]] = row

        aggregated = {
            "fetch_time": bucket_key,
            "today_date": bucket_date,
            "today_pv": 0,
            "today_upvote": 0,
            "today_collect": 0,
            "today_share": 0,
            "today_show": 0,
        }
        for row in last_seen_by_token.values():
            aggregated["today_pv"] += row["today_pv"]
            aggregated["today_upvote"] += row["today_upvote"]
            aggregated["today_collect"] += row["today_collect"]
            aggregated["today_share"] += row["today_share"]
            aggregated["today_show"] += row["today_show"]

        if result and result[-1]["today_date"] == bucket_date:
            previous = result[-1]
            aggregated["today_pv"] = max(aggregated["today_pv"], previous["today_pv"])
            aggregated["today_upvote"] = max(aggregated["today_upvote"], previous["today_upvote"])
            aggregated["today_collect"] = max(aggregated["today_collect"], previous["today_collect"])
            aggregated["today_share"] = max(aggregated["today_share"], previous["today_share"])
            aggregated["today_show"] = max(aggregated["today_show"], previous["today_show"])

        result.append(aggregated)

    if len(result) > limit:
        result = result[-limit:]
    return result

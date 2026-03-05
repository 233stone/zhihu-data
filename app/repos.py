import json
import os
import sqlite3
from datetime import datetime
from typing import Any

DB_PATH = "zhihu_data.db"

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


def migrate_from_config_json(config_path: str = "config.json") -> None:
    """如果存在旧的 config.json，自动导入其数据到数据库"""
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
    else:
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
            SELECT fetch_time, today_date, today_pv, today_upvote, today_collect, today_share, today_show
            FROM article_stats
            ORDER BY fetch_time DESC
            LIMIT ?
            """,
            (raw_limit,),
        ).fetchall()
        conn.close()

        bucketed: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                fetch_dt = datetime.strptime(row["fetch_time"], "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue

            bucket_minute = (fetch_dt.minute // bucket_minutes) * bucket_minutes
            bucket_dt = fetch_dt.replace(minute=bucket_minute, second=0, microsecond=0)
            bucket_key = bucket_dt.strftime("%Y-%m-%d %H:%M")

            if bucket_key not in bucketed:
                bucketed[bucket_key] = {
                    "fetch_time": bucket_key,
                    "today_date": row["today_date"],
                    "today_pv": 0,
                    "today_upvote": 0,
                    "today_collect": 0,
                    "today_share": 0,
                    "today_show": 0,
                }

            bucketed[bucket_key]["today_pv"] += row["today_pv"] or 0
            bucketed[bucket_key]["today_upvote"] += row["today_upvote"] or 0
            bucketed[bucket_key]["today_collect"] += row["today_collect"] or 0
            bucketed[bucket_key]["today_share"] += row["today_share"] or 0
            bucketed[bucket_key]["today_show"] += row["today_show"] or 0

        result = sorted(bucketed.values(), key=lambda item: item["fetch_time"])
        if len(result) > limit:
            result = result[-limit:]
        return result

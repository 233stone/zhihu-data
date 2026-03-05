import threading
import time
from datetime import datetime
from typing import Any

import requests as http_requests

from app import repos

ZHIHU_AGGR_API = "https://www.zhihu.com/api/v4/creators/analysis/realtime/content/aggr"


def build_headers(config: dict[str, str]) -> dict[str, str]:
    headers = {
        "user-agent": config.get("user_agent", ""),
        "x-zse-93": config.get("x_zse_93", ""),
        "x-zse-96": config.get("x_zse_96", ""),
    }
    cookie = config.get("cookie", "")
    if cookie:
        headers["cookie"] = cookie
    return headers


def _build_aggr_url(token: str, end_date: str | None = None) -> str:
    date_str = end_date or datetime.now().strftime("%Y-%m-%d")
    return f"{ZHIHU_AGGR_API}?type=answer&token={token}&end={date_str}"


def _request_article_aggr(
    token: str,
    config: dict[str, str],
    timeout: int,
) -> http_requests.Response:
    url = _build_aggr_url(token)
    headers = build_headers(config)
    return http_requests.get(url, headers=headers, timeout=timeout)


def validate_auth_config(config: dict[str, str]) -> dict[str, Any]:
    """保存配置时校验 Cookie 与 x-zse-96 是否可用"""
    cookie = (config.get("cookie") or "").strip()
    x_zse_96 = (config.get("x_zse_96") or "").strip()

    if not cookie or not x_zse_96:
        return {
            "ok": False,
            "code": "missing_auth",
            "message": "Cookie 和 x-zse-96 不能为空，请补全后再保存。",
        }

    articles = repos.list_articles_basic()
    if not articles:
        return {
            "ok": True,
            "code": "skipped_no_article",
            "message": "当前没有监控文章，已保存配置，但暂时无法自动校验 Cookie / x-zse-96。",
        }

    test_token = articles[0]["token"]
    try:
        resp = _request_article_aggr(test_token, config, timeout=12)
    except Exception as e:
        return {
            "ok": False,
            "code": "network_error",
            "message": f"自动校验失败：{type(e).__name__}，请稍后重试。",
        }

    if resp.status_code == 200:
        return {
            "ok": True,
            "code": "ok",
            "message": "Cookie 和 x-zse-96 校验通过。",
        }

    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "code": "unauthorized",
            "message": f"Cookie 或 x-zse-96 可能无效（HTTP {resp.status_code}）。",
        }

    return {
        "ok": False,
        "code": "request_failed",
        "message": f"自动校验失败，知乎接口返回 HTTP {resp.status_code}。",
    }


def fetch_article_title(token: str, config: dict[str, str]) -> str | None:
    try:
        resp = _request_article_aggr(token, config, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("answer", {}).get("title") or None
    except Exception:
        return None


def fetch_and_store_article_stats(
    token: str,
    title: str,
    config: dict[str, str],
) -> bool:
    """抓取单篇文章数据并入库"""
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 正在抓取: {title}")
        response = _request_article_aggr(token, config, timeout=15)

        if response.status_code != 200:
            print(f"  -> [失败] 状态码: {response.status_code}")
            return False

        data = response.json()
        today = data.get("today") or {}
        advanced = today.get("advanced") or {}

        repos.insert_article_stats(
            {
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "token": token,
                "title": title,
                "today_date": today.get("p_date", ""),
                "today_pv": today.get("pv", 0),
                "today_show": today.get("show", 0),
                "today_upvote": today.get("upvote", 0),
                "today_comment": today.get("comment", 0),
                "today_collect": today.get("collect", 0),
                "today_share": today.get("share", 0),
                "today_incr_upvote": today.get("incr_upvote_num") or 0,
                "today_desc_upvote": today.get("desc_upvote_num") or 0,
                "finish_read_percent": advanced.get("finish_read_percent", ""),
                "positive_interact_percent": advanced.get(
                    "positive_interact_percent", ""
                ),
                "follower_translate": advanced.get("follower_translate", 0),
            }
        )

        print(
            f"  -> 入库成功 | {today.get('p_date', '')}: "
            f"阅读={today.get('pv', 0)}, 赞同={today.get('upvote', 0)}, 收藏={today.get('collect', 0)}"
        )
        return True
    except Exception as e:
        print(f"  -> [异常] {type(e).__name__}: {e}")
        return False


def _parse_percent(rate_text: str) -> float | None:
    if not rate_text or not rate_text.endswith("%"):
        return None
    try:
        return float(rate_text.replace("%", ""))
    except ValueError:
        return None


def calculate_summary(date_filter: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_pv = sum((row.get("today_pv") or 0) for row in rows)
    total_show = sum((row.get("today_show") or 0) for row in rows)
    total_upvote = sum((row.get("today_upvote") or 0) for row in rows)
    total_comment = sum((row.get("today_comment") or 0) for row in rows)
    total_collect = sum((row.get("today_collect") or 0) for row in rows)
    total_share = sum((row.get("today_share") or 0) for row in rows)

    finish_rates: list[float] = []
    for row in rows:
        parsed = _parse_percent(row.get("finish_read_percent") or "")
        if parsed is not None:
            finish_rates.append(parsed)

    avg_finish_rate = (
        f"{sum(finish_rates) / len(finish_rates):.2f}%" if finish_rates else "0%"
    )
    click_rate = f"{(total_pv / total_show * 100):.2f}%" if total_show > 0 else "0%"

    return {
        "date": date_filter,
        "total_pv": total_pv,
        "total_show": total_show,
        "total_upvote": total_upvote,
        "total_comment": total_comment,
        "total_collect": total_collect,
        "total_share": total_share,
        "avg_finish_rate": avg_finish_rate,
        "click_rate": click_rate,
        "article_count": len(rows),
    }


def append_click_rate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        pv = item.get("today_pv") or 0
        show = item.get("today_show") or 0
        item["click_rate"] = f"{(pv / show * 100):.2f}%" if show > 0 else "0%"
        result.append(item)
    return result


def _safe_int(value: str | None, default: int, min_value: int = 0) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, min_value)


class SchedulerRunner:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="zhihu-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _wait_seconds(self, seconds: int) -> bool:
        for _ in range(max(seconds, 0)):
            if self._stop_event.is_set():
                return False
            time.sleep(1)
        return True

    def _loop(self) -> None:
        # 启动后等待 5 秒再开始第一次抓取，让 Flask 先完成启动
        if not self._wait_seconds(5):
            return

        while not self._stop_event.is_set():
            try:
                config = repos.get_config_dict()
                articles = repos.list_articles_basic()
                delay = _safe_int(config.get("request_delay_seconds"), default=5)
                interval = _safe_int(config.get("interval_minutes"), default=10, min_value=1)

                if not articles:
                    print(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        "暂无监控文章，跳过本轮抓取"
                    )
                else:
                    print(
                        f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"开始第 {len(articles)} 篇文章的抓取..."
                    )
                    for index, article in enumerate(articles):
                        fetch_and_store_article_stats(
                            token=article["token"],
                            title=article["title"],
                            config=config,
                        )
                        is_last = index == len(articles) - 1
                        if not is_last and not self._wait_seconds(delay):
                            return

                print(f"等待 {interval} 分钟...\n")
                if not self._wait_seconds(interval * 60):
                    return
            except Exception as e:
                print(f"[调度异常] {e}")
                if not self._wait_seconds(60):
                    return

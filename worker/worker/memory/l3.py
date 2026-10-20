"""L3 全局记忆：历史帖向量库。写作前召回风格样例，发布后写回；被改写的帖子降权。"""
import sqlite3
from typing import Any

import sqlite_vec


class GlobalMemory:
    def __init__(self, con: sqlite3.Connection, embedder: Any, dims: int = 8) -> None:
        self._con = con
        self._embedder = embedder
        self._dims = dims
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS post_vec USING vec0("
            f"post_id INTEGER PRIMARY KEY, embedding float[{dims}])"
        )
        con.commit()

    def add(self, text: str, platform: str, title: str, body: str, edited: bool) -> int:
        cur = self._con.execute(
            "INSERT INTO post_archive(platform, title, body, edited_by_user) VALUES(?, ?, ?, ?)",
            (platform, title, body, int(edited)),
        )
        post_id = cur.lastrowid
        (vec,) = self._embedder.embed([text])
        self._con.execute(
            "INSERT INTO post_vec(post_id, embedding) VALUES(?, ?)",
            (post_id, sqlite_vec.serialize_float32(vec)),
        )
        self._con.commit()
        return post_id

    def recall(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        (query,) = self._embedder.embed([text])
        rows = self._con.execute(
            "SELECT post_id, distance FROM post_vec WHERE embedding MATCH ? AND k = ?",
            (sqlite_vec.serialize_float32(query), k * 2),
        ).fetchall()
        posts = {
            pid: {"platform": platform, "title": title, "body": body, "edited": bool(edited)}
            for pid, platform, title, body, edited in self._con.execute(
                "SELECT post_id, platform, title, body, edited_by_user FROM post_archive"
            )
        }
        ranked = sorted(
            ((posts[pid], dist) for pid, dist in rows),
            key=lambda item: (item[0]["edited"], item[1]),  # 未改写优先，其次距离
        )
        return [dict(p, distance=dist) for p, dist in ranked[:k]]

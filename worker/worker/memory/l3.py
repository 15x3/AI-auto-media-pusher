"""L3 全局记忆：历史帖向量库。写作前召回风格样例，发布后写回；被改写的帖子降权。"""
import sqlite3
from typing import TYPE_CHECKING, Any

import sqlite_vec

if TYPE_CHECKING:
    from worker.llm.client import Embedder


class GlobalMemory:
    def __init__(self, con: sqlite3.Connection, embedder: "Embedder", dims: int | None = None) -> None:
        self._con = con
        self._embedder = embedder
        probe = len(embedder.embed(["probe"])[0])
        if dims is not None and dims != probe:
            raise ValueError(f"embedder 维度 {probe} 与声明 dims={dims} 不符")
        dims = probe
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS post_vec USING vec0("
            f"post_id INTEGER PRIMARY KEY, embedding float[{dims}])"
        )
        con.commit()

    def add(self, text: str, platform: str, title: str, body: str, edited: bool) -> int:
        (vec,) = self._embedder.embed([text])  # 先 embed：失败时未触碰任何写路径
        try:
            cur = self._con.execute(
                "INSERT INTO post_archive(platform, title, body, edited_by_user) VALUES(?, ?, ?, ?)",
                (platform, title, body, int(edited)),
            )
            post_id = cur.lastrowid
            self._con.execute(
                "INSERT INTO post_vec(post_id, embedding) VALUES(?, ?)",
                (post_id, sqlite_vec.serialize_float32(vec)),
            )
        except Exception:
            self._con.rollback()
            raise
        self._con.commit()
        return post_id

    def recall(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        (query,) = self._embedder.embed([text])
        # KNN 窗口放大到全库：edited 帖密集时 k*2 会把较远的未改写帖整批挡在窗口外
        total = self._con.execute("SELECT COUNT(*) FROM post_archive").fetchone()[0]
        rows = self._con.execute(
            "SELECT post_id, distance FROM post_vec WHERE embedding MATCH ? AND k = ?",
            (sqlite_vec.serialize_float32(query), max(k * 2, total)),
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

"""SQLite 单文件存储：L2 偏好 / L3 帖库 / 草稿 三组表的建库与连接。"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_pref (
    agent_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    UNIQUE(agent_id, key)
);
CREATE TABLE IF NOT EXISTS post_archive (
    post_id        INTEGER PRIMARY KEY,
    platform       TEXT NOT NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    edited_by_user INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS draft (
    draft_id    TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    images_json TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'pending_review',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con

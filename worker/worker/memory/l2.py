"""L2 Agent 记忆：按 Agent 持久化的配置与交互偏好。"""
import json
import sqlite3
from typing import Any


class AgentMemory:
    def __init__(self, con: sqlite3.Connection, agent_id: str) -> None:
        self._con = con
        self._agent = agent_id

    def set_pref(self, key: str, value: Any) -> None:
        self._con.execute(
            "INSERT INTO agent_pref(agent_id, key, value) VALUES(?, ?, ?) "
            "ON CONFLICT(agent_id, key) DO UPDATE SET value=excluded.value",
            (self._agent, key, json.dumps(value, ensure_ascii=False)),
        )
        self._con.commit()

    def get_prefs(self) -> dict[str, Any]:
        rows = self._con.execute(
            "SELECT key, value FROM agent_pref WHERE agent_id=?", (self._agent,)
        ).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def record_rejection(self, reason: str) -> None:
        rejections = self.get_prefs().get("rejections", [])
        rejections.append(reason)
        self.set_pref("rejections", rejections)

"""JSON-RPC 消息协议：请求/响应 + correlation id。"""
from dataclasses import dataclass, field
from itertools import count
from typing import Any

_IDS = count(1)


@dataclass
class Request:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int = field(default_factory=lambda: next(_IDS))

    def to_json(self) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}


@dataclass
class Response:
    id: int
    result: Any = None
    error: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Response":
        return cls(id=data["id"], result=data.get("result"), error=data.get("error"))

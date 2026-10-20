"""L1 工作记忆：单次流水线运行上下文，运行结束归档。"""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunContext:
    run_id: int
    topic: str | None = None
    draft_id: str | None = None
    recalled: list[dict[str, Any]] = field(default_factory=list)
    archived: dict[str, Any] | None = None

    def archive(self) -> dict[str, Any]:
        self.archived = asdict(self)
        self.archived.pop("archived", None)
        return self.archived

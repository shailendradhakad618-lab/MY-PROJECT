from dataclasses import dataclass, field
from typing import Any, Dict, List
@dataclass
class Intent:
    name: str = "unknown"
    confidence: float = 0.0
    entities: Dict[str, Any] = field(default_factory=dict)
    needs_web: bool = False
    needs_ai: bool = False
@dataclass
class Action:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    risky: bool = False
@dataclass
class TaskPlan:
    goal: str
    actions: List[Action] = field(default_factory=list)
    source: str = "local"

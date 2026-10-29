"""A procedure: numbered steps plus "this must happen before that" rules."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Step:
    id: str
    text: str


@dataclass
class Procedure:
    name: str
    steps: list[Step]
    rules: list[tuple[str, str]] = field(default_factory=list)  # (before, after) step ids

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)

    def describe(self) -> str:
        """Plain-text version for prompts."""
        lines = [f"Procedure: {self.name}", "", "Steps:"]
        lines += [f"- {s.id}: {s.text}" for s in self.steps]
        if self.rules:
            lines += ["", "Ordering rules (the first step must happen before the second):"]
            lines += [f"- {a} before {b}" for a, b in self.rules]
        return "\n".join(lines)

    def save(self, path: Path) -> None:
        data = {"name": self.name, "steps": [asdict(s) for s in self.steps], "rules": [list(r) for r in self.rules]}
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "Procedure":
        data = json.loads(path.read_text())
        steps = [Step(**s) for s in data["steps"]]
        ids = {s.id for s in steps}
        rules = [(a, b) for a, b in data.get("rules", [])]
        unknown = {x for rule in rules for x in rule} - ids
        if unknown:
            raise ValueError(f"{path}: rules mention unknown steps {sorted(unknown)}")
        return cls(name=data["name"], steps=steps, rules=rules)

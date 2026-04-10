"""
VerificationReport returned by the verifier agent.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class VerificationReport:
    passes: bool = True
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_issue(self, msg: str):
        self.issues.append(msg)
        self.passes = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def summary(self) -> str:
        if self.passes:
            return f"PASS — {len(self.warnings)} warning(s)"
        return f"FAIL — {len(self.issues)} issue(s), {len(self.warnings)} warning(s)"

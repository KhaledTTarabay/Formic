from typing import Literal

Status = Literal["open", "in_progress", "fixed", "wont_fix", "cannot_reproduce", "duplicate", "verified"]
Urgency = Literal["low", "normal", "high", "critical"]
BugType = Literal["bug", "crash", "regression", "test_failure", "build_failure", "performance", "security"]
Outcome = Literal["fixed","wont_fix","cannot_reproduce"]
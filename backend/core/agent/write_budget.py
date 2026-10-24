"""Per-turn write budget (CakeCRM `assistant/write_budget.py`, from Chatty's security module).

A BudgetState is created fresh for each turn and counts write tool calls, executed or proposed,
so one turn can never run away issuing unbounded writes: the first call over the limit is
refused, the next one ends the turn.
"""

from dataclasses import dataclass
from enum import Enum

WRITE_BUDGET_PER_TURN = 20


class BudgetAction(Enum):
    ALLOW = "allow"
    REJECT = "reject"
    TERMINATE = "terminate"


@dataclass
class BudgetState:
    limit: int = WRITE_BUDGET_PER_TURN
    writes_used: int = 0
    rejected_once: bool = False

    def check_write(self) -> BudgetAction:
        if self.writes_used < self.limit:
            self.writes_used += 1
            return BudgetAction.ALLOW
        if not self.rejected_once:
            self.rejected_once = True
            return BudgetAction.REJECT
        return BudgetAction.TERMINATE

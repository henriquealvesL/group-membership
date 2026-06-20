from dataclasses import dataclass
from typing import List, Tuple

Member = Tuple[str, int]  # (host, port)


@dataclass
class View:
    """
    Represents a consistent snapshot of the group composition.

    A sequence of views V0, V1, V2, ... is maintained over time.
    Each transition is caused by a join, a graceful leave, or a detected failure.

    Properties (from the slides):
      - Integrity:    a view is only installed by its own members
      - Initial view: V0 has a pre-defined set of members
      - Total order:  all processes install views in the same order
      - Agreement:    if one correct process installs view V, all correct ones do
      - Fairness:     transitions are caused only by join, leave, or failure events
    """

    view_id: int
    members: List[Member]

    # ── Derived properties ────────────────────────────────────────────

    def coordinator(self) -> Member:
        """
        The member with the lexicographically smallest (host, port) acts as
        coordinator for view changes. This is deterministic and requires no
        election — all processes compute the same result from the same view.
        """
        return min(self.members)

    def with_member(self, member: Member) -> "View":
        new_members = sorted(set(self.members) | {member})
        return View(self.view_id + 1, new_members)

    def without(self, member: Member) -> "View":
        new_members = [m for m in self.members if m != member]
        return View(self.view_id + 1, new_members)

    # ── Serialization ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {"view_id": self.view_id, "members": [list(m) for m in self.members]}

    @classmethod
    def from_dict(cls, d: dict) -> "View":
        return cls(d["view_id"], [tuple(m) for m in d["members"]])

    # ── Helpers ───────────────────────────────────────────────────────

    def __contains__(self, member: Member) -> bool:
        return member in self.members

    def __str__(self) -> str:
        members_str = ", ".join(f"{h}:{p}" for h, p in sorted(self.members))
        return f"View(id={self.view_id}, [{members_str}])"

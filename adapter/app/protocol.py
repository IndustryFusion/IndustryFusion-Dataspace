#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""The rules in protocol.md, as plain functions. The sender and the receiver both use these."""

from dataclasses import dataclass
from datetime import datetime

OPEN = "OPEN"
ESCALATING = "ESCALATING"
CLOSED_PREFIX = "CLOSED_"

REQUIRED, OPTIONAL, FORBIDDEN = "required", "optional", "forbidden"
FIELDS = ("capability", "in_reply_to", "authorization", "outcome")
VALIDITY = {
    "request": (OPTIONAL, OPTIONAL, FORBIDDEN, FORBIDDEN),
    "inform": (OPTIONAL, OPTIONAL, FORBIDDEN, FORBIDDEN),
    "grant": (REQUIRED, REQUIRED, REQUIRED, FORBIDDEN),
    "deny": (REQUIRED, REQUIRED, FORBIDDEN, FORBIDDEN),
    "cancel": (OPTIONAL, REQUIRED, FORBIDDEN, FORBIDDEN),
    "close": (FORBIDDEN, OPTIONAL, FORBIDDEN, REQUIRED),
    "reopen": (FORBIDDEN, OPTIONAL, FORBIDDEN, FORBIDDEN),
    "escalate": (FORBIDDEN, OPTIONAL, FORBIDDEN, FORBIDDEN),
    "deescalate": (FORBIDDEN, OPTIONAL, FORBIDDEN, FORBIDDEN),
}
OUTCOMES = {"resolved", "withdrawn", "rejected", "failed", "timed_out", "superseded", "escalated"}
NOT_REOPENABLE = {"escalated", "superseded"}
# These act on an existing conversation. Anything else can start one.
NEEDS_CONVERSATION = {"close", "reopen", "deescalate"}
# These can change a conversation's state, so they name the step they were based on.
STEPS = {"close", "escalate", "deescalate", "reopen"}


@dataclass(frozen=True)
class Invalid:
    reason: str
    detail: str


def _authorization_problem(authorization: object) -> str | None:
    if not isinstance(authorization, dict):
        return "authorization must be an object"
    if authorization.get("scope") != "conversation":
        return 'authorization.scope must be "conversation"'
    expires = authorization.get("expires_at")
    if expires is not None:
        try:
            datetime.fromisoformat(expires)
        except (TypeError, ValueError):
            return "authorization.expires_at must be a date-time"
    if not isinstance(authorization.get("constraints", {}), dict):
        return "authorization.constraints must be an object"
    return None


def check_validity(
    performative: str, capability: object, in_reply_to: object, authorization: object, outcome: object
) -> Invalid | None:
    """Why a message breaks the validity rules, or None if it doesn't."""
    rules = VALIDITY.get(performative)
    if rules is None:
        return Invalid("unknown_performative", f"There is no performative {performative[:100]!r}")
    values = (capability, in_reply_to, authorization, outcome)
    for name, rule, value in zip(FIELDS, rules, values, strict=True):
        present = value not in (None, "")
        if rule == REQUIRED and not present:
            return Invalid(f"{name}_required", f"{performative} requires {name}")
        if rule == FORBIDDEN and present:
            return Invalid(f"{name}_forbidden", f"{performative} does not allow {name}")
    if outcome not in (None, "") and outcome not in OUTCOMES:
        return Invalid("unknown_outcome", f"There is no outcome {str(outcome)[:100]!r}")
    if authorization not in (None, ""):
        problem = _authorization_problem(authorization)
        if problem:
            return Invalid("invalid_authorization", problem)
    return None


@dataclass(frozen=True)
class Decision:
    """What a message does to a conversation. A refused message has a reason."""

    applied: bool = True
    transition: str | None = None
    reason: str | None = None
    detail: str | None = None

    @property
    def refused(self) -> bool:
        return self.reason is not None


NO_CHANGE = Decision(applied=False)


def refuse(reason: str, detail: str) -> Decision:
    return Decision(applied=False, reason=reason, detail=detail)


def closed_state(outcome: str) -> str:
    return CLOSED_PREFIX + outcome.upper()


def decide(state: str, escalated_by: str | None, performative: str, sender: str, outcome: str | None) -> Decision:
    """Apply the state rules to one copy of a conversation."""
    if state == OPEN:
        if performative == "close":
            if outcome == "escalated":
                return refuse("escalation_required", "A close as escalated needs an escalate first")
            return Decision(transition="close")
        if performative == "escalate":
            return Decision(transition="escalate")
        if performative == "reopen":
            return NO_CHANGE
        if performative == "deescalate":
            return refuse("not_escalated", "The conversation is not escalated")
        return Decision()

    if state == ESCALATING:
        by_escalator = sender == escalated_by
        if performative == "escalate":
            return NO_CHANGE if by_escalator else refuse("already_escalated", "The other side has escalated this")
        if performative in {"close", "deescalate"}:
            if not by_escalator:
                return refuse("not_escalator", f"Only the escalator may {performative} this")
            return Decision(transition=performative)
        if performative == "reopen":
            return refuse("not_closed", "An escalated conversation is not closed")
        return Decision()

    if performative == "close":
        return NO_CHANGE
    if performative == "reopen":
        current = state.removeprefix(CLOSED_PREFIX).lower()
        if current in NOT_REOPENABLE:
            return refuse("reopen_not_allowed", f"A conversation closed as {current} can't be reopened")
        return Decision(transition="reopen")
    return refuse("conversation_closed", f"The conversation is {state}")

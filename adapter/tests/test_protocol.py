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
"""The rules in protocol.md, table by table, on their own and through the sender's and receiver's routes."""

import itertools

import pytest
from conftest import PEER, auth
from sqlalchemy import select

from app.db import Conversation, InboxMessage, OutboxMessage
from app.protocol import FIELDS, FORBIDDEN, OUTCOMES, REQUIRED, check_validity, decide

GRANT_AUTHORIZATION = {"scope": "conversation", "expires_at": "2026-12-01T10:00:00Z", "constraints": {}}
VALUES = {
    "capability": "twin:history",
    "in_reply_to": "m0",
    "authorization": GRANT_AUTHORIZATION,
    "outcome": "resolved",
}

# Written out from the table in protocol.md, and not taken from the code.
OPT, REQ, NOT = "optional", "required", "forbidden"
TABLE = {
    name: dict(zip(FIELDS, rules, strict=True))
    for name, rules in {
        "request": (OPT, OPT, NOT, NOT),
        "inform": (OPT, OPT, NOT, NOT),
        "grant": (REQ, REQ, REQ, NOT),
        "deny": (REQ, REQ, NOT, NOT),
        "cancel": (OPT, REQ, NOT, NOT),
        "close": (NOT, OPT, NOT, REQ),
        "reopen": (NOT, OPT, NOT, NOT),
        "escalate": (NOT, OPT, NOT, NOT),
        "deescalate": (NOT, OPT, NOT, NOT),
    }.items()
}
COMBINATIONS = [
    (performative, dict(zip(FIELDS, present, strict=True)))
    for performative in TABLE
    for present in itertools.product([False, True], repeat=len(FIELDS))
]


def expected_valid(performative: str, present: dict[str, bool]) -> bool:
    for name, rule in TABLE[performative].items():
        if rule == "required" and not present[name]:
            return False
        if rule == "forbidden" and present[name]:
            return False
    return True


def fields_for(present: dict[str, bool]) -> dict:
    return {name: VALUES[name] for name, here in present.items() if here}


@pytest.mark.parametrize("performative, present", COMBINATIONS)
def test_every_performative_against_every_field(performative, present):
    values = {name: VALUES[name] if here else None for name, here in present.items()}
    problem = check_validity(performative, **values)
    assert (problem is None) == expected_valid(performative, present), problem
    if problem:
        assert problem.reason.split("_")[-1] in {REQUIRED, FORBIDDEN}


@pytest.mark.parametrize("performative, present", COMBINATIONS)
def test_sender_route_applies_the_table(harness, performative, present):
    # A state violation is a different answer, so give what needs a conversation one to act on.
    harness.send(payload={}, conversation_id="c1")
    response = harness.send(performative=performative, conversation_id="c1", payload={}, **fields_for(present))
    if expected_valid(performative, present):
        assert response.status_code != 422, response.text
    else:
        assert response.status_code == 422, response.text
        body = response.json()
        assert set(body) == {"error", "reason", "detail", "performative"}
        assert body["error"] == "invalid_message"
        assert body["performative"] == performative


@pytest.mark.parametrize("performative, present", COMBINATIONS)
def test_receiver_route_applies_the_table(harness, performative, present):
    assert harness.notify("first", conversation_id="c1").status_code == 202
    response = harness.notify("m1", conversation_id="c1", performative=performative, **fields_for(present))
    if expected_valid(performative, present):
        assert response.status_code != 422, response.text
    else:
        assert response.status_code == 422, response.text
        assert response.json()["error"] == "invalid_message"


@pytest.mark.parametrize(
    "fields",
    [
        {"performative": "shout"},
        {"performative": "close", "outcome": "finished"},
        {"performative": "close", "outcome": "RESOLVED"},
    ],
)
def test_unknown_words_are_invalid(harness, fields):
    response = harness.send(payload={}, **fields)
    assert response.status_code == 422
    assert response.json()["reason"] in {"unknown_performative", "unknown_outcome"}


@pytest.mark.parametrize(
    "authorization",
    [
        {},
        {"scope": "everything"},
        {"scope": "conversation", "expires_at": "tomorrow"},
        {"scope": "conversation", "expires_at": 12},
        {"scope": "conversation", "constraints": "none"},
    ],
)
def test_malformed_authorization_is_invalid(harness, authorization):
    response = harness.send(
        performative="grant", capability="twin:direct", in_reply_to="m0", authorization=authorization, payload={}
    )
    assert response.status_code == 422
    assert response.json()["reason"] in {"invalid_authorization", "authorization_required"}


@pytest.mark.parametrize(
    "authorization", [{"scope": "conversation"}, {"scope": "conversation", "expires_at": None, "constraints": {"a": 1}}]
)
def test_authorization_with_only_what_is_needed(authorization):
    assert check_validity("grant", "twin:direct", "m0", authorization, None) is None


def test_invalid_at_the_sender_stores_nothing(harness):
    response = harness.send(performative="grant", payload={"a": 1}, conversation_id="c1")
    assert response.status_code == 422
    assert harness.storage.objects == {}

    async def rows():
        async with harness.services.db.session() as session:
            sent = (await session.execute(select(OutboxMessage))).scalars().all()
            conversations = (await session.execute(select(Conversation))).scalars().all()
            return sent, conversations

    assert harness.run(rows) == ([], [])
    assert harness.world.notifications == []


def test_invalid_files_are_refused_like_messages(harness):
    for performative in ("grant", "close", "deny"):
        response = harness.client.post(
            "/outbox/files",
            data={"receiver_participant": PEER, "performative": performative},
            files=[("files", ("a", b"x"))],
            headers=auth(),
        )
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_message"
    assert harness.storage.objects == {}


def test_invalid_at_the_receiver_is_kept_for_audit(harness):
    response = harness.notify("bad", performative="grant", conversation_id="c1")
    assert response.status_code == 422

    async def row():
        async with harness.services.db.session() as session:
            return await session.get(InboxMessage, "bad"), await session.get(Conversation, "c1")

    stored, conversation = harness.run(row)
    assert (stored.status, stored.applied) == ("error", False)
    assert "capability_required" in stored.error_message
    assert conversation is None
    harness.settle()
    assert not hasattr(harness, "pushed_to")


S, OTHER = "urn:sender", "urn:other"
ORDINARY = ["request", "inform", "grant", "deny", "cancel"]
# (state, escalated by, performative, outcome) -> (applied, transition, reason)
STATE_TABLE = [
    *[("OPEN", None, name, None, True, None, None) for name in ORDINARY],
    ("OPEN", None, "close", "resolved", True, "close", None),
    ("OPEN", None, "close", "escalated", False, None, "escalation_required"),
    ("OPEN", None, "escalate", None, True, "escalate", None),
    ("OPEN", None, "deescalate", None, False, None, "not_escalated"),
    ("OPEN", None, "reopen", None, False, None, None),
    *[("ESCALATING", S, name, None, True, None, None) for name in ORDINARY],
    *[("ESCALATING", OTHER, name, None, True, None, None) for name in ORDINARY],
    ("ESCALATING", S, "close", "resolved", True, "close", None),
    ("ESCALATING", S, "close", "escalated", True, "close", None),
    ("ESCALATING", OTHER, "close", "resolved", False, None, "not_escalator"),
    ("ESCALATING", OTHER, "close", "escalated", False, None, "not_escalator"),
    ("ESCALATING", S, "deescalate", None, True, "deescalate", None),
    ("ESCALATING", OTHER, "deescalate", None, False, None, "not_escalator"),
    ("ESCALATING", S, "escalate", None, False, None, None),
    ("ESCALATING", OTHER, "escalate", None, False, None, "already_escalated"),
    ("ESCALATING", S, "reopen", None, False, None, "not_closed"),
    ("ESCALATING", OTHER, "reopen", None, False, None, "not_closed"),
    *[
        row
        for outcome in sorted(OUTCOMES)
        for row in (
            *[(f"CLOSED_{outcome.upper()}", None, name, None, False, None, "conversation_closed") for name in ORDINARY],
            (f"CLOSED_{outcome.upper()}", None, "close", "resolved", False, None, None),
            (f"CLOSED_{outcome.upper()}", None, "close", outcome, False, None, None),
            (f"CLOSED_{outcome.upper()}", None, "escalate", None, False, None, "conversation_closed"),
            (f"CLOSED_{outcome.upper()}", None, "deescalate", None, False, None, "conversation_closed"),
            (
                f"CLOSED_{outcome.upper()}",
                None,
                "reopen",
                None,
                outcome not in {"escalated", "superseded"},
                "reopen" if outcome not in {"escalated", "superseded"} else None,
                "reopen_not_allowed" if outcome in {"escalated", "superseded"} else None,
            ),
        )
    ],
]


@pytest.mark.parametrize("state, escalated_by, performative, outcome, applied, transition, reason", STATE_TABLE)
def test_every_performative_against_every_state(
    state, escalated_by, performative, outcome, applied, transition, reason
):
    decision = decide(state, escalated_by, performative, S, outcome)
    assert (decision.applied, decision.transition, decision.reason) == (applied, transition, reason)


def test_the_state_table_covers_every_performative_in_every_state():
    seen = {(row[0], row[2]) for row in STATE_TABLE}
    states = {"OPEN", "ESCALATING", *{f"CLOSED_{outcome.upper()}" for outcome in OUTCOMES}}
    assert seen == set(itertools.product(states, TABLE))

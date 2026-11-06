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
"""Crossing steps, failed notifications and forged steps. Message ids are fixed, so each order is always tested."""

import asyncio
import contextlib
import random

import httpx
import pytest
from conftest import PEER, auth
from test_two_sided import HOST, Mesh, Side, assert_same, settle
from test_two_sided import two_sided as two_sided_on_postgres

from app import delivery as delivery_module
from app.routes import outbox
from app.routes.outbox import OutgoingMessage, _accept

LOW, MIDDLE, HIGH, HIGHEST = (f"{digit * 8}-0000-4000-8000-000000000000" for digit in "1579")


def two_sided(scenario) -> None:
    if not HOST:
        pytest.skip("TEST_POSTGRES_HOST is not set")
    two_sided_on_postgres(scenario)


@contextlib.contextmanager
def message_ids(*ids: str):
    """The ids that the next accepted messages get, in order."""
    upcoming = iter(ids)
    real = outbox.uuid.uuid4
    outbox.uuid.uuid4 = lambda: next(upcoming)
    try:
        yield
    finally:
        outbox.uuid.uuid4 = real


def failing_notifications(side: Side, mesh: Mesh, times: int = 1, after_arrival: bool = False) -> None:
    """The next notifications from this side fail. With after_arrival, they arrive and only the answer is lost."""
    left = {"count": times}

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/transfer-request" and left["count"] > 0:
            left["count"] -= 1
            if after_arrival:
                await mesh.handle(request)
            raise httpx.ConnectError("the peer is restarting")
        return await mesh.handle(request)

    side.services.http._transport = httpx.MockTransport(handle)


def close(outcome: str = "resolved") -> dict:
    return {"conversation_id": "c", "performative": "close", "outcome": outcome}


async def opened(fo: Side, mb: Side) -> None:
    await fo.send(conversation_id="c")
    await settle(fo, mb)


async def applied_of(side: Side, message_id: str) -> bool:
    messages = (await side.conversation("c"))["messages"]
    return next(item["applied"] for item in messages if item["message_id"] == message_id)


def test_repeating_a_step_whose_notification_failed_sends_it_again():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        first = await fo.send(**close("superseded"))
        await settle(fo, mb)
        assert (await fo.status(first["message_id"]))["status"] == "error"
        assert (await fo.conversation("c"))["state"] == "CLOSED_SUPERSEDED"
        assert (await mb.conversation("c"))["state"] == "OPEN"

        again = await fo.send(**close("superseded"))
        assert again["applied"] is True
        await assert_same(fo, mb, "c", "CLOSED_SUPERSEDED", "superseded")
        assert (await fo.status(again["message_id"]))["status"] == "notified"
        assert await applied_of(fo, first["message_id"]) is False
        assert await applied_of(fo, again["message_id"]) is True
        assert await applied_of(mb, again["message_id"]) is True

    two_sided(scenario)


def test_a_repeat_can_change_the_outcome_of_a_step_that_never_arrived():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        await fo.send(**close("resolved"))
        await settle(fo, mb)
        again = await fo.send(**close("failed"))
        assert again["conversation_state"] == "CLOSED_FAILED"
        await assert_same(fo, mb, "c", "CLOSED_FAILED", "failed")

    two_sided(scenario)


def test_a_repeat_accepted_before_the_failure_replaces_the_step_when_its_turn_comes():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        first = await fo.send(**close("resolved"))
        again = await fo.send(**close("resolved"))
        assert again["applied"] is False
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        assert await applied_of(fo, first["message_id"]) is False
        assert await applied_of(fo, again["message_id"]) is True
        assert (await fo.status(again["message_id"]))["applied"] is True

    two_sided(scenario)


def test_a_repeat_after_a_lost_answer_takes_the_step_that_arrived():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh, after_arrival=True)
        first = await fo.send(**close("resolved"))
        await settle(fo, mb)
        assert (await fo.status(first["message_id"]))["status"] == "error"
        assert (await mb.conversation("c"))["state"] == "CLOSED_RESOLVED"

        again = await fo.send(**close("failed"))
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        assert (await fo.status(first["message_id"]))["status"] == "notified"
        assert await applied_of(fo, first["message_id"]) is True
        assert await applied_of(fo, again["message_id"]) is False

    two_sided(scenario)


def test_the_other_sides_step_wins_over_a_failed_one_whatever_the_ids():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        with message_ids(LOW, HIGH):
            lost = await fo.send(**close("resolved"))
            await settle(fo, mb)
            won = await mb.send(**close("withdrawn"))
        await assert_same(fo, mb, "c", "CLOSED_WITHDRAWN", "withdrawn")
        assert await applied_of(fo, lost["message_id"]) is False
        assert await applied_of(fo, won["message_id"]) is True

    two_sided(scenario)


def test_the_other_sides_step_wins_over_a_refused_one_whatever_the_ids(harness):
    harness.send(conversation_id="c1", payload={})
    harness.world.peer_status = 409
    with message_ids(LOW):
        assert (
            harness.send(performative="close", outcome="resolved", conversation_id="c1", payload={}).status_code == 202
        )
    status = harness.client.get(f"/outbox/messages/{LOW}/status", headers=auth()).json()
    assert status["status"] == "rejected"

    answer = harness.notify(HIGH, conversation_id="c1", performative="close", outcome="failed", based_on=None)
    assert answer.status_code == 202
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert conversation["state"] == "CLOSED_FAILED"
    messages = {item["message_id"]: item["applied"] for item in conversation["messages"]}
    assert (messages[LOW], messages[HIGH]) == (False, True)


@contextlib.contextmanager
def own_close_in_progress(harness, message_id: str):
    """This side's close is accepted, and its delivery is held at the connector for as long as this lasts."""
    release = []

    async def hold(_asset: str) -> None:
        await release[0].wait()

    async def make() -> None:
        release.append(asyncio.Event())

    async def go() -> None:
        release[0].set()

    harness.run(make)
    harness.send(conversation_id="c1", payload={})
    harness.connector.on_offer = hold
    try:
        with message_ids(message_id):
            harness.client.post(
                "/outbox/messages",
                json={
                    "receiver_participant": PEER,
                    "conversation_id": "c1",
                    "performative": "close",
                    "outcome": "resolved",
                },
                headers=auth(),
            )
        yield
    finally:
        harness.run(go)
        harness.settle()


def test_a_step_still_on_its_way_keeps_the_lower_id(harness):
    with own_close_in_progress(harness, MIDDLE):
        higher = harness.notify(HIGH, conversation_id="c1", performative="close", outcome="failed", based_on=None)
        assert (higher.status_code, higher.json()["applied"]) == (202, False)
        assert higher.json()["state_message_id"] == MIDDLE
        assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_RESOLVED"

        lower = harness.notify(LOW, conversation_id="c1", performative="close", outcome="withdrawn", based_on=None)
        assert (lower.status_code, lower.json()["applied"]) == (202, True)
        assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_WITHDRAWN"


def test_a_step_based_on_one_that_lost_changes_nothing(harness):
    with own_close_in_progress(harness, LOW):
        lost = harness.notify(HIGH, conversation_id="c1", performative="close", outcome="failed", based_on=None)
        assert lost.json()["applied"] is False
        follow = harness.notify(HIGHEST, conversation_id="c1", performative="reopen", based_on=HIGH)
        assert (follow.status_code, follow.json()["applied"]) == (202, False)
        assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_RESOLVED"


@pytest.mark.parametrize("fo_first", [True, False], ids=["fo-lower", "mb-lower"])
def test_close_and_reopen_crossing_a_close(fo_first):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        ids = (LOW, MIDDLE, HIGH) if fo_first else (MIDDLE, HIGH, LOW)
        mesh.held.clear()
        with message_ids(*ids):
            await fo.send(**close("resolved"))
            await fo.send(conversation_id="c", performative="reopen")
            await mb.send(**close("withdrawn"))
        mesh.held.set()
        if fo_first:
            await assert_same(fo, mb, "c", "OPEN")
            assert await applied_of(fo, HIGH) is False
            assert await applied_of(mb, HIGH) is False
        else:
            await assert_same(fo, mb, "c", "CLOSED_WITHDRAWN", "withdrawn")
            for side in (fo, mb):
                assert await applied_of(side, LOW) is True
                assert await applied_of(side, MIDDLE) is False
                assert await applied_of(side, HIGH) is False

    two_sided(scenario)


@pytest.mark.parametrize("fo_lower", [True, False], ids=["close-lower", "escalate-lower"])
def test_close_crossing_escalate(fo_lower):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        mesh.held.clear()
        with message_ids(*((LOW, HIGH) if fo_lower else (HIGH, LOW))):
            await fo.send(**close("resolved"))
            await mb.send(conversation_id="c", performative="escalate")
        mesh.held.set()
        if fo_lower:
            shown = await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
            assert shown["escalated_by"] is None
        else:
            shown = await assert_same(fo, mb, "c", "ESCALATING")
            assert shown["escalated_by"] == mb.participant
        statuses = [(await fo.status(LOW if fo_lower else HIGH))["status"]]
        statuses.append((await mb.status(HIGH if fo_lower else LOW))["status"])
        assert statuses == ["notified", "notified"]

    two_sided(scenario)


def test_a_later_step_on_the_branch_that_lost_is_void():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        mesh.held.clear()
        with message_ids(LOW, HIGH, HIGHEST):
            await fo.send(**close("resolved"))
            await mb.send(conversation_id="c", performative="escalate")
            await mb.send(**close("withdrawn"))
        mesh.held.set()
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        for side in (fo, mb):
            assert await applied_of(side, HIGH) is False
            assert await applied_of(side, HIGHEST) is False

    two_sided(scenario)


def test_a_late_refusal_does_not_lose_the_settlement():
    """The side that would have refused a step settles it instead, however late its answer gets recorded."""

    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        real_set = delivery_module.set_outbox
        release = asyncio.Event()

        async def slow(services, message_id, **values):
            if values.get("status") in {"rejected", "notified"} and services is fo.services:
                await release.wait()
            await real_set(services, message_id, **values)

        delivery_module.set_outbox = slow
        try:
            mesh.held.clear()
            with message_ids(LOW, MIDDLE, HIGH):
                await fo.send(**close("resolved"))
                await mb.send(conversation_id="c", performative="escalate")
                mesh.held.set()
                await asyncio.sleep(0.2)
                await mb.send(**close("withdrawn"))
            await asyncio.sleep(0.2)
        finally:
            release.set()
            await settle(fo, mb)
            delivery_module.set_outbox = real_set
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")

    two_sided(scenario)


def test_the_winners_failed_notification_does_not_split_them():
    """The other side already holds the winner, from the answer to its own notification."""

    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        release = asyncio.Event()
        real_offer = fo.services.connector.offer

        async def held_offer(asset: str, source: str) -> None:
            if asset == LOW:
                await release.wait()
            await real_offer(asset, source)

        fo.services.connector = type(fo.services.connector)(mesh)
        fo.services.connector.offer = held_offer
        failing_notifications(fo, mesh)
        with message_ids(LOW, HIGH):
            await fo.send(**close("resolved"))
            await mb.send(**close("withdrawn"))
        await mb.services.settle()
        assert (await mb.conversation("c"))["state"] == "CLOSED_RESOLVED"
        release.set()
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")

    two_sided(scenario)


STEP_CHOICES = [
    ("inform", {}),
    ("close", {"outcome": "resolved"}),
    ("close", {"outcome": "failed"}),
    ("reopen", {}),
    ("escalate", {}),
    ("deescalate", {}),
]


async def act(side: Side, chosen: random.Random, conversation: str) -> None:
    for _ in range(chosen.randint(1, 3)):
        performative, extra = chosen.choice(STEP_CHOICES)
        answer = await side.post(conversation_id=conversation, performative=performative, **extra)
        assert answer.status_code in {202, 409}, answer.text


@pytest.mark.parametrize("seed", [7, 11])
def test_random_crossing_steps_always_end_in_the_same_state(seed):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        chosen = random.Random(seed)
        mesh.varying_offers = True
        for number in range(40):
            conversation = f"f{number}"
            await fo.send(conversation_id=conversation)
            await settle(fo, mb)

            await asyncio.gather(act(fo, chosen, conversation), act(mb, chosen, conversation))
            await settle(fo, mb)
            first, second = await fo.conversation(conversation), await mb.conversation(conversation)
            for name in ("state", "outcome", "escalated_by"):
                assert first[name] == second[name], (name, first, second)
            for shown in (first, second):
                assert not [item for item in shown["messages"] if item["status"] in {"pending", "registered"}]

    two_sided(scenario)


@pytest.mark.parametrize("based_on", [None, "unset"], ids=["names-a-base", "no-base-field"])
def test_a_peer_cannot_rewrite_a_settled_close(harness, based_on):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    fields = {} if based_on == "unset" else {"based_on": based_on}
    answer = harness.notify("0", conversation_id="c1", performative="close", outcome="failed", **fields)
    assert (answer.status_code, answer.json()["applied"]) == (202, False)
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert (conversation["state"], conversation["outcome"]) == ("CLOSED_RESOLVED", "resolved")
    own = next(item for item in conversation["messages"] if item["performative"] == "close")
    assert own["applied"] is True


def test_a_peer_cannot_rewrite_a_settled_escalation(harness):
    harness.send(conversation_id="c1", performative="escalate", payload={})
    answer = harness.notify("0", conversation_id="c1", performative="escalate", based_on=None)
    assert (answer.status_code, answer.json()["applied"]) == (202, False)
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert conversation["escalated_by"] != PEER


def test_a_peers_own_earlier_step_cannot_be_rewritten_by_itself(harness):
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    assert (
        harness.notify("m2", conversation_id="c1", performative="close", outcome="resolved", based_on=None).status_code
        == 202
    )
    answer = harness.notify("0", conversation_id="c1", performative="close", outcome="failed", based_on=None)
    assert (answer.status_code, answer.json()["applied"], answer.json()["state_message_id"]) == (202, False, "m2")
    assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_RESOLVED"


def test_stating_not_applied_does_not_get_past_the_rules(harness):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    answer = harness.notify("late", conversation_id="c1", performative="inform", sender_applied=False)
    assert answer.status_code == 409
    assert answer.json()["reason"] == "conversation_closed"


def test_stating_not_applied_needs_a_conversation(harness):
    answer = harness.notify("orphan", conversation_id="never-opened", sender_applied=False)
    assert answer.status_code == 409
    assert answer.json()["reason"] == "conversation_not_found"
    assert harness.client.get("/conversations/never-opened", headers=auth()).status_code == 404


def test_a_third_party_learns_nothing_from_a_refusal(harness):
    third = "urn:test:third"
    harness.world.registered[third] = {"participant_id": third, "adapter_url": "http://third.test"}
    harness.world.compatible = [PEER, third]
    harness.send(conversation_id="secret", payload={})
    harness.send(conversation_id="secret", performative="close", outcome="rejected", payload={})
    answer = harness.notify("probe", sender=third, conversation_id="secret")
    assert answer.status_code == 409
    body = answer.json()
    assert (body["reason"], body["conversation_state"], body["closed_at"]) == ("counterpart_mismatch", None, None)
    assert "CLOSED" not in answer.text


@pytest.mark.parametrize("registered", [True, False], ids=["incompatible", "unregistered"])
def test_receiver_applies_the_role_rules(harness, registered):
    other = "urn:test:same-role"
    if registered:
        harness.world.registered[other] = {"participant_id": other, "adapter_url": "http://other.test"}
    pushes = []

    async def push(destination: str) -> None:
        pushes.append(destination)

    harness.connector.on_push = push
    answer = harness.notify("role", sender=other, conversation_id="new-one")
    harness.settle()
    assert answer.status_code == 403
    assert pushes == []
    assert harness.client.get("/inbox/messages/role", headers=auth()).status_code == 404
    assert harness.client.get("/conversations/new-one", headers=auth()).status_code == 404


def test_registry_outage_at_the_receiver_is_unavailable(harness):
    harness.world.registry_up = False
    assert harness.notify("m1").status_code == 503


def test_role_refusal_is_visible_to_the_sender(harness):
    harness.world.peer_status = 403
    message_id = harness.send(payload={}).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()["status"] == "rejected"


def test_content_cannot_be_pushed_to_a_refused_message(harness):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    assert harness.notify("refused", conversation_id="c1").status_code == 409
    assert harness.client.post("/internal/inbox-receive/refused", content=b'{"x": 1}').status_code == 404
    row = harness.client.get("/inbox/messages/refused", headers=auth()).json()
    assert (row["status"], row["applied"], row["payload"]) == ("error", False, None)


def test_a_failed_fetch_can_still_recover(harness):
    assert (
        harness.notify(
            "m1", conversation_id="c1", performative="close", outcome="failed", sender_applied=False
        ).status_code
        == 409
    )
    assert harness.notify("m0", conversation_id="c1").status_code == 202
    harness.connector.fetch_error = RuntimeError("no connection")
    assert harness.notify("m2", conversation_id="c1", sender_applied=False).status_code == 202
    harness.settle()
    assert harness.client.get("/inbox/messages/m2", headers=auth()).json()["status"] == "error"
    assert harness.client.post("/internal/inbox-receive/m2", content=b"{}").status_code == 200


def test_a_repeat_whose_state_differs_at_the_receiver_says_so(harness):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    harness.world.peer_answer = {
        "applied": False, "conversation_state": "OPEN", "outcome": None, "escalated_by": None,
        "state_message_id": "other",
    }  # fmt: skip
    repeat = harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={}).json()
    status = harness.client.get(f"/outbox/messages/{repeat['message_id']}/status", headers=auth()).json()
    assert status["applied"] is False
    assert "OPEN" in status["error_message"]


@pytest.mark.parametrize(
    "answer",
    [
        {"conversation_state": "OPEN"},
        {"state_message_id": "x", "conversation_state": "MADE_UP", "applied": False},
        {"state_message_id": "x", "conversation_state": "CLOSED_FAILED", "outcome": "resolved", "applied": False},
        {"state_message_id": "x", "conversation_state": "ESCALATING", "applied": False},
        ["not", "an", "object"],
    ],
)
def test_an_answer_that_makes_no_sense_changes_nothing(harness, answer):
    harness.world.peer_answer = answer
    response = harness.send(conversation_id="c1", performative="escalate", payload={})
    assert response.status_code == 202
    status = harness.client.get(f"/outbox/messages/{response.json()['message_id']}/status", headers=auth()).json()
    assert (status["status"], status["applied"], status["conversation_state"]) == ("notified", True, "ESCALATING")


def test_cancelling_accept_does_not_hold_up_the_queue_or_shutdown(harness):
    async def scenario() -> str:
        services = harness.services
        real_session = services.db.session

        class SlowCommit:
            def __init__(self) -> None:
                self.inner = real_session()

            async def __aenter__(self):
                session = await self.inner.__aenter__()
                commit = session.commit

                async def slow() -> None:
                    await asyncio.sleep(0.2)
                    await commit()

                session.commit = slow
                return session

            async def __aexit__(self, *details):
                return await self.inner.__aexit__(*details)

        services.db.session = SlowCommit
        body = OutgoingMessage(receiver_participant=PEER, conversation_id="cancelled", payload={})
        accepting = asyncio.create_task(_accept(services, body, "m", None, {"adapter_url": "http://peer.test"}, False))
        await asyncio.sleep(0.05)
        accepting.cancel()
        await asyncio.gather(accepting, return_exceptions=True)
        services.db.session = real_session
        await asyncio.wait_for(services.settle(), 3)
        return "settled"

    assert harness.run(scenario) == "settled"
    assert harness.world.notifications == []

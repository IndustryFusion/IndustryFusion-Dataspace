# Design

## Context

`gateway-api.md` is the agent contract, and `architecture.md` describes the adapter's flows. #9 adds tests for behaviour that is easy to get wrong: empty payloads, unregistered receivers, duplicates and status overwrites.

## Goals / Non-Goals

**Goals:**

- Two adapters exchange JSON both ways through real connectors.
- Each behaviour named in #9 has a dedicated test.

**Non-Goals:**

- Durable retries. Delivery runs as in-process background tasks, and `protocol.md` lists the limits.

## Decisions

**SQLAlchemy with asyncpg, and tables created at startup.** It is the stack `architecture.md` names. A monitor recreates missing tables every 15 seconds. Alternative: a migration tool, which adds a step at every start for a schema that is still settling.

**A small storage class over the S3 API, using boto3 in a worker thread.** Any S3-compatible store works, with only endpoint and credentials to set. Alternative: a store-specific client, which would tie the adapter to one product.

**One connector resource per message.** Each message gets an asset, a policy and a contract definition, as `architecture.md` describes. Alternative: one shared policy and contract, which saves calls but needs bookkeeping that #20 would redo.

**An empty payload is still stored as a JSON document.** `{}` is written like any other payload, so the data plane always finds an object to read and delivery follows one path. A missing payload is stored as JSON `null`, and the inbox shows `null`. Alternative: skipping the connector for empty messages, which `protocol.md` lists as a known limit rather than a feature, and which would add a second path.

**Inbox status updates are conditional.** Writes from the transfer flow only apply while the row isn't `received`, `acked` or `error`, so a late poll can't overwrite a message that arrived. The push handler is the only writer of `received`. Alternative: a lock around the whole flow, which would hold a transaction for up to 120 seconds.

**A duplicate `message_id` at the receiver returns `202` and does nothing.** A retried notification is safe, and the insert uses the primary key. Alternative: `409`, which the sender would record as a failure of a message that was in fact delivered.

**Failed notifications set the sender's status by cause.** A `4xx` answer means the receiver refused it, so the status is `rejected`. Anything else is `error`.

**Unit tests use SQLite and an in-memory store, and the end-to-end check uses real services.** Route and flow tests stay fast, and `scripts/message-exchange-check.py` runs two participants on the local cluster. Alternative: PostgreSQL in every test, which is slower and adds little for these queries.

**A local script sets up the two participants.** It creates databases, Keycloak clients and connector and adapter Deployments, the steps #14 automates. Alternative: waiting for #14, which would leave this change unproven.

## Architectural implications

None. Matches `architecture.md`. As `protocol.md` records, the routes the connector calls have no authentication, and #20 addresses this.

## Risks / Trade-offs

- [A restart strands messages in progress] → Known limit, listed in `protocol.md`.
- [Each message runs a full connector cycle, taking seconds] → Known limit, listed in `protocol.md`.
- [SQLite differs from PostgreSQL] → The end-to-end check runs on PostgreSQL.

## Open Questions

None.

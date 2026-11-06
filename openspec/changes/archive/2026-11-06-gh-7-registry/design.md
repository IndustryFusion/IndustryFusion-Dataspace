# Design

## Context

`architecture.md` describes the registry as a small service with its own database. `gateway-api.md` shows the record that agents see through the gateway.

## Goals / Non-Goals

**Goals:**

- One place for role rules, so adding a role changes one file.

**Non-Goals:**

- Authentication, in #20.

## Decisions

**One table with a JSON record.** The table holds `participant_id` and the record as JSONB. Fields can change without a migration while the record settles. Alternative: one column per field, which adds migrations for no query benefit, since lookups are by id or a scan of a small table.

**The role rules are a list of directed pairs, in code.** Compatibility is `(from_role, to_role)`, so a one-way rule is possible. Today both directions exist for `factory_owner` and `machine_builder`. Alternative: rules in the database, which would need an administration route nobody has asked for.

**Roles are stored as full IRIs.** A bare name, a `ds:` name and an IRI all store the same value, so comparisons have one form. The list filter accepts the same spellings. Alternative: storing what was sent, which would make comparison depend on spelling.

**The service starts without the database.** It answers `/health` immediately and retries the database every 5 seconds in the background. Other routes give `503` until it connects. Alternative: exiting and relying on restarts, which adds restart delays and noise during an ordered startup.

**Health is liveness only.** It does not depend on the database, so a database outage doesn't restart the pod. Alternative: including the database, which restarts pods without fixing anything.

**Direct SQL with a small store interface.** Two statements' worth of queries don't justify an ORM. API tests use an in-memory store, and persistence tests use a real PostgreSQL. Alternative: SQLite in tests, which has no JSONB and would test something else.

**A local Service with no Ingress.** This meets "no public route". The chart in #15 follows the same rule.

## Architectural implications

None. No conflict with `architecture.md`. The registry has no authentication, as #20 records.

## Risks / Trade-offs

- [No authentication] → Cluster-internal only, and #20 restricts it.
- [Records aren't checked against each other] → Duplicate URLs are the management API's concern, in #14.

## Open Questions

None.

# Tasks

## 1. Adapter

- [ ] 1.1 Add the catalogue and the two tables; verify tests for each role's capabilities, and a description matching each default
- [ ] 1.2 Add the access route; verify tests for `provider=`, `consumer=`, neither, both, unregistered, incompatible and an unreachable provider
- [ ] 1.3 Add the request routes; verify tests for each scenario in "Asking for access" and "Listing requests"
- [ ] 1.4 Add the decision route; verify tests for approve, deny with a note, repeat resolution and an unknown id
- [ ] 1.5 Add the policy route; verify tests for approve, deny, reset, repeated reset, and a consumer not allowed
- [ ] 1.6 Add the internal routes; verify tests for each credential and each scenario in "Internal routes"
- [ ] 1.7 Show concurrent requests store one row, and concurrent decisions have one winner; verify tests on PostgreSQL that fail with a read-then-write version

## 2. Gateway

- [ ] 2.1 Add the two peer routes; verify tests for each scenario, including that `X-Internal-Key` isn't passed on

## 3. Advisory

- [ ] 3.1 Verify by a two-sided test that a message naming a denied capability is delivered
- [ ] 3.2 Verify by a two-sided test that `grant` and `deny` messages leave approval records unchanged

## 4. Documents

- [ ] 4.1 Update `gateway-api.md` for `403` and `decision_note`; update `protocol.md`, `architecture.md` and `manifest.md` on advisory access; verify by reading against the delta specs

## 5. End to end

- [ ] 5.1 Extend `scripts/message-exchange-check.py` with request, approval, access check, denial and reset through both agent and internal routes, and an incompatible participant; verify on the local cluster
- [ ] 5.2 Verify the management API's own routes for reset. This needs #14
- [ ] 5.3 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive in a follow-up Pull Request with `Closes #13`.

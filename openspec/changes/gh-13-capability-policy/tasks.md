# Tasks

## 1. Adapter

- [x] 1.1 Add the catalogue and the two tables; verify tests for each role's capabilities, and a description matching each default
- [x] 1.2 Add the access route; verify tests for `provider=`, `consumer=`, neither, both, unregistered, incompatible and an unreachable provider
- [x] 1.3 Add the request routes; verify tests for each scenario in "Asking for access" and "Listing requests"
- [x] 1.4 Add the decision route; verify tests for approve, deny with a note, repeat resolution and an unknown id
- [x] 1.5 Add the policy route; verify tests for approve, deny, reset, repeated reset, and a consumer not allowed
- [x] 1.6 Add the internal routes; verify tests for each credential and each scenario in "Internal routes"
- [x] 1.7 Show concurrent requests store one row, and concurrent decisions have one winner; verify tests on PostgreSQL that fail with a read-then-write version

- [x] 1.8 Make a description follow the effective default; verify a test for each view
- [x] 1.9 Make a request racing a reset give a normal answer; verify a test on PostgreSQL
- [x] 1.10 Give `503` for an unusable answer from a provider; verify tests

## 2. Addressing

- [x] 2.1 Call the provider at its `adapter_url`, and give `503` when it has none; verify tests, including a provider that also has a `peer_notify_url`

## 3. Advisory

- [x] 3.1 Verify by a two-sided test that a message naming a denied capability is delivered
- [x] 3.2 Verify by a two-sided test that `grant` and `deny` messages leave approval records unchanged

## 4. Documents

- [x] 4.1 Update `gateway-api.md` for `403` and `decision_note`; update `protocol.md`, `architecture.md` and `manifest.md` on advisory access; verify by reading against the delta specs

- [x] 4.2 Record in `keycloak.md` and `design.md` what an unchecked audience means for a token sent to peers; verify by reading

## 5. End to end

- [x] 5.1 Extend `scripts/message-exchange-check.py` with request, approval, access check, denial and reset through both agent and internal routes, and an incompatible participant; verify on the local cluster
- [x] 5.2 Verify the management API's own routes for reset. This needs #14. Verified with `scripts/management-check.py` from #14 on a local cluster
- [x] 5.3 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive in a follow-up Pull Request with `Closes #13`.

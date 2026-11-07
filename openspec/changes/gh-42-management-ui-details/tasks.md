# Tasks

## 1. Management API

- [x] 1.1 Add `checked_at` and `response_ms` to `GET /api/health`; verify with tests for a healthy, a failing, a slow and an unconfigured component
- [x] 1.2 Add `conversation_id` to `GET /api/policy` entries; verify with a test of a decision made in a conversation and a default
- [x] 1.3 Read an external provider's capabilities through the gateway's peer route with the consumer's token, and give `unavailable_reasons` where that fails; verify with tests for one and two external sides, an unreachable gateway or adapter, a refused token, a consumer without a client, an answer of the wrong shape, no internal key sent, and no secret or token in the answer or the log
- [x] 1.4 Keep reads admin-only; verify with tests that `GET /api/policy` and the capability routes give `401` without a token and `403` with a token lacking the role, with no adapter or gateway call

## 2. Management UI

- [x] 2.1 Participants: addresses, "(external)", copy buttons and Refresh; verify with browser tests against a running management API, including that no secret is in the page until credentials are asked for
- [x] 2.2 Health: summary line, response times, time of the check and Refresh; verify with browser tests against a running management API, including a component going down and an unconfigured one
- [x] 2.3 Policies: classification and conversation columns, an external side's rows without actions, and the reason when it can't be read; verify with browser tests against a running management API
- [x] 2.4 Show the browser tests can fail; verify by running them against the UI without each change

## 3. End to end

- [ ] 3.1 Show an external participant's policies on the Policies screen with `scripts/external-demo.py` up, through the real gateway and adapter; verify on a local cluster. The API's answer was verified on a local cluster through the real gateway and adapter; the screen itself only with stand-ins

## 4. Documents

- [x] 4.1 Update `management-api.md`, `architecture.md` and `keycloak.md` for the new fields, the external read, its token and the issuer it needs; verify by reading them against the behaviour

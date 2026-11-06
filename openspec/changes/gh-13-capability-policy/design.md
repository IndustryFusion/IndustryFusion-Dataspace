# Design

## Context

`protocol.md` holds the catalogue and the status values, and `gateway-api.md` the agent routes. `architecture.md` lists the internal routes. The issue settles that access is advisory, that an incompatible role gets `403`, and that a decision's note is stored and returned.

## Goals / Non-Goals

**Goals:**

- A request, an approval and an access check work between two adapters.
- Nothing in the message path reads capability state, or writes it.
- Concurrent decisions on one request give one winner.

**Non-Goals:**

- Enforcement of any kind on messages.
- Management API routes (#14).

## Decisions

**State lives on the provider's adapter.** A consumer's adapter asks the provider's over the internal routes, with its own token. So `GET /capabilities/access?provider=` always shows what the provider holds. Alternative: a copy on each side, which adds a second state that can differ, for no gain while access is advisory.

**The catalogue is fixed in code, with descriptions that match the defaults.** A row in `capability_policies` exists only once a default has been changed, so the catalogue's value applies otherwise. `mb:confidential` is `auto`, and its description says it is available by default, as the issue requires. Alternative: seeding rows for each adapter on start, which needs a step to keep them current with the catalogue.

**One row per consumer and capability, with a uniqueness rule.** A repeated request returns the existing row, whatever its status, and a denied consumer asks again only after a reset. Concurrent requests create one row. Alternatives: a new row per request, which needs a rule for which row decides access; or a repeat request reopening a denial, which would let a consumer undo a provider's decision.

**A request for a capability the default already allows stores nothing.** It answers `202` with status `auto`, and `id: null`. Otherwise a pending row would replace `auto` as the effective status, and asking would reduce a consumer's access. Alternative: storing it anyway, as `protocol.md`'s table would then show `pending`.

**A capability the provider doesn't offer gives `404`.** `gateway-api.md` lists `404` for unknown things, and the issue doesn't name a status. Alternative: `422`, which suggests the request's form is at fault.

**A decision's note is `decision_note`.** A request already has `note`, from the consumer. The provider's goes in its own field, so neither replaces the other. It is returned by `PATCH`, by `GET /capabilities/requests`, by a repeated `POST /capabilities/requests`, and in the consumer's `GET /capabilities/access` entry. Alternative: one `note` field, which would lose the consumer's.

**Decide with one conditional update.** A decision changes a row only while it is `pending`, in one statement, and an answer of no rows then gives `404` or `409`. So concurrent decisions have one winner, and the winner's note is the one kept. Alternative: read, then write, which lets two decisions both succeed.

**`POST /capabilities/policy` overrides, and `reset` deletes the row.** Approve and deny apply whatever the row's status, as the provider acts on its own policy. Reset returns to the default, is safe to repeat, and works for a consumer no longer registered, so old rows can be cleared. Approve and deny need a registered, compatible consumer: `404` and `403`. Alternative: keeping a row with status `reset`, which adds a status the contract doesn't have.

**The management route follows the same rule for a decision.** `PATCH /internal/capabilities/approvals/{id}` gives `409` for approve or deny on a resolved request, and `reset` always works. To change a decision, reset first, or use `POST /internal/capabilities/approvals` with a decision, which overrides as the agent's policy route does. Alternative: letting it overwrite, which makes one route's `409` depend on who calls.

**Who may call the internal routes.** `X-Internal-Key` allows everything, with a constant-time compare, and an empty configured key allows nothing. A peer token must be valid and hold the role for its own `participant_id`, and its role must be compatible with this adapter's. It may read only its own approvals, and may only `request`, for itself. `PATCH` routes need the key.

**The role check runs on both adapters.** The consumer's adapter checks before calling, as it does before sending. The provider's checks again, as a peer may run other software.

**`consumer=` makes no registry call.** It reads only this adapter's own data, and the issue uses it for a participant's own defaults too, so it works for any id. `provider=` checks registration and role, as it reaches another participant.

**Add two narrow peer routes to the gateway.** A participant's `peer_notify_url` is the gateway's peer route, so a capability call to that address must land on the provider's adapter. `GET /peer/{receiver}/internal/capabilities` and `POST /peer/{receiver}/internal/capabilities/approvals` forward there, need a valid token, and never pass `X-Internal-Key`. The catch-all stays closed to `internal/*`. Alternative: always using `adapter_url`, which doesn't reach across a cluster boundary, and which #18 would have to change.

## Architectural implications

`architecture.md` describes the gateway as having two forwarding routes, and the peer route as "the one deliberate exception" to blocking `internal/*`. This adds two more paths to that one exception, for the same reason. The document is updated. The alternative above avoids this but needs revisiting in #18, so it is presented for review here.

`architecture.md` calls the dataspace "governed", and `manifest.md` already qualifies this. The change states plainly in both that the check is the sending application's.

## Risks / Trade-offs

- [A provider's adapter is down] → `provider=` and a request answer `503`. There is no cached answer.
- [Peers can read their own approvals with a token only] → Intended. `GET /api/participants/{id}/capabilities` showing other peers' requests publicly is a separate matter, tracked in #20.
- [An application doesn't check access] → A message naming a denied capability is delivered. This is the issue's decision, stated in the documents and in a test.

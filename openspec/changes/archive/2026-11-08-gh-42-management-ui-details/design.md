# Design

## Context

The management UI has three screens: Health, Participants and Policies (#16). Participants are listed in a table, with credentials shown in a panel when an administrator asks. `GET /api/policy` reads each hosted provider's capability state from its adapter with that participant's internal key, and lists an external provider under `unavailable` (#14, #18). An external adapter answers `GET /internal/capabilities` for a peer that presents its own participant token, with only that peer's approvals, and the gateway forwards `GET /peer/{receiver}/internal/capabilities` to it (#18). Policy and capability reads need an administrator (#20).

## Decisions

### Participants

The issue speaks of cards. The screen is a table, and stays one: each row is a participant's card. Each row gains:

- **Adapter** and **DSP** addresses, as the read returned them. Without admin mode a hosted participant's `adapter_url` is `null`, and its `dsp_url` too unless it is reachable, so the cell says "Not public". In admin mode the read has the token, and the whole record is shown.
- **(external)** after the id of a participant with `hosted` false.

The credentials panel gains a Copy button for the client id and one for the secret, which write that value to the clipboard and say so. They exist only while the panel shows credentials an administrator asked for, or that a registration returned. A **Refresh** button above the list reads it again, and shows the API's error if that fails.

### Health

`GET /api/health` gains:

- `checked_at`, the time the check started, in ISO 8601 with a time zone.
- `response_ms` on each component: the whole milliseconds its probe took, whether or not it succeeded. `null` for a component that isn't configured.

The screen shows a summary line, such as "5 of 6 components ok" with the overall status, the response time per row, "Checked at" with the local time, and a **Refresh** button that checks again at once. The 15-second refresh stays, and is restarted by a manual refresh, so two reads don't overlap.

Alternatives: timing in the UI, which measures the whole call rather than each component; a separate `summary` object in the answer, which the UI can work out from `components`.

### Policies

`GET /api/policy` entries gain `conversation_id`, from the approval the status comes from, and `null` for a default. `data_classification` is already in each entry. The table gains a **Classification** and a **Conversation** column.

### Reading an external provider's policies

For a pair where a provider is external, `GET /api/policy`:

1. Gets the client secret of the other side of the pair, the consumer, from Keycloak, with the caller's admin token. This is how `GET /api/participants/{id}/credentials` reads it.
2. Gets a token for the consumer from Keycloak, with the client-credentials grant.
3. Calls `GET {GATEWAY_URL}/peer/{provider}/internal/capabilities` with that token. The gateway forwards it to the provider's adapter, which answers with its capabilities and the consumer's approvals, as it would for that consumer's own adapter.

The token is used for this one read. It isn't kept, logged or returned. The internal key is never sent. The answer is used only if it has the documented shape.

Where any step fails, the provider stays in `unavailable`, and a new `unavailable_reasons` object maps its id to a short reason: the consumer has no client, the token was refused, the gateway or the adapter couldn't be reached, the adapter refused the token, or its answer couldn't be used. The reason never holds a secret, a token or an address. `unavailable` keeps its type, a list of ids, so a client that reads it today keeps working.

The screen shows an external provider's rows like any others, with no Approve, Deny or Reset, as the hub doesn't change an external participant's policy. Where one couldn't be read, the note names it with the reason.

Alternatives:

- **Calling the external adapter directly,** at its `adapter_url` or `peer_notify_url`. The issue asks for the read to go through the gateway, and the gateway is where the hub's other calls to peers already go.
- **Asking the consumer's hosted adapter, through its agent route `GET /capabilities/access?provider=`.** It works only for a hosted consumer, and a pair of two external participants has none. Its answer also drops the approval fields this view shows.
- **A management identity that adapters trust for reads.** Adapters would need to accept a new kind of caller, which is a change to every adapter, including external ones.

**Security.** This reads, with a participant's token, what that participant could read itself, and only with an administrator's token, which can already read that participant's secret. It adds no access an administrator doesn't have. It does mean the management API asks Keycloak for participant tokens, which `keycloak.md` will say. The external adapter sees a call from the consumer, as it would from the consumer's own adapter.

**Issuer.** The external adapter checks the token's issuer. The token comes from this service's `KEYCLOAK_URL`, so it is accepted where that gives the same issuer as the address the external adapter is configured with. Where it doesn't, the adapter refuses the token, and the reason says so. `management-api.md` will say this.

## Conflicts with existing documents and specs

- `management-api` "Policy view" still has scenarios that read a hosted pair, and capabilities, without a token, while `security-hardening` "Public management reads" and the code need an administrator. The modified requirement says admin token throughout, which is the behaviour today and what the issue asks to keep.
- `management-api.md` says an external side "is listed in `unavailable`". That becomes the case where it can't be read.
- `management-ui` "Policies screen", scenario "An external side", shows a note about the other side in admin mode. It now shows the other side's rows, or the reason.

## Risks

- **The external adapter can't be reached through the gateway** where the gateway can't reach it. That is the same path hosted adapters already use for notifications and capability calls to it, so a failure here means those fail too. The screen shows the reason.
- **One slow external adapter slows the policy view.** The read has the same timeout as the other calls to adapters, and the two directions of a pair are read at the same time.

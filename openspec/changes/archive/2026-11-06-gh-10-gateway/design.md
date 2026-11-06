# Design

## Context

`architecture.md` describes the gateway as routing only, and `gateway-api.md` lists its statuses. It holds no secrets and no state beyond caches.

## Goals / Non-Goals

**Goals:**

- A token reaches only its own participant's adapter.
- `internal/*` can't be reached through the catch-all route, however the path is written.

**Non-Goals:**

- Business rules, which belong in the adapter.

## Decisions

**Check the path after decoding and normalizing it.** The catch-all decodes percent-escapes, resolves `.` and `..`, and refuses anything whose first segment is `internal`, in any case. The normalized path is what gets forwarded. Alternative: a prefix check on the raw path, which `foo/../internal/x` or `%69nternal/x` would pass.

**Refetch signing keys once, on an unknown key or a failed signature.** A key rotation is picked up without a restart, and a bad token can't cause more than one fetch per request. Alternative: refetching on a timer, which leaves a window where valid tokens fail after a rotation.

**A signature failure with cached keys forces a refetch.** Rotation can reuse a key id, so an unknown id isn't the only sign. To keep bad tokens from causing a fetch per request, refetches are limited to one every 10 seconds. Alternative: refetching only on an unknown key id, which misses that case.

**The registry cache is per participant, for 30 seconds, and doesn't keep failures.** A removed participant keeps routing for up to 30 seconds, which `architecture.md` accepts. Alternative: no cache, which adds a registry call to every request.

**Forward the caller's `Authorization` header unchanged.** The adapter checks the token again, as `architecture.md` describes. Hop-by-hop headers aren't forwarded.

**Buffer bodies, with a 120 second timeout.** Simple, and enough for messages. Alternative: streaming, which #11 can adopt if file sizes need it.

**A local Service with a port-forward.** The end-to-end check talks only to the gateway and Keycloak. Peer notifications stay inside the cluster, using each participant's `adapter_url`. The peer route is covered by tests, and by a check on the local cluster that calls it directly. Its real use, with external participants, comes in #18.

## Architectural implications

None. Matches `architecture.md`.

## Risks / Trade-offs

- [A removed participant routes for up to 30 seconds] → Accepted. The adapter's own check still applies.
- [Bodies are held in memory] → Revisited in #11.

## Open Questions

None.

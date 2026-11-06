# Design

## Context

`gateway-api.md` defines the two routes, and `architecture.md` "Data Flow Detail" shows files following the same path as JSON: the sender's adapter stores them, and the connector's data plane reads them from `/internal/payload/{id}` and pushes them to `/internal/inbox-receive/{id}`. The gateway design for #10 left streaming to this change.

## Goals / Non-Goals

**Goals:**

- Several files go in, and the same bytes come out.
- A file near the limit does not need its size in memory in the gateway or adapter.
- The limit is one setting, documented, and refused with a clear status.

**Non-Goals:**

- Scanning or interpreting file content.
- Deploying an Ingress (#15).

## Decisions

**Stream in the gateway.** The request body is forwarded as it arrives, and the answer is returned as it arrives. Requests with a known length keep that length towards the adapter. Alternative: keep buffering and raise the pod's memory, which ties memory use to the largest upload times the number of uploads.

**Enforce the limit in the gateway and the adapter, with the same setting.** The gateway refuses a stated length over the limit before contacting the adapter, and counts bytes for a body with no stated length. The adapter counts as well, because the connector and other in-cluster callers don't pass through the gateway. Alternative: Ingress only, which leaves the services unprotected in any deployment without one.

**The limit counts the request body, including multipart framing.** It is simple to state and to check before parsing. Default 1 GiB, set by `MAX_UPLOAD_BYTES`. The ZIP sent onward adds a small overhead per file, so the receiving side allows a margin of 1 MiB plus the limit.

**Read the form inside the route, after authentication.** A route that declares file parameters has its body parsed before its dependencies run, so an unauthenticated caller could fill the disk. Reading the form by hand keeps authentication first. Alternative: declared `File` parameters, which are shorter but read the body first.

**Store the ZIP uncompressed.** Files are bundled with the `stored` method, so a large upload does not spend time compressing, and its size is known from its parts. Alternative: deflate, which saves space on the internal path only, at a cost for files that are already compressed.

**File names are reduced to a safe base name.** A name with a path keeps only its last part, control characters are removed, an empty name becomes `file-<n>`, and a repeated name gets a number. So nothing unpacks outside its folder, and no file replaces another. Alternative: refusing such uploads, which fails for clients that send a full path.

**Temporary files in the adapter, streaming to storage.** The form is read to temporary files, the ZIP is written to one, and storage reads from that. Received content goes to a temporary file before storage too. A pod needs temporary disk of about twice its largest upload. Alternative: holding parts in memory, which is what this change removes.

**A purged file message reads as `payload: null`, and keeps `has_files: true`.** `gateway-api.md` says `payload` is `null` when its content was purged. The download then gives `404`. So does a download before the content has arrived. `400` stays for a message with no files.

**Mark a file message by its stored name on the sender's side.** The outbox has no `has_files` column, and the `files/` key says what is needed: which media type to serve. Alternative: a new column, which needs a migration for no benefit.

## Architectural implications

None. This delivers what `architecture.md` "Data Flow Detail" describes.

The Ingress must allow the same body size. `gateway-api.md` says so for #15.

## Risks / Trade-offs

- [The transfer budget, `TRANSFER_BUDGET_SECONDS`, is 120 seconds by default] → A slow link can use it up on a large file, and the message then shows `error`. The end-to-end check measures a file at the limit, and the setting stays configurable.
- [An unauthenticated in-cluster caller can still push to `/internal/inbox-receive/{id}`] → Known limit, tracked in #20. The size limit applies there too, and the message must already exist.

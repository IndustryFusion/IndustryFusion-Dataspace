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

**Only the file routes have the large limit.** A declared JSON body is read whole into memory and parsed before a route's dependencies run, so before its token is checked. A large limit there let 500 MiB with no token take an adapter to 7.5 GiB. So `POST /outbox/messages` has `MAX_JSON_BYTES` (default 4 MiB), and every other adapter route that takes a body has a fixed 256 KiB. The check runs while reading and before parsing, with or without a stated length. The gateway applies `MAX_JSON_BYTES` to everything but `POST /outbox/files`. Alternatives: reading JSON by hand after authentication on every route, which loses declared models and still leaves a signed peer able to send a huge body; and a single small limit, which is too tight for a message or too loose for a control call.

**Validation errors don't repeat the input.** The standard validation body would echo what was sent, which made a 200 MiB request answer with 1.2 GB. The adapter's answers keep `loc`, `msg` and `type`. Identifying fields such as `receiver_participant` are limited to 512 characters, and refusals that name a value shorten it.

**A stored JSON message is no larger than the body that carried it.** It is written without escaping non-ASCII characters, so `é` stays 2 bytes and doesn't become 6. So a message under `MAX_JSON_BYTES` at the sender is under it at the receiver, which applies the same limit to any arrival without files, including a `content_ref` asset. Such content is read into memory when an agent reads the message, so it can't have the file limit. Alternative: a larger arrival limit, which would only move the problem to the read.

**Read the form inside the route, after authentication.** A route that declares file parameters has its body parsed before its dependencies run, so an unauthenticated caller could fill the disk. Reading the form by hand keeps authentication first. Alternative: declared `File` parameters, which are shorter but read the body first.

**Store the ZIP uncompressed.** Files are bundled with the `stored` method, so a large upload does not spend time compressing, and its size is known from its parts. Alternative: deflate, which saves space on the internal path only, at a cost for files that are already compressed.

**File names are reduced to a safe base name.** A name with a path keeps only its last part, where `/`, `\\` and `:` all separate parts, so a drive letter or an alternate data stream goes too. Control characters and trailing dots and spaces are removed, a name reserved on Windows such as `CON` gets a leading `_`, an empty name becomes `file-<n>`, and a repeated name gets a number. So nothing unpacks outside its folder, and no file replaces another. Alternative: refusing such uploads, which fails for clients that send a full path.

**Temporary files in the adapter, streaming to storage.** The form is read to temporary files, the ZIP is written to one, and storage reads from that. Received content goes to a temporary file before storage too. A pod needs temporary disk of about twice its largest upload. Alternative: holding parts in memory, which is what this change removes.

**Many small parts stay on disk too.** The form reader keeps a part in memory up to a size, 1 MiB by default, so 1000 parts just under that took an adapter to 1.1 GiB. Here a part moves to disk after 64 KiB, an upload has at most 256 files and 16 other fields, and such a field at most 64 KiB. That bounds memory for a form at about 17 MiB. Alternative: a cap on the number of parts alone, which either stays large or refuses real uploads.

**A purged file message reads as `payload: null`, and keeps `has_files: true`.** `gateway-api.md` says `payload` is `null` when its content was purged. The download then gives `404`. So does a download before the content has arrived. `400` stays for a message with no files.

**Mark a file message by its stored name on the sender's side.** The outbox has no `has_files` column, and the `files/` key says what is needed: which media type to serve. Alternative: a new column, which needs a migration for no benefit.

## Architectural implications

None. This delivers what `architecture.md` "Data Flow Detail" describes.

The Ingress must allow the same body size. `gateway-api.md` says so for #15.

## Risks / Trade-offs

- [The transfer budget, `TRANSFER_BUDGET_SECONDS`, is 120 seconds by default] → A slow link can use it up on a large file, and the message then shows `error`. The end-to-end check measures a file at the limit, and the setting stays configurable.
- [An unauthenticated in-cluster caller can still push to `/internal/inbox-receive/{id}`] → Known limit, tracked in #20. The size limit applies there too, and the message must already exist.

## Decisions after review

**JSON is stored compactly, and the size is checked.** The body limit can't by itself bound what is stored, as a number such as `1e5` is written back as `100000.0`. So the sender checks the stored size against `MAX_JSON_BYTES` and answers `413`, where it would otherwise tell the agent `notified` while the receiver refuses the content.

**A `content_ref` asset stays limited to `MAX_JSON_BYTES` on arrival.** The push itself is streamed to storage, so a larger limit would be safe at that point. But such a message has no files, so its content can only be read by `GET /inbox/messages`, which reads it into memory for every listing, and `download` gives `400`. Restoring 1 GiB there would make one message able to exhaust the adapter on each list. Alternative: serve such content through `download`, which changes the published contract, and is left to a maintainer.

**`authorization` is limited at the sender to 200 KiB.** It travels in the notification, which the receiver limits to 256 KiB, so a larger one would be accepted with `202` and then refused. Alternative: raise that route's limit to `MAX_JSON_BYTES`. Rejected, as it parses its body before checking the token.

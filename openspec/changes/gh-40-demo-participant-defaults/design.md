# Design

## Context

`POST /api/demo` reads `DEMO_PARTICIPANTS`, which is empty unless set. `POST /api/participants` treats a missing `externally_reachable` as `false`, and gives `422` for `true` where `GATEWAY_PEER_URL` or `DSP_GATEWAY_PEER_URL` isn't set (#18). The Helm chart sets both peer addresses by default, to the in-cluster gateway and DSP gateway. The IFRIC lookup needs `IFRIC_BACKEND_URL`, `IFRIC_READER_CLIENT_ID` and `IFRIC_READER_CLIENT_SECRET` (#17).

## Decisions

### The demo default

Unset or empty, `DEMO_PARTICIPANTS` means:

| `participant_id` | `participant_type` |
|---|---|
| `urn:demo:factory-owner` | `factory_owner` |
| `urn:demo:machine-builder` | `machine_builder` |
| `urn:demo:second-machine-builder` | `machine_builder` |

The first two are the ids the local environment already uses. The third lets a factory owner choose between two machine builders, so a pair isn't the only case the demo shows. `[]` means no demo participants, which is how an installation turns the demo off.

Empty means the default, rather than none, because the chart passes the value through as an empty string when it isn't set. Making empty mean none would need a chart change, and would still leave a fresh Helm install with no demo.

Alternatives:

- **Real IFRIC company ids**, so the demo shows company details. These are records in a registry this project doesn't control, and `keycloak.md` says other participant ids must never equal a real `company_ifric_id`. Using real ones for a demo would be the opposite.
- **Two participants**, as the local environment has. The issue asks for a third.

### The JSON form

A value whose first non-blank character is `[` is a JSON list. Each entry is an object with `participant_id` and `participant_type`, and optionally `externally_reachable`, a boolean. Other keys are refused, so a misspelt key is not silently ignored. Anything else is the `<id>=<type>,...` form, as today.

In both forms, each id has to pass the same check as `POST /api/participants`, each type has to be a known one, and no id may appear twice. Otherwise the service stops at start, logging one line that names `DEMO_PARTICIPANTS`, the entry and the problem, and exits with a non-zero status. It doesn't wait for `POST /api/demo` to find out, as a value that can't be used is a deployment mistake.

Alternatives: logging and starting with no demo, which hides the mistake until someone calls the route; refusing at the route, which leaves a running service with a broken setting.

### Reachable by default

`externally_reachable` left out of a hosted registration means `true`. Given explicitly, it is used as given. An external participant left without it is `false`, as the flag means nothing for it.

This applies to repeated registrations too: registering an existing hosted participant again without the flag makes it reachable, restarting its adapter and connector if it wasn't. A repeated registration states what the participant should be, and the UI always sends the flag. Alternative: keeping the stored value when the flag is left out. That makes the same request mean different things for new and existing participants.

**What this changes for hosted-only traffic.** #14 recorded that giving every hosted participant a `peer_notify_url` sends hosted traffic through the gateway for no reason, and #18 recorded that two reachable hosted participants talk through the public addresses, which must work inside the cluster too. Both now hold by default. With the chart's default peer addresses, those are the in-cluster gateway and DSP gateway, so this works, at the cost of one more hop for notifications, capability calls, pushed content and DSP traffic. An installation that wants the shorter path registers its hosted participants with `externally_reachable: false`. This is the behaviour the issue asks for. It is listed here so the maintainers can see the cost.

### Reachability that can't be had

Where a hosted participant is to be reachable, by default or by asking, and `GATEWAY_PEER_URL` or `DSP_GATEWAY_PEER_URL` isn't set, the registration goes ahead as not reachable. The record stored and returned has `externally_reachable: false`, `peer_notify_url: null` and the connector's own `dsp_url`. The answer adds `warnings`, a list of messages, here one saying the participant isn't reachable from outside and naming the setting that is missing. `POST /api/demo` returns the same per record. The warning isn't stored, and reads don't have it.

The record says `false` because that is what the participant is: what it announces is the connector's own address, and nothing outside can reach it. Storing `true` would make the reads and the external flows' documentation say something untrue.

Alternatives:

- **Storing `true` and announcing internal addresses.** The participant looks reachable and isn't, which #18 refused to allow.
- **Keeping `422` for an explicit `true`,** and downgrading only the default. The issue asks for registration to succeed where the addresses aren't configured, and a client can't tell the two cases apart in the answer.
- **A separate field such as `reachable`.** Adds a second flag with almost the same meaning to the published record.

`warnings` is a new field on the registration answer only. It is additive, and `management-api.md` gains it.

### The UI form

The registration form's "Reachable" box starts ticked, so the UI registers what the API does by default. The form still sends the value, so an administrator can untick it.

### The IFRIC reader's client id

`IFRIC_READER_CLIENT_ID` unset or empty means `dataspace-ifric-reader`, the client `keycloak.md` names. Empty means the default because the chart passes an empty string from the Secret when it isn't set. IFRIC now counts as configured with `IFRIC_BACKEND_URL` and `IFRIC_READER_CLIENT_SECRET`, and nothing is called without them.

### The local environment

`deploy/local/services.yaml` and `deploy/helm/values/environments/local.yaml` set two demo participants. They stop setting it, so the default applies there too.

## Conflicts with existing documents and specs

- `management-api` "Demo participants", scenario "None configured": empty now means the default, and `[]` means none.
- `management-api` "Registering a hosted participant", scenario "Reaching a hosted participant from outside", and `external-participants` "Addresses of a reachable hosted participant", scenarios "Not reachable" and "Peer address not configured": the default and the `422` change.
- `ifric-company-details`, scenario "Not configured": the client id no longer has to be set.
- `management-api.md` says reachability gives `422` without the peer addresses, and that `DEMO_PARTICIPANTS` is comma-separated. Both are updated.

## Risks

- **A participant that was not reachable becomes reachable when registered again** without the flag. Its adapter and connector restart. This only happens on a repeated registration, which is a deliberate act, and `management-api.md` says so.
- **Public peer addresses that don't work inside the cluster.** An installation that sets `participants.gatewayPeerUrl` to an address only reachable from outside now breaks traffic between its hosted participants, where before only reachable ones were affected. `deploy/README.md` already says these addresses have to work from both sides, and it will say so where the default is described.

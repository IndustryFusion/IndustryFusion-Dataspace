# Design

## Context

`architecture.md` draws the external flow, and `protocol.md` lists what crosses between adapters. Two things in those drawings don't hold as written, and both are settled here.

## Decisions

### Content pushed to a hosted adapter goes through the peer route

Transfers are `HttpData-PUSH`: the **provider's** connector posts the content to the destination that the consumer names. So when an external participant sends to a hosted one, the external connector has to reach the hosted adapter's `/internal/inbox-receive/{id}`. `architecture.md` calls that adapter internal-only, and the demo's NetworkPolicy blocks it. The drawing leaves this out.

A hosted adapter with a peer address names `{peer address}/internal/inbox-receive/{id}` as the destination, and the gateway forwards `POST /peer/{receiver}/internal/inbox-receive/{id}`.

A connector's data plane holds no Keycloak token, so the route can't ask for one, and it is on the public gateway. So the destination carries a **transfer token** in a header: a keyed hash of the message id, made with the receiver's own client secret. It lets its holder deliver that one message, and the receiver can check it with nothing stored. The provider sees it, and that is all it needs. The gateway refuses a request without the header, and the adapter checks its value whenever it is present. A call inside the cluster with no header is still accepted, as it is today, and #20 closes that.

Alternatives:

- **No token on the route.** It would open what #20 means to close, to the internet, on every installation with a public gateway.
- **Passing the receiver's own bearer token in the destination.** That widens the token exposure in `keycloak.md`.
- **A NetworkPolicy allowing the external connector to reach the adapter.** It only works in a demo, and defeats the point of it.
- **Pull instead of push,** through the connector's public port. It changes how every transfer works, for all participants.

### The peer route stays open to any valid token

Each new route checks a token, except inbound content as above, and leaves authorization to the adapter. The adapter already checks the caller on capability calls: a peer gets only its own approvals, and may only ask for itself. The gateway removes `X-Internal-Key` on every peer route, as the adapter treats that header as management, and a guess from outside must not reach it.

Only `GET .../internal/capabilities`, `POST .../internal/capabilities/approvals` and the two routes above are forwarded. Management's `PATCH` routes aren't. Alternative: a general forward of `/peer/{receiver}/internal/*`, which would expose whatever is added to the adapter later.

### What `externally_reachable` changes for a hosted participant

| Address | Not reachable | Reachable |
|---|---|---|
| `adapter_url` | The adapter | The adapter. Never the gateway, which would forward to itself |
| `peer_notify_url` | `null` | `{GATEWAY_PEER_URL}/peer/{id}` |
| `dsp_url` and the adapter's advertised DSP address | The connector | `{DSP_GATEWAY_PEER_URL}/{slug}/api/v1/dsp` |
| The connector's callback address | The connector | The same DSP gateway address |
| The connector's public base address | The connector | `{DSP_GATEWAY_PEER_URL}/{slug}/api/v1/public` |
| Where content is pushed | The adapter | Through the peer route |

Two reachable hosted participants also talk this way, so a deployment's public addresses have to work from inside the cluster too. Alternative: choosing an address per peer, which needs each side to know more about the other, and gives two paths to test.

A hosted participant needs `GATEWAY_PEER_URL`, and for its connector `DSP_GATEWAY_PEER_URL`, to be set for this. Setting `externally_reachable` while one is missing gives `422`, rather than a participant that looks reachable and isn't. Today it silently leaves `peer_notify_url` as `null`. A connector reads its address at start, so changing `externally_reachable` restarts its pod.

### The DSP gateway

A stateless path router, with `PARTICIPANTS_NAMESPACE` as its only setting. The slug must be eight hexadecimal characters, so it can't name another host. A path with a `..` segment, however it is written, is refused, so nothing can walk from the two allowed prefixes to the control or management ports. Bodies are streamed.

It doesn't consult the registry, so it can't tell whether a slug's participant is `externally_reachable`: exposing it exposes every hosted connector's DSP and public ports to whoever can reach the Ingress. DSP traffic is authorized by the connectors, and until #20 they use a mock identity and permit-all policies, so this is a real limit. It is stated in `architecture.md`. Alternative: looking each slug up, which needs a reverse index the registry doesn't have, and goes beyond "stateless".

### The demo

A template in `deploy/local` for one participant's namespace, and `scripts/external-demo.py up` and `down`. Each participant has its own PostgreSQL, SeaweedFS, adapter and connector, and registers through the management API with `hosted: false`. `REGISTRY_URL` is the management API's `/api`.

A NetworkPolicy allows egress only to its own namespace, DNS, the gateway, the DSP gateway, the management API, Keycloak, and the other demo participant. It allows ingress to the adapter and DSP ports only from the hosted participants' namespace and the other demo participant. It works at the level of addresses and ports, so "public routes" means those services: it can't tell one path on the management API from another, and that port also serves its admin routes, which check a token.

### The contract suite

`--local` runs the external flows if the demo is up, reaching the external adapters by port-forward, as an external agent calls its own adapter. It makes the suite's hosted participants reachable first, with a repeated registration. Without the demo the flows stay not run, with a line that says how to bring it up, because a run that deploys and removes namespaces itself would be slow and surprising. The workflow brings the demo up. Against another deployment, `--external-owner` and `--external-builder` take `url,id,secret`.

### Token exposure, stated and not changed

`keycloak.md` records that a peer can replay the bearer token it receives. External participants make this sharper in a specific way, and the documents now say so: a hosted adapter sends its token to an external adapter on every notification and capability call, and **the gateway is public**, so that peer can call the gateway with the token, from anywhere, as the hosted participant. That is the whole agent API: reading its inbox, sending in its name and changing its capability policy, until the token expires. The same holds between two external participants, at each other's adapters. Registering an external participant is therefore a decision to trust it with this, and the onboarding text says so.

## Conflicts

`architecture.md` says of the peer route that it is "the one deliberate exception" to blocking `internal/*`, and that "the only door" is route 1. #13 recorded that #18 would decide otherwise. This change updates the text.

`architecture.md` says of Direction 1 that the transfer needs no relay. The negotiation needs none, and the content does. This change updates the text.

`management-api.md` says a registration's `peer_notify_url` is `null` where `GATEWAY_PEER_URL` isn't set, by leaving it out. The change above makes that `422`.

## Risks

- [An external participant can name any `provider_dsp_url` in a notification, and a hosted connector will call it] → Known, and already true between hosted participants. Listed for #20, whose connector identity limits what such a call can achieve, and its NetworkPolicies limit where it can go.
- [Any hosted connector can be reached through an exposed DSP gateway] → Stated above. Hosted-only installations don't expose it.
- [Exposing the gateway exposes the content route] → It needs a valid transfer token for one message.

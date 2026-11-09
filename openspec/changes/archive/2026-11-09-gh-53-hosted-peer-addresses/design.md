# Design

## Context

`shown_to_agents` in `gateway/app/main.py` answers `GET /participants/compatible`:
- for a hosted peer, it sets `adapter_url` to null;
- it keeps `dsp_url` only if the peer is `externally_reachable`;
- it leaves an external peer's addresses as they are.

Since #40, management registers a hosted participant as reachable by default when `GATEWAY_PEER_URL` and `DSP_GATEWAY_PEER_URL` are set. Its record's `dsp_url` is then `<DSP_GATEWAY_PEER_URL>/<path>/api/v1/dsp`, its address on the DSP gateway. Without both settings, it is not reachable, and its record's `dsp_url` is the connector's own address, `http://connector-<slug>.<participants namespace>:8082/api/v1/dsp`, which the gateway hides.

The Helm charts always set both peer addresses, by default to the services' addresses in the cluster, so on the local cluster every hosted participant is reachable. `discovery` in `scripts/contract_test.py` still requires every hosted entry's `dsp_url` to be null, and fails.

The gateway behaves as the `api-gateway` spec says, so the test is what changes. The spec's scenario, "its `dsp_url` is null unless it is reachable", doesn't say what the address is when it is reachable. This change adds that.

## Decisions

The maintainer accepted the decisions below.

### What the check requires

For each hosted entry in `GET /participants/compatible`:

1. `adapter_url` is null.
2. If `externally_reachable` is false, `dsp_url` is null.
3. If `externally_reachable` is true, `dsp_url`:
   - starts with the DSP gateway peer address, followed by `/`;
   - has exactly one path segment after that;
   - ends with `/api/v1/dsp`.

Each failure names the entry's `participant_id` and the field. External entries aren't checked by this check, as before.

"An address that only works inside the hub" means any `dsp_url` that isn't under the configured DSP gateway peer address, such as the connector's own address or the adapter's. Rule 3 refuses both.

Alternatives:
- **Requiring the exact address, `<peer>/<sha256(id)[:8]>/api/v1/dsp`.** This is stricter, but ties the contract to how management names its routes, which `gateway-api.md` doesn't document. Rejected.
- **Only checking that `dsp_url` isn't a connector or adapter address.** The test would need to know every form of internal address. Rejected in favour of a positive rule.

### How the suite learns the DSP gateway peer address

- **`--local`:** the suite reads the `DSP_GATEWAY_PEER_URL` variable of the `management` Deployment in namespace `dataspace`, with `kubectl --kubeconfig .local/kubeconfig`, through `local_cluster.kubectl`. It acts only on the local cluster's own kubeconfig, never the default. Management uses the same variable to make the addresses, so the suite compares against exactly what produced them. If the variable is empty, no hosted participant can be reachable, and rule 3 can't apply. An entry that is reachable anyway fails.
- **Another deployment:** `--dsp-gateway-peer-url <url>` gives it. The operator knows it: it is `participants.dspGatewayPeerUrl` in the Helm values, or the DSP gateway's in-cluster address by default.
- **Neither:** rules 1 and 2 still run. Rule 3 is reported as `NOT RUN`, naming the option, in the same way the suite reports external flows it can't run. A run with reachable hosted peers and no address then shows that something wasn't checked, instead of passing silently.

Alternatives:
- **A route that publishes the peer address,** such as a field in management's `GET /api/health`. This changes product behaviour, which the issue rules out.
- **Reading it from the participant's own registry record.** That record's `dsp_url` is the value being checked, so the comparison would prove nothing.

### Both branches are checked

On a default local cluster, every hosted peer is reachable, so rule 2 has no entry to check in a normal run. It is covered in two ways:
- **`--self-test`** gets cases built from a sample entry, one for each wrong form:
  - an `adapter_url`;
  - a `dsp_url` while not reachable;
  - a `dsp_url` under another address, such as the connector's;
  - a `dsp_url` with more than one segment or without `/api/v1/dsp`.
  Each must be refused, and the valid reachable and not-reachable entries must pass. Self-test runs in CI.
- **A manual run with the peer addresses unset.** On a local cluster, `DSP_GATEWAY_PEER_URL` and `GATEWAY_PEER_URL` are emptied on the management Deployment, and the suite's participants are registered again. Hosted peers are then not reachable, and the suite must pass with rule 2 applying. This is a verification task, not a CI step.

Alternative: registering an extra hosted participant that isn't reachable on every run. That costs another adapter and connector start-up, about a minute, for a branch the self-test already covers. Rejected.

### The check's name

"A hosted peer shows no adapter address, and its DSP gateway address only if reachable". This replaces "A hosted peer's addresses inside the hub are left out", which no longer describes the rule.

## Conflicts with existing documents and specs

- **The issue's wording.** The issue says the address is "never an address that only works inside the hub (a cluster Service name …)". On the local cluster, the configured DSP gateway peer address is itself a cluster Service name, `http://dsp-gateway.dataspace:8085`, which works for peers in the same cluster, such as the external demo. So the check doesn't refuse cluster Service names as such. It refuses anything that isn't under the configured peer address. The maintainer confirmed this reading.
- **`api-gateway` spec**, "Compatible participants": the scenario "A hosted peer" gains what a reachable peer's `dsp_url` is. The gateway already behaves this way.
- **`gateway-api.md`** says a reachable hosted peer's `dsp_url` is shown, but not what it is. It gains the same sentence.

## Risks

- **A deployment whose `DSP_GATEWAY_PEER_URL` has a trailing slash.** Management strips it when it reads the setting, and so does the suite.
- **A wrong `--dsp-gateway-peer-url`** makes the check fail. The message shows both the expected prefix and the address found.

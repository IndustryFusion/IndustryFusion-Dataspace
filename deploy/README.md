# Deploying the dataspace

This installs the dataspace on Kubernetes with [Helmfile](https://helmfile.readthedocs.io). Fixed services go in namespace `dataspace`, and the management API creates participants' adapters and connectors in `dataspace-participants`.

`deploy/local` is separate. It holds stand-ins for the local environment that `scripts/local-env.sh` creates. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## What you need first

- `kubectl` and `helm`, with `KUBECONFIG` pointing at the cluster. `bootstrap.sh` installs `helmfile` if it is missing.
- An Ingress controller, if you enable the Ingress. The annotations are for [ingress-nginx](https://kubernetes.github.io/ingress-nginx/). Any other controller needs its own, through `ingress.annotations`, and has to allow the same body size.
- [cert-manager](https://cert-manager.io), if you want it to issue certificates.
- PostgreSQL, S3-compatible storage and Keycloak. They aren't installed here. By default they are the ones from the [IndustryFusion DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack in namespace `iff`, at the addresses in `values/common.yaml`.
- The realm set up once, as [keycloak.md](../keycloak.md) describes. `scripts/setup-keycloak.py` does this.
- The images of `registry`, `gateway`, `dsp-gateway`, `management`, `adapter` and `connector` in a registry the cluster can pull from, as `[<images.registry>/]<images.repo>/<name>:<images.version>`. This project doesn't publish images yet, so build them with `docker build`.

## Install

Run these from `deploy/helm`.

1. **Prepare the cluster.** This installs `helmfile` under `.tools` if needed, and creates both namespaces. It can be repeated.

   ```bash
   ./bootstrap.sh up
   export PATH="$PWD/.tools:$PATH"
   ```

2. **Fill in the secrets.** Copy the example and set each value. The copy is ignored by git.

   ```bash
   cp values/secrets.yaml.example values/secrets.yaml
   ```

3. **Add an environment.** Copy `values/environments/local.yaml` to `values/environments/<name>.yaml` outside version control, or to a private repository, and add it under `environments:` in `helmfile.yaml`. Set the image names, the Ingress hosts and, if they differ, the dependencies. Settings not given come from `values/common.yaml`.

4. **Install.** Releases go in order, each waiting until its pods are ready.

   ```bash
   helmfile -e <name> sync
   ```

5. **Check it.**

   ```bash
   kubectl -n dataspace get pods
   curl https://<management host>/api/health
   ```

## Onboard a participant

Get an admin token, then register. See [management-api.md](../management-api.md).

```bash
curl -s https://<management host>/api/admin/token -H 'Content-Type: application/json' \
  -d '{"client_id": "dataspace-admin-cli", "client_secret": "<secret>"}'
curl -s https://<management host>/api/participants -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"participant_id": "urn:example:factory-owner-1", "participant_type": "factory_owner"}'
```

A registration waits for the participant's pods, so it can take a few minutes.

## Settings to know

| Setting | Notes |
|---|---|
| `limits.maxUploadBytes`, `limits.maxJsonBytes` | The one place these are set. The gateway, management and, through management, every new adapter read them. The gateway Ingress allows exactly `maxUploadBytes`, and the management Ingress `maxJsonBytes`. A participant that already exists gets a new value when it is registered again |
| `dependencies.keycloak.url` | Used by every service, and compared exactly with a token's issuer. Keycloak has to be reachable at this address from inside the cluster, and tokens have to be minted through it. No addresses are fixed: use a name your cluster resolves |
| `ingress.management.allowFrom` | Restrict who reaches management. See "What is and is not publicly reachable" in [architecture.md](../architecture.md) |
| `ingress.dspGateway.enabled`, `ingress.dspGateway.host` | Exposes the DSP gateway, for external participants. Off by default, and hosted-only installations leave it off. It routes to every hosted connector's DSP and public ports. See "DSP Gateway" in [architecture.md](../architecture.md) |
| `participants.gatewayPeerUrl`, `participants.dspGatewayPeerUrl` | What an `externally_reachable` participant announces, such as `https://<gateway host>`. Empty means the addresses inside the cluster, which work only for peers in this cluster. They have to work from inside the cluster too |
| `ingress.tls.certManagerClusterIssuer` | With `ingress.tls.enabled`, adds the cert-manager annotation. Without it, the named TLS Secrets have to exist |

With external participants, connectors push content through the gateway, and through the DSP gateway's addresses. A connector's HTTP client reuses a connection for up to 5 minutes, and a push on a connection the other end has dropped fails the transfer. The services keep idle connections for longer. So must anything in front of them: with ingress-nginx, set `keep-alive` above 300 in its ConfigMap, as its default is 75 seconds.

A body over the limit is refused by the Ingress with `413`, with the Ingress's own body. A smaller request over `MAX_JSON_BYTES` is refused by the gateway, with the contract's error.

Run one replica of management, as [management-api.md](../management-api.md) describes.

## Changing a secret

The services read the secrets file's values when they start, and each participant's pods read a copy from their own Secret. To change a value:

1. Change it in the secrets file, and run `helmfile -e <name> sync`.
2. Restart the services that use it: `kubectl -n dataspace rollout restart deploy/<name>`, for `registry`, `gateway` and `management`.
3. Register each hosted participant again, with `POST /api/participants` and the same fields. Its Secret takes the new value, and its pods restart. A participant whose Secret doesn't change isn't restarted. Until this is done, management can't reach an adapter it hasn't reached with the new key: it answers `502` saying the adapter refused the internal key.

To change the PostgreSQL password or the S3 keys, change them in those services first.

## Uninstall

To remove participants' databases, buckets and Keycloak clients too, delete each with `DELETE /api/participants/{id}` first, as these are outside the two namespaces.

```bash
DATASPACE_ENVIRONMENT=<name> ./bootstrap.sh down
```

This removes the releases, every participant object, and the two namespaces. The dependencies and the realm stay, and so does the `registry` database with its entries, so a later install finds those participants registered, with no pods. To start clean, delete participants first, and then drop that database.

# Deploying the dataspace

This installs the dataspace on Kubernetes with [Helmfile](https://helmfile.readthedocs.io). Fixed services go in namespace `dataspace`, and the management API creates participants' adapters and connectors in `dataspace-participants`.

`deploy/local` is separate. It holds stand-ins for the local environment that `scripts/local-env.sh` creates. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## What you need first

- `kubectl` and `helm`, with `KUBECONFIG` pointing at the cluster. `bootstrap.sh` installs `helmfile` if it is missing.
- An Ingress controller, if you enable the Ingress. The annotations are for [ingress-nginx](https://kubernetes.github.io/ingress-nginx/). Any other controller needs its own, through `ingress.annotations`, and has to allow the same body size.
- [cert-manager](https://cert-manager.io), if you want it to issue certificates.
- A network plugin that enforces NetworkPolicies, for `networkPolicy.enabled`. Without one, they are accepted and do nothing.
- PostgreSQL, S3-compatible storage and Keycloak. They aren't installed here. The PostgreSQL user in the secrets file has to be able to create databases and roles. By default they are the ones from the [IndustryFusion DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack in namespace `iff`, at the addresses in `values/common.yaml`.
- The realm set up once, as [keycloak.md](../keycloak.md) describes. `scripts/setup-keycloak.py` does this.
- The images of `registry`, `gateway`, `dsp-gateway`, `management`, `adapter` and `connector` in a registry the cluster can pull from, as `[<images.registry>/]<images.repo>/<name>:<images.version>`. Build and push them with the script below.

## Building and pushing the images

`scripts/build-images.sh` builds the six images, and pushes each as `<REGISTRY>/<REPO>/<name>:<VERSION>`. It needs Docker and bash 4.3 or later (macOS ships 3.2: install a newer one, for example with Homebrew), and the registry has to accept your pushes, for example after `docker login`. Run it from the repository's root folder:

```bash
REGISTRY=registry.example.com:5000 REPO=dataspace VERSION=1.2.3 ./scripts/build-images.sh
```

| Setting | Default | Chart value to set to the same |
|---|---|---|
| `REGISTRY` | `k3d-iff.localhost:12345` | `images.registry` |
| `REPO` | `dataspace` | `images.repo` |
| `VERSION` | `latest` | `images.version` |

- Settings set in the shell take precedence over a config file, `scripts/build-images.env`, which git ignores. Copy `scripts/build-images.env.example` to start one, or point `BUILD_IMAGES_CONFIG` at another file. The file holds `KEY=value` lines for these three keys and is never run.
- Name images to build only those, such as `./scripts/build-images.sh adapter connector`.
- `--build-only` builds without pushing. `--list` prints the names and builds nothing.
- An empty `REGISTRY` means no prefix, as in the chart. It works with `--build-only`, but the script won't push without a registry.
- The script stops at the first failed build or push, and says which image and which step failed. Images it pushed before that stay in the registry.
- `REGISTRY` is checked before anything is built or listed: `host` or `host:port`, optionally with a lowercase path, without a trailing slash or spaces. `REPO` is lowercase parts joined by `/`, and `VERSION` is a Docker tag. An invalid value stops the script, which says where the value came from.
- A registry that speaks plain HTTP, such as the default `k3d-iff.localhost:12345` from k3d, has to be listed in Docker's `insecure-registries`, unless it is `localhost` or an address Docker resolves to loopback. Otherwise the push fails with `server gave HTTP response to HTTPS client`. On Linux, add it to `/etc/docker/daemon.json` and restart Docker. With Docker Desktop, add it under Settings, Docker Engine:

  ```json
  { "insecure-registries": ["k3d-iff.localhost:12345"] }
  ```

Then set the same three values in your environment's values file, step 3 below:

```yaml
images:
  registry: registry.example.com:5000
  repo: dataspace
  version: 1.2.3
```

The chart uses them for the four fixed services, and passes them to the management API, which names participants' `adapter` and `connector` images the same way. `values/common.yaml` has `registry: ""` and `version: dev`, which are the local environment's names, so set all three.

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
| `ingress.management.allowFrom` | Who reaches management, required with its Ingress. See "What is and is not publicly reachable" in [architecture.md](../architecture.md). External participants' adapters read participants there, so include them |
| `networkPolicy.enabled` | On by default. See "Security Layers" in [architecture.md](../architecture.md) |
| `dependencies.s3.iamUrl` | For an S3 identity per participant. See below |
| `ingress.dspGateway.enabled`, `ingress.dspGateway.host` | Exposes the DSP gateway, for external participants. Off by default, and hosted-only installations leave it off. It routes to every hosted connector's DSP and public ports. See "DSP Gateway" in [architecture.md](../architecture.md) |
| `participants.gatewayPeerUrl`, `participants.dspGatewayPeerUrl` | What an `externally_reachable` participant announces, such as `https://<gateway host>`. Empty means the addresses inside the cluster, which work only for peers in this cluster. They have to work from inside the cluster too, as hosted participants are reachable by default and talk to each other through them |
| `ingress.tls.certManagerClusterIssuer` | With `ingress.tls.enabled`, adds the cert-manager annotation. Without it, the named TLS Secrets have to exist |

With external participants, connectors push content through the gateway, and through the DSP gateway's addresses. A connector's HTTP client reuses a connection for up to 5 minutes, and a push on a connection the other end has dropped fails the transfer. The services keep idle connections for longer. So must anything in front of them: with ingress-nginx, set `keep-alive` above 300 in its ConfigMap, as its default is 75 seconds.

### An S3 identity per participant

Without `dependencies.s3.iamUrl`, **participants share the S3 identity in the secrets file, so one participant's credentials can read another's bucket.** PostgreSQL users and internal keys are per participant in any case.

To separate them, the storage has to keep its identities in its own list, and management has to be able to change it:

- Run SeaweedFS **without** `-s3.config`, and with `-iam`. Add the identity in the secrets file to its list: `s3.configure -user dataspace-management -access_key <key> -secret_key <secret> -actions Admin,Read,Write,List,Tagging -apply` in `weed shell`. Until it has a list, SeaweedFS accepts anyone. `write_storage_identities` in `scripts/local-env.sh` shows how.
- Set `dependencies.s3.iamUrl` to its IAM API's address.
- Allow only management to reach the IAM port, and nothing to reach the filer's port but the storage itself. In the version used here, the IAM API didn't refuse a wrong signature, and the filer serves every identity's keys in plain text.

**Even then, the separation isn't complete.** In the version used here, SeaweedFS 3.80, a copy is only checked against its destination. So with one participant's keys, a direct read, write or list of another's bucket is refused, and `CopyObject` or `UploadPartCopy` of an object it can name, into its own bucket, succeeds. Listing stays refused, so it has to know the key, which holds a message's id. No policy or setting closed this. `scripts/security-check.py` reports it as a known gap, and exits with 2. See "A known gap" in the design of `gh-20-security-hardening`, for the alternatives and the decision it waits on.

**Don't set this on a storage started with `-s3.config`,** which includes the [DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack's. SeaweedFS uses its filer's list instead of its static one once that exists, so that stack's other identities would stop working, and the participants' would go at its next restart. Move that storage's identities to the filer's list first, or give the dataspace its own storage.

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

# Deploying the dataspace

This installs the dataspace on Kubernetes with [Helmfile](https://helmfile.readthedocs.io). Fixed services go in the namespace `NAMESPACE` names, `dataspace` by default. The management API creates participants' adapters and connectors in `PARTICIPANTS_NAMESPACE`, `dataspace-participants` by default.

The layout is the one DigitalTwin and XANA use:

```
helm/
  bootstrap.sh              # checks Helm, installs helmfile and helm-diff, creates and removes the namespaces
  helmfile.yaml.gotmpl      # the environment and the releases
  values.yaml.gotmpl        # what every chart reads: the environment's values with env.sh's settings
  common.yaml               # settings shared by every installation
  env.sh                    # sourced before helmfile and scripts/build-images.sh
  environment/
    default.yaml            # this installation's settings
    secrets.yaml.example    # copy to secrets.yaml, which git ignores
  charts/
    common/                 # the Secret registry and management read
    registry/
    gateway/
    dsp-gateway/
    management/             # with its service account, its rights and the participants' network policies
```

`deploy/local` is separate. It holds stand-ins for the local environment that `scripts/local-env.sh` creates, which deploys these charts too. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## What you need first

- `kubectl` and `helm`, with `KUBECONFIG` pointing at the cluster. `bootstrap.sh` checks Helm's version, and installs the pinned `helmfile` and the helm-diff plugin if they are missing. A `helmfile` of another version on `PATH` is left alone, and the pinned one goes in `.tools`, which comes first.
- An Ingress controller, if you enable the Ingress. The annotations are for [ingress-nginx](https://kubernetes.github.io/ingress-nginx/). Any other controller needs its own, through `ingress.annotations`, and has to allow the same body size.
- [cert-manager](https://cert-manager.io), if you want it to issue certificates.
- A network plugin that enforces NetworkPolicies, for `networkPolicy.enabled`. Without one, they are accepted and do nothing.
- PostgreSQL, S3-compatible storage and Keycloak. They aren't installed here. The PostgreSQL user in the secrets file has to be able to create databases and roles. By default they are the ones from the [IndustryFusion DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack in namespace `iff`, at the addresses in `common.yaml`.
- The realm set up once, as [keycloak.md](../keycloak.md) describes. `scripts/setup-keycloak.py` does this.
- The images of `registry`, `gateway`, `dsp-gateway`, `management`, `adapter` and `connector` in a registry the cluster can pull from, as `[<LOCAL_REGISTRY>/]<MAIN_REPO>/<name>:<MAIN_VERSION>`. Build and push them with the script below.

## env.sh

Source it in the shell you run helmfile and the build script from:

```bash
source helm/env.sh
```

| Variable | Default | What it sets |
|---|---|---|
| `NAMESPACE` | `dataspace` | where the services run |
| `PARTICIPANTS_NAMESPACE` | `dataspace-participants` | where management creates participants |
| `LOCAL_REGISTRY` | `k3d-iff.localhost:12345` | the images' registry. Empty means no prefix |
| `MAIN_REPO` | `dataspace` | the images' repository |
| `MAIN_VERSION` | `latest` | the images' tag |
| `HELM_VERSION` | `3.14.0` | the oldest Helm `bootstrap.sh` accepts |
| `HELMFILE_VERSION` | `0.169.2` | the helmfile `bootstrap.sh` installs, for Linux or macOS on amd64 or arm64. `bootstrap.sh` holds the checksums |
| `HELM_DIFF_PLUGIN` | `3.15.11` | the helm-diff plugin `bootstrap.sh tools` installs if none is, for `helmfile diff` and `helmfile apply` |

A variable already exported keeps its value, even an empty one, so you can export them before sourcing, or edit `env.sh` in a copy you keep with your installation. Export them on their own line: `LOCAL_REGISTRY=... source helm/env.sh` on one line doesn't keep the value after `source`. It holds no secret. The charts and `scripts/build-images.sh` read the same three image variables, so what the script pushes is what the charts deploy. Without `env.sh`, helmfile stops and names the variable that is missing.

## Building and pushing the images

`scripts/build-images.sh` builds the six images, and pushes each as `<LOCAL_REGISTRY>/<MAIN_REPO>/<name>:<MAIN_VERSION>`. It needs Docker and bash 4.3 or later (macOS ships 3.2: install a newer one, for example with Homebrew), and the registry has to accept your pushes, for example after `docker login`. Run it from the repository's root folder:

```bash
export LOCAL_REGISTRY=registry.example.com:5000 MAIN_VERSION=1.2.3
source helm/env.sh
./scripts/build-images.sh
```

- The script reads the three variables from the shell. Unset, they have the defaults above. `REGISTRY`, `REPO` and `VERSION` are not read, and the script says so if they are set.
- Name images to build only those, such as `./scripts/build-images.sh adapter connector`.
- `--build-only` builds without pushing. `--list` prints the names and builds nothing.
- An empty `LOCAL_REGISTRY` means no prefix, as in the charts. It works with `--build-only`, but the script won't push without a registry.
- The script stops at the first failed build or push, and says which image and which step failed. Images it pushed before that stay in the registry.
- `LOCAL_REGISTRY` is checked before anything is built or listed: `host` or `host:port`, optionally with a lowercase path, without a trailing slash or spaces. `MAIN_REPO` is lowercase parts joined by `/`, and `MAIN_VERSION` is a Docker tag. An invalid value stops the script, which says so.
- A registry that speaks plain HTTP, such as the default `k3d-iff.localhost:12345` from k3d, has to be listed in Docker's `insecure-registries`, unless it is `localhost` or an address Docker resolves to loopback. Otherwise the push fails with `server gave HTTP response to HTTPS client`. On Linux, add it to `/etc/docker/daemon.json` and restart Docker. With Docker Desktop, add it under Settings, Docker Engine:

  ```json
  { "insecure-registries": ["k3d-iff.localhost:12345"] }
  ```

The charts use the same variables for the four fixed services, and pass them to the management API, which names participants' `adapter` and `connector` images the same way.

## Install

Run these from `helm/`, in a shell where `env.sh` is sourced.

**Running helmfile.** Run helmfile from `helm/` after `source ./env.sh`, or from elsewhere with `-f helm/helmfile.yaml.gotmpl`, after `source helm/env.sh`. Keep the file's name. Don't make a `helmfile.yaml` from it, by copying or renaming:
- with both files present, helmfile refuses to start;
- helmfile v1 reads a `helmfile.yaml` as plain YAML, so the template in it fails to parse. The pinned 0.169.2 still renders it, but the `.gotmpl` name works with both.

1. **Prepare the cluster.** This checks Helm, installs `helmfile` under `.tools` and helm-diff if needed, and creates both namespaces. It can be repeated.

   ```bash
   ./bootstrap.sh up
   export PATH="$PWD/.tools:$PATH"
   ```

2. **Fill in the secrets.** Copy the example and set each value. The copy is ignored by git. To keep it elsewhere, set `DATASPACE_SECRETS_FILE` to its path.

   ```bash
   cp environment/secrets.yaml.example environment/secrets.yaml
   ```

3. **Fill in the environment.** Set your installation's values in `environment/default.yaml`: at least the Ingress hosts if you enable the Ingress, whether the management UI has a login (see "Management access"), and the dependencies' addresses if they differ from `common.yaml`. Settings not given come from `common.yaml`. Keep a real installation's hosts out of this repository: keep the file in a private one, or put them in a file of your own and set `DATASPACE_VALUES_FILE` to its path, which is layered after `environment/default.yaml`.

4. **Install.** Releases go in order, each waiting until its pods are ready: `common`, then `registry` and `dsp-gateway`, then `gateway`, then `management`.

   ```bash
   helmfile -e default sync
   ```

5. **Check it.**

   ```bash
   kubectl -n "$NAMESPACE" get pods
   curl https://<management host>/api/health
   ```

### An install from before helm/

Installs made before the deployment moved to `helm/` used the releases `dataspace-common`, `dataspace-registry`, `dataspace-gateway`, `dataspace-dsp-gateway` and `dataspace-management`. Helm can't hand their objects to the new releases, so remove the old ones first, then install as above. Participants, their databases and buckets stay, and the services are unavailable until the new releases are ready:

```bash
helm -n dataspace uninstall dataspace-management dataspace-gateway dataspace-dsp-gateway dataspace-registry dataspace-common
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

Set these in `environment/default.yaml`.

| Setting | Notes |
|---|---|
| `limits.maxUploadBytes`, `limits.maxJsonBytes` | The one place these are set. The gateway, management and, through management, every new adapter read them. The gateway Ingress allows exactly `maxUploadBytes`, and the management Ingress `maxJsonBytes`. A participant that already exists gets a new value when it is registered again |
| `dependencies.keycloak.url` | Used by every service, and compared exactly with a token's issuer. Keycloak has to be reachable at this address from inside the cluster, and tokens have to be minted through it. No addresses are fixed: use a name your cluster resolves |
| `ingress.management.basicAuth.enabled` | A username and password in front of the management UI, from `secrets.managementBasicAuth` in the secrets file. Off by default. See "Management access" below |
| `ingress.management.allowFrom` | Optional. The addresses allowed to reach management, on both its Ingress objects. Empty means any address. See "Management access" below |
| `networkPolicy.enabled` | On by default. See "Security Layers" in [architecture.md](../architecture.md) |
| `dependencies.s3.iamUrl` | For an S3 identity per participant. See below |
| `ingress.dspGateway.enabled`, `ingress.dspGateway.host` | Exposes the DSP gateway, for external participants. Off by default, and hosted-only installations leave it off. It routes to every hosted connector's DSP and public ports. See "DSP Gateway" in [architecture.md](../architecture.md) |
| `participants.gatewayPeerUrl`, `participants.dspGatewayPeerUrl` | What an `externally_reachable` participant announces, such as `https://<gateway host>`. Empty means the addresses inside the cluster, which work only for peers in this cluster. They have to work from inside the cluster too, as hosted participants are reachable by default and talk to each other through them |
| `ingress.tls.certManagerClusterIssuer` | With `ingress.tls.enabled`, adds the cert-manager annotation. Without it, the named TLS Secrets have to exist |

With external participants, connectors push content through the gateway, and through the DSP gateway's addresses. A connector's HTTP client reuses a connection for up to 5 minutes, and a push on a connection the other end has dropped fails the transfer. The services keep idle connections for longer. So must anything in front of them: with ingress-nginx, set `keep-alive` above 300 in its ConfigMap, as its default is 75 seconds.

### Management access

Management has two Ingress objects on its host:
- **`management`** routes `/api` and `/health`. Every change there needs a Keycloak admin token. A read without a token gives only the public view, which external participants' adapters use.
- **`management-ui`** routes the rest: the UI and its files.

**The UI login.** Set `ingress.management.basicAuth.enabled: true`, and put a username and password in the secrets file:

```yaml
secrets:
  managementBasicAuth:
    user: admin
    password: <a long random password>
```

- The browser then asks for them before showing the UI. In the UI, an administrator still signs in with the admin client, which gives the token `/api` needs.
- `/api` and `/health` never ask for the login. The UI and adapters send a bearer token there, and adapters can't answer a password prompt.
- Management treats the Basic credentials a browser sends with every call after the login as no token.
- Rendering stops if the login is on without a username or a password.
- Only a bcrypt hash goes into the cluster, in the Secret `management-basic-auth`. The hash is kept while the credentials stay the same, so a repeated `helmfile sync` leaves the Secret alone. `helmfile diff` can't look in the cluster, so it shows that Secret as changed each time. That is expected.
- To change the password, change it in the secrets file and run `helmfile -e default sync`.
- Use the login with TLS (`ingress.tls.enabled`): without it, the browser sends the password in clear text.

**The allowlist** is optional. With `ingress.management.allowFrom`, such as `10.0.0.0/8,192.0.2.10/32`, both objects only admit those addresses. Use it to keep management to known networks, such as an office or a VPN.
- Include every external participant's adapter address, as adapters read participants there.
- nginx has to see the client's real address, or the list matches the load balancer instead. On most clouds that means `externalTrafficPolicy: Local` on the Ingress controller's Service, or the PROXY protocol, with `use-proxy-protocol: "true"` in the controller's ConfigMap and the load balancer set to send it.

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

1. Change it in the secrets file, and run `helmfile -e default sync`.
2. Restart the services that use it: `kubectl -n "$NAMESPACE" rollout restart deploy/<name>`, for `registry`, `gateway` and `management`.
3. Register each hosted participant again, with `POST /api/participants` and the same fields. Its Secret takes the new value, and its pods restart. A participant whose Secret doesn't change isn't restarted. Until this is done, management can't reach an adapter it hasn't reached with the new key: it answers `502` saying the adapter refused the internal key.

To change the PostgreSQL password or the S3 keys, change them in those services first.

## Uninstall

To remove participants' databases, buckets and Keycloak clients too, delete each with `DELETE /api/participants/{id}` first, as these are outside the two namespaces.

```bash
./bootstrap.sh down
```

It doesn't need the secrets file, and neither does `helmfile list`. Rendering and installing stop without it, naming the file.

This removes the releases, every participant object, and the two namespaces. The dependencies and the realm stay, and so does the `registry` database with its entries, so a later install finds those participants registered, with no pods. To start clean, delete participants first, and then drop that database.

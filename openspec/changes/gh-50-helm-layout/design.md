# Design

## Context

Today `deploy/helm/helmfile.yaml` installs one chart, `charts/dataspace`, five times: as `dataspace-common`, `dataspace-registry`, `dataspace-gateway`, `dataspace-dsp-gateway` and `dataspace-management`. Each release sets `component`, and the templates switch on it.

- **`common`** holds the shared Secret `service-credentials`, the `management` service account, its Role and RoleBinding in `dataspace-participants`, and three NetworkPolicies: `adapters` and `connectors` in `dataspace-participants`, and `registry`.
- **Values** come from `values/common.yaml`, then `values/environments/<env>.yaml` (`default` or `local`), then the secrets file. Image names and namespaces are in `common.yaml`.
- **The local cluster** doesn't use the chart. `scripts/local-env.sh services` creates the Secret with `kubectl` and applies `deploy/local/services.yaml` and `deploy/local/network-policies.yaml`, which repeat the chart's objects by hand. `local-env.sh helm-secrets` writes `.local/helm-secrets.yaml` for trying the chart with `-e local`.
- **`scripts/build-images.sh`** reads `REGISTRY`, `REPO` and `VERSION`, from the shell, then `scripts/build-images.env`, then the defaults.

DigitalTwin and XANA lay out their deployments as a top-level `helm/` folder with `helmfile.yaml.gotmpl`, `common.yaml`, `environment/<env>.yaml`, `values.yaml.gotmpl`, `env.sh` and one chart per service. This change uses the same layout.

## Decisions

The maintainer took the decisions in the first five sections, accepted the proposals in the sections after them, and decided the build script's config file is dropped.

### One environment (maintainer's decision)

The only environment is `default`. It layers `helm/common.yaml`, then `helm/environment/default.yaml`, then `helm/environment/secrets.yaml`, or the file `DATASPACE_SECRETS_FILE` names. There is no `local`, `production` or other environment.

- `environment/secrets.yaml` is git-ignored, and `environment/secrets.yaml.example` lists every secret key.
- An operator with more than one installation keeps one `environment/default.yaml` and one secrets file per installation, for example in a private repository.
- `scripts/local-env.sh` deploys `default`, and passes the local cluster's settings in a generated values file (see "The local cluster").

### `helm/env.sh` (maintainer's decision)

Operators run `source helm/env.sh` before `helmfile` and `scripts/build-images.sh`. It exports:

| Variable | Default | Used for |
|---|---|---|
| `NAMESPACE` | `dataspace` | the releases' namespace, and the services' namespace in the charts |
| `PARTICIPANTS_NAMESPACE` | `dataspace-participants` | where management creates participants, and the participant RBAC and network policies |
| `LOCAL_REGISTRY` | `k3d-iff.localhost:12345` | the image registry. Empty means no prefix |
| `MAIN_REPO` | `dataspace` | the image repository |
| `MAIN_VERSION` | `latest` | the image tag |
| `HELM_VERSION` | the version CI uses | the oldest Helm that `bootstrap.sh` accepts |
| `HELMFILE_VERSION` | today's `0.169.2` | the helmfile that `bootstrap.sh` downloads |
| `HELM_DIFF_PLUGIN` | a pinned helm-diff version | the plugin `bootstrap.sh` installs, which `helmfile diff` and `helmfile apply` need |

- Each variable keeps a value already set in the shell, even an empty one, so `LOCAL_REGISTRY= source helm/env.sh` gives names without a registry.
- `env.sh` holds no secret, and no environment-specific host.
- The helmfile checksum stays in `bootstrap.sh`, next to the version it belongs to. `bootstrap.sh` stops if `HELMFILE_VERSION` names a version whose checksum it doesn't hold, rather than download something unchecked.

### Image names from the same three variables (maintainer's decision)

`values.yaml.gotmpl` sets `images.registry`, `images.repo` and `images.version` from `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`. The charts render `[<images.registry>/]<images.repo>/<name>:<images.version>` as today, and the management API still receives `MAIN_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` for participant images.

`scripts/build-images.sh` reads `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` in place of `REGISTRY`, `REPO` and `VERSION`, from the shell only, with the same defaults when a variable is unset and the same validation. A variable set in the shell, even empty, wins over the default.

The maintainer decided to drop `scripts/build-images.env`, `scripts/build-images.env.example` and `BUILD_IMAGES_CONFIG`: `helm/env.sh` is the one place to set the three values, for the charts and the script alike. The script's file parsing, its tests and its `.gitignore` entry go with it. `scripts/build-images-test.py`, `scripts/check-image-names.py` and the CI job use the new names. The old names are not read, so a value left in them is ignored. The script says so if it finds `REGISTRY`, `REPO` or `VERSION` set, so an old habit doesn't silently push somewhere else.

`images.*` and `namespaces.*` leave `common.yaml`, so each has one source. `images.pullPolicy` stays in `common.yaml`.

`values.yaml.gotmpl` reads `MAIN_REPO`, `MAIN_VERSION`, `NAMESPACE` and `PARTICIPANTS_NAMESPACE` with `requiredEnv`, so running helmfile without `source helm/env.sh` stops with the missing variable's name. `LOCAL_REGISTRY` may be empty.

### Charts and releases (maintainer's decision)

| Release | Chart | Objects | Needs |
|---|---|---|---|
| `common` | `charts/common` | Secret `service-credentials`, read by `registry` and `management` | none |
| `registry` | `charts/registry` | Deployment, Service, NetworkPolicy `registry` | `common` |
| `gateway` | `charts/gateway` | Deployment, Service, Ingress | `registry` |
| `dsp-gateway` | `charts/dsp-gateway` | Deployment, Service, optional Ingress | `common` |
| `management` | `charts/management` | Deployment, Service, Ingress, ServiceAccount, Role and RoleBinding in `PARTICIPANTS_NAMESPACE`, NetworkPolicies `adapters` and `connectors` | `registry`, `gateway`, `dsp-gateway` |

- The `needs` order is today's. No pod waits on something a later release creates: the Secret comes first, and the network policies and RBAC are installed with the release whose pods use them.
- The participant network policies go with `management`, which creates the pods they select. Before the change they existed before any participant could, and they still do, because participants are only created through a running management.
- Release names lose the `dataspace-` prefix, as the issue lists them. Helm can't adopt objects that another release owns, so an existing install has to remove the old releases before installing the new ones. `helm/README.md` says how. Installing on a real cluster is out of scope, and there is no automatic migration.

### The local cluster (maintainer's decision)

`scripts/local-env.sh services` sources `helm/env.sh` and builds the images with `scripts/build-images.sh --build-only`, then loads them into kind. It then deploys the `default` environment with helmfile, with two generated files in `.local/`:

- `helm-secrets.yaml`, as today, and
- `helm-values.yaml`, with the local hosts and settings that `values/environments/local.yaml` holds today. These are the Ingress hosts `dataspace.localtest.me` and `dataspace-management.localtest.me`, the open management allow-list, and SeaweedFS's IAM address.

Neither file is committed. Both are passed to helmfile through `DATASPACE_SECRETS_FILE` and a second variable, `DATASPACE_VALUES_FILE`, which adds an optional values file after `environment/default.yaml`. It is the same pattern as the secrets file, and an operator can use it too.

`local-env.sh` sets `LOCAL_REGISTRY` to empty and `MAIN_VERSION` to `dev` before sourcing `env.sh`. The local images then keep today's names, `dataspace/<name>:dev`, which the external demo and the participant templates in `deploy/local/` use.

`deploy/local/services.yaml` and `deploy/local/network-policies.yaml` repeat the chart's objects and are removed. `local-env.sh` no longer creates the Secret itself, because the `common` release does. The rest of `deploy/local/` stays: the infrastructure, the namespaces and the participant and external-demo templates.

Alternatives:
- **Keeping `services.yaml` beside the chart.** Rejected: two descriptions of the same objects drift, and the issue asks the local cluster to deploy `default`.
- **The env.sh defaults for local images.** This would give `k3d-iff.localhost:12345/dataspace/<name>:latest`. It works with kind, but it renames the images the external demo uses, which is out of scope.

### `values.yaml.gotmpl`

It turns the environment values into what the charts read, so the charts never read environment files:

- the image settings and namespaces from `env.sh`
- the services' in-cluster addresses: registry, gateway and DSP gateway URLs
- the limits check: an upload limit below the JSON limit fails rendering here, once, instead of in each chart

Every release gets `common.yaml`, the environment files, the secrets file and then `values.yaml.gotmpl`.

### Shared template helpers

Each chart has its own `_helpers.tpl` with only the helpers it uses: labels, the image name, secret references, and the PostgreSQL, Keycloak and limit variables. The same few helpers therefore appear in more than one chart. The check below catches a difference between them and today's output, and `check-helm-values.py` keeps checking the rules that span charts, such as Ingress body sizes against limits.

Alternatives:
- **A library chart** as a dependency of each chart. It avoids the repetition, but adds `helm dependency build` and vendored archives, and doesn't match how DigitalTwin and XANA lay out their charts.
- **Computing the env lists in `values.yaml.gotmpl`.** Templates would move out of the charts, which then couldn't be read or linted on their own.

### The same objects as before (maintainer's decision)

A new script, `scripts/check-helm-layout.py --before <git revision>`, extracts `deploy/helm` from that revision with `git archive`, and renders it per release with `helm template`. It renders the new layout with `helmfile template` and compares the two. It does this twice:
- with default settings: `default`, example secrets, and the old image and namespace values given through `env.sh`'s variables
- with the local cluster's settings: the old `local` environment against `default` with `local-env.sh`'s generated values file

Objects are matched by kind, namespace and name. They must be equal after removing the objects' `metadata.labels`, and the `app.kubernetes.io/instance` label wherever it appears, because it carries the release name. Every other field, including selectors, pod template labels other than the release, env order and annotations, must be equal. Missing or extra objects fail.

CI runs it against the Pull Request's base. If the revision has no `deploy/helm`, the script says there is nothing to compare and passes, so it doesn't block later changes. It can be run by hand against any revision.

Alternative: committed snapshots of today's output. These would have to be regenerated for every later intended change to the charts.

### CI

The `helm` job sources `helm/env.sh`, installs the pinned helmfile with `bootstrap.sh tools`, lints each of the five charts with `common.yaml` and `values.yaml.gotmpl`'s output, runs `helmfile -e default template`, runs `check-helm-values.py` from its new paths, and runs `check-helm-layout.py` against the base revision. The `images` job sources `helm/env.sh` and uses the new variable names. It still builds with `LOCAL_REGISTRY=ci.example:5000`.

`bootstrap.sh` gains a `tools` command that installs helmfile and the helm-diff plugin and checks Helm's version, without touching a cluster. `up` and `down` keep their meaning and call it first.

## Conflicts with existing documents and specs

- **The build script's config file.** After `source helm/env.sh`, the shell would shadow `scripts/build-images.env`. The maintainer decided to drop the file, so `env.sh` is the only place for the three values, and the `image-build` requirement "Configuration file and precedence" is removed.
- **`image-build` spec.** Its requirements name `REGISTRY`, `REPO`, `VERSION` and `deploy/README.md`. They change to the new names and `helm/README.md`, and the config file requirement is removed. The behaviour is otherwise unchanged.
- **`helm-deployment` spec.** "Installing from the documented procedure" names `deploy/README.md`, and "Layered values and secrets" says "an environment's values". Both change for the single `default` environment and the new paths.
- **`contract-tests` spec.** It names `deploy/README.md`.
- **Default image version.** `common.yaml` today defaults to `dev` with no registry. With `env.sh` the defaults become `k3d-iff.localhost:12345/dataspace/<name>:latest`, the build script's. This is the maintainer's choice of defaults for `env.sh`. The output check gives the old values explicitly, so it compares like with like.

## Risks

- **Existing installs** have to remove the old releases before installing. The README gives the commands, and services and participants are not affected, except that they are briefly unavailable.
- **The repeated helpers** can drift between charts after this change. The check guards this change only, and later reviews and `check-helm-values.py` guard the rules that matter.
- **The local cluster now depends on helmfile.** `local-env.sh services` installs the pinned version through `bootstrap.sh tools`, as the Helm install already does.

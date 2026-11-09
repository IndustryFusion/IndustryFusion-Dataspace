# Proposal

Issue: #50

## Why

The deployment lives under `deploy/helm/`, in one chart that switches on a `component` value, with environments under `values/environments/`. DigitalTwin and XANA use a top-level `helm/` folder with `helmfile.yaml.gotmpl`, `common.yaml`, `environment/<env>.yaml`, `values.yaml.gotmpl`, an `env.sh` and one chart per service. An operator who knows one IndustryFusion repository should find the same files in the same places here.

## What Changes

- **The deployment moves to `helm/`:**
  - `bootstrap.sh`, `helmfile.yaml.gotmpl`, `values.yaml.gotmpl`, `common.yaml`, `env.sh` and a `README.md`
  - `environment/default.yaml` and `environment/secrets.yaml.example`
  - `charts/common`, `charts/registry`, `charts/gateway`, `charts/dsp-gateway` and `charts/management`

  `deploy/helm/` is removed.
- **One environment, `default`.** It layers `common.yaml`, then `environment/default.yaml`, then `environment/secrets.yaml`, or the file `DATASPACE_SECRETS_FILE` names. The `local` environment is removed.
- **`helm/env.sh`** is sourced before helmfile and `scripts/build-images.sh`. It exports `NAMESPACE`, `PARTICIPANTS_NAMESPACE`, `LOCAL_REGISTRY`, `MAIN_REPO`, `MAIN_VERSION`, `HELM_VERSION`, `HELMFILE_VERSION` and `HELM_DIFF_PLUGIN`, and holds no secret.
  - Image names and namespaces come from these variables through `values.yaml.gotmpl`, and no longer from `common.yaml`.
- **One chart per service**, released as `registry`, `gateway`, `dsp-gateway` and `management`, after a small `common` release that holds the shared Secret. The `needs` order is the same as today.
  - The management service account, its participant RBAC and the participant network policies move to the `management` chart.
  - The registry's network policy moves to the `registry` chart.
- **The rendered objects stay the same, apart from labels.** A new check compares the new layout's output with the old layout's, with default settings and with the local cluster's settings.
- **`scripts/build-images.sh`** reads `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` instead of `REGISTRY`, `REPO` and `VERSION`, with the same defaults. Its config file example, its tests, `scripts/check-image-names.py` and CI change with it.
- **`scripts/local-env.sh services`** deploys the `default` environment with helmfile. It passes the local cluster's hosts and settings in a generated values file in `.local/`, next to the generated secrets file. `deploy/local/services.yaml` and `deploy/local/network-policies.yaml`, which duplicated the chart, are removed.
- **Moved with the layout:** CI's lint and render steps, `scripts/check-helm-values.py`, and the guide. `deploy/README.md` becomes `helm/README.md`, and other documents that name `deploy/helm` point to `helm/`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `helm-deployment`: the layout, the single environment, `env.sh`, the charts and their releases, and the check that the output is unchanged.
- `image-build`: the variables the script reads, and the guide's new place.
- `local-environment`: `scripts/local-env.sh services` deploys the services with the chart.
- `contract-tests`: the deployment guide's new place.

## Out of Scope

- Installing on a real cluster.
- New settings or behaviour. Settings, limits, the Ingress and TLS options, the network policies and the form of the image names stay as they are.
- Migrating an existing install from the old release names. `helm/README.md` describes removing the old releases first.
- The external demo and the participant templates in `deploy/local/`, which keep their `dataspace/<name>:dev` images.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: the reference to `deploy/README.md` in the storage section points to `helm/README.md`. The deployment description is otherwise unaffected.
- `CONTRIBUTING.md`: the Helm install and `scripts/local-env.sh services` paragraphs.
- `deploy/README.md`: it moves to `helm/README.md`. `deploy/README.md` keeps only what `deploy/local/` is, with a link to `helm/README.md`.
- CI (`.github/workflows/services.yml`): the `helm` job lints the five charts, renders the environment with helmfile and runs the new check. The `images` job reads the new variables.

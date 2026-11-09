# Tasks

## 1. Before moving

- [x] 1.1 Write `scripts/check-helm-layout.py`, which renders `deploy/helm` from a git revision and the new layout, and compares them, ignoring only `metadata.labels` and `app.kubernetes.io/instance`; verify it passes when both sides are today's layout, and fails, naming the object and field, when one field of one object is changed

## 2. The layout

- [x] 2.1 Create `helm/` with `env.sh`, `common.yaml`, `environment/default.yaml`, `environment/secrets.yaml.example`, `values.yaml.gotmpl` and `helmfile.yaml.gotmpl`, with the single `default` environment, `DATASPACE_VALUES_FILE` and `DATASPACE_SECRETS_FILE`; ignore `helm/environment/secrets.yaml`; verify with `helmfile -e default template`, `git check-ignore`, and a render without `env.sh` that stops naming a variable
- [x] 2.2 Split the chart into `common`, `registry`, `gateway`, `dsp-gateway` and `management`, with the objects and `needs` in the design; verify with `helm lint` on each chart and `scripts/check-helm-layout.py` against the base revision, with default and local settings
- [x] 2.3 Move `bootstrap.sh` to `helm/`, read the versions from `env.sh`, add `tools`, and keep the helmfile checksum; verify `tools` installs the pinned helmfile and helm-diff, and stops on an unknown version or an older Helm
- [x] 2.4 Remove `deploy/helm/`; verify with a search for `deploy/helm` outside archived changes

## 3. Images

- [x] 3.1 Make `scripts/build-images.sh` read `LOCAL_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION` from the shell only, and say so when it finds `REGISTRY`, `REPO` or `VERSION`; remove the config file, `BUILD_IMAGES_CONFIG`, `scripts/build-images.env.example`, its `.gitignore` entry and their tests; update `scripts/build-images-test.py`; verify with the tests, including the old-name message and that a `scripts/build-images.env` is not read, and a revert check
- [x] 3.2 Make `scripts/check-image-names.py` render the `default` environment with helmfile from the same three variables; verify it passes, and fails when a chart's image name is changed

## 4. The local cluster

- [x] 4.1 Make `scripts/local-env.sh services` source `helm/env.sh` with the local image names, build with `scripts/build-images.sh --build-only`, load the images, write `.local/helm-values.yaml` and `.local/helm-secrets.yaml`, and deploy `default` with helmfile; remove `deploy/local/services.yaml` and `deploy/local/network-policies.yaml`; verify on a new local cluster that all pods reach ready
- [ ] 4.2 Run the local end-to-end checks against it: `message-exchange-check.py`, `management-check.py`, `contract_test.py --local`, and `ingress-check.py` without an Ingress controller; verify on a local cluster. Open: message-exchange, management and ingress checks pass; the contract suite has 146 passed, 1 failed and 2 not run. The failure, "A hosted peer's addresses inside the hub are left out", comes from hosted participants being reachable by default since #40, with the same peer addresses the removed local manifests set, and is not caused by this change
- [x] 4.3 Run `services` again after changing a service's code; verify the new image is running

## 5. CI

- [x] 5.1 Update the `helm` job to source `env.sh`, install helmfile with `bootstrap.sh tools`, lint the five charts, render `default`, run `check-helm-values.py` and run `check-helm-layout.py` against the base; update the `images` job to the new variables; verify on the Pull Request

## 6. Documents

- [x] 6.1 Move `deploy/README.md` to `helm/README.md`, describing the layout, the environment, `env.sh`, the values an operator must fill in, the secrets file, the build script and removing the old releases. Leave `deploy/README.md` with only what `deploy/local/` is and a link. Verify by following it on a local cluster, apart from installing on a real cluster
- [x] 6.2 Update `CONTRIBUTING.md`, `architecture.md` and every other document that names `deploy/helm` or `deploy/README.md`; verify with a search

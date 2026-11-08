# Proposal

Issue: #47

## Why

CI builds the images but doesn't publish them anywhere. The chart expects `[<images.registry>/]<images.repo>/<name>:<images.version>`, and the management API names participants' adapter and connector images the same way. Apart from loading `:dev` images into the local kind cluster, operators have no supported way to get the six images into the registry their cluster pulls from.

## What Changes

- A new script, `scripts/build-images.sh`, builds `gateway`, `dsp-gateway`, `registry`, `management` (the API with the UI built in), `adapter` and `connector`, then tags and pushes each as `<REGISTRY>/<REPO>/<name>:<VERSION>`.
- `REGISTRY`, `REPO` and `VERSION` default to `k3d-iff.localhost:12345`, `dataspace` and `latest`. They can come from an optional, git-ignored config file, `scripts/build-images.env`. A variable set in the shell takes precedence over the file. A committed `scripts/build-images.env.example` shows the keys.
- Targets are all six images by default, or one or more named images. With `--build-only`, the script builds and tags but doesn't push. `--list` prints the names without building.
- `BUILD_IMAGES_CONFIG` can name another config file.
- An empty `REGISTRY` means no prefix, as in the chart. That is allowed for building, and refused for pushing, which would go to Docker Hub.
- Before it starts, the script prints the full names it will build. It stops at the first failure, saying which image and which step failed, with a non-zero exit code.
- CI runs shellcheck on the script, and runs it with `--build-only`.
- `deploy/README.md` replaces "This project doesn't publish images yet" with how to build and push the images, and how to set `images.registry`, `images.repo` and `images.version` to match.

## Capabilities

### New Capabilities

- `image-build`: building, tagging and pushing the dataspace images with one script.

### Modified Capabilities

None. The `helm-deployment` requirement "Installing from the documented procedure" already relies on images being present. This change gives the documented way to get them there, and `deploy/README.md` changes accordingly.

## Out of Scope

- A release or tag workflow, and publishing to a public registry.
- Installing on a real cluster.
- Multi-architecture images. The script builds for the machine it runs on.
- Changing the chart, its values or the names the management API gives participants' images.
- Changing the local environment, which keeps loading `dataspace/<name>:dev` into kind.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: none affected. It doesn't describe how images are built or published.
- `deploy/README.md`: "What you need first" describes the script and the matching `images.*` values.
- CI (`.github/workflows/services.yml`): a new job runs shellcheck and the script with `--build-only`.
- New files: `scripts/build-images.sh` and `scripts/build-images.env.example`. `.gitignore` gains `scripts/build-images.env`.

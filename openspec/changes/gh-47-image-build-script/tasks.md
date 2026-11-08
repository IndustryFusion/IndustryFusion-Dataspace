# Tasks

## 1. Script

- [ ] 1.1 Write `scripts/build-images.sh` with the IndustryFusion Foundation header: the six images and their builds, defaults, `--build-only`, `--list`, `--help` and named images; verify with `shellcheck` and the tests in 2.1
- [ ] 1.2 Read `REGISTRY`, `REPO` and `VERSION` from the shell, then `scripts/build-images.env` or `BUILD_IMAGES_CONFIG`, then the defaults, parsing the file without running it; add `scripts/build-images.env.example` and ignore `scripts/build-images.env`; verify with the tests in 2.1 and `git check-ignore`
- [ ] 1.3 Print the targets first; stop at the first failed build or push with the image and step; refuse an unknown name, an empty `REPO` or `VERSION`, an empty `REGISTRY` when pushing, and a missing `docker`; verify with the tests in 2.1

## 2. Tests

- [ ] 2.1 Add a test for the script that runs it with a stand-in `docker` on `PATH`, recording the calls and failing on request. It covers defaults, the file and its precedence, a file line that isn't `KEY=value` and is not run, a missing named file, named images, build-only, list, unknown names, empty settings, failed builds and pushes, and no Docker. Verify it fails against a script that ignores the file or the arguments
- [ ] 2.2 Add a check that renders the chart with given `images.*` values and compares its four images and the `MAIN_*` names for `adapter` and `connector` with `--list`; verify it fails when a name or value differs
- [ ] 2.3 Add a CI job that runs shellcheck, the tests in 2.1, the check in 2.2 and `--build-only`; verify on the Pull Request

## 3. End to end

- [ ] 3.1 With no settings, run the script against a `registry:2` container reachable as `k3d-iff.localhost:12345`, and list the six `latest` tags in the registry; verify on a local machine
- [ ] 3.2 With `REGISTRY`, `REPO` and `VERSION=1.2.3`, push to a local `registry:2` container, pull each image back, start the `management` image and read the UI from it; verify on a local machine
- [ ] 3.3 Stop the registry and run the script; check it exits non-zero, naming the first image's push; verify on a local machine

## 4. Documents

- [ ] 4.1 Update "What you need first" in `deploy/README.md`: building and pushing with the script, the config file, and setting `images.registry`, `images.repo` and `images.version` to match; verify by following it on a local machine

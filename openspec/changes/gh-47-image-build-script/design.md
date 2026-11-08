# Design

## Context

The chart names each fixed service's image `[<images.registry>/]<images.repo>/<component>:<images.version>`, leaving out the registry when it is empty. It also passes the same three values to the management API as `MAIN_REGISTRY`, `MAIN_REPO` and `MAIN_VERSION`, and the API names participants' `adapter` and `connector` images the same way. So the chart renders four images directly and the other two through those variables. `values/common.yaml` sets `registry: ""`, `repo: dataspace` and `version: dev`.

The earlier `scripts/build-images.sh` from the previous codebase built the six images and pushed `<REGISTRY>/<REPO>/<name>:<VERSION>`, defaulting to `k3d-iff.localhost:12345`, `dataspace` and `latest`. This change matches that behaviour and adds what the issue asks for: a config file, named images and build-only. The script is written new for this repository, and no code is taken from the earlier one.

## Decisions

### The images and how each is built

| Name | Build |
|---|---|
| `gateway`, `dsp-gateway`, `registry`, `adapter`, `connector` | the folder of that name, with its own `Dockerfile` |
| `management` | the `management` folder, with `management/api/Dockerfile`, which builds the UI into the image |

These are the same builds CI and `scripts/local-env.sh` already run. The names are the chart's component names and the API's participant image names, so `<REGISTRY>/<REPO>/<name>:<VERSION>` is what the chart renders with `images.registry=<REGISTRY>`, `images.repo=<REPO>` and `images.version=<VERSION>`.

Alternative: reading the list from the chart or the services' folders. Rejected because it adds parsing for six fixed names. A test checks the list against what the chart and the API render instead.

### Command line

`scripts/build-images.sh [--build-only] [<name> ...]`, plus `--help`.

- With no names, all six are built, in the order of the table.
- Names may be given in any order, are built in the given order, and a repeated name is built once.
- An unknown name or option stops the script before anything is built. It names what is unknown and lists the valid names.

Alternative: selecting images through a variable such as `IMAGES=...`. Rejected because arguments are what the issue describes, and they show up in the shell history as given.

### Configuration and precedence

The script reads `REGISTRY`, `REPO` and `VERSION` from each of these sources in turn, and the first source that has a key gives its value:

1. A variable set in the shell, including one set to an empty string.
2. The config file `scripts/build-images.env`, if it exists.
3. The defaults: `k3d-iff.localhost:12345`, `dataspace` and `latest`.

`BUILD_IMAGES_CONFIG` names a different config file. If it names a file that doesn't exist, that is an error. The default file may simply be missing.

The file is read as data, one `KEY=value` line each, with blank lines and `#` comments allowed. It is never run as shell. Lines for other keys, or lines that aren't `KEY=value`, stop the script with the file's name and line number. A file in `scripts/` is easy to edit, but the script would run whatever a sourced file contains, so the file is parsed instead.

`scripts/build-images.env` is git-ignored. `scripts/build-images.env.example` is committed and shows the three keys with their defaults.

Alternatives:
- **Sourcing the file.** Simpler, but it runs the file as code.
- **Only shell variables.** The issue asks for a file.
- **Command-line options for the values.** These can be added later. Variables and the file cover the issue.

### An empty registry

An empty `REPO` or `VERSION` is refused, because the chart would render an invalid name.

An empty `REGISTRY` means no registry prefix, `<REPO>/<name>:<VERSION>`, as the chart renders it. That is allowed with `--build-only`, which then gives names such as `dataspace/gateway:dev`, the names the local environment uses. Pushing with an empty `REGISTRY` is refused before anything is built, because Docker would push to Docker Hub, and publishing to a public registry is out of scope.

Alternative: allowing the push. Rejected, because a missing setting would quietly publish to a public registry.

### Output and failures

- Before building, the script prints the full name of each target. It then prints each step as it starts: building, tagging where needed, and pushing.
- The script runs with `set -euo pipefail`.
- If a build, tag or push fails, the script stops at once, without going on to the next image. The last line it prints names the image and the step, for example `Failed: push of k3d-iff.localhost:12345/dataspace/adapter:latest`, and it exits non-zero.
- Images already pushed stay pushed. The script doesn't try to undo anything.
- If `docker` can't be found, the script stops before building.

Alternative: building everything and reporting all failures at the end. Rejected, because the issue asks it to stop on the first failure.

### Tagging

Each image is built with its full name as the tag, so no separate tag step is needed. `docker build` uses the build cache. The script doesn't pass `--pull` or `--no-cache`, and a clean build is left to the operator.

### CI

A new job in `services.yml`:
- runs `shellcheck scripts/build-images.sh`;
- runs `scripts/build-images.sh --build-only` with `REGISTRY` set to an example host, so it builds all six images through the script;
- runs a check that the names the script prints for some `REGISTRY`, `REPO` and `VERSION` are the ones a `helm template` with the same values renders, together with the `MAIN_*` variables for `adapter` and `connector`.

The script prints the target names with `--list`, which builds nothing. The check uses it, and it is documented.

The script's tests are a Python script in `scripts/`. They run the script with a stand-in `docker` first on `PATH`, which records each call and can be made to fail. They run directly, the way the contract suite's `--self-test` does, so no new test framework is added.

The existing per-service image builds stay as they are, so this change doesn't alter what fails when a service's image breaks. That builds each image twice in CI.

Alternative: replacing the per-service builds with the new job. This would save CI time but change the existing "CI for services" checks, so it is left for the maintainer to decide.

### Pushing in tests

The issue's acceptance criteria say the push is checked against a local registry container (`registry:2`). That check is a verification task run by hand, and CI doesn't push. Adding a registry service to CI is possible, but the issue asks only for build-only in CI.

## Conflicts with existing documents and specs

- The script's default version is `latest`, but `values/common.yaml` sets `images.version: dev`, and its registry default differs from the chart's empty one. This isn't a conflict, because the operator sets both to the same values. `deploy/README.md` will say so explicitly.
- The `project-foundations` requirement "CI for services" is unchanged. The new job adds to it.

## Risks

- A wrong `REGISTRY` pushes to an unexpected registry. The printed names before the build, and the refusal of an empty registry, reduce this.
- The script relies on the build layout in the table. A test compares it with the chart and the API, so a renamed service fails CI.

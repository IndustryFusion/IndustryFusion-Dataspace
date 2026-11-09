#!/usr/bin/env bash
#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Builds the dataspace images and pushes them as <LOCAL_REGISTRY>/<MAIN_REPO>/<name>:<MAIN_VERSION>, the names the
# charts in helm/ render from the same variables. Run `source helm/env.sh` first to use its settings. See
# helm/README.md.
#
# Uses nothing but bash and docker, so its tests can run it with a stand-in docker alone on PATH.

set -euo pipefail

# The script is written for bash 4.3 or later. Checked first, with nothing newer used before.
if [ "${BASH_VERSINFO[0]}" -lt 4 ] || { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 3 ]; }; then
  echo "build-images: needs bash 4.3 or later, and this is bash $BASH_VERSION. On macOS, install a newer bash, for example with Homebrew, and run: bash scripts/build-images.sh" >&2
  exit 1
fi

usage() {
  local line
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'TEXT'
Usage: scripts/build-images.sh [--build-only | --list] [<name> ...]

Builds the dataspace images and pushes each as <LOCAL_REGISTRY>/<MAIN_REPO>/<name>:<MAIN_VERSION>.

  <name>        Build only these: gateway, dsp-gateway, registry, management, adapter, connector.
                Without names, all six are built.
  --build-only  Build and name the images, but push nothing.
  --list        Print the full name of each image, and build nothing.
  --help        Show this text.

Settings, from the shell, where `source helm/env.sh` sets them for the charts too. Unset, they have these
defaults. Set, even empty, they are used as they are:

  LOCAL_REGISTRY  k3d-iff.localhost:12345   host[:port], with an optional path. Empty means no prefix.
                                            Pushing needs one.
  MAIN_REPO       dataspace                 Lowercase path parts, such as team/dataspace.
  MAIN_VERSION    latest                    A tag: letters, digits, _ . and -, up to 128, not starting with . or -.
TEXT
}

stop() {
  printf 'build-images: %s\n' "$1" >&2
  exit 1
}

# The script's own folder, without calling dirname, so no tool beyond docker is needed.
here="${BASH_SOURCE[0]}"
if [[ "$here" == */* ]]; then here="${here%/*}"; else here="."; fi
root="$(cd "$here/.." && pwd)"

all_images=(gateway dsp-gateway registry management adapter connector)

# --- Arguments ---

mode=push
chosen=()
for argument in "$@"; do
  case "$argument" in
    --help | -h)
      usage
      exit 0
      ;;
    --build-only)
      [[ "$mode" == list ]] && stop "--build-only and --list can't be used together"
      mode=build
      ;;
    --list)
      [[ "$mode" == build ]] && stop "--build-only and --list can't be used together"
      mode=list
      ;;
    -*)
      stop "Unknown option: $argument. See --help."
      ;;
    *)
      known=no
      for image in "${all_images[@]}"; do [[ "$image" == "$argument" ]] && known=yes; done
      [[ "$known" == yes ]] || stop "Unknown image: $argument. The images are: ${all_images[*]}"
      seen=no
      for image in "${chosen[@]+"${chosen[@]}"}"; do [[ "$image" == "$argument" ]] && seen=yes; done
      [[ "$seen" == yes ]] || chosen+=("$argument")
      ;;
  esac
done
[[ ${#chosen[@]} -gt 0 ]] || chosen=("${all_images[@]}")

# --- Settings ---

# helm/env.sh sets these for the charts too. A variable set in the shell, even empty, wins over its default.
old_names=()
for key in REGISTRY REPO VERSION; do
  if [[ -v $key ]]; then old_names+=("$key"); fi
done
if [[ ${#old_names[@]} -gt 0 ]]; then
  printf 'build-images: %s set, but not read. The script reads LOCAL_REGISTRY, MAIN_REPO and MAIN_VERSION, which helm/env.sh sets.\n' "${old_names[*]}" >&2
fi

# Where a setting came from, for messages about it.
origin() {
  if [[ -v $1 ]]; then printf 'set in the shell'; else printf 'the default'; fi
}
registry="${LOCAL_REGISTRY-k3d-iff.localhost:12345}"
repo="${MAIN_REPO-dataspace}"
version="${MAIN_VERSION-latest}"

[[ -n "$repo" ]] || stop "MAIN_REPO is empty ($(origin MAIN_REPO)). It names the repository, such as dataspace."
[[ -n "$version" ]] || stop "MAIN_VERSION is empty ($(origin MAIN_VERSION)). It is the tag, such as latest or 1.2.3."

# The forms Docker accepts in an image reference. A path part is lowercase letters and digits, joined by
# one . or _, two _, or any number of -.
path_part='[a-z0-9]+(([._]|__|-+)[a-z0-9]+)*'
host_part='[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?'
registry_form="^${host_part}(\.${host_part})*(:[0-9]+)?(/${path_part})*\$"
repo_form="^${path_part}(/${path_part})*\$"
version_form='^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'

if [[ -n "$registry" ]]; then
  if [[ ! "$registry" =~ $registry_form ]]; then
    stop "LOCAL_REGISTRY is not a registry address ($(origin LOCAL_REGISTRY)): '$registry'. Use host or host:port, optionally with a lowercase path, without a trailing slash or spaces, such as registry.example.com:5000."
  fi
  if [[ "$registry" =~ :([0-9]+)(/|$) ]] && { [[ ${#BASH_REMATCH[1]} -gt 5 ]] || ((10#${BASH_REMATCH[1]} < 1 || 10#${BASH_REMATCH[1]} > 65535)); }; then
    stop "LOCAL_REGISTRY has a port outside 1 to 65535 ($(origin LOCAL_REGISTRY)): '$registry'."
  fi
fi
if [[ ! "$repo" =~ $repo_form ]]; then
  stop "MAIN_REPO is not a repository path ($(origin MAIN_REPO)): '$repo'. Use lowercase letters, digits and . _ - in parts joined by /, such as team/dataspace."
fi
if [[ ! "$version" =~ $version_form ]]; then
  stop "MAIN_VERSION is not a tag ($(origin MAIN_VERSION)): '$version'. Use up to 128 letters, digits, _ . and -, not starting with . or -, such as 1.2.3."
fi
if [[ -z "$registry" && "$mode" == push ]]; then
  stop "LOCAL_REGISTRY is empty ($(origin LOCAL_REGISTRY)), and pushing needs one: without it, docker would push to Docker Hub. Set LOCAL_REGISTRY, or use --build-only."
fi

# Docker refuses a name, without its tag, of more than 255 characters.
for image in "${chosen[@]}"; do
  if [[ -n "$registry" ]]; then name="$registry/$repo/$image"; else name="$repo/$image"; fi
  if [[ ${#name} -gt 255 ]]; then
    stop "The image name $name is ${#name} characters long, and Docker allows 255. Shorten LOCAL_REGISTRY ($(origin LOCAL_REGISTRY)) or MAIN_REPO ($(origin MAIN_REPO))."
  fi
done

full_name() {
  if [[ -n "$registry" ]]; then
    printf '%s/%s/%s:%s' "$registry" "$repo" "$1" "$version"
  else
    printf '%s/%s:%s' "$repo" "$1" "$version"
  fi
}

# --- Listing ---

if [[ "$mode" == list ]]; then
  for image in "${chosen[@]}"; do printf '%s\n' "$(full_name "$image")"; done
  exit 0
fi

# --- Building and pushing ---

if [[ "$mode" == push ]]; then echo "Images to build and push:"; else echo "Images to build, without pushing:"; fi
for image in "${chosen[@]}"; do printf '  %s\n' "$(full_name "$image")"; done

command -v docker >/dev/null 2>&1 || stop "docker was not found on PATH. It is needed to build the images."

for image in "${chosen[@]}"; do
  name="$(full_name "$image")"
  echo "Building $name"
  if [[ "$image" == management ]]; then
    # The API's Dockerfile builds the UI too, so it is built from the folder holding both.
    docker build -t "$name" -f "$root/management/api/Dockerfile" "$root/management" ||
      stop "Failed: build of $name"
  else
    docker build -t "$name" "$root/$image" || stop "Failed: build of $name"
  fi
done

if [[ "$mode" == push ]]; then
  for image in "${chosen[@]}"; do
    name="$(full_name "$image")"
    echo "Pushing $name"
    docker push "$name" || stop "Failed: push of $name"
  done
  echo "Pushed ${#chosen[@]} images."
else
  echo "Built ${#chosen[@]} images. Nothing was pushed."
fi

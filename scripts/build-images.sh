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

# Builds the dataspace images and pushes them as <REGISTRY>/<REPO>/<name>:<VERSION>, the names the chart
# renders from images.registry, images.repo and images.version. See deploy/README.md.
#
# Uses nothing but bash and docker, so its tests can run it with a stand-in docker alone on PATH.

set -euo pipefail

usage() {
  local line
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'TEXT'
Usage: scripts/build-images.sh [--build-only | --list] [<name> ...]

Builds the dataspace images and pushes each as <REGISTRY>/<REPO>/<name>:<VERSION>.

  <name>        Build only these: gateway, dsp-gateway, registry, management, adapter, connector.
                Without names, all six are built.
  --build-only  Build and name the images, but push nothing.
  --list        Print the full name of each image, and build nothing.
  --help        Show this text.

Settings, from the shell first, then the config file, then the defaults:

  REGISTRY  k3d-iff.localhost:12345   Empty means no prefix. Pushing needs one.
  REPO      dataspace
  VERSION   latest

The config file is scripts/build-images.env, or the file BUILD_IMAGES_CONFIG names. It holds KEY=value
lines for those three keys, with blank lines and # comments. It is read, never run.
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

# Which settings the shell gives, even empty. Those win over the file.
declare -A from_shell=()
for key in REGISTRY REPO VERSION; do
  if [[ -v $key ]]; then from_shell[$key]=1; fi
done

declare -A from_file=()
if [[ -v BUILD_IMAGES_CONFIG ]]; then
  config="$BUILD_IMAGES_CONFIG"
  [[ -e "$config" ]] || stop "The config file BUILD_IMAGES_CONFIG names doesn't exist: $config"
  [[ -r "$config" && ! -d "$config" ]] || stop "The config file BUILD_IMAGES_CONFIG names can't be read: $config"
else
  config="$root/scripts/build-images.env"
fi
if [[ -e "$config" ]]; then
  [[ -r "$config" && ! -d "$config" ]] || stop "The config file can't be read: $config"
  number=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    number=$((number + 1))
    line="${line%$'\r'}"
    trimmed="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$trimmed" || "$trimmed" == \#* ]] && continue
    if [[ "$trimmed" =~ ^(REGISTRY|REPO|VERSION)=(.*)$ ]]; then
      value="${BASH_REMATCH[2]}"
      value="${value%"${value##*[![:space:]]}"}"
      # A value may be quoted. Nothing in it is expanded.
      if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
      key="${trimmed%%=*}"
      from_file[$key]="$value"
    else
      stop "$config, line $number: expected REGISTRY=, REPO= or VERSION=, not: $trimmed"
    fi
  done <"$config"
fi

setting() {
  local key="$1" default="$2"
  if [[ -n "${from_shell[$key]:-}" ]]; then
    printf '%s' "${!key}"
  elif [[ -v "from_file[$key]" ]]; then
    printf '%s' "${from_file[$key]}"
  else
    printf '%s' "$default"
  fi
}
registry="$(setting REGISTRY k3d-iff.localhost:12345)"
repo="$(setting REPO dataspace)"
version="$(setting VERSION latest)"

[[ -n "$repo" ]] || stop "REPO is empty. It names the repository, such as dataspace."
[[ -n "$version" ]] || stop "VERSION is empty. It is the tag, such as latest or 1.2.3."
if [[ -z "$registry" && "$mode" == push ]]; then
  stop "REGISTRY is empty, and pushing needs one: without it, docker would push to Docker Hub. Set REGISTRY, or use --build-only."
fi

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

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
# Prepares a cluster for the dataspace, and removes it again. See helm/README.md.
# It acts on the cluster that KUBECONFIG points at, and shows which one before changing anything.
# tools checks Helm and installs helmfile and the helm-diff plugin. helmfile does the same without helm-diff, which
# only helmfile diff and apply need. Neither touches a cluster.
#
# Usage: helm/bootstrap.sh tools | helmfile | up | down

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$HERE/.tools"
# shellcheck source-path=SCRIPTDIR source=env.sh
source "$HERE/env.sh"
SERVICES_NAMESPACE="$NAMESPACE"
export PATH="$TOOLS:$PATH"

# The checksum of each helmfile archive this script will download, by version and platform. Another version needs
# its checksums added here, from the release's checksums file.
helmfile_sha256() {
  case "$1/$2" in
    0.169.2/linux_amd64) echo 34a5ca9c5fda733f0322f7b12a2959b7de4ab125bcf6531337751e263b027d58 ;;
    0.169.2/linux_arm64) echo 49332b6b685de1a08a481dfe57fd1ce8f9ae9df4d73485d14830dedb5a05c157 ;;
    0.169.2/darwin_amd64) echo 477c1e8badf63af1189e898994de9309d808613f49a058e904c2a46b0cdf70e4 ;;
    0.169.2/darwin_arm64) echo f049e4e4c8d484a66e0179caf3895728167920d2f9202f24c28280ef17a739e0 ;;
    *) return 1 ;;
  esac
}

# The platform part of a helmfile archive's name: linux or darwin, amd64 or arm64.
platform() {
  local os arch
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) echo "No helmfile is set up here for $(uname -s). Install helmfile $HELMFILE_VERSION yourself." >&2; exit 1 ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=amd64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) echo "No helmfile is set up here for $(uname -m). Install helmfile $HELMFILE_VERSION yourself." >&2; exit 1 ;;
  esac
  echo "${os}_${arch}"
}

sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | awk '{ print $1 }'
}

# Whether version $1 is at least $2, comparing major, minor and patch.
at_least() {
  local IFS=.
  # shellcheck disable=SC2206
  local have=($1) want=($2) index
  for index in 0 1 2; do
    if [ "${have[index]:-0}" -gt "${want[index]:-0}" ]; then return 0; fi
    if [ "${have[index]:-0}" -lt "${want[index]:-0}" ]; then return 1; fi
  done
  return 0
}

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
  done
}

check_helm() {
  need kubectl helm curl tar gzip uname grep awk
  local current_helm
  current_helm=$(helm version --template '{{.Version}}' 2>/dev/null)
  current_helm="${current_helm#v}"
  current_helm="${current_helm%%+*}"
  if ! at_least "$current_helm" "$HELM_VERSION"; then
    echo "Helm $current_helm is older than HELM_VERSION, $HELM_VERSION. Install a newer Helm." >&2
    exit 1
  fi
  echo "Helm $current_helm"
}

# helmfile HELMFILE_VERSION, from PATH if that is the version, or else downloaded to .tools, checked against its
# checksum. .tools comes first on PATH here and in the scripts, so the pinned one is used.
install_helmfile() {
  local found=""
  if command -v helmfile >/dev/null; then
    found=$(helmfile --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
  fi
  if [ "$found" = "$HELMFILE_VERSION" ]; then
    echo "helmfile $found is present: $(command -v helmfile)"
    return
  fi
  local where sha256
  where=$(platform)
  sha256=$(helmfile_sha256 "$HELMFILE_VERSION" "$where") || {
    echo "No checksum is known for helmfile $HELMFILE_VERSION on $where, so it isn't downloaded. Add it to helm/bootstrap.sh." >&2
    exit 1
  }
  if [ -n "$found" ]; then echo "helmfile $found is on PATH, and HELMFILE_VERSION is $HELMFILE_VERSION."; fi
  mkdir -p "$TOOLS"
  local archive="$TOOLS/helmfile.tgz"
  curl -fsSL -o "$archive" \
    "https://github.com/helmfile/helmfile/releases/download/v$HELMFILE_VERSION/helmfile_${HELMFILE_VERSION}_${where}.tar.gz"
  if [ "$(sha256_of "$archive")" != "$sha256" ]; then
    rm -f "$archive"
    echo "The helmfile archive doesn't match its checksum, so it isn't installed." >&2
    exit 1
  fi
  tar -xzf "$archive" -C "$TOOLS" helmfile
  rm -f "$archive"
  echo "Installed helmfile $HELMFILE_VERSION in $TOOLS. Add it to PATH to run helmfile yourself."
}

# helmfile diff and helmfile apply need it. A version already installed is left as it is.
install_helm_diff() {
  local installed current_helm
  installed=$(helm plugin list 2>/dev/null | awk '$1 == "diff" { print $2 }')
  if [ -n "$installed" ]; then
    # helmfile.yaml.gotmpl gives helm-diff --dry-run=server, which it takes from 3.9.4.
    if ! at_least "$installed" 3.9.4; then
      echo "helm-diff $installed is older than 3.9.4, which helmfile diff and apply need here. Run: helm plugin update diff" >&2
      exit 1
    fi
    echo "helm-diff $installed is present"
    return
  fi
  current_helm=$(helm version --template '{{.Version}}' 2>/dev/null)
  local verify=()
  case "$current_helm" in v3.*) ;; *) verify=(--verify=false) ;; esac
  helm plugin install https://github.com/databus23/helm-diff --version "v$HELM_DIFF_PLUGIN" "${verify[@]}" >/dev/null
  echo "Installed helm-diff $HELM_DIFF_PLUGIN"
}

install_tools() {
  check_helm
  install_helmfile
  install_helm_diff
}

up() {
  install_tools
  echo "Cluster: $(kubectl config current-context)"
  for namespace in "$SERVICES_NAMESPACE" "$PARTICIPANTS_NAMESPACE"; do
    kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl label namespace "$namespace" app.kubernetes.io/part-of=dataspace --overwrite >/dev/null
  done
  echo "Namespaces are ready: $SERVICES_NAMESPACE, $PARTICIPANTS_NAMESPACE"
}

down() {
  check_helm
  install_helmfile
  echo "Cluster: $(kubectl config current-context)"
  local left
  left=$(kubectl -n "$PARTICIPANTS_NAMESPACE" get deployments -l app.kubernetes.io/managed-by=dataspace-management \
    -o name 2>/dev/null | wc -l)
  if [ "$left" -gt 0 ]; then
    echo "Note: $left participant Deployments remain. Their databases, buckets and Keycloak clients stay behind," >&2
    echo "as they are outside these namespaces. Use DELETE /api/participants/{id} first to remove those too." >&2
  fi
  (cd "$HERE" && helmfile -e default destroy)
  kubectl -n "$PARTICIPANTS_NAMESPACE" delete deployments,services,secrets,configmaps \
    -l app.kubernetes.io/managed-by=dataspace-management --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kubectl delete namespace "$PARTICIPANTS_NAMESPACE" "$SERVICES_NAMESPACE" --ignore-not-found --wait=true
  echo "The dataspace is removed from this cluster."
  echo "What stays, as it is outside these namespaces: the registry database with its entries, participants' databases,"
  echo "buckets and Keycloak clients, the realm, and PostgreSQL, S3 storage and Keycloak themselves."
}

case "${1:-}" in
  tools) install_tools ;;
  helmfile) check_helm && install_helmfile ;;
  up) up ;;
  down) down ;;
  *) echo "Usage: $0 tools | helmfile | up | down" >&2; exit 2 ;;
esac

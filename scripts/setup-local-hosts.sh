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
#
# Adds or removes the host entries used to reach the local environment by name.
# Set HOSTS_FILE to act on a file other than /etc/hosts.
#
# Usage: scripts/setup-local-hosts.sh add | remove

set -euo pipefail

HOSTS_FILE="${HOSTS_FILE:-/etc/hosts}"
BEGIN="# BEGIN dataspace local environment"
END="# END dataspace local environment"
NAMES="keycloak-service.iff gateway.dataspace.local management.dataspace.local"

write() {
  if [ -w "$HOSTS_FILE" ]; then cat > "$HOSTS_FILE"; else sudo tee "$HOSTS_FILE" >/dev/null; fi
}

without_block() {
  sed "/^$BEGIN\$/,/^$END\$/d" "$HOSTS_FILE"
}

case "${1:-}" in
  add)
    content=$({ without_block; echo "$BEGIN"; for name in $NAMES; do echo "127.0.0.1 $name"; done; echo "$END"; })
    printf '%s\n' "$content" | write
    ;;
  remove)
    content=$(without_block)
    printf '%s\n' "$content" | write
    ;;
  *)
    echo "Usage: $0 add | remove" >&2
    exit 2
    ;;
esac

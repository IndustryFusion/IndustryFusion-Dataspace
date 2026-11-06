#!/usr/bin/env python3
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
"""Sets up the dataspace realm described in keycloak.md. Safe to repeat."""

import argparse
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

REALM = "dataspace"
ADMIN_ROLE = "dataspace-admin"
ADMIN_CLIENT = "dataspace-admin-cli"
IFRIC_CLIENT = "dataspace-ifric-reader"
MANAGEMENT_ROLES = ["manage-clients", "manage-realm", "manage-users"]


class Keycloak:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.changes = 0
        body = urllib.parse.urlencode(
            {"grant_type": "password", "client_id": "admin-cli", "username": user, "password": password}
        ).encode()
        request = urllib.request.Request(f"{self.url}/realms/master/protocol/openid-connect/token", body)
        with urllib.request.urlopen(request) as response:
            self.token = json.load(response)["access_token"]

    def call(self, method: str, path: str, payload: object | None = None) -> object | None:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(f"{self.url}/admin{path}", data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def exists(self, path: str) -> bool:
        try:
            self.call("GET", path)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return False
            raise
        return True

    def ensure_realm(self) -> None:
        if not self.exists(f"/realms/{REALM}"):
            self.call("POST", "/realms", {"realm": REALM, "enabled": True})
            self.changes += 1

    def ensure_role(self) -> None:
        if not self.exists(f"/realms/{REALM}/roles/{ADMIN_ROLE}"):
            self.call("POST", f"/realms/{REALM}/roles", {"name": ADMIN_ROLE})
            self.changes += 1

    def client_uuid(self, client_id: str) -> str | None:
        found = self.call("GET", f"/realms/{REALM}/clients?clientId={urllib.parse.quote(client_id)}")
        return found[0]["id"] if found else None

    def ensure_service_client(self, client_id: str) -> str:
        uuid = self.client_uuid(client_id)
        if uuid is None:
            self.call(
                "POST",
                f"/realms/{REALM}/clients",
                {
                    "clientId": client_id,
                    "publicClient": False,
                    "serviceAccountsEnabled": True,
                    "standardFlowEnabled": False,
                    "directAccessGrantsEnabled": False,
                },
            )
            self.changes += 1
            uuid = self.client_uuid(client_id)
        return uuid

    def grant_admin_roles(self, client_uuid: str) -> None:
        realm_path = f"/realms/{REALM}"
        user = self.call("GET", f"{realm_path}/clients/{client_uuid}/service-account-user")["id"]

        held = self.call("GET", f"{realm_path}/users/{user}/role-mappings/realm")
        if ADMIN_ROLE not in {role["name"] for role in held}:
            role = self.call("GET", f"{realm_path}/roles/{ADMIN_ROLE}")
            self.call("POST", f"{realm_path}/users/{user}/role-mappings/realm", [role])
            self.changes += 1

        management = self.client_uuid("realm-management")
        mapping = f"{realm_path}/users/{user}/role-mappings/clients/{management}"
        held = {role["name"] for role in self.call("GET", mapping)}
        missing = [name for name in MANAGEMENT_ROLES if name not in held]
        if missing:
            roles = [self.call("GET", f"{realm_path}/clients/{management}/roles/{name}") for name in missing]
            self.call("POST", mapping, roles)
            self.changes += 1

    def client_secret(self, client_uuid: str) -> str:
        return self.call("GET", f"/realms/{REALM}/clients/{client_uuid}/client-secret")["value"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Keycloak base URL, including any path such as /auth")
    parser.add_argument("--secret-file", help="Write the admin client's secret to this file")
    parser.add_argument("--with-ifric-reader", action="store_true", help="Also create the optional reader client")
    args = parser.parse_args()

    keycloak = Keycloak(args.url, os.environ["KEYCLOAK_ADMIN_USER"], os.environ["KEYCLOAK_ADMIN_PASSWORD"])
    keycloak.ensure_realm()
    keycloak.ensure_role()
    admin_client = keycloak.ensure_service_client(ADMIN_CLIENT)
    keycloak.grant_admin_roles(admin_client)
    if args.with_ifric_reader:
        keycloak.ensure_service_client(IFRIC_CLIENT)

    if args.secret_file:
        path = pathlib.Path(args.secret_file)
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(keycloak.client_secret(admin_client))

    print(f"Realm {REALM} is set up. Changes made: {keycloak.changes}")


if __name__ == "__main__":
    main()

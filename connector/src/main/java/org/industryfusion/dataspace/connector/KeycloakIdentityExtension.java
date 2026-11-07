//
// Copyright (c) 2026 IndustryFusion Foundation
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
package org.industryfusion.dataspace.connector;

import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Provider;
import org.eclipse.edc.spi.iam.AudienceResolver;
import org.eclipse.edc.spi.iam.IdentityService;
import org.eclipse.edc.spi.result.Result;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.spi.types.TypeManager;

/** A connector proves who it is with a token from its participant's own Keycloak client. See keycloak.md. */
public class KeycloakIdentityExtension implements ServiceExtension {

    private static final String KEYCLOAK_URL_SETTING = "dataspace.keycloak.url";
    private static final String KEYCLOAK_REALM_SETTING = "dataspace.keycloak.realm";
    private static final String CLIENT_SECRET_SETTING = "dataspace.keycloak.client.secret";

    @Inject
    private TypeManager typeManager;

    @Override
    public String name() {
        return "Keycloak identity";
    }

    @Provider
    public IdentityService identityService(ServiceExtensionContext context) {
        var config = context.getConfig();
        var issuer = config.getString(KEYCLOAK_URL_SETTING).replaceAll("/+$", "")
                + "/realms/" + config.getString(KEYCLOAK_REALM_SETTING);
        return new KeycloakIdentityService(
                issuer,
                context.getParticipantId(),
                config.getString(CLIENT_SECRET_SETTING),
                typeManager.getMapper(),
                context.getMonitor());
    }

    @Provider
    public AudienceResolver audienceResolver() {
        return message -> Result.success(message.getCounterPartyAddress());
    }
}

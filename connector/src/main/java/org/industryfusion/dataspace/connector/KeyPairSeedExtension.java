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

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;

import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.EdcException;
import org.eclipse.edc.spi.security.Vault;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;

/** Puts a new RSA key pair for the data plane into the in-memory vault at each start. */
public class KeyPairSeedExtension implements ServiceExtension {

    private static final String PRIVATE_ALIAS_SETTING = "edc.transfer.proxy.token.signer.privatekey.alias";
    private static final String PUBLIC_ALIAS_SETTING = "edc.transfer.proxy.token.verifier.publickey.alias";
    private static final int KEY_BITS = 2048;

    @Inject
    private Vault vault;

    @Override
    public String name() {
        return "Data plane key pair seed";
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        var config = context.getConfig();
        var keys = generate();
        vault.storeSecret(config.getString(PRIVATE_ALIAS_SETTING), pem("PRIVATE KEY", keys.getPrivate().getEncoded()));
        vault.storeSecret(config.getString(PUBLIC_ALIAS_SETTING), pem("PUBLIC KEY", keys.getPublic().getEncoded()));
        context.getMonitor().info("Generated the data plane key pair");
    }

    private static KeyPair generate() {
        try {
            var generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(KEY_BITS);
            return generator.generateKeyPair();
        } catch (NoSuchAlgorithmException error) {
            throw new EdcException(error);
        }
    }

    private static String pem(String label, byte[] encoded) {
        var body = Base64.getMimeEncoder(64, new byte[] {'\n'}).encodeToString(encoded);
        return "-----BEGIN " + label + "-----\n" + body + "\n-----END " + label + "-----\n";
    }
}

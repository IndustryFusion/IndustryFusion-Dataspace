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

plugins {
    java
    id("com.gradleup.shadow") version "8.3.5"
}

val edcVersion = "0.9.0"

repositories {
    mavenCentral()
}

java {
    toolchain.languageVersion = JavaLanguageVersion.of(21)
}

dependencies {
    fun edc(module: String) = "org.eclipse.edc:$module:$edcVersion"

    implementation(edc("core-spi"))
    implementation(edc("boot-spi"))
    implementation("com.nimbusds:nimbus-jose-jwt:9.40")

    // Runtime and configuration
    runtimeOnly(edc("boot"))
    runtimeOnly(edc("connector-core"))
    runtimeOnly(edc("http"))
    runtimeOnly(edc("configuration-filesystem"))
    runtimeOnly(edc("api-observability"))

    // Control plane, with token-protected management API. Its DSP identity is in this project's extension
    runtimeOnly(edc("control-plane-core"))
    runtimeOnly(edc("control-plane-api"))
    runtimeOnly(edc("control-plane-api-client"))
    runtimeOnly(edc("management-api"))
    runtimeOnly(edc("auth-tokenbased"))
    runtimeOnly(edc("dsp"))

    // Data plane in the same process
    runtimeOnly(edc("control-api-configuration"))
    runtimeOnly(edc("data-plane-core"))
    runtimeOnly(edc("data-plane-http"))
    runtimeOnly(edc("data-plane-signaling-api"))
    runtimeOnly(edc("data-plane-signaling-client"))
    runtimeOnly(edc("data-plane-self-registration"))
    runtimeOnly(edc("data-plane-selector-core"))
    runtimeOnly(edc("transfer-data-plane-signaling"))

    // SQL stores
    runtimeOnly(edc("transaction-local"))
    runtimeOnly(edc("sql-pool-apache-commons"))
    runtimeOnly(edc("sql-bootstrapper"))
    runtimeOnly(edc("control-plane-sql"))
    runtimeOnly(edc("data-plane-store-sql"))
    runtimeOnly(edc("data-plane-instance-store-sql"))
    runtimeOnly(edc("accesstokendata-store-sql"))
    runtimeOnly("org.postgresql:postgresql:42.7.4")
}

tasks.shadowJar {
    archiveFileName = "connector.jar"
    mergeServiceFiles()
    manifest {
        attributes("Main-Class" to "org.eclipse.edc.boot.system.runtime.BaseRuntime")
    }
}

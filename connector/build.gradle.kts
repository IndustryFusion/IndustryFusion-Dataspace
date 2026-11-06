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
    runtimeOnly("org.eclipse.edc:boot:$edcVersion")
    runtimeOnly("org.eclipse.edc:connector-core:$edcVersion")
}

tasks.shadowJar {
    archiveFileName = "connector.jar"
    mergeServiceFiles()
    manifest {
        attributes("Main-Class" to "org.eclipse.edc.boot.system.runtime.BaseRuntime")
    }
}

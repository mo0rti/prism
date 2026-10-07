import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// The backend's address (gradle.properties). It reaches BuildConfig and nothing else.
val apiBaseUrl: String = providers.gradleProperty("apiBaseUrl").get()

// The shared API contract. A unit test checks the client against it.
val apiContract = rootProject.file("../shared/api-contracts/openapi.yml")

android {
    namespace = "com.example.prismgolden.mobileandroid"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.example.prismgolden.mobileandroid"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
    }

    buildTypes {
        release {
            // Shrinking and signing belong to the release setup the project owner chooses
            // (see the `deployment` skill's mobile note).
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests {
            // The Compose UI test runs on the JVM with Robolectric and needs the merged resources.
            isIncludeAndroidResources = true
            all {
                it.systemProperty("prism.apiContract", apiContract.absolutePath)
            }
        }
    }
    lint {
        abortOnError = true
        warningsAsErrors = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_21)
    }
}

// Only debug builds may use cleartext HTTP (src/debug), so a release build refuses an http base URL.
tasks.configureEach {
    if (name == "assembleRelease" || name == "bundleRelease") {
        doFirst {
            check(apiBaseUrl.startsWith("https://")) {
                "A release build needs an https apiBaseUrl (-PapiBaseUrl=https://...); cleartext HTTP is allowed in debug builds only."
            }
        }
    }
}

dependencies {
    // Compose
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.activity.compose)
    debugImplementation(libs.compose.ui.tooling)

    // Lifecycle
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.lifecycle.viewmodel.compose)

    // Coroutines
    implementation(libs.coroutines.android)

    // Network and serialization
    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)

    // Unit tests (JVM)
    testImplementation(libs.junit)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.snakeyaml)
    testImplementation(libs.robolectric)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
    debugImplementation(libs.compose.ui.test.manifest)
}

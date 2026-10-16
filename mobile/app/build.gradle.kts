plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// A release importing a model must explicitly pin its SHA-256. Debug builds
// may import a locally provided model for testing; this is NOT a signature.
val approvedModelSha256 = providers.gradleProperty("tervoroApprovedModelSha256")
    .orElse("")
    .get()
    .lowercase()
require(approvedModelSha256.isEmpty() || approvedModelSha256.matches(Regex("[0-9a-f]{64}"))) {
    "tervoroApprovedModelSha256 must be an exact 64-character SHA-256 digest"
}

android {
    namespace = "com.tervoro.capybara"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.tervoro.capybara"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "APPROVED_MODEL_SHA256", "\"$approvedModelSha256\"")

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
    }

    flavorDimensions += "runtime"
    productFlavors {
        create("demo") {
            dimension = "runtime"
            applicationIdSuffix = ".demo"
            versionNameSuffix = "-demo"
            buildConfigField("String", "RUNTIME_NAME", "\"Deterministic TAL demo\"")
        }
        create("litert") {
            dimension = "runtime"
            buildConfigField("String", "RUNTIME_NAME", "\"LiteRT-LM on-device\"")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging.resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
}

dependencies {
    implementation(project(":tal-core"))

    val composeBom = platform("androidx.compose:compose-bom:2026.08.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.fragment:fragment-ktx:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")

    "litertImplementation"("com.google.ai.edge.litertlm:litertlm-android:0.14.0")

    testImplementation(kotlin("test"))
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

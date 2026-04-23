plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.chaquopy)
}

android {
    namespace = "com.gpxpoienricher"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.gpxpoienricher"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
    buildFeatures {
        viewBinding = true
    }

    sourceSets {
        named("main") {
            assets.srcDirs("src/main/assets")
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip {
            install("requests>=2.28")
            install("gpxpy>=1.6")
            install("PyYAML>=6.0")
            install("babel")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("../../src")
        }
    }
}

// Sync original YAML profiles into assets before every build — single source of truth
tasks.register<Copy>("syncProfileAssets") {
    from("../../profiles")
    into("src/main/assets/profiles")
    include("*.yaml")
}
tasks.named("preBuild") { dependsOn("syncProfileAssets") }

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.lifecycle.livedata.ktx)
    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.navigation.fragment.ktx)
    implementation(libs.navigation.ui.ktx)
    implementation(libs.kotlinx.coroutines.android)
}

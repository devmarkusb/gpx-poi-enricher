import java.io.File
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.chaquopy)
}

/** Reads `project.version` from repo-root pyproject.toml and maps it to a monotonic versionCode. */
fun readVersionFromPyproject(pyproject: java.io.File): Pair<Int, String> {
    require(pyproject.exists()) { "Missing ${pyproject.absolutePath}" }
    val text = pyproject.readText()
    val m =
        Regex("""(?m)^version\s*=\s*"([^"]+)"""")
            .find(text)
            ?: error("No version = \"…\" line in pyproject.toml")
    val raw = m.groupValues[1]
    val semverCore = raw.split("+", limit = 2).first().split("-", limit = 2).first().trim()
    val parts = semverCore.split(".").map { it.toIntOrNull() ?: 0 }
    val major = parts.getOrElse(0) { 0 }
    val minor = parts.getOrElse(1) { 0 }
    val patch = parts.getOrElse(2) { 0 }
    val code = major * 1_000_000 + minor * 1_000 + patch
    require(code in 1..2_147_483_647) { "versionCode $code out of range for Google Play" }
    return Pair(code, raw)
}

val repoRoot = rootProject.projectDir.parentFile
val pyprojectToml = repoRoot.resolve("pyproject.toml")
val (playVersionCode, playVersionName) = readVersionFromPyproject(pyprojectToml)
val keystorePropertiesFile = rootProject.file("keystore.properties")

android {
    namespace = "com.gpxpoienricher"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.gpxpoienricher"
        minSdk = 26
        targetSdk = 34
        versionCode = playVersionCode
        versionName = playVersionName

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            val props = Properties()
            keystorePropertiesFile.inputStream().use { props.load(it) }
            create("release") {
                storeFile = rootProject.file(props.getProperty("storeFile")!!)
                storePassword = props.getProperty("storePassword")!!
                keyAlias = props.getProperty("keyAlias")!!
                keyPassword = props.getProperty("keyPassword")!!
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            ndk {
                debugSymbolLevel = "SYMBOL_TABLE"
            }
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
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

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    sourceSets {
        named("main") {
            assets.srcDirs("src/main/assets")
        }
    }
}

chaquopy {
    defaultConfig {
        // Chaquopy's bundled pip uses 'cgi' (removed in Python 3.13+); force 3.12 as build host.
        listOf(
            "/opt/homebrew/opt/python@3.12/bin/python3.12",
            "/usr/bin/python3.12",
        ).firstOrNull { File(it).canExecute() }?.let { buildPython(it) }
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

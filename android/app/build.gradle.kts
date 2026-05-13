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

fun loadOptionalLocalProperty(key: String): String? {
    val candidates = listOf(
        rootProject.file("local.properties"),
        repoRoot.resolve("local.properties"),
    )
    val f = candidates.firstOrNull { it.exists() } ?: return null
    return f.inputStream().use { stream ->
        Properties().apply { load(stream) }.getProperty(key)?.trim()?.takeIf { it.isNotEmpty() }
    }
}

val pyprojectToml = repoRoot.resolve("pyproject.toml")
val (playVersionCode, playVersionName) = readVersionFromPyproject(pyprojectToml)
val keystorePropertiesFile = rootProject.file("keystore.properties")

// AdMob / Play Billing overrides (optional keys in android/local.properties or repo-root local.properties):
//   admobAppId=ca-app-pub-XXXX~YYYY
//   admobBannerAdUnitId=ca-app-pub-XXXX/ZZZZ
//   removeAdsInappProductId=remove_ads
val admobAppId = loadOptionalLocalProperty("admobAppId")
    ?: "ca-app-pub-3940256099942544~3347511713"
val admobBannerUnitId = loadOptionalLocalProperty("admobBannerAdUnitId")
    ?: "ca-app-pub-3940256099942544/6300978111"
val removeAdsProductId = loadOptionalLocalProperty("removeAdsInappProductId") ?: "remove_ads"

android {
    namespace = "com.gpxpoienricher"
    compileSdk = 35

    defaultConfig {
        // Play Store application id (Kotlin sources remain under `namespace` above).
        applicationId = "org.cismypa.gpxpoienricher"
        minSdk = 26
        targetSdk = 35
        versionCode = playVersionCode
        versionName = playVersionName

        manifestPlaceholders["admobAppId"] = admobAppId
        resValue("string", "admob_banner_ad_unit_id", admobBannerUnitId)
        buildConfigField("String", "REMOVE_ADS_INAPP_PRODUCT_ID", "\"$removeAdsProductId\"")

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
        buildConfig = true
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
        val py = listOf(
            "/opt/homebrew/opt/python@3.13/bin/python3.13",
            "/usr/bin/python3.13",
            "/usr/local/bin/python3.13",
        ).firstOrNull { File(it).canExecute() }
        buildPython(py ?: "python3.13")
        version = "3.13"
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
    implementation(libs.play.billing.ktx)
    implementation(libs.play.services.ads)
    implementation(libs.user.messaging.platform)
}

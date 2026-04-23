package com.gpxpoienricher.service

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.gpxpoienricher.core.TrackUtils
import com.gpxpoienricher.data.LatLon
import com.gpxpoienricher.data.PoiResult
import com.gpxpoienricher.data.Profile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request

private val OVERPASS_URLS = listOf(
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
)

class OverpassService(private val client: OkHttpClient = sharedHttpClient) {

    fun buildQuery(
        points: List<LatLon>,
        maxKm: Double,
        profile: Profile,
        countryCode: String
    ): String {
        val radiusM = (maxKm * 1000).toInt()
        val lines = mutableListOf<String>()

        for ((lat, lon) in points) {
            val selectors = listOf(
                "node(around:$radiusM,$lat,$lon)",
                "way(around:$radiusM,$lat,$lon)",
                "relation(around:$radiusM,$lat,$lon)"
            )
            for (sel in selectors) {
                for (tag in profile.tags) {
                    val cond = if (tag.value == "*") """["${tag.key}"]"""
                    else """["${tag.key}"="${tag.value}"]"""
                    val extra = StringBuilder()
                    tag.and?.forEach { a ->
                        extra.append(
                            if (a.value == "*") """["${a.key}"]"""
                            else """["${a.key}"="${a.value}"]"""
                        )
                    }
                    lines.add("$sel$cond$extra;")
                }
            }
        }

        val terms = profile.termsForCountry(countryCode)
        if (terms.isNotEmpty()) {
            val regex = terms.joinToString("|") { Regex.escape(it) }
            for ((lat, lon) in points) {
                val selectors = listOf(
                    "node(around:$radiusM,$lat,$lon)",
                    "way(around:$radiusM,$lat,$lon)",
                    "relation(around:$radiusM,$lat,$lon)"
                )
                for (sel in selectors) {
                    lines.add("""$sel["name"~"$regex", i];""")
                    lines.add("""$sel["description"~"$regex", i];""")
                    lines.add("""$sel["operator"~"$regex", i];""")
                }
            }
        }

        if (lines.isEmpty()) throw IllegalStateException(
            "No Overpass query could be built for profile '${profile.id}' and country '$countryCode'"
        )

        return "[out:json][timeout:180];\n(\n${lines.joinToString("\n")}\n);\nout center tags;\n"
    }

    suspend fun query(
        query: String,
        maxRetries: Int = 2,
        onProgress: ((String) -> Unit)? = null
    ): JsonObject = withContext(Dispatchers.IO) {
        var lastError: Exception? = null
        for (url in OVERPASS_URLS) {
            for (attempt in 0 until maxRetries) {
                onProgress?.invoke("Querying $url (attempt ${attempt + 1}/$maxRetries)...")
                try {
                    val body = FormBody.Builder().add("data", query).build()
                    val req = Request.Builder().url(url).post(body).header("User-Agent", USER_AGENT).build()
                    val resp = client.newCall(req).execute()
                    val text = resp.body?.string() ?: ""
                    val ct = resp.headers["content-type"] ?: ""

                    if (resp.isSuccessful && "json" in ct.lowercase()) {
                        return@withContext JsonParser.parseString(text).asJsonObject
                    }

                    val busy = resp.code in listOf(429, 500, 502, 504)
                        || "too busy" in text.lowercase()
                        || "timeout" in text.lowercase()
                    val waitMs = minOf(60_000L, 5_000L * (1 shl attempt))
                    lastError = RuntimeException("Overpass error at $url (${resp.code})")
                    if (busy) {
                        onProgress?.invoke("Overpass busy, waiting ${waitMs / 1000}s...")
                        delay(waitMs)
                    } else {
                        delay(waitMs)
                    }
                } catch (e: Exception) {
                    lastError = e
                    val waitMs = minOf(60_000L, 5_000L * (1 shl attempt))
                    onProgress?.invoke("Request failed at $url: ${e.message}")
                    delay(waitMs)
                }
            }
        }
        throw lastError ?: RuntimeException("All Overpass endpoints failed")
    }

    fun extractCandidates(
        data: JsonObject,
        trackPoints: List<LatLon>,
        maxKm: Double,
        profile: Profile
    ): List<PoiResult> {
        val dedup = LinkedHashMap<Pair<Long, Long>, PoiResult>()
        val elements = data.getAsJsonArray("elements") ?: return emptyList()

        for (el in elements) {
            val obj = el.asJsonObject
            val lat: Double
            val lon: Double
            if (obj.has("lat") && obj.has("lon")) {
                lat = obj["lat"].asDouble
                lon = obj["lon"].asDouble
            } else {
                val center = obj.getAsJsonObject("center") ?: continue
                lat = center["lat"]?.asDouble ?: continue
                lon = center["lon"]?.asDouble ?: continue
            }

            val tags = obj.getAsJsonObject("tags")
            val tagsMap = tags?.entrySet()?.associate { it.key to it.value.asString } ?: emptyMap()

            val d = TrackUtils.minDistanceToTrackKm(lat, lon, trackPoints)
            if (d > maxKm) continue

            val key = Pair((lat * 100000).toLong(), (lon * 100000).toLong())
            if (key !in dedup) {
                dedup[key] = PoiResult(
                    lat = lat,
                    lon = lon,
                    name = chooseName(tagsMap, profile),
                    kind = chooseKind(tagsMap, profile),
                    distanceKm = d,
                    tags = tagsMap
                )
            }
        }
        return dedup.values.toList()
    }

    private fun chooseName(tags: Map<String, String>, profile: Profile): String {
        for (key in listOf("name", "official_name", "short_name", "brand", "operator")) {
            val v = tags[key]?.trim()
            if (!v.isNullOrEmpty()) return v
        }
        for (tag in profile.tags) {
            if (tag.value != "*" && tags[tag.key] == tag.value) {
                return "${profile.description} (${tag.key}=${tag.value})"
            }
        }
        return profile.description
    }

    private fun chooseKind(tags: Map<String, String>, profile: Profile): String {
        val matches = mutableListOf<String>()
        for (tag in profile.tags) {
            if (tag.value == "*") {
                tags[tag.key]?.let { matches.add("${tag.key}=$it") }
            } else if (tags[tag.key] == tag.value) {
                matches.add("${tag.key}=${tag.value}")
            }
        }
        return if (matches.isNotEmpty()) "${profile.description} [${matches.take(3).joinToString(", ")}]"
        else profile.description
    }
}

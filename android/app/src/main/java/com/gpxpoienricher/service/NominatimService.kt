package com.gpxpoienricher.service

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

private const val REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
private const val SEARCH_URL = "https://nominatim.openstreetmap.org/search"

class NominatimService(private val client: OkHttpClient = sharedHttpClient) {

    private val gson = Gson()

    suspend fun reverseCountryCode(lat: Double, lon: Double): String = withContext(Dispatchers.IO) {
        val url = "$REVERSE_URL?lat=$lat&lon=$lon&format=jsonv2&zoom=5&addressdetails=1"
        val req = Request.Builder().url(url).header("User-Agent", USER_AGENT).build()
        val body = client.newCall(req).execute().use { it.body?.string() ?: "" }
        val map = gson.fromJson<Map<String, Any>>(body, object : TypeToken<Map<String, Any>>() {}.type)
        @Suppress("UNCHECKED_CAST")
        ((map["address"] as? Map<String, Any>)?.get("country_code") as? String)?.uppercase() ?: ""
    }

    suspend fun geocode(name: String): Pair<Double, Double>? = withContext(Dispatchers.IO) {
        val queries = buildGeocodeFallbacks(name)
        for ((i, query) in queries.withIndex()) {
            if (i > 0) delay(1100)
            val encoded = java.net.URLEncoder.encode(query, "UTF-8")
            val url = "$SEARCH_URL?q=$encoded&format=jsonv2&limit=1"
            val req = Request.Builder().url(url).header("User-Agent", USER_AGENT).build()
            val body = client.newCall(req).execute().use { it.body?.string() ?: "" }
            val list = gson.fromJson<List<Map<String, Any>>>(body, object : TypeToken<List<Map<String, Any>>>() {}.type)
            if (!list.isNullOrEmpty()) {
                val first = list[0]
                val lat = (first["lat"] as? String)?.toDoubleOrNull() ?: continue
                val lon = (first["lon"] as? String)?.toDoubleOrNull() ?: continue
                return@withContext Pair(lat, lon)
            }
        }
        null
    }

    private fun buildGeocodeFallbacks(name: String): List<String> {
        val parts = name.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        val candidates = mutableListOf(name)
        if (parts.size >= 2) {
            candidates.add(parts.dropLast(1).joinToString(", "))
            candidates.add("${parts.first()}, ${parts.last()}")
            candidates.add(parts.first())
        }
        return candidates.distinct()
    }
}

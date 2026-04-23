package com.gpxpoienricher.service

import com.google.gson.JsonParser
import com.gpxpoienricher.data.LatLon
import com.gpxpoienricher.data.WaypointResolved
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

private const val OSRM_BASE = "https://router.project-osrm.org/route/v1"
private val OSRM_PROFILES = mapOf("driving" to "car", "cycling" to "bike", "walking" to "foot")

class OsrmService(private val client: OkHttpClient = sharedHttpClient) {

    suspend fun route(
        waypoints: List<WaypointResolved>,
        mode: String
    ): List<LatLon> = withContext(Dispatchers.IO) {
        val profile = OSRM_PROFILES[mode] ?: "car"
        val coordStr = waypoints.joinToString(";") { "${"%.6f".format(it.lon)},${"%.6f".format(it.lat)}" }
        val url = "$OSRM_BASE/$profile/$coordStr?overview=full&geometries=geojson"
        val req = Request.Builder().url(url).header("User-Agent", USER_AGENT).build()
        val body = client.newCall(req).execute().use { it.body?.string() ?: "" }
        val json = JsonParser.parseString(body).asJsonObject
        if (json["code"]?.asString != "Ok") {
            throw RuntimeException("OSRM error: ${json["message"]?.asString ?: body.take(200)}")
        }
        val coords = json["routes"].asJsonArray[0].asJsonObject["geometry"]
            .asJsonObject["coordinates"].asJsonArray
        coords.map { c ->
            val arr = c.asJsonArray
            LatLon(arr[1].asDouble, arr[0].asDouble)
        }
    }
}

package com.gpxpoienricher.core

import com.gpxpoienricher.data.LatLon
import com.gpxpoienricher.data.WaypointResolved
import com.gpxpoienricher.service.NominatimService
import com.gpxpoienricher.service.OsrmService
import com.gpxpoienricher.service.USER_AGENT
import com.gpxpoienricher.service.sharedHttpClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.Request
import java.net.URLDecoder

private val COORD_RE = Regex("""^-?\d+\.?\d*,-?\d+\.?\d*$""")

data class MapsGpxResult(
    val trackPoints: List<LatLon>,
    val waypoints: List<WaypointResolved>
)

class MapsToGpx(
    private val nominatim: NominatimService = NominatimService(),
    private val osrm: OsrmService = OsrmService()
) {

    suspend fun convert(
        url: String,
        mode: String,
        onLog: (String) -> Unit = {}
    ): MapsGpxResult {
        val expanded = expandUrl(url, onLog)
        onLog("URL: $expanded")

        val raw = parseWaypoints(expanded)
        onLog("Found ${raw.size} waypoints in URL.")
        require(raw.size >= 2) { "Need at least origin and destination (2 waypoints)" }

        onLog("Resolving waypoints...")
        val resolved = resolveWaypoints(raw, onLog)
        for (w in resolved) onLog("  ${w.label}  (${w.lat}, ${w.lon})")

        onLog("Routing via OSRM ($mode)...")
        val track = osrm.route(resolved, mode)
        onLog("  ${track.size} track points returned.")

        return MapsGpxResult(track, resolved)
    }

    private suspend fun expandUrl(url: String, onLog: (String) -> Unit): String {
        if ("goo.gl" !in url && "maps.app" !in url) return url
        onLog("Expanding short URL...")
        return withContext(Dispatchers.IO) {
            // GET request — OkHttp follows all redirects and response.request.url is the final URL
            val req = Request.Builder().url(url).get().header("User-Agent", USER_AGENT).build()
            sharedHttpClient.newCall(req).execute().use { resp ->
                // OkHttp: response.request is the request that produced this response (final redirect)
                resp.request.url.toString()
            }
        }
    }

    private fun parseWaypoints(url: String): List<Map<String, Any>> {
        val parsed = java.net.URL(url)
        val query = parsed.query ?: ""
        val qs = parseQueryString(query)

        if ("origin" in qs || "destination" in qs) {
            val waypoints = mutableListOf<Map<String, Any>>()
            qs["origin"]?.let { addWaypoint(it, waypoints) }
            qs["waypoints"]?.split("|")?.forEach { addWaypoint(it.removePrefix("via:"), waypoints) }
            qs["destination"]?.let { addWaypoint(it, waypoints) }
            return waypoints
        }

        val path = parsed.path ?: ""
        val marker = "/maps/dir/"
        val idx = path.indexOf(marker)
        if (idx < 0) throw IllegalArgumentException("URL does not look like a Google Maps directions link: $url")
        val after = path.substring(idx + marker.length)
        val parts = after.split("/").filter { it.isNotEmpty() }.map { URLDecoder.decode(it, "UTF-8") }
        return parts
            .takeWhile { !it.startsWith("@") && !it.startsWith("data=") }
            .map { part ->
                if (isCoordinate(part)) mapOf("coord" to parseCoord(part))
                else mapOf("name" to part)
            }
    }

    private fun addWaypoint(raw: String, list: MutableList<Map<String, Any>>) {
        val s = raw.trim()
        if (s.isEmpty()) return
        if (isCoordinate(s)) list.add(mapOf("coord" to parseCoord(s)))
        else list.add(mapOf("name" to s))
    }

    private suspend fun resolveWaypoints(
        raw: List<Map<String, Any>>,
        onLog: (String) -> Unit
    ): List<WaypointResolved> {
        val result = mutableListOf<WaypointResolved>()
        for ((i, wpt) in raw.withIndex()) {
            if ("coord" in wpt) {
                @Suppress("UNCHECKED_CAST")
                val (lat, lon) = wpt["coord"] as Pair<Double, Double>
                result.add(WaypointResolved(lat, lon, "${"%.6f".format(lat)},${"%.6f".format(lon)}"))
            } else {
                val name = wpt["name"] as String
                onLog("  Geocoding '$name'...")
                val coord = nominatim.geocode(name)
                    ?: throw IllegalArgumentException("Nominatim could not geocode: '$name'")
                result.add(WaypointResolved(coord.first, coord.second, name))
                if (i < raw.size - 1) delay(1100)
            }
        }
        return result
    }

    private fun isCoordinate(s: String): Boolean {
        if (!COORD_RE.matches(s)) return false
        val (lat, lon) = s.split(",")
        return lat.toDouble() in -90.0..90.0 && lon.toDouble() in -180.0..180.0
    }

    private fun parseCoord(s: String): Pair<Double, Double> {
        val (lat, lon) = s.split(",")
        return Pair(lat.toDouble(), lon.toDouble())
    }

    private fun parseQueryString(query: String): Map<String, String> {
        if (query.isEmpty()) return emptyMap()
        return query.split("&").associate { pair ->
            val eq = pair.indexOf('=')
            if (eq < 0) pair to ""
            else {
                val k = URLDecoder.decode(pair.substring(0, eq), "UTF-8")
                val v = URLDecoder.decode(pair.substring(eq + 1), "UTF-8")
                k to v
            }
        }
    }
}

package com.gpxpoienricher.core

import com.gpxpoienricher.data.LatLon
import com.gpxpoienricher.data.PoiResult
import com.gpxpoienricher.data.Profile
import com.gpxpoienricher.service.NominatimService
import com.gpxpoienricher.service.OverpassService
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive

class Enricher(
    private val nominatim: NominatimService = NominatimService(),
    private val overpass: OverpassService = OverpassService()
) {

    suspend fun enrich(
        trackPoints: List<LatLon>,
        profile: Profile,
        maxKm: Double? = null,
        sampleKm: Double? = null,
        batchSize: Int? = null,
        countrySpacingKm: Double = 40.0,
        onLog: (String) -> Unit = {}
    ): List<PoiResult> {
        val _maxKm = maxKm ?: profile.maxKm
        val _sampleKm = sampleKm ?: profile.sampleKm
        val _batchSize = batchSize ?: profile.batchSize

        onLog("Loaded ${trackPoints.size} track points.")
        val sampled = TrackUtils.sampleTrackByDistance(trackPoints, _sampleKm)
        onLog("Sampled to ${sampled.size} points at ~$_sampleKm km spacing.")
        onLog("Profile: ${profile.id} (${profile.description})")
        onLog("max_km=$_maxKm, sample_km=$_sampleKm, batch_size=$_batchSize")

        // Detect country segments
        onLog("Detecting country segments via Nominatim...")
        val countrySegments = detectCountrySegments(sampled, countrySpacingKm, onLog)
        val segments = if (countrySegments.isEmpty()) mapOf("EN" to sampled) else countrySegments

        val allCandidates = LinkedHashMap<Pair<Long, Long>, PoiResult>()
        val batches = segments.values.sumOf { pts ->
            (pts.size + _batchSize - 1) / _batchSize
        }
        var batchNum = 0

        for ((cc, pts) in segments) {
            for (batch in pts.chunked(_batchSize)) {
                currentCoroutineContext().ensureActive()
                batchNum++
                onLog("Overpass batch $batchNum/$batches (country=$cc, ${batch.size} points)...")
                try {
                    val query = overpass.buildQuery(batch, _maxKm, profile, cc)
                    val data = overpass.query(query, profile.retries) { msg -> onLog(msg) }
                    val candidates = overpass.extractCandidates(data, trackPoints, _maxKm, profile)
                    for (c in candidates) {
                        val key = Pair((c.lat * 100000).toLong(), (c.lon * 100000).toLong())
                        if (key !in allCandidates) allCandidates[key] = c
                    }
                    onLog("  ${allCandidates.size} unique POIs so far.")
                    if (batchNum >= 3 && allCandidates.isEmpty() && batchNum < batches) {
                        throw RuntimeException(
                            "No POIs found after $batchNum batches. Try increasing max_km (currently $_maxKm km) or using a broader profile."
                        )
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    onLog("Warning: batch $batchNum failed: ${e.message}")
                }
                delay(1000)
            }
        }

        val result = allCandidates.values.sortedWith(compareBy({ it.distanceKm }, { it.name.lowercase() }))
        onLog("\nFound ${result.size} POIs total.")
        return result
    }

    private suspend fun detectCountrySegments(
        sampled: List<LatLon>,
        minSpacingKm: Double,
        onLog: (String) -> Unit
    ): Map<String, List<LatLon>> {
        val result = LinkedHashMap<String, MutableList<LatLon>>()
        var lastRev: LatLon? = null
        var lastCc: String? = null

        for ((i, pt) in sampled.withIndex()) {
            currentCoroutineContext().ensureActive()
            val needCall = lastRev == null ||
                TrackUtils.haversineKm(lastRev!!.lat, lastRev!!.lon, pt.lat, pt.lon) >= minSpacingKm
            if (needCall) {
                try {
                    val cc = nominatim.reverseCountryCode(pt.lat, pt.lon)
                    if (cc.isNotEmpty()) lastCc = cc
                    onLog("  Nominatim: point $i → country=${lastCc ?: "?"}")
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    onLog("  Nominatim reverse failed for point $i: ${e.message}")
                }
                lastRev = pt
                delay(1100)
            }
            lastCc?.let { cc -> result.getOrPut(cc) { mutableListOf() }.add(pt) }
        }
        return result
    }
}

package com.gpxpoienricher.core

import com.gpxpoienricher.data.LatLon
import kotlin.math.*

object TrackUtils {

    fun haversineKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371.0088
        val p1 = Math.toRadians(lat1)
        val p2 = Math.toRadians(lat2)
        val dphi = Math.toRadians(lat2 - lat1)
        val dlambda = Math.toRadians(lon2 - lon1)
        val a = sin(dphi / 2).pow(2) + cos(p1) * cos(p2) * sin(dlambda / 2).pow(2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }

    fun sampleTrackByDistance(points: List<LatLon>, spacingKm: Double): List<LatLon> {
        if (points.isEmpty()) return emptyList()
        val sampled = mutableListOf(points[0])
        var distSince = 0.0
        for (i in 1 until points.size) {
            val a = points[i - 1]
            val b = points[i]
            distSince += haversineKm(a.lat, a.lon, b.lat, b.lon)
            if (distSince >= spacingKm) {
                sampled.add(b)
                distSince = 0.0
            }
        }
        if (sampled.last() != points.last()) sampled.add(points.last())
        return sampled
    }

    fun minDistanceToTrackKm(lat: Double, lon: Double, track: List<LatLon>, coarseStep: Int = 30): Double {
        var bestIdx = 0
        var best = Double.MAX_VALUE
        for (i in track.indices step coarseStep) {
            val d = haversineKm(lat, lon, track[i].lat, track[i].lon)
            if (d < best) { best = d; bestIdx = i }
        }
        val start = maxOf(0, bestIdx - 5 * coarseStep)
        val end = minOf(track.size, bestIdx + 5 * coarseStep + 1)
        for (i in start until end) {
            val d = haversineKm(lat, lon, track[i].lat, track[i].lon)
            if (d < best) best = d
        }
        return best
    }

    fun cumulativeDistancesM(points: List<LatLon>): List<Double> {
        val cum = mutableListOf(0.0)
        var total = 0.0
        for (i in 1 until points.size) {
            total += haversineKm(points[i - 1].lat, points[i - 1].lon, points[i].lat, points[i].lon) * 1000.0
            cum.add(total)
        }
        return cum
    }
}

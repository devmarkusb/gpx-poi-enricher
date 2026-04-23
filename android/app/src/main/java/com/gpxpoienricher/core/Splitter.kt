package com.gpxpoienricher.core

import com.gpxpoienricher.data.SplitWaypoint

object Splitter {

    fun split(points: List<TrackPoint>, segments: Int): List<SplitWaypoint> {
        require(segments >= 2) { "segments must be >= 2" }
        require(points.size >= 2) { "GPX must contain at least 2 track points" }

        val latLons = points.map { com.gpxpoienricher.data.LatLon(it.lat, it.lon) }
        val cumulative = TrackUtils.cumulativeDistancesM(latLons)
        val total = cumulative.last()
        val waypoints = mutableListOf<SplitWaypoint>()

        for (i in 1 until segments) {
            val frac = i.toDouble() / segments
            val target = total * frac
            val wpt = pointAtDistance(points, cumulative, target)
            waypoints.add(SplitWaypoint(
                lat = wpt.lat,
                lon = wpt.lon,
                ele = wpt.ele,
                name = "Split $i",
                description = "${"%.1f".format(frac * 100)}% of track length"
            ))
        }
        return waypoints
    }

    private fun pointAtDistance(
        points: List<TrackPoint>,
        cumulative: List<Double>,
        target: Double
    ): TrackPoint {
        if (target <= 0) return points.first()
        if (target >= cumulative.last()) return points.last()
        for (i in 1 until cumulative.size) {
            if (cumulative[i] >= target) {
                val segLen = cumulative[i] - cumulative[i - 1]
                if (segLen == 0.0) return points[i]
                val t = (target - cumulative[i - 1]) / segLen
                return interpolate(points[i - 1], points[i], t)
            }
        }
        return points.last()
    }

    private fun interpolate(a: TrackPoint, b: TrackPoint, t: Double): TrackPoint {
        val lat = a.lat + t * (b.lat - a.lat)
        val lon = a.lon + t * (b.lon - a.lon)
        val ele = when {
            a.ele != null && b.ele != null -> a.ele + t * (b.ele - a.ele)
            a.ele != null -> a.ele
            else -> b.ele
        }
        return TrackPoint(lat, lon, ele)
    }
}

package com.gpxpoienricher.data

data class PoiResult(
    val lat: Double,
    val lon: Double,
    val name: String,
    val kind: String,
    val distanceKm: Double,
    val tags: Map<String, String> = emptyMap()
)

data class WaypointResolved(
    val lat: Double,
    val lon: Double,
    val label: String
)

data class LatLon(val lat: Double, val lon: Double)

data class SplitWaypoint(
    val lat: Double,
    val lon: Double,
    val ele: Double?,
    val name: String,
    val description: String
)

package com.gpxpoienricher.core

import com.gpxpoienricher.data.LatLon
import com.gpxpoienricher.data.PoiResult
import com.gpxpoienricher.data.SplitWaypoint
import com.gpxpoienricher.data.WaypointResolved
import java.io.OutputStream

private const val GPX_NS = "http://www.topografix.com/GPX/1/1"
private const val XSI = "http://www.w3.org/2001/XMLSchema-instance"
private const val SCHEMA = "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd"

object GpxWriter {

    fun writeWaypoints(
        pois: List<PoiResult>,
        symbol: String,
        typeLabel: String,
        stream: OutputStream
    ) {
        val sb = StringBuilder()
        sb.appendLine("""<?xml version="1.0" encoding="UTF-8"?>""")
        sb.appendLine("""<gpx xmlns="$GPX_NS" xmlns:xsi="$XSI" xsi:schemaLocation="$SCHEMA" version="1.1" creator="GpxPoiEnricher">""")
        for (poi in pois) {
            sb.appendLine("""  <wpt lat="${"%.6f".format(poi.lat)}" lon="${"%.6f".format(poi.lon)}">""")
            sb.appendLine("""    <name>${escapeXml(poi.name)}</name>""")
            sb.appendLine("""    <type>${escapeXml(typeLabel)}</type>""")
            sb.appendLine("""    <desc>${escapeXml("${poi.kind}; approx ${"%.1f".format(poi.distanceKm)} km from track")}</desc>""")
            sb.appendLine("""    <sym>${escapeXml(symbol)}</sym>""")
            sb.appendLine("""  </wpt>""")
        }
        sb.appendLine("""</gpx>""")
        stream.write(sb.toString().toByteArray(Charsets.UTF_8))
    }

    fun writeSplitWaypoints(waypoints: List<SplitWaypoint>, stream: OutputStream) {
        val sb = StringBuilder()
        sb.appendLine("""<?xml version="1.0" encoding="UTF-8"?>""")
        sb.appendLine("""<gpx xmlns="$GPX_NS" xmlns:xsi="$XSI" xsi:schemaLocation="$SCHEMA" version="1.1" creator="GpxPoiEnricher">""")
        for (wpt in waypoints) {
            val eleAttr = if (wpt.ele != null) "\n    <ele>${"%.1f".format(wpt.ele)}</ele>" else ""
            sb.appendLine("""  <wpt lat="${"%.6f".format(wpt.lat)}" lon="${"%.6f".format(wpt.lon)}">$eleAttr""")
            sb.appendLine("""    <name>${escapeXml(wpt.name)}</name>""")
            sb.appendLine("""    <desc>${escapeXml(wpt.description)}</desc>""")
            sb.appendLine("""  </wpt>""")
        }
        sb.appendLine("""</gpx>""")
        stream.write(sb.toString().toByteArray(Charsets.UTF_8))
    }

    fun writeMapsRoute(
        trackPoints: List<LatLon>,
        waypoints: List<WaypointResolved>,
        trackName: String,
        stream: OutputStream
    ) {
        val sb = StringBuilder()
        sb.appendLine("""<?xml version="1.0" encoding="UTF-8"?>""")
        sb.appendLine("""<gpx xmlns="$GPX_NS" xmlns:xsi="$XSI" xsi:schemaLocation="$SCHEMA" version="1.1" creator="GpxPoiEnricher">""")
        for (wpt in waypoints) {
            sb.appendLine("""  <wpt lat="${"%.6f".format(wpt.lat)}" lon="${"%.6f".format(wpt.lon)}">""")
            sb.appendLine("""    <name>${escapeXml(wpt.label)}</name>""")
            sb.appendLine("""  </wpt>""")
        }
        sb.appendLine("""  <trk>""")
        sb.appendLine("""    <name>${escapeXml(trackName)}</name>""")
        sb.appendLine("""    <trkseg>""")
        for (pt in trackPoints) {
            sb.appendLine("""      <trkpt lat="${"%.6f".format(pt.lat)}" lon="${"%.6f".format(pt.lon)}"/>""")
        }
        sb.appendLine("""    </trkseg>""")
        sb.appendLine("""  </trk>""")
        sb.appendLine("""</gpx>""")
        stream.write(sb.toString().toByteArray(Charsets.UTF_8))
    }

    private fun escapeXml(s: String): String = s
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&apos;")
}

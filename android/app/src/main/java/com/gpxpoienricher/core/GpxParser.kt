package com.gpxpoienricher.core

import com.gpxpoienricher.data.LatLon
import org.xmlpull.v1.XmlPullParser
import org.xmlpull.v1.XmlPullParserFactory
import java.io.InputStream

private const val GPX_NS = "http://www.topografix.com/GPX/1/1"

data class TrackPoint(val lat: Double, val lon: Double, val ele: Double? = null)

object GpxParser {

    fun parseTrackPoints(stream: InputStream): List<LatLon> {
        return parseTrackPointsFull(stream).map { LatLon(it.lat, it.lon) }
    }

    fun parseTrackPointsFull(stream: InputStream): List<TrackPoint> {
        val factory = XmlPullParserFactory.newInstance().apply { isNamespaceAware = true }
        val parser = factory.newPullParser()
        parser.setInput(stream, "UTF-8")

        val points = mutableListOf<TrackPoint>()
        var inTrkpt = false
        var currentLat = 0.0
        var currentLon = 0.0
        var currentEle: Double? = null

        var event = parser.eventType
        while (event != XmlPullParser.END_DOCUMENT) {
            when (event) {
                XmlPullParser.START_TAG -> {
                    val localName = parser.name?.substringAfterLast(':') ?: parser.name ?: ""
                    if (localName == "trkpt") {
                        inTrkpt = true
                        currentLat = parser.getAttributeValue(null, "lat")?.toDoubleOrNull() ?: 0.0
                        currentLon = parser.getAttributeValue(null, "lon")?.toDoubleOrNull() ?: 0.0
                        currentEle = null
                    } else if (inTrkpt && localName == "ele") {
                        parser.next()
                        currentEle = parser.text?.toDoubleOrNull()
                    }
                }
                XmlPullParser.END_TAG -> {
                    val localName = parser.name?.substringAfterLast(':') ?: parser.name ?: ""
                    if (localName == "trkpt" && inTrkpt) {
                        points.add(TrackPoint(currentLat, currentLon, currentEle))
                        inTrkpt = false
                    }
                }
            }
            event = parser.next()
        }
        if (points.isEmpty()) throw IllegalArgumentException("No track points found in GPX file")
        return points
    }
}

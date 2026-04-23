package com.gpxpoienricher

/** Passed to Python bridge functions; Python calls .onLog(message). */
class LogCallback(private val handler: (String) -> Unit) {
    fun onLog(message: String) = handler(message)
}

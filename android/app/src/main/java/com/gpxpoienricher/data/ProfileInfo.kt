package com.gpxpoienricher.data

/** [source] is ``builtin``, ``user``, or ``profiles`` (single-folder layout). */
data class ProfileInfo(val id: String, val description: String, val source: String = "builtin")

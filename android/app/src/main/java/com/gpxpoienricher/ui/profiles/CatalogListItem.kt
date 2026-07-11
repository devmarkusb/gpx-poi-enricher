package com.gpxpoienricher.ui.profiles

data class CatalogListItem(
    val entryId: String,
    val label: String,
    val categoryLabel: String,
    val installed: Boolean,
) {
    fun displayLabel(): String {
        val suffix = if (installed) " (installed)" else ""
        return "$label$suffix"
    }
}

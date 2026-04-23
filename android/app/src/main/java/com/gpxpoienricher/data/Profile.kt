package com.gpxpoienricher.data

data class ProfileTag(
    val key: String,
    val value: String,
    val and: List<ProfileTag>? = null
)

data class ProfileDefaults(
    val max_km: Double = 10.0,
    val sample_km: Double = 20.0,
    val batch_size: Int = 4,
    val retries: Int = 2
)

data class Profile(
    val id: String,
    val description: String,
    val symbol: String,
    val defaults: ProfileDefaults = ProfileDefaults(),
    val tags: List<ProfileTag> = emptyList(),
    val terms: Map<String, List<String>> = emptyMap()
) {
    val maxKm: Double get() = defaults.max_km
    val sampleKm: Double get() = defaults.sample_km
    val batchSize: Int get() = defaults.batch_size
    val retries: Int get() = defaults.retries

    fun termsForCountry(cc: String): List<String> {
        val seen = LinkedHashSet<String>()
        (terms[cc] ?: emptyList()).forEach { seen.add(it) }
        (terms["EN"] ?: emptyList()).forEach { seen.add(it) }
        return seen.toList()
    }
}

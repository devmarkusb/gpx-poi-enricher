package com.gpxpoienricher.core

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.gpxpoienricher.data.Profile

object ProfileLoader {

    private val gson = Gson()

    fun loadAll(context: Context): List<Profile> {
        val assetManager = context.assets
        val files = assetManager.list("profiles") ?: return emptyList()
        return files
            .filter { it.endsWith(".json") }
            .mapNotNull { filename ->
                runCatching {
                    assetManager.open("profiles/$filename").use { stream ->
                        val json = stream.bufferedReader().readText()
                        gson.fromJson(json, Profile::class.java)
                    }
                }.getOrNull()
            }
            .sortedBy { it.description }
    }
}

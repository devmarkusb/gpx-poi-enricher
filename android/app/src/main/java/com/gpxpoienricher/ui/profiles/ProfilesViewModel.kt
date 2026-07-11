package com.gpxpoienricher.ui.profiles

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import com.gpxpoienricher.GpxApp
import com.gpxpoienricher.data.ProfileInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class ProfilesViewModel(app: Application) : AndroidViewModel(app) {

    private val _profiles = MutableLiveData<List<ProfileInfo>>(emptyList())
    val profiles: LiveData<List<ProfileInfo>> = _profiles

    private val _yaml = MutableLiveData("")
    val yaml: LiveData<String> = _yaml

    private val _sourceHint = MutableLiveData("")
    val sourceHint: LiveData<String> = _sourceHint

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private val _busy = MutableLiveData(false)
    val busy: LiveData<Boolean> = _busy

    private val _catalogItems = MutableLiveData<List<CatalogListItem>>(emptyList())
    val catalogItems: LiveData<List<CatalogListItem>> = _catalogItems

    init {
        reloadList()
    }

    fun reloadList() {
        viewModelScope.launch(Dispatchers.IO) {
            val dir = GpxApp.extractProfiles()
            val json = Python.getInstance().getModule("gpx_bridge")
                .callAttr("list_profiles", dir.absolutePath).toString()
            _profiles.postValue(parseProfiles(json))
        }
    }

    fun loadProfile(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            _busy.postValue(true)
            try {
                val dir = GpxApp.extractProfiles()
                val yamlText = Python.getInstance().getModule("gpx_bridge")
                    .callAttr("get_profile_yaml", dir.absolutePath, id).toString()
                _yaml.postValue(yamlText)
                val src = _profiles.value?.find { it.id == id }?.source ?: ""
                val hint = when (src) {
                    "user" -> "Stored in user folder — you can delete this copy."
                    "builtin" -> "Built-in — Save writes a user override with the same id."
                    else -> ""
                }
                _sourceHint.postValue(hint)
            } catch (e: Exception) {
                _snackbar.postValue(e.message)
            } finally {
                _busy.postValue(false)
            }
        }
    }

    fun saveYaml(text: String) {
        viewModelScope.launch(Dispatchers.IO) {
            _busy.postValue(true)
            try {
                val dir = GpxApp.extractProfiles()
                Python.getInstance().getModule("gpx_bridge").callAttr(
                    "save_profile_yaml",
                    dir.absolutePath,
                    text,
                )
                _snackbar.postValue("Profile saved.")
                reloadList()
            } catch (e: Exception) {
                _snackbar.postValue(e.message ?: "Save failed")
            } finally {
                _busy.postValue(false)
            }
        }
    }

    fun deleteCurrent(profileId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val src = _profiles.value?.find { it.id == profileId }?.source ?: return@launch
            if (src != "user") {
                _snackbar.postValue("Only user-saved profiles can be deleted.")
                return@launch
            }
            _busy.postValue(true)
            try {
                val dir = GpxApp.extractProfiles()
                Python.getInstance().getModule("gpx_bridge").callAttr(
                    "delete_profile",
                    dir.absolutePath,
                    profileId,
                )
                _snackbar.postValue("Profile removed.")
                reloadList()
            } catch (e: Exception) {
                _snackbar.postValue(e.message)
            } finally {
                _busy.postValue(false)
            }
        }
    }

    fun loadTemplate() {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val tpl = Python.getInstance().getModule("gpx_bridge")
                    .callAttr("new_profile_template_yaml").toString()
                _yaml.postValue(tpl)
                _sourceHint.postValue("New template — pick Save after editing.")
            } catch (e: Exception) {
                _snackbar.postValue(e.message)
            }
        }
    }

    fun loadCatalog() {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val json = Python.getInstance().getModule("gpx_bridge")
                    .callAttr("list_catalog").toString()
                val installed = _profiles.value?.map { it.id }?.toSet() ?: emptySet()
                _catalogItems.postValue(parseCatalog(json, installed))
            } catch (e: Exception) {
                _snackbar.postValue(e.message)
            }
        }
    }

    fun addFromCatalog(entryId: String, allowOverride: Boolean = false) {
        viewModelScope.launch(Dispatchers.IO) {
            val installed = _profiles.value?.any { it.id == entryId } == true
            if (installed && !allowOverride) {
                _snackbar.postValue("exists:$entryId")
                return@launch
            }
            _busy.postValue(true)
            try {
                val dir = GpxApp.extractProfiles()
                Python.getInstance().getModule("gpx_bridge").callAttr(
                    "add_profile_from_catalog",
                    dir.absolutePath,
                    entryId,
                )
                _snackbar.postValue("added:$entryId")
                reloadList()
                loadProfile(entryId)
            } catch (e: Exception) {
                _snackbar.postValue(e.message ?: "Could not add profile")
            } finally {
                _busy.postValue(false)
            }
        }
    }

    fun importYamlString(content: String) {
        _yaml.postValue(content)
        _sourceHint.postValue("Imported — review and Save.")
    }

    fun clearSnackbar() {
        _snackbar.value = null
    }

    private fun parseProfiles(json: String): List<ProfileInfo> {
        val arr = org.json.JSONArray(json)
        return (0 until arr.length())
            .map { i ->
                val o = arr.getJSONObject(i)
                ProfileInfo(
                    o.getString("id"),
                    o.getString("description"),
                    o.optString("source", "builtin"),
                )
            }
            .sortedWith(compareBy({ it.source == "user" }, { it.description.lowercase() }))
    }

    private fun parseCatalog(json: String, installedIds: Set<String>): List<CatalogListItem> {
        val arr = org.json.JSONArray(json)
        val out = mutableListOf<CatalogListItem>()
        for (i in 0 until arr.length()) {
            val cat = arr.getJSONObject(i)
            val categoryLabel = cat.getString("label")
            val entries = cat.getJSONArray("entries")
            for (j in 0 until entries.length()) {
                val e = entries.getJSONObject(j)
                val id = e.getString("id")
                out.add(
                    CatalogListItem(
                        entryId = id,
                        label = e.getString("label"),
                        categoryLabel = categoryLabel,
                        installed = id in installedIds,
                    ),
                )
            }
        }
        return out.sortedWith(compareBy({ it.categoryLabel.lowercase() }, { it.label.lowercase() }))
    }
}

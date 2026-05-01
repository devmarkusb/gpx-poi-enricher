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
}

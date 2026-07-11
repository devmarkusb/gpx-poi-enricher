package com.gpxpoienricher.ui.profiles

import android.content.DialogInterface
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.ListView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.textfield.TextInputEditText
import com.gpxpoienricher.R
import com.gpxpoienricher.data.ProfileInfo
import com.gpxpoienricher.databinding.FragmentProfilesBinding

class ProfilesFragment : Fragment() {

    private var _binding: FragmentProfilesBinding? = null
    private val binding get() = _binding!!

    private val viewModel: ProfilesViewModel by viewModels()

    private var profileList: List<ProfileInfo> = emptyList()
    private var catalogItems: List<CatalogListItem> = emptyList()
    private var suppressSpinnerCallback = false
    private var lastSelectedId: String? = null
    private var catalogDialog: AlertDialog? = null
    private var pendingCatalogDialog = false

    private val importYaml = registerForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri == null) return@registerForActivityResult
        val text = requireContext().contentResolver.openInputStream(uri)?.bufferedReader()
            ?.use { it.readText() } ?: return@registerForActivityResult
        viewModel.importYamlString(text)
    }

    private val exportYaml = registerForActivityResult(
        ActivityResultContracts.CreateDocument("application/x-yaml"),
    ) { uri ->
        if (uri == null) return@registerForActivityResult
        val yaml = binding.profileYamlEdit.text?.toString() ?: return@registerForActivityResult
        requireContext().contentResolver.openOutputStream(uri)?.use {
            it.write(yaml.toByteArray(Charsets.UTF_8))
        }
        Snackbar.make(binding.root, "Exported.", Snackbar.LENGTH_SHORT).show()
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentProfilesBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.profileSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, v: View?, position: Int, id: Long) {
                if (suppressSpinnerCallback) return
                profileList.getOrNull(position)?.let {
                    lastSelectedId = it.id
                    viewModel.loadProfile(it.id)
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        viewModel.profiles.observe(viewLifecycleOwner) { list ->
            profileList = list
            val labels = list.map { p -> "${p.description} (${p.id})" }
            suppressSpinnerCallback = true
            binding.profileSpinner.adapter = ArrayAdapter(
                requireContext(),
                android.R.layout.simple_spinner_dropdown_item,
                labels,
            )
            val want = lastSelectedId ?: list.firstOrNull()?.id
            val idx = want?.let { w -> list.indexOfFirst { it.id == w } }?.takeIf { it >= 0 } ?: 0
            if (list.isNotEmpty()) {
                val pick = idx.coerceAtMost(list.lastIndex)
                binding.profileSpinner.setSelection(pick)
                lastSelectedId = list[pick].id
                viewModel.loadProfile(lastSelectedId!!)
            }
            suppressSpinnerCallback = false
        }

        viewModel.yaml.observe(viewLifecycleOwner) { text ->
            if (binding.profileYamlEdit.text?.toString() != text) {
                binding.profileYamlEdit.setText(text)
            }
        }

        viewModel.sourceHint.observe(viewLifecycleOwner) { hint ->
            binding.profileSourceHint.text = hint
        }

        viewModel.snackbar.observe(viewLifecycleOwner) { msg ->
            if (msg.isNullOrBlank()) return@observe
            when {
                msg.startsWith("exists:") -> {
                    val entryId = msg.removePrefix("exists:")
                    val label = catalogItems.find { it.entryId == entryId }?.label ?: entryId
                    AlertDialog.Builder(requireContext())
                        .setTitle(R.string.title_catalog_picker)
                        .setMessage(getString(R.string.msg_catalog_profile_exists, label))
                        .setPositiveButton(android.R.string.ok) { _, _ ->
                            viewModel.addFromCatalog(entryId, allowOverride = true)
                        }
                        .setNegativeButton(android.R.string.cancel, null)
                        .show()
                }
                msg.startsWith("added:") -> {
                    val entryId = msg.removePrefix("added:")
                    lastSelectedId = entryId
                    val label = catalogItems.find { it.entryId == entryId }?.label ?: entryId
                    Snackbar.make(
                        binding.root,
                        getString(R.string.msg_catalog_profile_added, label),
                        Snackbar.LENGTH_LONG,
                    ).show()
                }
                else -> Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
            }
            viewModel.clearSnackbar()
        }

        viewModel.catalogItems.observe(viewLifecycleOwner) { items ->
            catalogItems = items
            if (pendingCatalogDialog && items.isNotEmpty()) {
                pendingCatalogDialog = false
                showCatalogDialog()
            }
        }

        viewModel.busy.observe(viewLifecycleOwner) { busy ->
            val en = !busy
            binding.btnSaveProfile.isEnabled = en
            binding.btnRevertProfile.isEnabled = en
            binding.btnNewTemplate.isEnabled = en
            binding.btnAddFromCatalog.isEnabled = en
            binding.btnImportProfile.isEnabled = en
            binding.btnExportProfile.isEnabled = en
            binding.btnDeleteProfile.isEnabled = en
        }

        binding.btnSaveProfile.setOnClickListener {
            viewModel.saveYaml(binding.profileYamlEdit.text?.toString() ?: "")
        }
        binding.btnRevertProfile.setOnClickListener {
            val idx = binding.profileSpinner.selectedItemPosition
            profileList.getOrNull(idx)?.let { viewModel.loadProfile(it.id) }
        }
        binding.btnNewTemplate.setOnClickListener { viewModel.loadTemplate() }
        binding.btnAddFromCatalog.setOnClickListener {
            if (catalogItems.isEmpty()) {
                pendingCatalogDialog = true
                viewModel.loadCatalog()
            } else {
                showCatalogDialog()
            }
        }
        binding.btnImportProfile.setOnClickListener {
            importYaml.launch(arrayOf("application/x-yaml", "text/plain", "*/*"))
        }
        binding.btnExportProfile.setOnClickListener {
            val idx = binding.profileSpinner.selectedItemPosition
            val id = profileList.getOrNull(idx)?.id ?: "profile"
            exportYaml.launch("$id.yaml")
        }
        binding.btnDeleteProfile.setOnClickListener {
            val idx = binding.profileSpinner.selectedItemPosition
            val p = profileList.getOrNull(idx) ?: return@setOnClickListener
            if (p.source != "user") {
                Snackbar.make(binding.root, "Only user-saved profiles can be deleted.", Snackbar.LENGTH_LONG).show()
                return@setOnClickListener
            }
            AlertDialog.Builder(requireContext())
                .setTitle("Delete profile")
                .setMessage("Remove user profile \"${p.id}\"?")
                .setPositiveButton("Delete") { _: DialogInterface, _: Int ->
                    viewModel.deleteCurrent(p.id)
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        }
    }

    private fun showCatalogDialog() {
        if (catalogItems.isEmpty()) {
            pendingCatalogDialog = true
            viewModel.loadCatalog()
            return
        }
        val dialogView = layoutInflater.inflate(R.layout.dialog_profile_catalog, null)
        val filterEdit = dialogView.findViewById<TextInputEditText>(R.id.catalog_filter)
        val listView = dialogView.findViewById<ListView>(R.id.catalog_list)
        var filtered = catalogItems
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_list_item_1,
            filtered.map { it.displayLabel() }.toMutableList(),
        )
        listView.adapter = adapter
        filterEdit?.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) {
                val needle = s?.toString()?.trim()?.lowercase().orEmpty()
                filtered = if (needle.isEmpty()) {
                    catalogItems
                } else {
                    catalogItems.filter {
                        it.label.lowercase().contains(needle) ||
                            it.categoryLabel.lowercase().contains(needle) ||
                            it.entryId.contains(needle)
                    }
                }
                adapter.clear()
                adapter.addAll(filtered.map { it.displayLabel() })
            }
        })
        catalogDialog?.dismiss()
        catalogDialog = AlertDialog.Builder(requireContext())
            .setTitle(R.string.title_catalog_picker)
            .setView(dialogView)
            .setNegativeButton(android.R.string.cancel, null)
            .create()
        listView.onItemClickListener = AdapterView.OnItemClickListener { _, _, position, _ ->
            val item = filtered.getOrNull(position) ?: return@OnItemClickListener
            catalogDialog?.dismiss()
            lastSelectedId = item.entryId
            viewModel.addFromCatalog(item.entryId)
        }
        catalogDialog?.show()
    }

    override fun onDestroyView() {
        catalogDialog?.dismiss()
        catalogDialog = null
        _binding = null
        super.onDestroyView()
    }
}

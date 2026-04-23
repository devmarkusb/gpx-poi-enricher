package com.gpxpoienricher.ui.enricher

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.databinding.FragmentEnricherBinding

class EnricherFragment : Fragment() {

    private var _binding: FragmentEnricherBinding? = null
    private val binding get() = _binding!!
    private val viewModel: EnricherViewModel by viewModels()

    private val openInput = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            requireContext().contentResolver.takePersistableUriPermission(
                it, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            viewModel.setInputFile(it)
        }
    }

    private val createOutput = registerForActivityResult(ActivityResultContracts.CreateDocument("application/gpx+xml")) { uri ->
        uri?.let {
            requireContext().contentResolver.takePersistableUriPermission(
                it, android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            viewModel.setOutputFile(it)
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentEnricherBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        viewModel.profiles.observe(viewLifecycleOwner) { profiles ->
            val names = profiles.map { it.description }
            binding.profileSpinner.adapter = ArrayAdapter(
                requireContext(), android.R.layout.simple_spinner_item, names
            ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
        }

        viewModel.inputName.observe(viewLifecycleOwner) { name ->
            binding.inputFileName.text = name ?: "No file selected"
        }

        viewModel.outputName.observe(viewLifecycleOwner) { name ->
            binding.outputFileName.text = name ?: "No file selected"
        }

        viewModel.isRunning.observe(viewLifecycleOwner) { running ->
            binding.btnRun.isEnabled = !running
            binding.btnCancel.isEnabled = running
            binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE
        }

        viewModel.logLines.observe(viewLifecycleOwner) { lines ->
            binding.logOutput.text = lines.joinToString("\n")
            binding.logScroll.post { binding.logScroll.fullScroll(View.FOCUS_DOWN) }
        }

        viewModel.snackbar.observe(viewLifecycleOwner) { msg ->
            msg?.let {
                Snackbar.make(binding.root, it, Snackbar.LENGTH_LONG).show()
                viewModel.clearSnackbar()
            }
        }

        binding.btnBrowseInput.setOnClickListener {
            openInput.launch(arrayOf("application/gpx+xml", "*/*"))
        }

        binding.btnBrowseOutput.setOnClickListener {
            createOutput.launch("output.gpx")
        }

        binding.btnRun.setOnClickListener {
            val maxKm = binding.editMaxKm.text?.toString()?.toDoubleOrNull()
            val sampleKm = binding.editSampleKm.text?.toString()?.toDoubleOrNull()
            viewModel.run(binding.profileSpinner.selectedItemPosition, maxKm, sampleKm)
        }

        binding.btnCancel.setOnClickListener { viewModel.cancel() }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

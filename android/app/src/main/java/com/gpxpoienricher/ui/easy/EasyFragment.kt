package com.gpxpoienricher.ui.easy

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.databinding.FragmentEasyBinding

class EasyFragment : Fragment() {

    private var _binding: FragmentEasyBinding? = null
    private val binding get() = _binding!!
    private val vm: EasyViewModel by viewModels()

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentEasyBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        vm.profiles.observe(viewLifecycleOwner) { profiles ->
            val adapter = ArrayAdapter(
                requireContext(),
                android.R.layout.simple_spinner_item,
                profiles.map { it.description },
            )
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            binding.spinnerProfile.adapter = adapter
        }

        vm.isRunning.observe(viewLifecycleOwner) { running ->
            binding.btnGenerate.isEnabled = !running
            binding.btnCancel.isEnabled = running
            binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE
        }

        vm.logLines.observe(viewLifecycleOwner) { lines ->
            binding.logOutput.text = lines.joinToString("\n")
            binding.logScroll.post { binding.logScroll.fullScroll(View.FOCUS_DOWN) }
        }

        vm.result.observe(viewLifecycleOwner) { result ->
            if (result == null) {
                binding.cardResults.visibility = View.GONE
                return@observe
            }
            binding.cardResults.visibility = View.VISIBLE
            val reusedNote = if (result.trackReused) "  (reused)" else ""
            binding.textTrackFile.text = result.trackPath + reusedNote
            binding.textPoiFile.text = "${result.poiPath}  (${result.poiCount} POI(s))"

            if (result.alternateFullPaths.isNotEmpty()) {
                binding.labelAlternateFull.visibility = View.VISIBLE
                binding.textAlternatePaths.visibility = View.VISIBLE
                binding.textAlternatePaths.text = result.alternateFullPaths.joinToString("\n")
            } else {
                binding.labelAlternateFull.visibility = View.GONE
                binding.textAlternatePaths.visibility = View.GONE
            }

            if (result.detourResults.isNotEmpty()) {
                binding.labelDetourSection.visibility = View.VISIBLE
                binding.textDetourFiles.visibility = View.VISIBLE
                binding.textDetourFiles.text = result.detourResults.joinToString("\n\n") { d ->
                    "${d.trackPath}\n  → ${d.poiPath}  (${d.poiCount} POI(s))"
                }
            } else {
                binding.labelDetourSection.visibility = View.GONE
                binding.textDetourFiles.visibility = View.GONE
            }
        }

        vm.snackbar.observe(viewLifecycleOwner) { msg ->
            if (msg != null) {
                Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
                vm.clearSnackbar()
            }
        }

        binding.btnGenerate.setOnClickListener {
            val url = binding.editUrl.text?.toString() ?: ""
            val extras = binding.editExtraUrls.text?.toString() ?: ""
            vm.generate(url, extras, binding.spinnerProfile.selectedItemPosition)
        }

        binding.btnCancel.setOnClickListener { vm.cancel() }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

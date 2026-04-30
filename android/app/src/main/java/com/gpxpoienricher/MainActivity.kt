package com.gpxpoienricher

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.setupWithNavController
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val navHostFragment = supportFragmentManager
            .findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        val navController = navHostFragment.navController
        binding.bottomNav.setupWithNavController(navController)

        val savedDest = GuiStatePreferences.readNavDestinationId(this)
        binding.bottomNav.post {
            if (savedDest != navController.currentDestination?.id) {
                binding.bottomNav.selectedItemId = savedDest
            }
        }
        navController.addOnDestinationChangedListener { _, destination, _ ->
            GuiStatePreferences.writeNavDestinationId(this@MainActivity, destination.id)
        }
    }
}

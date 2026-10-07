package com.example.prismgolden.mobileandroid

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.prismgolden.mobileandroid.designsystem.theme.AppTheme
import com.example.prismgolden.mobileandroid.ui.AppRoot

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as App).container
        setContent {
            AppTheme {
                AppRoot(container = container)
            }
        }
    }
}

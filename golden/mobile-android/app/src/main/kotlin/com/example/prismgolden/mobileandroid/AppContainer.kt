package com.example.prismgolden.mobileandroid

import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.example.prismgolden.mobileandroid.data.api.ApiClient
import com.example.prismgolden.mobileandroid.data.api.RetrofitApiClient
import com.example.prismgolden.mobileandroid.data.api.createApiService
import com.example.prismgolden.mobileandroid.session.SessionStore
import com.example.prismgolden.mobileandroid.ui.profile.ProfileViewModel
import com.example.prismgolden.mobileandroid.ui.signin.SignInViewModel

/**
 * Wires the app by hand: one session, one client, and the factory that builds the ViewModels.
 * A project that outgrows this adds a DI framework here, in one place.
 */
class AppContainer(
    apiBaseUrl: String,
    val sessionStore: SessionStore = SessionStore(),
    val apiClient: ApiClient = RetrofitApiClient(createApiService(apiBaseUrl)),
) {
    val viewModelFactory: ViewModelProvider.Factory = viewModelFactory {
        initializer { SignInViewModel(apiClient, sessionStore) }
        initializer { ProfileViewModel(apiClient, sessionStore) }
    }
}

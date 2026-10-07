package com.example.prismgolden.mobileandroid.ui

import androidx.compose.runtime.Composable
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.prismgolden.mobileandroid.AppContainer
import com.example.prismgolden.mobileandroid.ui.profile.ProfileRoute
import com.example.prismgolden.mobileandroid.ui.profile.ProfileViewModel
import com.example.prismgolden.mobileandroid.ui.signin.SignInRoute
import com.example.prismgolden.mobileandroid.ui.signin.SignInViewModel

/** Shows the profile while a session is open and the local development sign-in otherwise. */
@Composable
fun AppRoot(container: AppContainer) {
    val signedIn = container.sessionStore.accessToken.collectAsStateWithLifecycle().value != null
    if (signedIn) {
        ProfileRoute(viewModel = viewModel<ProfileViewModel>(factory = container.viewModelFactory))
    } else {
        SignInRoute(viewModel = viewModel<SignInViewModel>(factory = container.viewModelFactory))
    }
}

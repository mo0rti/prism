package com.example.prismgolden.mobileandroid.ui.signin

import androidx.compose.runtime.Composable
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/** Connects the sign-in screen to its ViewModel. */
@Composable
fun SignInRoute(viewModel: SignInViewModel, sessionEnded: Boolean = false) {
    val state = viewModel.uiState.collectAsStateWithLifecycle().value
    SignInScreen(state = state, onSignInClick = viewModel::onSignInClick, sessionEnded = sessionEnded)
}

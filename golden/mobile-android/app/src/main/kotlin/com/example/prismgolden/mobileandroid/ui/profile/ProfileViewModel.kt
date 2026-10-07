package com.example.prismgolden.mobileandroid.ui.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import com.example.prismgolden.mobileandroid.data.api.ApiClient
import com.example.prismgolden.mobileandroid.data.api.ApiError
import com.example.prismgolden.mobileandroid.data.api.ApiResult
import com.example.prismgolden.mobileandroid.data.api.UserProfile
import com.example.prismgolden.mobileandroid.session.SessionStore

/** Why the profile could not be read. The screen turns each into a message. */
enum class ProfileError {
    Network,
    Server,
    Unexpected,
}

sealed interface ProfileUiState {
    data object Loading : ProfileUiState

    data class Loaded(val profile: UserProfile) : ProfileUiState

    data class Failed(val error: ProfileError) : ProfileUiState
}

/**
 * Shows the signed-in user: it reads `GET /api/me` with the session's token whenever a session opens,
 * and again on retry. A rejected token (expired or invalid) closes the session, which returns the app
 * to the sign-in screen.
 */
class ProfileViewModel(
    private val apiClient: ApiClient,
    private val sessionStore: SessionStore,
) : ViewModel() {

    private val _uiState = MutableStateFlow<ProfileUiState>(ProfileUiState.Loading)
    val uiState: StateFlow<ProfileUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            sessionStore.accessToken.collectLatest { token ->
                if (token == null) _uiState.value = ProfileUiState.Loading else load(token)
            }
        }
    }

    fun onRetryClick() {
        val token = sessionStore.accessToken.value ?: return
        viewModelScope.launch { load(token) }
    }

    fun onSignOutClick() {
        sessionStore.close()
    }

    private suspend fun load(token: String) {
        _uiState.value = ProfileUiState.Loading
        when (val result = apiClient.getMe(token)) {
            is ApiResult.Success -> _uiState.value = ProfileUiState.Loaded(result.value)
            is ApiResult.Failure -> when (result.error) {
                ApiError.Unauthorized -> sessionStore.close(sessionEnded = true)
                ApiError.Network -> _uiState.value = ProfileUiState.Failed(ProfileError.Network)
                ApiError.Server -> _uiState.value = ProfileUiState.Failed(ProfileError.Server)
                ApiError.NotServed, ApiError.LoopbackOnly, ApiError.Unexpected ->
                    _uiState.value = ProfileUiState.Failed(ProfileError.Unexpected)
            }
        }
    }
}

package com.example.prismgolden.mobileandroid.ui.profile

import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import com.example.prismgolden.mobileandroid.data.api.ApiError
import com.example.prismgolden.mobileandroid.data.api.ApiResult
import com.example.prismgolden.mobileandroid.session.SessionStore
import com.example.prismgolden.mobileandroid.support.FakeApiClient
import com.example.prismgolden.mobileandroid.support.MainDispatcherRule
import com.example.prismgolden.mobileandroid.support.TEST_PROFILE

class ProfileViewModelTest {

    @get:Rule
    val mainDispatcher = MainDispatcherRule()

    private val client = FakeApiClient()
    private val session = SessionStore()
    private lateinit var viewModel: ProfileViewModel

    // Built after the rule has replaced the main dispatcher, because a ViewModel takes its scope when it is created.
    @Before
    fun createViewModel() {
        viewModel = ProfileViewModel(client, session)
    }

    @Test
    fun `the state is loading and no request is sent before a session opens`() {
        assertEquals(ProfileUiState.Loading, viewModel.uiState.value)
        assertEquals(emptyList<String>(), client.meTokens)
    }

    @Test
    fun `opening a session loads the profile with its token`() {
        session.open("session-token")

        assertEquals(ProfileUiState.Loaded(TEST_PROFILE), viewModel.uiState.value)
        assertEquals(listOf("session-token"), client.meTokens)
    }

    @Test
    fun `the state is loading while the profile is read`() {
        val gate = CompletableDeferred<Unit>()
        client.gate = gate

        session.open("session-token")
        assertEquals(ProfileUiState.Loading, viewModel.uiState.value)

        gate.complete(Unit)
        assertEquals(ProfileUiState.Loaded(TEST_PROFILE), viewModel.uiState.value)
    }

    @Test
    fun `an unreachable backend fails and a retry reads the profile again`() {
        client.meResult = ApiResult.Failure(ApiError.Network)
        session.open("session-token")
        assertEquals(ProfileUiState.Failed(ProfileError.Network), viewModel.uiState.value)

        client.meResult = ApiResult.Success(TEST_PROFILE)
        viewModel.onRetryClick()

        assertEquals(ProfileUiState.Loaded(TEST_PROFILE), viewModel.uiState.value)
        assertEquals(listOf("session-token", "session-token"), client.meTokens)
    }

    @Test
    fun `a server error and an unreadable answer are told apart`() {
        client.meResult = ApiResult.Failure(ApiError.Server)
        session.open("session-token")
        assertEquals(ProfileUiState.Failed(ProfileError.Server), viewModel.uiState.value)

        client.meResult = ApiResult.Failure(ApiError.Unexpected)
        viewModel.onRetryClick()
        assertEquals(ProfileUiState.Failed(ProfileError.Unexpected), viewModel.uiState.value)
    }

    @Test
    fun `a rejected token closes the session`() {
        client.meResult = ApiResult.Failure(ApiError.Unauthorized)

        session.open("expired-token")

        assertNull(session.accessToken.value)
        assertTrue("the sign-in screen says the session ended", session.sessionEnded.value)
    }

    @Test
    fun `signing out closes the session and clears the profile`() {
        session.open("session-token")

        viewModel.onSignOutClick()

        assertNull(session.accessToken.value)
        assertFalse("signing out is not an ended session", session.sessionEnded.value)
        assertEquals(ProfileUiState.Loading, viewModel.uiState.value)
    }

    @Test
    fun `a later session loads the profile again`() {
        session.open("first-token")
        viewModel.onSignOutClick()

        session.open("second-token")

        assertEquals(listOf("first-token", "second-token"), client.meTokens)
        assertEquals(ProfileUiState.Loaded(TEST_PROFILE), viewModel.uiState.value)
    }
}

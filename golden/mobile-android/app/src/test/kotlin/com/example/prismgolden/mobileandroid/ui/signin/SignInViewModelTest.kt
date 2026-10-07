package com.example.prismgolden.mobileandroid.ui.signin

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
import com.example.prismgolden.mobileandroid.data.api.DevTokenResponse
import com.example.prismgolden.mobileandroid.session.SessionStore
import com.example.prismgolden.mobileandroid.support.FakeApiClient
import com.example.prismgolden.mobileandroid.support.MainDispatcherRule

class SignInViewModelTest {

    @get:Rule
    val mainDispatcher = MainDispatcherRule()

    private val client = FakeApiClient()
    private val session = SessionStore()
    private lateinit var viewModel: SignInViewModel

    // Built after the rule has replaced the main dispatcher, because a ViewModel takes its scope when it is created.
    @Before
    fun createViewModel() {
        viewModel = SignInViewModel(client, session)
    }

    @Test
    fun `signing in opens the session with the token of the dev identity`() {
        viewModel.onSignInClick()

        assertEquals("fake-token", session.accessToken.value)
        assertEquals(SignInUiState(), viewModel.uiState.value)
        assertEquals(1, client.tokenRequests.size)
    }

    @Test
    fun `the state is loading while the dev identity answers`() {
        val gate = CompletableDeferred<Unit>()
        client.gate = gate

        viewModel.onSignInClick()
        assertTrue(viewModel.uiState.value.isLoading)
        assertNull(session.accessToken.value)

        gate.complete(Unit)
        assertFalse(viewModel.uiState.value.isLoading)
        assertEquals("fake-token", session.accessToken.value)
    }

    @Test
    fun `a second tap while loading sends no second request`() {
        client.gate = CompletableDeferred()

        viewModel.onSignInClick()
        viewModel.onSignInClick()

        assertEquals(1, client.tokenRequests.size)
    }

    @Test
    fun `a backend without the dev identity is reported and no session opens`() {
        client.tokenResult = ApiResult.Failure(ApiError.NotServed)

        viewModel.onSignInClick()

        assertEquals(SignInUiState(error = SignInError.DevIdentityUnavailable), viewModel.uiState.value)
        assertNull(session.accessToken.value)
    }

    @Test
    fun `a request that did not come from loopback is reported`() {
        client.tokenResult = ApiResult.Failure(ApiError.LoopbackOnly)

        viewModel.onSignInClick()

        assertEquals(SignInError.LoopbackOnly, viewModel.uiState.value.error)
        assertNull(session.accessToken.value)
    }

    @Test
    fun `an unreachable backend is reported`() {
        client.tokenResult = ApiResult.Failure(ApiError.Network)

        viewModel.onSignInClick()

        assertEquals(SignInError.Network, viewModel.uiState.value.error)
    }

    @Test
    fun `any other failure is reported as unexpected`() {
        client.tokenResult = ApiResult.Failure(ApiError.Server)

        viewModel.onSignInClick()

        assertEquals(SignInError.Unexpected, viewModel.uiState.value.error)
    }

    @Test
    fun `a new attempt clears the previous error`() {
        client.tokenResult = ApiResult.Failure(ApiError.Network)
        viewModel.onSignInClick()
        assertEquals(SignInError.Network, viewModel.uiState.value.error)

        client.tokenResult = ApiResult.Success(DevTokenResponse("second-token", "Bearer", 900))
        viewModel.onSignInClick()

        assertNull(viewModel.uiState.value.error)
        assertEquals("second-token", session.accessToken.value)
    }
}

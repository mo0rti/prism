package com.example.prismgolden.mobileandroid.ui.signin

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import com.example.prismgolden.mobileandroid.designsystem.theme.AppTheme

/**
 * A Compose UI test of the sign-in screen. Robolectric runs it on the JVM, so the unit tests and the CI
 * build cover it without an emulator.
 */
@RunWith(RobolectricTestRunner::class)
class SignInScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    private fun show(state: SignInUiState = SignInUiState(), onSignInClick: () -> Unit = {}) {
        composeRule.setContent {
            AppTheme {
                SignInScreen(state = state, onSignInClick = onSignInClick)
            }
        }
    }

    @Test
    fun `the screen is labelled as the local development sign-in`() {
        show()

        composeRule.onNodeWithText("Local development sign-in").assertIsDisplayed()
    }

    @Test
    fun `the screen says it is not complete authentication`() {
        show()

        composeRule.onNodeWithText("It is not complete authentication.", substring = true).assertIsDisplayed()
    }

    @Test
    fun `tapping the button signs in`() {
        var taps = 0
        show(onSignInClick = { taps++ })

        composeRule.onNodeWithText("Sign in as local developer").performClick()

        assertEquals(1, taps)
    }

    @Test
    fun `an error explains how to reach the backend`() {
        show(SignInUiState(error = SignInError.LoopbackOnly))

        composeRule.onNodeWithText("adb reverse", substring = true).assertIsDisplayed()
    }

    @Test
    fun `the button is disabled while signing in`() {
        show(SignInUiState(isLoading = true))

        composeRule.onNode(hasClickAction()).assertIsNotEnabled()
    }
}

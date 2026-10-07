package com.example.prismgolden.mobileandroid.support

import kotlinx.coroutines.CompletableDeferred
import com.example.prismgolden.mobileandroid.data.api.ApiClient
import com.example.prismgolden.mobileandroid.data.api.ApiResult
import com.example.prismgolden.mobileandroid.data.api.DevTokenRequest
import com.example.prismgolden.mobileandroid.data.api.DevTokenResponse
import com.example.prismgolden.mobileandroid.data.api.UserProfile

val TEST_PROFILE = UserProfile(
    id = "0b6f0b3e-0000-4000-8000-000000000000",
    displayName = "Local Developer",
    email = "developer@example.test",
    createdAt = "2026-01-01T00:00:00Z",
)

/** A backend that answers what a test tells it to, and records what it was asked. */
class FakeApiClient : ApiClient {
    var tokenResult: ApiResult<DevTokenResponse> = ApiResult.Success(DevTokenResponse("fake-token", "Bearer", 900))
    var meResult: ApiResult<UserProfile> = ApiResult.Success(TEST_PROFILE)

    /** While set, a call suspends until the test completes it. */
    var gate: CompletableDeferred<Unit>? = null

    val tokenRequests = mutableListOf<DevTokenRequest>()
    val meTokens = mutableListOf<String>()

    override suspend fun createDevToken(request: DevTokenRequest): ApiResult<DevTokenResponse> {
        tokenRequests += request
        gate?.await()
        return tokenResult
    }

    override suspend fun getMe(accessToken: String): ApiResult<UserProfile> {
        meTokens += accessToken
        gate?.await()
        return meResult
    }
}

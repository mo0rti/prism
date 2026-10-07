package com.example.prismgolden.mobileandroid.data.api

/** What can go wrong with a call to the backend. The ViewModels turn each into a message. */
enum class ApiError {
    /** The backend does not serve this route: it does not run under its `local` profile. */
    NotServed,

    /** The backend refused the request because it did not arrive from its own loopback interface. */
    LoopbackOnly,

    /** The bearer token is missing, invalid or expired. */
    Unauthorized,

    /** The backend could not be reached. */
    Network,

    /** The backend answered with an error status. */
    Server,

    /** The answer could not be read. */
    Unexpected,
}

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>

    data class Failure(val error: ApiError) : ApiResult<Nothing>
}

/**
 * The backend as the ViewModels see it. The interface exists so a test can substitute a fake;
 * `RetrofitApiClient` is the only implementation the app ships.
 */
interface ApiClient {
    suspend fun createDevToken(request: DevTokenRequest = DevTokenRequest()): ApiResult<DevTokenResponse>

    suspend fun getMe(accessToken: String): ApiResult<UserProfile>
}

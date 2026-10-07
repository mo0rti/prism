package com.example.prismgolden.backend.modules.devidentity.error

import com.example.prismgolden.backend.shared.error.ErrorCode
import org.springframework.http.HttpStatus

/** Error codes owned by the dev-identity module. */
enum class DevIdentityErrorCode(
    override val httpStatus: HttpStatus,
    override val defaultMessage: String
) : ErrorCode {
    LOOPBACK_ONLY(HttpStatus.FORBIDDEN, "The development identity answers only requests from this machine");

    override val code: String = name
}

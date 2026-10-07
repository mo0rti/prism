package com.example.prismgolden.backend.shared.exception

import com.example.prismgolden.backend.shared.error.CommonErrorCode
import com.example.prismgolden.backend.shared.error.ErrorCode
import org.springframework.http.HttpStatus

/**
 * HTTP 409 wrapper around a typed [ErrorCode].
 *
 * The guard keeps the wrapper type and supplied error code aligned so callers
 * cannot accidentally return a non-409 error through this exception.
 */
class ConflictException(
    errorCode: ErrorCode = CommonErrorCode.CONFLICT,
    message: String = errorCode.defaultMessage,
    details: Map<String, Any>? = null
) : ApiException(errorCode, message, details) {
    init {
        require(errorCode.httpStatus == HttpStatus.CONFLICT) {
            "ConflictException requires a CONFLICT error code, got ${errorCode.code} (${errorCode.httpStatus})"
        }
    }
}

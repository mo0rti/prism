package com.example.prismgolden.backend.shared.exception

import com.example.prismgolden.backend.modules.devidentity.error.DevIdentityErrorCode
import com.example.prismgolden.backend.shared.error.CommonErrorCode
import com.example.prismgolden.backend.shared.model.ApiErrorResponse
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.HttpStatus

class ErrorModelTest {

    private val handler = GlobalExceptionHandler()

    @Test
    fun `an api exception keeps the status, code and message of its error code`() {
        val response = handler.handleApiException(NotFoundException())

        assertEquals(HttpStatus.NOT_FOUND, response.statusCode)
        assertEquals(ApiErrorResponse(code = "NOT_FOUND", message = "Resource not found"), response.body)
    }

    @Test
    fun `a module error code and details travel through the built-in exception`() {
        val response = handler.handleApiException(
            ForbiddenException(DevIdentityErrorCode.LOOPBACK_ONLY, details = mapOf("remote" to "203.0.113.7"))
        )

        assertEquals(HttpStatus.FORBIDDEN, response.statusCode)
        val body = response.body as ApiErrorResponse
        assertEquals("LOOPBACK_ONLY", body.code)
        assertEquals(mapOf("remote" to "203.0.113.7"), body.details)
    }

    @Test
    fun `an unexpected exception is a 500 that does not leak its message`() {
        val response = handler.handleGeneric(IllegalStateException("secret internal detail"))

        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.statusCode)
        assertEquals("An unexpected error occurred", (response.body as ApiErrorResponse).message)
    }

    @Test
    fun `a built-in exception refuses an error code of another status`() {
        assertThrows<IllegalArgumentException> { NotFoundException(CommonErrorCode.FORBIDDEN) }
        assertThrows<IllegalArgumentException> { ForbiddenException(CommonErrorCode.NOT_FOUND) }
        assertThrows<IllegalArgumentException> { UnauthorizedException(CommonErrorCode.CONFLICT) }
        assertThrows<IllegalArgumentException> { ConflictException(CommonErrorCode.BAD_REQUEST) }
        assertThrows<IllegalArgumentException> { BadRequestException(CommonErrorCode.UNAUTHORIZED) }
    }
}

package com.example.prismgolden.backend.modules.devidentity.controller

import com.example.prismgolden.backend.modules.devidentity.dto.DevJwksResponse
import com.example.prismgolden.backend.modules.devidentity.dto.DevTokenRequest
import com.example.prismgolden.backend.modules.devidentity.dto.DevTokenResponse
import com.example.prismgolden.backend.modules.devidentity.error.DevIdentityErrorCode
import com.example.prismgolden.backend.modules.devidentity.service.DevIdentityJwksService
import com.example.prismgolden.backend.modules.devidentity.service.DevIdentityTokenService
import com.example.prismgolden.backend.modules.devidentity.service.LoopbackRequestPolicy
import com.example.prismgolden.backend.shared.exception.ForbiddenException
import jakarta.servlet.http.HttpServletRequest
import jakarta.validation.Valid
import org.springframework.context.annotation.Profile
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

/**
 * The routes of the local development identity:
 *
 * - `POST /api/dev-identity/token` signs a development token.
 * - `GET /api/dev-identity/jwks` publishes the public key that verifies those tokens, as a JWKS document.
 *
 * Both exist only under the `local` profile, so every other profile answers 404, and both accept only
 * requests from the loopback interface.
 *
 * This is local sign-in for development. It is not authentication, and the OpenAPI contract marks both
 * routes `x-prism-dev-only`.
 */
@RestController
@Profile("local")
@RequestMapping("/api/dev-identity")
class DevIdentityController(
    private val tokenService: DevIdentityTokenService,
    private val jwksService: DevIdentityJwksService
) {

    @PostMapping("/token")
    fun token(
        @Valid @RequestBody(required = false) request: DevTokenRequest?,
        servletRequest: HttpServletRequest
    ): DevTokenResponse {
        requireLoopback(servletRequest)
        val issued = tokenService.issue(email = request?.email, displayName = request?.displayName)
        return DevTokenResponse(accessToken = issued.value, expiresIn = issued.expiresIn.seconds)
    }

    @GetMapping("/jwks")
    fun jwks(servletRequest: HttpServletRequest): DevJwksResponse {
        requireLoopback(servletRequest)
        return jwksService.publicKeySet()
    }

    private fun requireLoopback(servletRequest: HttpServletRequest) {
        val allowed = LoopbackRequestPolicy.allows(
            remoteAddress = servletRequest.remoteAddr,
            serverName = servletRequest.serverName,
            headerNames = servletRequest.headerNames.toList()
        )
        if (!allowed) {
            throw ForbiddenException(DevIdentityErrorCode.LOOPBACK_ONLY)
        }
    }
}

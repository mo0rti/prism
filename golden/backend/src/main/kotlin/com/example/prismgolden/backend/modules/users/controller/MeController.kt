package com.example.prismgolden.backend.modules.users.controller

import com.example.prismgolden.backend.modules.users.dto.UserProfileResponse
import com.example.prismgolden.backend.modules.users.dto.toResponse
import com.example.prismgolden.backend.modules.users.model.IdentityClaims
import com.example.prismgolden.backend.modules.users.service.UserService
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.security.oauth2.jwt.Jwt
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

/** `GET /api/me`: the profile of the user the bearer token belongs to. */
@RestController
@RequestMapping("/api/me")
class MeController(
    private val userService: UserService
) {

    @GetMapping
    fun me(@AuthenticationPrincipal jwt: Jwt): UserProfileResponse {
        val claims = IdentityClaims(
            subject = jwt.subject,
            email = jwt.getClaimAsString("email"),
            name = jwt.getClaimAsString("name")
        )
        return userService.profileFor(claims).toResponse()
    }
}

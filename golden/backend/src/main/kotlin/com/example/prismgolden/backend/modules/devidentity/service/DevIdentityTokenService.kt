package com.example.prismgolden.backend.modules.devidentity.service

import com.example.prismgolden.backend.bootstrap.properties.DevIdentityProperties
import com.example.prismgolden.backend.modules.devidentity.model.DevIdentity
import com.example.prismgolden.backend.modules.devidentity.model.IssuedToken
import org.springframework.context.annotation.Profile
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm
import org.springframework.security.oauth2.jwt.JwsHeader
import org.springframework.security.oauth2.jwt.JwtClaimsSet
import org.springframework.security.oauth2.jwt.JwtEncoder
import org.springframework.security.oauth2.jwt.JwtEncoderParameters
import org.springframework.stereotype.Service
import java.time.Instant

/**
 * Signs the short-lived tokens of the local development identity.
 *
 * The subject is `dev:<email>`, so the same email always signs in as the same user. The `email` and
 * `name` claims let the users module create the profile on the first call to `GET /api/me`, the same way
 * it would for the tokens of a real provider.
 */
@Service
@Profile("local")
class DevIdentityTokenService(
    private val encoder: JwtEncoder,
    private val properties: DevIdentityProperties
) {

    fun issue(email: String?, displayName: String?): IssuedToken {
        val resolvedEmail = email?.trim()?.takeIf { it.isNotEmpty() } ?: DevIdentity.DEFAULT_EMAIL
        val resolvedName = displayName?.trim()?.takeIf { it.isNotEmpty() } ?: DevIdentity.DEFAULT_DISPLAY_NAME
        val issuedAt = Instant.now()
        val claims = JwtClaimsSet.builder()
            .issuer(DevIdentity.ISSUER)
            .subject("dev:${resolvedEmail.lowercase()}")
            .issuedAt(issuedAt)
            .expiresAt(issuedAt.plus(properties.tokenTtl))
            .claim("email", resolvedEmail)
            .claim("name", resolvedName)
            .build()
        val header = JwsHeader.with(SignatureAlgorithm.RS256).build()
        val token = encoder.encode(JwtEncoderParameters.from(header, claims)).tokenValue
        return IssuedToken(value = token, expiresIn = properties.tokenTtl)
    }
}

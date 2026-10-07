package com.example.prismgolden.backend.bootstrap.security

import org.springframework.security.oauth2.jwt.BadJwtException
import org.springframework.security.oauth2.jwt.Jwt
import org.springframework.security.oauth2.jwt.JwtDecoder

/**
 * The decoder of an app with no identity provider: it rejects every token.
 *
 * Failing closed keeps a deployment that forgot its issuer from accepting anything.
 */
class RejectingJwtDecoder : JwtDecoder {

    override fun decode(token: String): Jwt =
        throw BadJwtException("No identity provider is configured")
}

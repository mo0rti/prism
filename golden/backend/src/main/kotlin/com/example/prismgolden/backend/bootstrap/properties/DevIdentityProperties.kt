package com.example.prismgolden.backend.bootstrap.properties

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

/**
 * Settings of the local development identity (`prism.dev-identity.*`, profile `local` only).
 *
 * The token lifetime stays short on purpose: it is capped at one hour.
 */
@ConfigurationProperties(prefix = "prism.dev-identity")
data class DevIdentityProperties(
    val tokenTtl: Duration = Duration.ofMinutes(15)
) {
    init {
        require(!tokenTtl.isNegative && !tokenTtl.isZero && tokenTtl <= MAX_TOKEN_TTL) {
            "prism.dev-identity.token-ttl must be longer than zero and at most $MAX_TOKEN_TTL, got $tokenTtl"
        }
    }

    companion object {
        val MAX_TOKEN_TTL: Duration = Duration.ofHours(1)
    }
}

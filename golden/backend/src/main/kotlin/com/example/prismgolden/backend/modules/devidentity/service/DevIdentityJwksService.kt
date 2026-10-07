package com.example.prismgolden.backend.modules.devidentity.service

import com.example.prismgolden.backend.modules.devidentity.dto.DevJwksResponse
import com.nimbusds.jose.jwk.JWKSet
import com.nimbusds.jose.jwk.RSAKey
import org.springframework.context.annotation.Profile
import org.springframework.stereotype.Service

/**
 * Publishes the public half of the dev identity's signing key, so another local service (such as an
 * agent service) can verify the tokens without any shared secret.
 *
 * Only the public key leaves this class: the key set is built from [RSAKey.toPublicJWK] and serialized
 * with `publicKeysOnly`, so the private members never reach the response.
 */
@Service
@Profile("local")
class DevIdentityJwksService(
    private val devIdentityKey: RSAKey
) {

    fun publicKeySet(): DevJwksResponse {
        val keys = JWKSet(devIdentityKey.toPublicJWK()).toJSONObject(true)["keys"]
        @Suppress("UNCHECKED_CAST")
        return DevJwksResponse(keys = keys as List<Map<String, Any>>)
    }
}

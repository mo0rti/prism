package com.example.prismgolden.backend.modules.devidentity.dto

/** The JSON Web Key Set (RFC 7517) of the dev identity: the public key that verifies its tokens. */
data class DevJwksResponse(
    val keys: List<Map<String, Any>>
)

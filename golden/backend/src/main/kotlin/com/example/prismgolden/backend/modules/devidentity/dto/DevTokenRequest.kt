package com.example.prismgolden.backend.modules.devidentity.dto

import jakarta.validation.constraints.Email
import jakarta.validation.constraints.Size

/** Who the dev identity signs in as. Both fields are optional. */
data class DevTokenRequest(
    @field:Email
    @field:Size(max = 320)
    val email: String? = null,

    @field:Size(max = 100)
    val displayName: String? = null
)

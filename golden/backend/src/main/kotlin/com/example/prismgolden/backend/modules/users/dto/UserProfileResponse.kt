package com.example.prismgolden.backend.modules.users.dto

import java.time.Instant
import java.util.UUID

data class UserProfileResponse(
    val id: UUID,
    val displayName: String,
    val email: String?,
    val createdAt: Instant
)

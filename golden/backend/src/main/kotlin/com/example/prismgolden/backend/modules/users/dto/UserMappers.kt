package com.example.prismgolden.backend.modules.users.dto

import com.example.prismgolden.backend.modules.users.model.User

fun User.toResponse(): UserProfileResponse = UserProfileResponse(
    id = id,
    displayName = displayName,
    email = email,
    createdAt = createdAt
)

package com.example.prismgolden.backend.modules.users.model

/** What the users module reads from a verified token: who it is for and what the provider says about them. */
data class IdentityClaims(
    val subject: String,
    val email: String?,
    val name: String?
)

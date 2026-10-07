package com.example.prismgolden.backend.modules.users.model

import com.example.prismgolden.backend.shared.audit.AuditableEntity
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.Id
import jakarta.persistence.Table
import java.util.UUID

/** The profile of a signed-in user. `subject` is the `sub` claim of the identity provider's token. */
@Entity
@Table(name = "users")
class User(
    @Id
    val id: UUID = UUID.randomUUID(),

    @Column(nullable = false, updatable = false, unique = true)
    val subject: String,

    @Column
    var email: String? = null,

    @Column(name = "display_name", nullable = false)
    var displayName: String
) : AuditableEntity()

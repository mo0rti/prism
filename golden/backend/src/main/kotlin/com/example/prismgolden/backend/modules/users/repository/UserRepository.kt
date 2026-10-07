package com.example.prismgolden.backend.modules.users.repository

import com.example.prismgolden.backend.modules.users.model.User
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface UserRepository : JpaRepository<User, UUID> {
    fun findBySubject(subject: String): User?
}

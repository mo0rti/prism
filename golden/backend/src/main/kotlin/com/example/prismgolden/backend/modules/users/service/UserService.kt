package com.example.prismgolden.backend.modules.users.service

import com.example.prismgolden.backend.modules.users.model.IdentityClaims
import com.example.prismgolden.backend.modules.users.model.User
import com.example.prismgolden.backend.modules.users.repository.UserRepository
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.stereotype.Service

/**
 * Looks up the profile of a signed-in user and creates it the first time a token's subject calls the API.
 *
 * Not `@Transactional` as a whole: when two first calls race, the loser's insert fails on the unique
 * `subject` and a failed insert cannot continue inside the same database transaction, so each repository
 * call runs in its own and the loser reads the winner's row.
 */
@Service
class UserService(
    private val userRepository: UserRepository
) {

    fun profileFor(claims: IdentityClaims): User =
        userRepository.findBySubject(claims.subject) ?: createProfile(claims)

    private fun createProfile(claims: IdentityClaims): User {
        val user = User(
            subject = claims.subject,
            email = claims.email?.trim()?.takeIf { it.isNotEmpty() },
            displayName = displayNameOf(claims)
        )
        return try {
            userRepository.saveAndFlush(user)
        } catch (ex: DataIntegrityViolationException) {
            userRepository.findBySubject(claims.subject) ?: throw ex
        }
    }

    private fun displayNameOf(claims: IdentityClaims): String =
        (claims.name?.trim()?.takeIf { it.isNotEmpty() }
            ?: claims.email?.trim()?.takeIf { it.isNotEmpty() }
            ?: claims.subject)
            .take(MAX_DISPLAY_NAME_LENGTH)

    companion object {
        const val MAX_DISPLAY_NAME_LENGTH = 100
    }
}

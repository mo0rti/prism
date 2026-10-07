package com.example.prismgolden.backend.modules.devidentity.model

/** The fixed facts of the local development identity. */
object DevIdentity {
    /** The `iss` claim of every dev-identity token. The resource server accepts no other issuer under `local`. */
    const val ISSUER = "prism-dev-identity"

    const val DEFAULT_EMAIL = "developer@example.test"
    const val DEFAULT_DISPLAY_NAME = "Local Developer"
}

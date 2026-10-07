package com.example.prismgolden.backend.bootstrap

import com.example.prismgolden.backend.bootstrap.properties.DevIdentityProperties
import com.example.prismgolden.backend.modules.devidentity.model.DevIdentity
import com.nimbusds.jose.jwk.JWKSet
import com.nimbusds.jose.jwk.RSAKey
import com.nimbusds.jose.jwk.source.ImmutableJWKSet
import com.nimbusds.jose.proc.SecurityContext
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.context.annotation.Profile
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator
import org.springframework.security.oauth2.jwt.JwtDecoder
import org.springframework.security.oauth2.jwt.JwtEncoder
import org.springframework.security.oauth2.jwt.JwtValidators
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder
import java.security.KeyPairGenerator
import java.security.interfaces.RSAPrivateKey
import java.security.interfaces.RSAPublicKey
import java.util.UUID

/**
 * The signing key, encoder and decoder of the local development identity.
 *
 * Exists only under the `local` profile. The key pair is generated in memory when the app starts and is
 * never written anywhere, so every restart invalidates the tokens of the previous run and no secret
 * exists in the repository or on disk.
 */
@Configuration(proxyBeanMethods = false)
@Profile("local")
@EnableConfigurationProperties(DevIdentityProperties::class)
class DevIdentityConfig {

    @Bean
    fun devIdentityKey(): RSAKey {
        val generator = KeyPairGenerator.getInstance("RSA")
        generator.initialize(2048)
        val pair = generator.generateKeyPair()
        return RSAKey.Builder(pair.public as RSAPublicKey)
            .privateKey(pair.private as RSAPrivateKey)
            .keyID(UUID.randomUUID().toString())
            .build()
    }

    @Bean
    fun devIdentityJwtEncoder(devIdentityKey: RSAKey): JwtEncoder =
        NimbusJwtEncoder(ImmutableJWKSet<SecurityContext>(JWKSet(devIdentityKey)))

    /** Accepts only tokens signed by this run's key, issued by [DevIdentity.ISSUER] and not expired. */
    @Bean
    fun devIdentityJwtDecoder(devIdentityKey: RSAKey): JwtDecoder {
        val decoder = NimbusJwtDecoder.withPublicKey(devIdentityKey.toRSAPublicKey()).build()
        decoder.setJwtValidator(DelegatingOAuth2TokenValidator(JwtValidators.createDefaultWithIssuer(DevIdentity.ISSUER)))
        return decoder
    }
}

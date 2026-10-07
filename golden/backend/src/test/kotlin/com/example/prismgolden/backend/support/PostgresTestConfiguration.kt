package com.example.prismgolden.backend.support

import org.springframework.boot.test.context.TestConfiguration
import org.springframework.boot.testcontainers.service.connection.ServiceConnection
import org.springframework.context.annotation.Bean
import org.testcontainers.postgresql.PostgreSQLContainer

/**
 * A throwaway PostgreSQL for the integration tests, started by Testcontainers and wired into the
 * datasource by `@ServiceConnection`. The tests need Docker and no other setup: they never touch the
 * development database of the workspace's docker-compose.yml.
 */
@TestConfiguration(proxyBeanMethods = false)
class PostgresTestConfiguration {

    @Bean
    @ServiceConnection
    fun postgres(): PostgreSQLContainer = PostgreSQLContainer("postgres:16-alpine")
}

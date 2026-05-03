---
name: testing-patterns
description: Backend testing conventions for JUnit and MockK. Use when writing or reviewing backend unit tests, service tests, integration tests, or deciding how a backend change should be verified under `backend/`.
---

# Testing Patterns

Use this skill for backend test structure and verification choices.

## Test Layout

Keep tests mirroring the main source structure under `src/test/kotlin/`.

## Unit Test Rules

- Use MockK rather than Mockito.
- Prefer constructor injection of mocks over Spring-based unit-test setup.
- Use backtick test names for readable scenarios.
- Group related scenarios with `@Nested` and `@DisplayName` when it improves clarity.
- Clean up MockK state between tests when required.

## Integration Test Rules

- Use `@SpringBootTest` only when the test genuinely needs a Spring context.
- Use the test profile for integration scenarios.
- Use `@AutoConfigureMockMvc` with `MockMvc` when the test must exercise route exposure, JWT filters, validation wiring, or exception mapping.
- Prefer narrower test slices over full-context tests when possible, but not when the real security/filter chain is the thing under test.

## Current Scaffold Baseline

- Service and domain behavior: MockK-heavy unit tests
- Security and auth exposure rules: `@SpringBootTest` integration tests
- Endpoint security/filter behavior: `@SpringBootTest` + `MockMvc`

Do not assume MVC or JPA slice tests are the default scaffold style.

## Slice Test Rules

- Use `@WebMvcTest` for focused controller mapping, request binding, and validation checks when the full security chain is not the target behavior.
- Use `@DataJpaTest` for custom repository queries, entity mappings, and persistence-specific behavior.
- Escalate to a fuller integration test when slices would hide the wiring you actually need confidence in.

## What to Test

- Service logic, validation, and exception paths with unit tests.
- Repository custom queries and entity mappings with `@DataJpaTest` or integration tests.
- Controller mapping and response behavior with MVC-slice or integration tests.
- Security, JWT filter, and public-route behavior with `@SpringBootTest` + `MockMvc`.
- Domain logic without mocks when possible.

## DTO Assertion Rules

- Assert typed DTO fields using their real Kotlin types rather than their eventual serialized JSON representation.
- When a response DTO exposes enums, assert the enum values directly in service tests.
- Keep serialization-shape assertions in controller or integration tests, not in pure service tests.

## OAuth Client Testing

- For code that calls external OAuth providers, prefer a mock web server or `MockRestServiceServer` to verify token exchange and user-info requests without hitting real providers.
- In higher-level auth service tests, mock or stub the OAuth client/service boundary instead of coupling every test to remote provider payload details.

## Avoid

- Mockito in Kotlin-first backend tests
- `@SpringBootTest` for pure unit tests
- `@MockBean` when plain constructor-injected mocks are enough
- `@WebMvcTest` when the real security chain is the behavior under test
- tests that target private methods instead of public behavior

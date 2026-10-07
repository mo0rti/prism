---
name: jackson-spring-boot4
description: Jackson 3.x rules for Spring Boot 4. Use when writing or reviewing code that involves JSON serialization, deserialization, ObjectMapper, or Jackson annotations in this Spring Boot 4 + Kotlin project.
---

# Jackson 3.x Usage Rules (Spring Boot 4)

This project uses **Spring Boot 4** which ships with **Jackson 3.x**. Jackson 3.x has a **split namespace** design - annotations and runtime classes live in different packages.

## Annotation Namespace Rules

Jackson 3.x annotations are split across TWO packages:

### Core annotations - `com.fasterxml.jackson.annotation.*`

These remain in the Jackson 2.x annotation JAR (Jackson 3.x depends on `jackson-annotations:2.x`).

```kotlin
import com.fasterxml.jackson.annotation.JsonProperty
import com.fasterxml.jackson.annotation.JsonIgnore
import com.fasterxml.jackson.annotation.JsonValue
import com.fasterxml.jackson.annotation.JsonFormat
import com.fasterxml.jackson.annotation.JsonCreator
import com.fasterxml.jackson.annotation.JsonInclude
import com.fasterxml.jackson.annotation.JsonIgnoreProperties
import com.fasterxml.jackson.annotation.JsonTypeInfo
import com.fasterxml.jackson.annotation.JsonSubTypes
```

There is NO `tools.jackson.annotation` package - it does not exist.

### Databind-specific annotations - `tools.jackson.databind.annotation.*`

These moved to the `tools.jackson` namespace in Jackson 3.x.

```kotlin
import tools.jackson.databind.annotation.JsonDeserialize
import tools.jackson.databind.annotation.JsonSerialize
import tools.jackson.databind.annotation.JsonNaming
```

Do NOT use the old `com.fasterxml.jackson.databind.annotation.*` for these - that is Jackson 2.x.

## Runtime Namespace Rules

### Runtime classes - use `tools.jackson.*`:

```kotlin
import tools.jackson.databind.ObjectMapper
import tools.jackson.databind.JsonNode
import tools.jackson.core.type.TypeReference
```

### NEVER use the old runtime namespace:

Using `com.fasterxml.jackson.databind.ObjectMapper` may still compile (the 2.x JAR can appear transitively) but it is a different class from the one Spring Boot 4 auto-configures. Mixing them leads to subtle bugs where Spring's config (custom serializers, modules, date formats) is silently ignored.

```kotlin
// These are WRONG - they are Jackson 2.x runtime classes:
import com.fasterxml.jackson.databind.ObjectMapper              // WRONG
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper   // WRONG
import com.fasterxml.jackson.core.type.TypeReference             // WRONG
```

## ObjectMapper Rules

1. **Inject Spring's ObjectMapper** - do NOT create standalone instances via `jacksonObjectMapper()`.

   ```kotlin
   // CORRECT: Inject Spring-managed ObjectMapper (tools.jackson.databind.ObjectMapper)
   @Service
   class MyService(private val objectMapper: ObjectMapper)

   // WRONG: Bypasses Spring config (custom serializers, modules, date formats not applied)
   private val objectMapper = jacksonObjectMapper()
   ```

2. **Never create ObjectMapper inside a method** - it is thread-safe and should be reused.

3. The only acceptable use of `jacksonObjectMapper()` is in classes that genuinely cannot participate in Spring DI (e.g., test utilities, CLI tools). All `@Service`, `@Component`, `@Controller` beans must inject.

## Entity Serialization Rules

- **Do NOT put Jackson annotations on JPA entity classes** (`@JsonIgnore`, `@JsonManagedReference`, `@JsonBackReference`, etc.). Entities should never be serialized directly to JSON - use DTOs as the serialization boundary.
- **Enums are an exception**: `@JsonValue` on an enum property is valid and expected (e.g., `enum class Foo(@JsonValue val value: String)`). This rule applies to `@Entity`-annotated classes, not enums.
- If you find Jackson annotations on an entity class, it is a code smell - remove them and ensure a DTO exists.

## Annotation Best Practices

- Do NOT add `@JsonProperty` when the annotation value matches the Kotlin property name exactly (it's redundant).
- For snake_case JSON keys, use `@JsonProperty("snake_case")` on camelCase Kotlin properties.
- For enums sent to/from external APIs, use `@JsonValue` on the serialization property.

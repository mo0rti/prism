package com.example.prismgolden.mobileandroid.data.api

import java.io.File
import kotlinx.serialization.KSerializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.yaml.snakeyaml.Yaml
import retrofit2.http.GET
import retrofit2.http.POST

/**
 * The client and `shared/api-contracts/openapi.yml` describe the same operations and shapes: the routes
 * `ApiService` calls, the fields of the three DTOs and the security of `getMe`. Change the contract and
 * the client together.
 */
class ApiContractTest {

    private val contract: Map<String, Any?> by lazy {
        val path = System.getProperty("prism.apiContract") ?: error("The build passes the contract's path as prism.apiContract")
        val file = File(path)
        assertTrue("The API contract is missing at ${file.absolutePath}", file.isFile)
        file.reader().use { Yaml().load<Map<String, Any?>>(it) }
    }

    @Suppress("UNCHECKED_CAST")
    private fun map(value: Any?): Map<String, Any?> = value as Map<String, Any?>

    private fun operation(path: String, method: String): Map<String, Any?> {
        val item = map(contract["paths"])[path]
        assertNotNull("The contract does not define $path", item)
        val operation = map(item)[method]
        assertNotNull("The contract does not define $method $path", operation)
        return map(operation)
    }

    private fun schema(name: String): Map<String, Any?> = map(map(map(contract["components"])["schemas"])[name])

    private fun fieldsOf(serializer: KSerializer<*>): List<Pair<String, Boolean>> =
        (0 until serializer.descriptor.elementsCount).map { index ->
            serializer.descriptor.getElementName(index) to serializer.descriptor.isElementOptional(index)
        }

    private fun assertMatchesSchema(name: String, serializer: KSerializer<*>) {
        val schema = schema(name)
        val properties = map(schema["properties"]).keys
        val required = (schema["required"] as? List<*>).orEmpty().map { it as String }.toSet()
        val fields = fieldsOf(serializer)

        assertEquals("$name: the DTO's fields and the contract's properties differ", properties, fields.map { it.first }.toSet())
        for ((field, optional) in fields) {
            assertEquals("$name.$field: required in the contract exactly when the DTO has no default", field !in required, optional)
        }
    }

    @Test
    fun `ApiService calls exactly the operations the contract defines for the slice`() {
        val calls = ApiService::class.java.declaredMethods.mapNotNull { method ->
            method.getAnnotation(POST::class.java)?.let { "post /${it.value}" }
                ?: method.getAnnotation(GET::class.java)?.let { "get /${it.value}" }
        }.toSet()

        assertEquals(setOf("post /api/dev-identity/token", "get /api/me"), calls)
        for (call in calls) {
            val (method, path) = call.split(" ")
            operation(path, method)
        }
    }

    @Test
    fun `the dev identity operation is dev only and open`() {
        val token = operation("/api/dev-identity/token", "post")

        assertEquals("createDevToken", token["operationId"])
        assertEquals(true, token["x-prism-dev-only"])
        assertEquals("the token route asks for no bearer token", emptyList<Any?>(), token["security"])
    }

    @Test
    fun `me uses the contract's global bearer security`() {
        val me = operation("/api/me", "get")

        assertEquals("getMe", me["operationId"])
        assertNull("me states no security of its own", me["security"])
        val security = (contract["security"] as List<*>).map { map(it).keys }
        assertTrue("the contract's default security is bearerAuth", security.any { "bearerAuth" in it })
    }

    @Test
    fun `the DTOs have the fields of the contract's schemas`() {
        assertMatchesSchema("DevTokenRequest", DevTokenRequest.serializer())
        assertMatchesSchema("DevTokenResponse", DevTokenResponse.serializer())
        assertMatchesSchema("UserProfile", UserProfile.serializer())
    }
}

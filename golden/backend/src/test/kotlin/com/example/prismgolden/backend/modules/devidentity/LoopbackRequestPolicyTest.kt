package com.example.prismgolden.backend.modules.devidentity

import com.example.prismgolden.backend.modules.devidentity.service.LoopbackRequestPolicy
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class LoopbackRequestPolicyTest {

    private val noHeaders = emptyList<String>()

    @Test
    fun `loopback addresses with a loopback host are allowed`() {
        assertTrue(LoopbackRequestPolicy.allows("127.0.0.1", "localhost:8080", noHeaders))
        assertTrue(LoopbackRequestPolicy.allows("127.0.0.1", "127.0.0.1:8080", noHeaders))
        assertTrue(LoopbackRequestPolicy.allows("0:0:0:0:0:0:0:1", "[::1]:8080", noHeaders))
        assertTrue(LoopbackRequestPolicy.allows("::1", "LOCALHOST", noHeaders))
    }

    @Test
    fun `any other peer address is refused`() {
        assertFalse(LoopbackRequestPolicy.allows("192.168.1.20", "localhost:8080", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("172.17.0.1", "localhost:8080", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("203.0.113.7", "localhost", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("0.0.0.0", "localhost", noHeaders))
    }

    @Test
    fun `a missing or unparsable peer address is refused`() {
        assertFalse(LoopbackRequestPolicy.allows(null, "localhost", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("", "localhost", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("not an address", "localhost", noHeaders))
    }

    @Test
    fun `a host that is not loopback is refused even from the loopback interface`() {
        assertFalse(LoopbackRequestPolicy.allows("127.0.0.1", "attacker.example", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("127.0.0.1", "localhost.attacker.example:8080", noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("127.0.0.1", null, noHeaders))
        assertFalse(LoopbackRequestPolicy.allows("127.0.0.1", "", noHeaders))
    }

    @Test
    fun `a forwarding header means the request went through a proxy`() {
        for (header in listOf("X-Forwarded-For", "x-forwarded-host", "Forwarded", "X-Real-IP")) {
            assertFalse(LoopbackRequestPolicy.allows("127.0.0.1", "localhost", listOf("Accept", header)), header)
        }
        assertTrue(LoopbackRequestPolicy.allows("127.0.0.1", "localhost", listOf("Accept", "Content-Type")))
    }
}

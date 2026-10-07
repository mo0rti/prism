package com.example.prismgolden.backend.modules.devidentity.service

import java.net.InetAddress

/**
 * Decides whether a request may use the development identity: it must come from the loopback interface
 * and be addressed to a loopback host name.
 *
 * - The remote address is the socket's peer address; no forwarding header is trusted.
 * - A request that carries a forwarding header went through a proxy and is refused.
 * - The server name (the Host header's name) must be a loopback one, which blocks DNS-rebinding pages.
 */
object LoopbackRequestPolicy {

    private val allowedHosts = setOf("localhost", "127.0.0.1", "::1")
    private val forwardingHeaders = listOf("Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP")

    fun allows(remoteAddress: String?, serverName: String?, headerNames: Collection<String>): Boolean {
        if (!isLoopbackAddress(remoteAddress)) return false
        if (headerNames.any { name -> forwardingHeaders.any { it.equals(name, ignoreCase = true) } }) return false
        return hostName(serverName) in allowedHosts
    }

    private fun isLoopbackAddress(remoteAddress: String?): Boolean {
        if (remoteAddress.isNullOrBlank()) return false
        // A literal IP address: this never resolves a name.
        return runCatching { InetAddress.getByName(remoteAddress).isLoopbackAddress }.getOrDefault(false)
    }

    private fun hostName(serverName: String?): String? {
        val value = serverName?.trim()?.lowercase()?.takeIf { it.isNotEmpty() } ?: return null
        if (value.startsWith("[")) {
            return value.substringAfter("[").substringBefore("]")
        }
        return value.substringBefore(":")
    }
}

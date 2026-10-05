import { NextRequest, NextResponse } from "next/server"
import { backendSession } from "@/lib/auth/backend-session"
import { resolveProxyPath } from "@/lib/config/api-routes"

export async function GET(
  request: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return proxyRequest(request, params.path, "GET")
}

export async function POST(
  request: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return proxyRequest(request, params.path, "POST")
}

export async function PUT(
  request: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return proxyRequest(request, params.path, "PUT")
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return proxyRequest(request, params.path, "PATCH")
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return proxyRequest(request, params.path, "DELETE")
}

async function proxyRequest(
  request: NextRequest,
  pathSegments: string[],
  method: string,
) {
  let persist = async (response: NextResponse) => response
  try {
    // Reject before any session work so a crafted path never reaches the backend
    // with a bearer token.
    const backendPath = resolveProxyPath(pathSegments)
    if (!backendPath) {
      return NextResponse.json({ error: "Invalid API path" }, { status: 400 })
    }

    const apiBaseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
    if (!apiBaseUrl) {
      return NextResponse.json({ error: "API_BASE_URL is not configured." }, { status: 500 })
    }

    const session = await backendSession(request)
    persist = session.persist
    if (!session.token?.accessToken) {
      return session.persist(NextResponse.json({ error: "Authentication required" }, { status: 401 }))
    }
    if (session.token.role !== "ADMIN") {
      return session.persist(NextResponse.json({ error: "Administrator access required" }, { status: 403 }))
    }
    const targetUrl = `${apiBaseUrl}${backendPath}${request.nextUrl.search}`

    const headers = new Headers()
    headers.set("accept", "application/json")

    const contentType = request.headers.get("content-type")
    if (contentType) {
      headers.set("content-type", contentType)
    }

    if (session.token?.accessToken) {
      headers.set("authorization", `Bearer ${session.token.accessToken}`)
    }

    let body: BodyInit | undefined
    if (!["GET", "DELETE"].includes(method)) {
      if (contentType?.includes("multipart/form-data")) {
        body = await request.formData()
        headers.delete("content-type")
      } else {
        const text = await request.text()
        body = text || undefined
      }
    }

    const response = await fetch(targetUrl, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    })

    if (response.status === 204) {
      return session.persist(new NextResponse(null, { status: 204 }))
    }

    const responseText = await response.text()
    const responseContentType = response.headers.get("content-type") || "application/json"

    return session.persist(new NextResponse(responseText, {
      status: response.status,
      headers: {
        "Content-Type": responseContentType,
      },
    }))
  } catch {
    return persist(NextResponse.json(
      {
        error: "Proxy Error",
      },
      { status: 500 },
    ))
  }
}

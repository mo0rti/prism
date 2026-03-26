import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/auth"
import { getBackendPath } from "@/lib/config/api-routes"

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
  try {
    const apiBaseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
    if (!apiBaseUrl) {
      return NextResponse.json({ error: "API_BASE_URL is not configured." }, { status: 500 })
    }

    const session = await auth()
    const frontendPath = `/api/v1/${pathSegments.join("/")}`
    const backendPath = getBackendPath(frontendPath)
    const targetUrl = `${apiBaseUrl}${backendPath}${request.nextUrl.search}`

    const headers = new Headers()
    headers.set("accept", "application/json")

    const contentType = request.headers.get("content-type")
    if (contentType) {
      headers.set("content-type", contentType)
    }

    if (session?.accessToken) {
      headers.set("authorization", `Bearer ${session.accessToken}`)
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
    })

    if (response.status === 204) {
      return new NextResponse(null, { status: 204 })
    }

    const responseText = await response.text()
    const responseContentType = response.headers.get("content-type") || "application/json"

    return new NextResponse(responseText, {
      status: response.status,
      headers: {
        "Content-Type": responseContentType,
      },
    })
  } catch (error) {
    return NextResponse.json(
      {
        error: "Proxy Error",
        details: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    )
  }
}

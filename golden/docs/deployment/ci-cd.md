# CI - Prism Golden

## Overview

All CI runs on **GitHub Actions** with **path-based triggers** - each platform's workflow only runs when its files change. The generated workflows build and test only. They hold no deploy job, no cloud credentials and no secrets.

Hosting, secrets and deployment belong to the user and their agent. The `deployment` skill (`.claude/skills/deployment/` and `.agents/skills/deployment/`) holds worked examples for the backend on Azure Container Apps and the web apps on Cloudflare Workers, including a GitHub Actions deploy job for each, and notes on mobile store releases.

## Workflows

| Workflow | Trigger Paths | What It Does |
|----------|--------------|--------------|
| `backend.yml` | `backend/**`, `shared/api-contracts/**` | `./gradlew build`: compile, every test (the integration tests start PostgreSQL with Testcontainers) and the jar; upload test reports |
| `web.yml` | `web/**`, `shared/api-contracts/**` | `npm ci`, lint, typecheck, Vitest tests, `next build` |
| `mobile-android.yml` | `mobile-android/**`, `shared/api-contracts/**` | `./gradlew assembleDebug testDebugUnitTest` (the debug APK and the JVM unit tests, the Compose UI test included); upload the APK and the test reports |
| `mobile-ios.yml` | `mobile-ios/**`, `shared/api-contracts/**` | XcodeGen, simulator build, XCTest unit and UI tests (macOS runner) |
| `agent-service.yml` | `agent-service/**`, `shared/api-contracts/**` | `uv sync --locked`, ruff lint and format check, mypy, pytest and the evaluation set with the fake provider; no network, no API key |
| `api-contracts.yml` | `shared/api-contracts/**` | Validate OpenAPI spec |


The iOS CI job generates the Xcode project from the app's `project.yml` with XcodeGen, so the `.xcodeproj` is never committed.


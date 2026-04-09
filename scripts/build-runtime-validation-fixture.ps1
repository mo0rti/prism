param(
    [string]$TargetDir = "C:\temp\prism-runtime-validate"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content.TrimStart("`r", "`n"), $utf8NoBom)
}

function Set-Stamp {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][datetime]$Timestamp
    )

    $item = Get-Item -LiteralPath $Path
    $item.LastWriteTime = $Timestamp
    $item.LastAccessTime = $Timestamp
}

$repoRoot = Split-Path -Parent $PSScriptRoot

if (Test-Path -LiteralPath $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
}

Push-Location $repoRoot
try {
    copier copy --trust --defaults `
        --data "project_name=Prism Runtime Validate" `
        --data "description=Reusable runtime validation fixture for Prism wiki commands" `
        --data "platforms=[backend,mobile-android,mobile-ios,web-user-app,web-admin-portal]" `
        . $TargetDir
}
finally {
    Pop-Location
}

$wikiRoot = Join-Path $TargetDir "knowledge\wiki"

Write-Utf8File (Join-Path $wikiRoot "index.md") @'
# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review | Introduced |
|----|---------|--------|-------|--------------|------------|
| F-010 | Saved Checkout | ready-for-dev | dev | done | 2026-04-01 |
| F-011 | Nutrition Score | ready-for-design | designer | pending | 2026-03-15 |
| F-012 | Notification Preferences | in-design | designer | not-needed | 2026-04-02 |
| F-013 | Recurring Delivery | ready-for-dev | dev | done | 2026-04-03 |
| F-014 | Goal Alerts | in-dev | dev | done | 2026-04-04 |
| F-020 | Auth Session Hardening | ready-for-dev | dev | done | 2026-04-01 |
| F-099 | Broken Fixture Page | unknown | none | not-needed | 2026-04-01 |

## Other wiki pages
| Page | Type | Summary | Date |
|------|------|---------|------|
| [SCHEMA.md](SCHEMA.md) | meta | Wiki conventions and operational rules | - |
| [SETTINGS.md](SETTINGS.md) | config | Wiki read/query settings | 2026-04-09 |
| [BOARD.md](advisory/BOARD.md) | config | Advisory board composition | 2026-04-09 |
'@

Write-Utf8File (Join-Path $wikiRoot "log.md") @'
# Wiki log

Append-only record of all wiki operations. Most recent entry at the bottom.
Format: ## YYYY-MM-DD [operation] | [subject]

---

## 2026-04-01 init | Wiki initialized

Wiki created from Prism template and seeded for runtime validation.

## 2026-04-02 po-intake | F-010

Saved Checkout drafted from fixture corpus.

## 2026-04-05 design-handoff | F-013

Recurring Delivery moved to ready-for-dev.
'@

Write-Utf8File (Join-Path $wikiRoot "advisory\BOARD.md") @'
# Advisory Board

## Members

- Dr. Sana Vermeer - Nutrition safety and regulated claims
- Eli Navarro - Growth and retention strategy
- Priya Rao - Mobile reliability and release risk
- Martin de Vries - Privacy, consent, and account security

## Focus

Used only for runtime validation of board-review-aware wiki commands.
'@

Write-Utf8File (Join-Path $wikiRoot "business-rules\BR-004-checkout-address-validation.md") @'
---
id: BR-004
title: Checkout Address Validation
introduced: 2026-04-01
source: fixture-offline-checkout
---

## Rule
Offline checkout must reject expired or incomplete saved addresses before order submission.

## Rationale
Saved checkout must stay reliable when the device reconnects after the customer edits an address offline.

## Affected features
F-010

## Exceptions
No exceptions.
'@

Write-Utf8File (Join-Path $wikiRoot "business-rules\BR-020-auth-token-rotation.md") @'
---
id: BR-020
title: Auth Token Rotation
introduced: 2026-04-02
source: security-fixture
---

## Rule
Auth refresh tokens must rotate after each successful refresh call.

## Rationale
This auth rule limits session replay risk and supports secure auth session handling across clients.

## Affected features
F-020

## Exceptions
No exceptions.
'@

Write-Utf8File (Join-Path $wikiRoot "decisions\ADR-020-auth-provider.md") @'
---
id: ADR-020
title: Auth Provider Session Hardening
date: 2026-04-03
status: accepted
---

## Context
The product needs stronger auth session behavior across mobile and web clients.

## Decision
Adopt rotating auth refresh tokens with device-bound session metadata.

## Rationale
This keeps the auth provider flow aligned across clients and backend enforcement.

## Consequences
Backend and client auth code must store additional auth session metadata.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-010-saved-checkout.md") @'
---
id: F-010
title: Saved Checkout
status: ready-for-dev
owner: dev
introduced: 2026-04-01
last-updated: 2026-04-08
platforms: [backend, mobile-android, mobile-ios, web-user-app]
sources: [knowledge/intake/fixture/offline-checkout.md]
advisory-review: done
---

## Summary
Customers can reuse a saved shipping address and payment preference during offline checkout.

## User story
As a returning customer, I want to finish checkout quickly, so that I can place repeat orders with less effort.

## Acceptance criteria
- [ ] Customers can start offline checkout with a previously saved address.
- [ ] The app blocks invalid or expired saved addresses before final submission.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should guest checkout support saved addresses later? | dev | resolved: no, account only |

## Platform scope
- **backend**: Validate saved address and payment preference payloads for offline checkout recovery.
- **mobile-android**: Pre-fill checkout with the saved address and show invalid-state handling.
- **mobile-ios**: Pre-fill checkout with the saved address and show invalid-state handling.
- **web-user-app**: Reuse saved checkout details in the account dashboard flow.

## Design
See `knowledge/wiki/design/F-010-saved-checkout.md`.

## Related features
- [F-013](features/F-013-recurring-delivery.md) - recurring delivery uses the same saved address model.

## API surface
Saved checkout resume and address validation endpoints are required.

## Board review summary
Board review is complete with no blocking conflicts.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-011-nutrition-score.md") @'
---
id: F-011
title: Nutrition Score
status: ready-for-design
owner: designer
introduced: 2026-03-15
last-updated: 2026-03-20
platforms: [mobile-android, mobile-ios, web-user-app]
sources: [knowledge/intake/fixture/nutrition-score.md]
advisory-review: pending
---

## Summary
Customers see a simplified nutrition score for each meal recommendation.

## User story
As a health-conscious customer, I want a quick nutrition score, so that I can compare meals faster.

## Acceptance criteria
- [ ] A nutrition score appears on all supported recommendation cards.
- [ ] The score explanation is accessible from the meal detail view.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What visual treatment should low-confidence scores use? | designer | open |

## Platform scope
- **mobile-android**: Show nutrition score chips in recommendations.
- **mobile-ios**: Show nutrition score chips in recommendations.
- **web-user-app**: Show nutrition score chips on meal cards.

## Design
Empty until design starts.

## Related features
- [F-014](features/F-014-goal-alerts.md) - both rely on nutrition-event messaging.

## API surface
No new endpoints expected; likely extends recommendation payloads.

## Board review summary
Board review is still pending.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-012-notification-preferences.md") @'
---
id: F-012
title: Notification Preferences
status: in-design
owner: designer
introduced: 2026-04-02
last-updated: 2026-04-07
platforms: [mobile-ios, web-user-app]
sources: [knowledge/intake/fixture/notification-preferences.md]
advisory-review: not-needed
---

## Summary
Customers can control which nutrition and delivery alerts they receive.

## User story
As a customer, I want to choose my alerts, so that I only receive messages that matter to me.

## Acceptance criteria
- [ ] Customers can opt in or out of goal alerts.
- [ ] Changes sync across supported clients.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should quiet hours be in scope for v1? | po | resolved: no |

## Platform scope
- **mobile-ios**: Preferences form and local alert summary.
- **web-user-app**: Preferences page in account settings.

## Design
Empty.

## Related features
- [F-014](features/F-014-goal-alerts.md) - alert content depends on these preferences.

## API surface
Preferences read/write API is needed.

## Board review summary
Not required.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-013-recurring-delivery.md") @'
---
id: F-013
title: Recurring Delivery
status: ready-for-dev
owner: dev
introduced: 2026-04-03
last-updated: 2026-04-06
platforms: [backend, mobile-android, mobile-ios, web-user-app]
sources: [knowledge/intake/fixture/recurring-delivery.md]
advisory-review: done
---

## Summary
Customers can schedule a recurring weekly delivery using saved checkout details.

## User story
As a repeat customer, I want a recurring delivery schedule, so that I do not have to reorder every week.

## Acceptance criteria
- [ ] Customers can choose a weekly cadence.
- [ ] Customers can pause or resume the recurring schedule.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should holiday skips be part of v1? | po | resolved: no |

## Platform scope
- **backend**: Delivery schedule creation, pause, and resume.
- **mobile-android**: Schedule configuration and status display.
- **mobile-ios**: Schedule configuration and status display.
- **web-user-app**: Schedule configuration and status display.

## Design
See `knowledge/wiki/design/F-013-recurring-delivery.md`.

## Related features
- [F-010](features/F-010-saved-checkout.md) - recurring delivery depends on saved checkout data.

## API surface
Recurring schedule create and pause endpoints are required.

## Board review summary
Complete.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-014-goal-alerts.md") @'
---
id: F-014
title: Goal Alerts
status: in-dev
owner: dev
introduced: 2026-04-04
last-updated: 2026-04-05
platforms: [backend, mobile-android, mobile-ios]
sources: [knowledge/intake/fixture/goal-alerts.md]
advisory-review: done
---

## Summary
Customers receive alerts when they move toward or away from nutrition goals.

## User story
As a customer, I want goal alerts, so that I understand my progress without opening the app.

## Acceptance criteria
- [ ] Alerts explain what changed.
- [ ] Alert history is visible in-app.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What is the empty state for alert history? | designer | open |
| 2 | Should alert delivery retry for 24 hours or 48 hours? | dev | open |

## Platform scope
- **backend**: Goal evaluation and alert event publishing.
- **mobile-android**: Alert history and push deep link handling.
- **mobile-ios**: Alert history and push deep link handling.

## Design
See `knowledge/wiki/design/F-014-goal-alerts.md`.

## Related features
- [F-012](features/F-012-notification-preferences.md) - alert delivery respects notification preferences.

## API surface
Goal alert history and acknowledgement APIs are required.

## Board review summary
Complete.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-020-auth-session-hardening.md") @'
---
id: F-020
title: Auth Session Hardening
status: ready-for-dev
owner: dev
introduced: 2026-04-01
last-updated: 2026-04-08
platforms: [backend, mobile-android, mobile-ios, web-user-app, web-admin-portal]
sources: [knowledge/intake/fixture/auth-session.md]
advisory-review: done
---

## Summary
The auth session flow is hardened with rotating refresh tokens and richer auth audit visibility.

## User story
As a security-conscious user, I want my auth session to stay protected, so that account access remains trustworthy.

## Acceptance criteria
- [ ] Auth refresh tokens rotate on every refresh.
- [ ] Auth session revocation is visible to admins and end users.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should auth session history be retained for 30 or 90 days? | po | open |

## Platform scope
- **backend**: Auth session issuance, rotation, and revocation.
- **mobile-android**: Auth session reauthentication prompts.
- **mobile-ios**: Auth session reauthentication prompts.
- **web-user-app**: Auth session management UI.
- **web-admin-portal**: Auth session audit view.

## Design
See `knowledge/wiki/design/F-020-auth-session-hardening.md`.

## Related features
- [F-010](features/F-010-saved-checkout.md) - auth session expiry impacts saved checkout resume.

## API surface
Auth session list, revoke, and rotate endpoints are required.

## Board review summary
Complete.

## Post-ship notes
Empty.
'@

Write-Utf8File (Join-Path $wikiRoot "features\F-099-broken.md") @'
---
id: F-099
title: Broken Fixture Page
owner: none
introduced: 2026-04-01
last-updated: 2026-04-08
platforms: [backend]
sources: [knowledge/intake/fixture/broken.md]
advisory-review: not-needed
---

## Summary
This malformed page exists only to validate malformed-page handling.
'@

Write-Utf8File (Join-Path $wikiRoot "design\F-010-saved-checkout.md") @'
---
feature-id: F-010
title: Saved Checkout
designer: Riley Chen
date: 2026-04-07
figma: not applicable
---

## Summary
This design covers the offline checkout resume flow for saved addresses and payment preferences.

## Key design decisions
- The invalid saved address state is shown inline before final confirmation.
- Offline checkout progress persists until the device reconnects.

## States covered
- Loading
- Saved address available
- Invalid saved address
- Expired payment method
- Submission success

## Component references
- Reuse the shared checkout summary card.

## Open design questions
No open design questions.
'@

Write-Utf8File (Join-Path $wikiRoot "design\F-013-recurring-delivery.md") @'
---
feature-id: F-013
title: Recurring Delivery
designer: Riley Chen
date: 2026-04-05
figma: not applicable
---

## Summary
This design covers recurring delivery schedule setup and schedule status review.

## Key design decisions
- Schedule pause and resume actions live on the same management screen.

## States covered
- Empty
- Scheduled
- Paused
- Error

## Component references
- Reuse the schedule summary card.

## Open design questions
No open design questions.
'@

Write-Utf8File (Join-Path $wikiRoot "design\F-014-goal-alerts.md") @'
---
feature-id: F-014
title: Goal Alerts
designer: Riley Chen
date: 2026-04-05
figma: not applicable
---

## Summary
This design covers in-app goal alert history and deep links from push notifications.

## Key design decisions
- Alert detail opens modally from the history list.

## States covered
- Loading
- History list
- Error
- Push deep link handoff

## Component references
- Reuse the timeline component.

## Open design questions
- Empty history state still needs a final decision.
'@

Write-Utf8File (Join-Path $wikiRoot "design\F-020-auth-session-hardening.md") @'
---
feature-id: F-020
title: Auth Session Hardening
designer: Morgan Patel
date: 2026-04-08
figma: not applicable
---

## Summary
This design covers auth session management and auth reauthentication prompts.

## Key design decisions
- Auth session revocation is exposed in both user and admin surfaces.
- Auth risk notifications use the standard security alert shell.

## States covered
- Session list
- Reauthentication required
- Revocation success
- Revocation error

## Component references
- Reuse the account security list pattern.

## Open design questions
No open design questions.
'@

Write-Utf8File (Join-Path $wikiRoot "api-contracts\F-010.md") @'
---
feature-id: F-010
version: 1
status: agreed
---

## Endpoints
- POST /checkout/offline-resume
- POST /checkout/address-validate

## Data models
- SavedCheckoutResumeRequest
- SavedCheckoutResumeResponse

## Authentication requirements
Bearer token required.

## Notes
Supports offline checkout resume and address validation.
'@

Write-Utf8File (Join-Path $wikiRoot "api-contracts\F-013.md") @'
---
feature-id: F-013
version: 1
status: agreed
---

## Endpoints
- POST /recurring-deliveries
- POST /recurring-deliveries/{id}/pause

## Data models
- RecurringDeliverySchedule

## Authentication requirements
Bearer token required.

## Notes
Recurring delivery schedule management endpoints.
'@

Write-Utf8File (Join-Path $wikiRoot "api-contracts\F-014.md") @'
---
feature-id: F-014
version: 1
status: draft
---

## Endpoints
- GET /goal-alerts
- POST /goal-alerts/{id}/acknowledge

## Data models
- GoalAlert

## Authentication requirements
Bearer token required.

## Notes
Still draft because acknowledgement semantics are unresolved.
'@

Write-Utf8File (Join-Path $wikiRoot "api-contracts\F-020.md") @'
---
feature-id: F-020
version: 1
status: agreed
---

## Endpoints
- POST /auth/refresh
- GET /auth/sessions
- POST /auth/sessions/{id}/revoke

## Data models
- AuthSession
- RotatingRefreshToken

## Authentication requirements
Bearer token required except for refresh.

## Notes
Auth session hardening contract for all clients.
'@

Write-Utf8File (Join-Path $wikiRoot "advisory\F-010-review.md") @'
---
feature-id: F-010
reviewed: 2026-04-07
board-members-consulted: [Priya Rao, Martin de Vries]
---

## 1. Conflicts
No conflicts identified.

## 2. Gaps
Spec is complete.

## 3. Build order
Backend validation should land before client rollout.

## 4. Biggest risk
Expired saved payment methods could create silent checkout failures.

## Board perspective summaries
Priya Rao highlighted resilience during reconnect flows.

## Actions required before dev starts
- [ ] Verify offline reconnect edge case coverage - dev

## Actions that can be deferred
- Add analytics for saved checkout resume failures post-ship.
'@

Write-Utf8File (Join-Path $wikiRoot "advisory\F-013-review.md") @'
---
feature-id: F-013
reviewed: 2026-04-05
board-members-consulted: [Eli Navarro]
---

## 1. Conflicts
No conflicts identified.

## 2. Gaps
Spec is complete.

## 3. Build order
Backend schedule creation must land before client pause and resume controls.

## 4. Biggest risk
Customers may assume holiday skip support exists in v1.

## Board perspective summaries
Eli Navarro recommended tight scope control for the first recurring delivery launch.

## Actions required before dev starts
- [ ] Ensure onboarding copy does not imply holiday skips - designer

## Actions that can be deferred
- Add retention experiments after launch.
'@

Write-Utf8File (Join-Path $wikiRoot "advisory\F-014-review.md") @'
---
feature-id: F-014
reviewed: 2026-04-05
board-members-consulted: [Dr. Sana Vermeer, Priya Rao]
---

## 1. Conflicts
No conflicts identified.

## 2. Gaps
Alert history empty-state copy is still unresolved.

## 3. Build order
Backend event generation must land before mobile clients finalize alert history rendering.

## 4. Biggest risk
Over-alerting could reduce trust in the goal program.

## Board perspective summaries
Dr. Sana Vermeer emphasized alert clarity for nutrition-sensitive users.

## Actions required before dev starts
- [ ] Finalize alert history empty-state design - designer

## Actions that can be deferred
- Tune alert cadence after the first cohort launch.
'@

Write-Utf8File (Join-Path $wikiRoot "advisory\F-020-review.md") @'
---
feature-id: F-020
reviewed: 2026-04-08
board-members-consulted: [Martin de Vries, Priya Rao]
---

## 1. Conflicts
No conflicts identified.

## 2. Gaps
Spec is complete.

## 3. Build order
Backend auth rotation must ship before clients rely on session revoke visibility.

## 4. Biggest risk
Incorrect refresh token rotation could log users out unexpectedly.

## Board perspective summaries
Martin de Vries focused on auth auditability and privacy-safe session metadata.

## Actions required before dev starts
- [ ] Confirm auth session retention policy - po

## Actions that can be deferred
- Add advanced admin filtering after baseline auth hardening ships.
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-010-backend.md") @'
---
feature-id: F-010
platform: backend
status: in-progress
---

## What to build
Implement offline checkout resume and saved address validation endpoints.

## Technical constraints
Reuse the existing checkout service boundary.

## Design reference
Not applicable.

## API contract reference
See `knowledge/wiki/api-contracts/F-010.md`.

## Acceptance criteria
- Resume payload validates saved address and payment references.

## Dependencies
No dependencies.
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-010-mobile-android.md") @'
---
feature-id: F-010
platform: mobile-android
status: pending
---

## What to build
Pre-fill checkout from the saved address model during offline checkout.

## Technical constraints
Persist pending checkout state locally until connectivity returns.

## Design reference
See `knowledge/wiki/design/F-010-saved-checkout.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-010.md`.

## Acceptance criteria
- Customers can resume offline checkout with a saved address.

## Dependencies
knowledge/wiki/platform-requirements/F-010-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-010-mobile-ios.md") @'
---
feature-id: F-010
platform: mobile-ios
status: pending
---

## What to build
Pre-fill checkout from the saved address model during offline checkout.

## Technical constraints
Persist pending checkout state locally until connectivity returns.

## Design reference
See `knowledge/wiki/design/F-010-saved-checkout.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-010.md`.

## Acceptance criteria
- Customers can resume offline checkout with a saved address.

## Dependencies
knowledge/wiki/platform-requirements/F-010-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-010-web-user-app.md") @'
---
feature-id: F-010
platform: web-user-app
status: pending
---

## What to build
Expose saved checkout resume in the account dashboard.

## Technical constraints
Reuse the existing order summary shell.

## Design reference
See `knowledge/wiki/design/F-010-saved-checkout.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-010.md`.

## Acceptance criteria
- Customers can resume checkout from the dashboard.

## Dependencies
knowledge/wiki/platform-requirements/F-010-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-013-backend.md") @'
---
feature-id: F-013
platform: backend
status: pending
---

## What to build
Create recurring delivery schedules and pause/resume them.

## Technical constraints
Schedule state must be idempotent across retries.

## Design reference
Not applicable.

## API contract reference
See `knowledge/wiki/api-contracts/F-013.md`.

## Acceptance criteria
- Schedule create and pause endpoints behave consistently.

## Dependencies
No dependencies.
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-013-mobile-android.md") @'
---
feature-id: F-013
platform: mobile-android
status: pending
---

## What to build
Schedule recurring delivery and show schedule status.

## Technical constraints
Reuse the delivery settings navigation shell.

## Design reference
See `knowledge/wiki/design/F-013-recurring-delivery.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-013.md`.

## Acceptance criteria
- Customers can schedule and pause recurring deliveries.

## Dependencies
knowledge/wiki/platform-requirements/F-013-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-013-web-user-app.md") @'
---
feature-id: F-013
platform: web-user-app
status: pending
---

## What to build
Schedule recurring delivery and show schedule status.

## Technical constraints
Reuse the account dashboard scheduling shell.

## Design reference
See `knowledge/wiki/design/F-013-recurring-delivery.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-013.md`.

## Acceptance criteria
- Customers can schedule and pause recurring deliveries.

## Dependencies
knowledge/wiki/platform-requirements/F-013-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-014-backend.md") @'
---
feature-id: F-014
platform: backend
status: in-progress
---

## What to build
Generate goal alert events and expose goal alert history.

## Technical constraints
Alert acknowledgement behavior is blocked on the draft API contract.

## Design reference
Not applicable.

## API contract reference
See `knowledge/wiki/api-contracts/F-014.md`.

## Acceptance criteria
- Goal alerts are generated from nutrition events.

## Dependencies
No dependencies.
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-014-mobile-android.md") @'
---
feature-id: F-014
platform: mobile-android
status: pending
---

## What to build
Render goal alert history and deep link from push notifications.

## Technical constraints
Alert acknowledgement waits on the draft backend contract.

## Design reference
See `knowledge/wiki/design/F-014-goal-alerts.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-014.md`.

## Acceptance criteria
- Customers can read alert history and open alert details.

## Dependencies
knowledge/wiki/platform-requirements/F-014-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-014-mobile-ios.md") @'
---
feature-id: F-014
platform: mobile-ios
status: pending
---

## What to build
Render goal alert history and deep link from push notifications.

## Technical constraints
Alert acknowledgement waits on the draft backend contract.

## Design reference
See `knowledge/wiki/design/F-014-goal-alerts.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-014.md`.

## Acceptance criteria
- Customers can read alert history and open alert details.

## Dependencies
knowledge/wiki/platform-requirements/F-014-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-020-backend.md") @'
---
feature-id: F-020
platform: backend
status: in-progress
---

## What to build
Implement rotating auth refresh tokens and auth session revoke endpoints.

## Technical constraints
Session metadata must remain privacy-safe.

## Design reference
Not applicable.

## API contract reference
See `knowledge/wiki/api-contracts/F-020.md`.

## Acceptance criteria
- Refresh tokens rotate after every refresh.

## Dependencies
No dependencies.
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-020-mobile-android.md") @'
---
feature-id: F-020
platform: mobile-android
status: pending
---

## What to build
Handle auth session reauthentication and revoked-session recovery.

## Technical constraints
Reuse the shared auth prompt shell.

## Design reference
See `knowledge/wiki/design/F-020-auth-session-hardening.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-020.md`.

## Acceptance criteria
- Customers are prompted to reauthenticate after auth session revoke events.

## Dependencies
knowledge/wiki/platform-requirements/F-020-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-020-mobile-ios.md") @'
---
feature-id: F-020
platform: mobile-ios
status: pending
---

## What to build
Handle auth session reauthentication and revoked-session recovery.

## Technical constraints
Reuse the shared auth prompt shell.

## Design reference
See `knowledge/wiki/design/F-020-auth-session-hardening.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-020.md`.

## Acceptance criteria
- Customers are prompted to reauthenticate after auth session revoke events.

## Dependencies
knowledge/wiki/platform-requirements/F-020-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-020-web-user-app.md") @'
---
feature-id: F-020
platform: web-user-app
status: pending
---

## What to build
Show auth session list and allow self-service session revoke.

## Technical constraints
Reuse the account security layout.

## Design reference
See `knowledge/wiki/design/F-020-auth-session-hardening.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-020.md`.

## Acceptance criteria
- Customers can revoke an auth session from the web app.

## Dependencies
knowledge/wiki/platform-requirements/F-020-backend.md
'@

Write-Utf8File (Join-Path $wikiRoot "platform-requirements\F-020-web-admin-portal.md") @'
---
feature-id: F-020
platform: web-admin-portal
status: pending
---

## What to build
Show auth session audit history and revoke actions for support staff.

## Technical constraints
Reuse the admin security audit table shell.

## Design reference
See `knowledge/wiki/design/F-020-auth-session-hardening.md`.

## API contract reference
See `knowledge/wiki/api-contracts/F-020.md`.

## Acceptance criteria
- Admins can inspect and revoke auth sessions.

## Dependencies
knowledge/wiki/platform-requirements/F-020-backend.md
'@

$timestampMap = @{
    (Join-Path $wikiRoot "features\F-010-saved-checkout.md") = [datetime]"2026-04-08"
    (Join-Path $wikiRoot "features\F-011-nutrition-score.md") = [datetime]"2026-03-20"
    (Join-Path $wikiRoot "features\F-012-notification-preferences.md") = [datetime]"2026-04-07"
    (Join-Path $wikiRoot "features\F-013-recurring-delivery.md") = [datetime]"2026-04-06"
    (Join-Path $wikiRoot "features\F-014-goal-alerts.md") = [datetime]"2026-04-05"
    (Join-Path $wikiRoot "features\F-020-auth-session-hardening.md") = [datetime]"2026-04-08"
    (Join-Path $wikiRoot "features\F-099-broken.md") = [datetime]"2026-04-08"
    (Join-Path $wikiRoot "design\F-010-saved-checkout.md") = [datetime]"2026-04-07"
    (Join-Path $wikiRoot "design\F-013-recurring-delivery.md") = [datetime]"2026-04-05"
    (Join-Path $wikiRoot "design\F-014-goal-alerts.md") = [datetime]"2026-04-05"
    (Join-Path $wikiRoot "design\F-020-auth-session-hardening.md") = [datetime]"2026-04-08"
    (Join-Path $wikiRoot "business-rules\BR-004-checkout-address-validation.md") = [datetime]"2026-04-01"
    (Join-Path $wikiRoot "business-rules\BR-020-auth-token-rotation.md") = [datetime]"2026-04-02"
    (Join-Path $wikiRoot "decisions\ADR-020-auth-provider.md") = [datetime]"2026-04-03"
}

foreach ($entry in $timestampMap.GetEnumerator()) {
    Set-Stamp -Path $entry.Key -Timestamp $entry.Value
}

Write-Host "Runtime validation fixture created at $TargetDir" -ForegroundColor Green

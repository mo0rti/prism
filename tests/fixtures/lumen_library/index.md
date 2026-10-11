# Wiki index

One line per wiki page, grouped by kind. This file is maintained by the AI agent and the
board service. Do not edit it directly.

## Direction and roadmap
- [Direction](direction.md): No direction is recorded yet.
- [Roadmap](roadmap.md): No roadmap is recorded yet.

## Features
- [F-001 Reserve a book](features/F-001-reserve-a-book.md): A reader reserves an available copy of a book in the reader app, and the catalog records the reservation.

## Design
- [Reserve a book](design/F-001-reserve-a-book.md): The book page offers a reserve button for an available copy and shows the pickup date after it.

## Technical design
- [Reserve a book technical design](technical-design/F-001-reserve-a-book.md): The catalog stores a reservation for an available copy and the reader app calls the new endpoint.

## App requirements
- [F-001 catalog-api](app-requirements/F-001-catalog-api.md): Requirements of F-001 for the catalog-api app.
- [F-001 reader-app](app-requirements/F-001-reader-app.md): Requirements of F-001 for the reader-app app.

## API contracts
- [F-001 API contract](api-contracts/F-001.md): API contract of F-001.

## Bugs
- [BUG-001 Reserve button does nothing](bugs/BUG-001-reserve-button-does-nothing.md): Reserve button does nothing.
- [BUG-002 Reservation response lacks the pickup date](bugs/BUG-002-reservation-response-lacks-the-pickup-date.md): Reservation response lacks the pickup date.
- [BUG-003 Reservation cache ignores copy status](bugs/BUG-003-reservation-cache-ignores-copy-status.md): Reservation cache ignores copy status.

## Releases
- [REL-001 Release of F-001 and BUG-001](releases/REL-001.md): F-001 is delivered to production; the Play Store upload of the reader app fails.
- [REL-002 Retry of REL-001](releases/REL-002.md): The reader app is delivered to the Play Store on the second attempt.
- [REL-003 Fix of BUG-002](releases/REL-003.md): BUG-002 is delivered to production.
- [REL-004 Rollback of REL-003](releases/REL-004.md): REL-003 is rolled back after the reservation errors.
- [REL-005 Redeploy of REL-004](releases/REL-005.md): The redeploy of build 413 fails.
- [REL-006 Redeploy of REL-005](releases/REL-006.md): Build 413 is redeployed to production.

## Incidents
- [INC-001 Reservations fail after the catalog fix](incidents/INC-001-reservations-fail-after-the-catalog-fix.md): Readers could not reserve books for 25 minutes.

## Advisory
- [Advisory board](advisory/BOARD.md): Advisory board composition.
- [Project foundation](advisory/PROJECT_FOUNDATION.md): Setup interview answers, risk framing and the initial board rationale.

## Meta
- [ACTIONS.md](ACTIONS.md): Lifecycle action registry, write scopes and action contracts.
- [CONNECTED.md](CONNECTED.md): How agents use the connected board and MCP service.
- [LIFECYCLE.md](LIFECYCLE.md): Feature, board and advisory protocol.
- [SCHEMA.md](SCHEMA.md): Wiki conventions and operational rules.
- [SETTINGS.md](SETTINGS.md): Project-level settings for wiki read and query behavior.
- [Status board](status-board.md): The status, owner and board review of every feature.

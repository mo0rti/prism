# Feature: [Name]

## Board Review

- **Product (Sarah)**: [approval/concerns]
- **Architecture (Marcus)**: [approval/concerns]
- **Security (Aisha)**: [approval/concerns]
- **Business (David)**: [approval/concerns]
- **Decision**: [Go / Rework / Defer]

## Business Logic

- What this feature does
- Who uses it (which user roles)
- Key rules and constraints
- Edge cases

## Entities

- [EntityName](../../backend/docs/entities/entity-name.md) - role in this feature

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /resource | List items |
| POST | /resource | Create item |
| GET | /resource/{id} | Get single item |
| PUT | /resource/{id} | Update item |
| DELETE | /resource/{id} | Delete item |

## Platform Implementation

### Backend
- Controller: `backend/src/.../features/name/controller/`
- Service: `backend/src/.../features/name/service/`
- Repository: `backend/src/.../features/name/repository/`

### User Web App
- Pages: `web-user-app/app/[locale]/dashboard/name/`
- API: `web-user-app/lib/api/name.ts`

### Admin Web Portal
- Pages: `web-admin-portal/app/admin/(dashboard)/name/`

### Android
- Screen: `mobile-android/.../ui/name/`
- ViewModel: `mobile-android/.../ui/name/NameViewModel.kt`

### iOS
- View: `mobile-ios/.../UI/Name/`
- ViewModel: `mobile-ios/.../UI/Name/NameViewModel.swift`

## Implementation Status

- [ ] Feature doc created
- [ ] Entity docs created
- [ ] Board review completed
- [ ] API contract defined in OpenAPI
- [ ] API clients generated
- [ ] Backend implemented
- [ ] Backend tests passing
- [ ] User web app implemented
- [ ] Admin portal implemented
- [ ] Android implemented
- [ ] iOS implemented

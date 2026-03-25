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

- [EntityName](../entities/entity-name.md) - role in this feature

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

### Web
- Pages: `web/src/app/(main)/name/`
- API: `web/src/lib/api/name.ts`

### Admin
- Pages: `admin/src/app/(dashboard)/name/`

### Android
- Screen: `android/.../ui/name/`
- ViewModel: `android/.../ui/name/NameViewModel.kt`

### iOS
- View: `ios/.../UI/Name/`
- ViewModel: `ios/.../UI/Name/NameViewModel.swift`

## Implementation Status

- [ ] Feature doc created
- [ ] Entity docs created
- [ ] Board review completed
- [ ] API contract defined in OpenAPI
- [ ] API clients generated
- [ ] Backend implemented
- [ ] Backend tests passing
- [ ] Web implemented
- [ ] Admin implemented
- [ ] Android implemented
- [ ] iOS implemented

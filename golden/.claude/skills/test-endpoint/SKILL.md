---
name: test-endpoint
description: Generate curl commands or Postman requests for testing API endpoints
argument-hint: "[endpoint path or description]"
disable-model-invocation: true
---

Create test requests for $ARGUMENTS.

For the requested endpoint, generate:

1. **cURL Command**:
   - Complete command with all required headers
   - JWT token placeholder: `Authorization: Bearer <YOUR_JWT_TOKEN>`; against a backend run with the `local` profile, get a development token first with `POST /api/dev-identity/token` (see `shared/api-contracts/openapi.yml`)
   - Request body (if POST/PUT/PATCH)
   - Proper formatting for readability

2. **Postman Request Details**:
   - Method and URL
   - Headers required
   - Body structure with example data
   - Expected response format

3. **Test Scenarios**:
   - Happy path (valid request, expected response)
   - Authentication errors (missing/invalid token)
   - Validation errors (invalid body, missing required fields)
   - Not found (invalid ID)
   - Edge cases specific to the endpoint

4. **Response Examples**:
   - Success response with status code
   - Error response format (`ApiErrorResponse` with code, message, details)

Include both authenticated and unauthenticated examples if the endpoint is public.

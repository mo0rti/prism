---
name: code-review
description: Perform a multi-perspective code review on staged or recent changes. Triggers when the user asks for a code review.
---

# Multi-Perspective Code Review

Review code changes from multiple engineering perspectives.

## How to Execute

1. Identify the code to review:
   - If the user specifies files, review those
   - Otherwise, check `git diff --staged` or `git diff HEAD~1` for recent changes

2. Review from each perspective:

### Correctness
- Does the code do what it's supposed to?
- Are edge cases handled?
- Are there off-by-one errors, null pointer risks, or race conditions?

### Architecture
- Does it follow the project's MVVM pattern?
- Is the separation of concerns correct (View -> ViewModel -> Repository -> API)?
- Does it use dependency injection properly?
- Are new files in the correct directories per the platform structure?

### Security
- SQL injection, XSS, or other injection risks?
- Are auth tokens handled securely?
- Is user input validated at system boundaries?
- Are secrets kept out of code?

### Performance
- N+1 query risks?
- Unnecessary re-renders (Compose/SwiftUI)?
- Missing pagination for list endpoints?
- Appropriate use of caching (Room/SwiftData)?

### Maintainability
- Is the code self-explanatory?
- Are names descriptive?
- Is there unnecessary complexity?
- Does it follow existing patterns in the codebase?

3. Present findings grouped by severity:
   - **Must fix**: Bugs, security issues, broken patterns
   - **Should fix**: Performance issues, missing edge cases
   - **Consider**: Style improvements, minor suggestions

4. If changes span multiple platforms, review each platform's code against its conventions (see platform-specific CLAUDE.md files).

Create a Flyway migration for Prism Golden.

Ask me for the schema change if I have not provided it clearly.

## Steps

1. **Analyze impact** - identify affected entities, relationships, indexes, and constraints.
   - Decide whether the change is additive or whether it alters/removes existing
     columns, constraints, or semantics.
   - For non-trivial destructive change, follow the expand-contract guidance in
     `@.claude/skills/migration-conventions/SKILL.md`.
2. **Determine the next version number** - check the existing files in `src/main/resources/db/migration/` of the backend app (`backend/`) for the current highest version; a new app starts with `V1__users.sql`.
3. **Create the migration SQL** - follow the conventions in `@.claude/skills/migration-conventions/SKILL.md`.
4. **Update Kotlin code if needed** - when the schema change affects entities or relationships, follow `@.claude/skills/jpa-kotlin-patterns/SKILL.md`.
5. **Check related docs** - update entity docs or backend docs if the schema meaning changed.
6. **Consider rollback** - document how to reverse the change if needed.

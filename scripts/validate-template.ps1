param(
    [string]$OutputRoot = (Join-Path ([System.IO.Path]::GetTempPath()) ("template-validation-" + [System.Guid]::NewGuid().ToString("N"))),
    [ValidateSet("full", "contract", "backend-smoke")]
    [string]$Mode = "full",
    [string]$ActionlintPath = "actionlint"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$CurrentClaudeCommands = @(
    "add-endpoint",
    "ask",
    "audit-feature",
    "board-review",
    "design-clarify",
    "design-handoff",
    "design-intake",
    "design-start",
    "dev-clarify",
    "dev-done",
    "dev-start",
    "document-entity",
    "feature-status",
    "feature-reopen",
    "generate-clients",
    "ingest",
    "lint-wiki",
    "po-clarify",
    "po-handoff",
    "po-intake",
    "po-specify",
    "prep-sprint",
    "setup-project",
    "verify-pages",
    "wiki-blockers",
    "wiki-owner",
    "wiki-app",
    "wiki-query",
    "wiki-show"
)

$CurrentWorkflowSkills = @(
    "ask",
    "audit-feature",
    "board-review",
    "design-clarify",
    "design-handoff",
    "design-intake",
    "design-start",
    "dev-clarify",
    "dev-done",
    "dev-start",
    "document-entity",
    "feature-status",
    "feature-reopen",
    "generate-clients",
    "ingest",
    "lint-wiki",
    "po-clarify",
    "po-handoff",
    "po-intake",
    "po-specify",
    "prep-sprint",
    "setup-project",
    "verify-pages",
    "wiki-blockers",
    "wiki-owner",
    "wiki-app",
    "wiki-query",
    "wiki-show"
)

$ExplicitOnlyWorkflowSkills = @(
    "ask",
    "audit-feature",
    "board-review",
    "design-clarify",
    "design-handoff",
    "design-intake",
    "design-start",
    "dev-clarify",
    "dev-done",
    "dev-start",
    "document-entity",
    "feature-reopen",
    "ingest",
    "po-clarify",
    "po-handoff",
    "po-intake",
    "po-specify",
    "setup-project",
    "verify-pages"
)

$PermissiveWorkflowSkills = @(
    "feature-status",
    "generate-clients",
    "lint-wiki",
    "prep-sprint",
    "wiki-blockers",
    "wiki-owner",
    "wiki-app",
    "wiki-query",
    "wiki-show"
)

function Assert-PathExists {
    param(
        [string]$Path,
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Assert-PathMissing {
    param(
        [string]$Path,
        [string]$Message
    )

    if (Test-Path -LiteralPath $Path) {
        throw $Message
    }
}

function Assert-FileContains {
    param(
        [string]$Path,
        [string]$Needle,
        [string]$Message
    )

    $content = Get-Content -Raw -LiteralPath $Path
    if (-not $content.Contains($Needle)) {
        throw $Message
    }
}

function Assert-FileNotContains {
    param(
        [string]$Path,
        [string]$Needle,
        [string]$Message
    )

    $content = Get-Content -Raw -LiteralPath $Path
    if ($content.Contains($Needle)) {
        throw $Message
    }
}

function Assert-FileUsesLfLineEndings {
    param(
        [string]$Path,
        [string]$Message
    )

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    for ($index = 0; $index -lt ($bytes.Length - 1); $index++) {
        if ($bytes[$index] -eq 13 -and $bytes[$index + 1] -eq 10) {
            throw $Message
        }
    }
}

function Get-TemplateTextFiles {
    param([string]$Root)

    $extensions = @(
        ".bat", ".cmd", ".css", ".env", ".example", ".java", ".jinja", ".js", ".json",
        ".jsonc", ".kt", ".kts", ".md", ".mjs", ".plist", ".properties",
        ".ps1", ".rb", ".sh", ".sql", ".swift", ".ts", ".tsx", ".txt",
        ".xml", ".yml", ".yaml"
    )

    Get-ChildItem -LiteralPath $Root -Recurse | Where-Object {
        -not $_.PSIsContainer -and
        $extensions -contains $_.Extension
    }
}

function Assert-TreeNotContains {
    param(
        [string]$Root,
        [string]$Needle,
        [string]$Message
    )

    foreach ($file in Get-TemplateTextFiles -Root $Root) {
        $content = Get-Content -Raw -LiteralPath $file.FullName
        if ($content.Contains($Needle)) {
            throw "$Message Found in $($file.FullName)."
        }
    }
}

function Assert-NoCopierPlaceholders {
    param([string]$Root)

    $patterns = @(
        "{%",
        "{{ project_",
        "{{ package_",
        "{{package_",
        "{{ ios_module_name",
        "{{ description",
        "{{ auth_methods",
        "{{ platforms",
        "{{ cloud_provider",
        "{{ web_hosting"
    )

    foreach ($pattern in $patterns) {
        Assert-TreeNotContains -Root $Root -Needle $pattern -Message "Generated output still contains unresolved Copier placeholders."
    }
}

function New-GeneratedProject {
    param(
        [string]$Name,
        [string[]]$DataArgs
    )

    $target = Join-Path $OutputRoot $Name
    Remove-TreeIfExists -Path $target

    $arguments = @("copy", "--trust", "--defaults", "--vcs-ref", "HEAD")
    foreach ($dataArg in $DataArgs) {
        $arguments += "--data"
        $arguments += $dataArg
    }
    $arguments += "."
    $arguments += $target

    # Copier writes notices to stderr. Windows PowerShell 5.1 turns native stderr
    # output into a terminating error under $ErrorActionPreference = "Stop", so the
    # call runs with "Continue" and only a non-zero exit code fails the generation.
    $copierExitCode = 0
    Push-Location $repoRoot
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        Write-Host "Generating sample: $Name"
        $ErrorActionPreference = "Continue"
        & python -m copier @arguments 2>&1 | ForEach-Object { Write-Host "$_" }
        $copierExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
        Pop-Location
    }
    if ($copierExitCode -ne 0) {
        throw "Copier generation failed for $Name."
    }

    if ($Mode -eq "contract") {
        $workflows = @(Get-ChildItem -LiteralPath (Join-Path $target ".github/workflows") -Filter "*.yml" -File | ForEach-Object { $_.FullName })
        & $ActionlintPath '-shellcheck=' '-pyflakes=' @workflows
        if ($LASTEXITCODE -ne 0) {
            throw "Generated workflow validation failed for $Name."
        }
    }
    Assert-PathExists -Path (Join-Path $target ".copier-answers.yml") -Message "Raw Copier generation must save its answers for future updates."
    return $target
}

function Validate-WikiStructure {
    param([string]$Root)

    # Knowledge wiki directories
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Message "Generated project missing knowledge/wiki/SCHEMA.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Message "Generated project missing knowledge/wiki/LIFECYCLE.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\index.md") -Message "Generated project missing knowledge/wiki/index.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\status-board.md") -Message "Generated project missing knowledge/wiki/status-board.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\direction.md") -Message "Generated project missing knowledge/wiki/direction.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\roadmap.md") -Message "Generated project missing knowledge/wiki/roadmap.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\log.md") -Message "Generated project missing knowledge/wiki/log.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\advisory\BOARD.md") -Message "Generated project missing knowledge/wiki/advisory/BOARD.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\advisory\PROJECT_FOUNDATION.md") -Message "Generated project missing knowledge/wiki/advisory/PROJECT_FOUNDATION.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\features\_FORMAT.md") -Message "Generated project missing knowledge/wiki/features/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\personas\_FORMAT.md") -Message "Generated project missing knowledge/wiki/personas/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\business-rules\_FORMAT.md") -Message "Generated project missing knowledge/wiki/business-rules/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\design\_FORMAT.md") -Message "Generated project missing knowledge/wiki/design/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\app-requirements\_FORMAT.md") -Message "Generated project missing knowledge/wiki/app-requirements/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\api-contracts\_FORMAT.md") -Message "Generated project missing knowledge/wiki/api-contracts/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\decisions\_FORMAT.md") -Message "Generated project missing knowledge/wiki/decisions/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\advisory\_FORMAT.md") -Message "Generated project missing knowledge/wiki/advisory/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\topics\_FORMAT.md") -Message "Generated project missing knowledge/wiki/topics/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\research\_FORMAT.md") -Message "Generated project missing knowledge/wiki/research/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\plans\_FORMAT.md") -Message "Generated project missing knowledge/wiki/plans/_FORMAT.md."

    # Intake structure
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\README.md") -Message "Generated project missing knowledge/intake/README.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\pending\PO_BRIEF_TEMPLATE.md") -Message "Generated project missing intake/pending/PO_BRIEF_TEMPLATE.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\pending\DESIGN_HANDOFF_TEMPLATE.md") -Message "Generated project missing intake/pending/DESIGN_HANDOFF_TEMPLATE.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\processed\.gitkeep") -Message "Generated project missing intake/processed/.gitkeep."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\quarantined\.gitkeep") -Message "Generated project missing intake/quarantined/.gitkeep."

    # AGENTS.md is the single source of agent rules; CLAUDE.md only imports it; AGENTS.md no longer exists
    Assert-PathExists -Path (Join-Path $Root "AGENTS.md") -Message "Generated project missing rendered AGENTS.md."
    Assert-PathExists -Path (Join-Path $Root "CLAUDE.md") -Message "Generated project missing rendered CLAUDE.md."
    Assert-PathMissing -Path (Join-Path $Root "CONTEXT.md") -Message "Generated project must not contain CONTEXT.md."
    Assert-FileContains -Path (Join-Path $Root "CLAUDE.md") -Needle "@AGENTS.md" -Message "Root CLAUDE.md must import AGENTS.md."

    # Current Claude command surface present (rendered, no .jinja suffix)
    foreach ($cmd in $CurrentClaudeCommands) {
        Assert-PathExists -Path (Join-Path $Root ".claude\commands\$cmd.md") -Message "Generated project missing .claude/commands/$cmd.md."
    }

    # Superseded commands must not exist
    Assert-PathMissing -Path (Join-Path $Root ".claude\commands\scaffold-feature.md") -Message "scaffold-feature command should not exist in generated project."
    Assert-PathMissing -Path (Join-Path $Root ".claude\commands\document-feature.md") -Message "document-feature command should not exist in generated project."

    # Current Codex workflow skills present
    foreach ($skill in $CurrentWorkflowSkills) {
        Assert-PathExists -Path (Join-Path $Root ".agents\skills\$skill\SKILL.md") -Message "Generated project missing .agents/skills/$skill/SKILL.md."
        Assert-PathExists -Path (Join-Path $Root ".agents\skills\$skill\agents\openai.yaml") -Message "Generated project missing .agents/skills/$skill/agents/openai.yaml."
    }

    foreach ($skill in $ExplicitOnlyWorkflowSkills) {
        Assert-FileContains -Path (Join-Path $Root ".agents\skills\$skill\agents\openai.yaml") -Needle "allow_implicit_invocation: false" -Message "Generated skill $skill must require explicit invocation."
    }

    foreach ($skill in $PermissiveWorkflowSkills) {
        Assert-FileContains -Path (Join-Path $Root ".agents\skills\$skill\agents\openai.yaml") -Needle "allow_implicit_invocation: true" -Message "Generated skill $skill must declare permissive invocation explicitly."
    }

    # Superseded skill must not exist
    Assert-PathMissing -Path (Join-Path $Root ".agents\skills\scaffold-feature") -Message "scaffold-feature skill should not exist in generated project."

    # business-rules/ keeps a .gitkeep alongside its required _FORMAT.md
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\business-rules\.gitkeep") -Message "Generated project missing knowledge/wiki/business-rules/.gitkeep."

    # Cursor project rule points to AGENTS.md; the wiki rule is gone
    Assert-PathExists -Path (Join-Path $Root ".cursor\rules\project.mdc") -Message "Generated project missing .cursor/rules/project.mdc."
    Assert-PathMissing -Path (Join-Path $Root ".cursor\rules\wiki.mdc") -Message "Generated project must not contain .cursor/rules/wiki.mdc."

    # docs/README.md present
    Assert-PathExists -Path (Join-Path $Root "docs\README.md") -Message "Generated project missing docs/README.md."

    # Current wiki usability artifacts
    Assert-PathExists -Path (Join-Path $Root "prism.workspace.yml") -Message "Generated project missing prism.workspace.yml."
    Assert-FileContains -Path (Join-Path $Root "prism.workspace.yml") -Needle "schema_version: 2" -Message "prism.workspace.yml must declare schema_version: 2."
    Assert-FileContains -Path (Join-Path $Root "prism.workspace.yml") -Needle "apps:" -Message "prism.workspace.yml must declare the workspace apps."
    Assert-FileContains -Path (Join-Path $Root "prism.workspace.yml") -Needle "min_prism_cli_version:" -Message "prism.workspace.yml must declare min_prism_cli_version."
    Assert-FileContains -Path (Join-Path $Root "prism.workspace.yml") -Needle "wiki_root: knowledge/wiki" -Message "prism.workspace.yml must point to knowledge/wiki."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\SETTINGS.md") -Message "Generated project missing knowledge/wiki/SETTINGS.md."
    Assert-FileContains -Path (Join-Path $Root ".gitignore") -Needle "knowledge/wiki/WIKI_REPORT.md" -Message "Generated project .gitignore must ignore knowledge/wiki/WIKI_REPORT.md."
    Assert-PathMissing -Path (Join-Path $Root "knowledge\wiki\WIKI_REPORT.md") -Message "Generated project should not include a committed knowledge/wiki/WIKI_REPORT.md on first render."

    # Generated README must onboard users into the required wiki setup step
    Assert-FileContains -Path (Join-Path $Root "README.md") -Needle "First-Time Setup" -Message "Generated README.md must include first-time wiki setup guidance."
    Assert-FileContains -Path (Join-Path $Root "README.md") -Needle "setup-project" -Message "Generated README.md must reference setup-project."
    Assert-FileContains -Path (Join-Path $Root "README.md") -Needle "knowledge/wiki" -Message "Generated README.md must reference the product wiki."
    Assert-FileContains -Path (Join-Path $Root "README.md") -Needle "Working With AI Agents" -Message "Generated README.md must carry the AI agent overview."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "## Project docs" -Message "The generated wiki index must list the docs pages under Project docs."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "(../../docs/architecture.md)" -Message "The generated wiki index must link docs/architecture.md."

    # Root context files must not reference old paths
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "docs/features/" -Message "Root AGENTS.md should not reference docs/features/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle '$scaffold-feature' -Message "Root AGENTS.md should not reference scaffold-feature."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "docs/advisory-board.md" -Message "Root AGENTS.md should not reference docs/advisory-board.md."

    # advisory-review skill must have been renamed to board-review (not present under old name)
    Assert-PathMissing -Path (Join-Path $Root ".agents\skills\advisory-review") -Message "advisory-review skill directory should not exist (it was renamed to board-review)."

    # LIFECYCLE.md must contain the advisory-review field and the four-question format; SCHEMA.md the confirm-before-committing rule
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Needle "advisory-review" -Message "LIFECYCLE.md must define the advisory-review field."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Needle "## 1. Conflicts" -Message "LIFECYCLE.md must include the four-question pre-dev review format (section 1)."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Needle "## 4. Biggest risk" -Message "LIFECYCLE.md must include the four-question pre-dev review format (section 4)."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "Confirm before committing" -Message "SCHEMA.md must include the confirm-before-committing operational rule."

    # Advisory placeholders must contain setup-project instruction
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\advisory\BOARD.md") -Needle "setup-project" -Message "advisory/BOARD.md placeholder must reference setup-project."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\advisory\PROJECT_FOUNDATION.md") -Needle "setup-project" -Message "advisory/PROJECT_FOUNDATION.md placeholder must reference setup-project."

    # status-board.md must have the Board Review column and no date column; index.md lists every page, one line each
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\status-board.md") -Needle "Board Review" -Message "wiki/status-board.md must include a Board Review column."
    Assert-FileNotContains -Path (Join-Path $Root "knowledge\wiki\status-board.md") -Needle "Introduced" -Message "wiki/status-board.md must not carry a date column."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "(status-board.md)" -Message "wiki/index.md must list status-board.md."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "(direction.md)" -Message "wiki/index.md must list direction.md."
    Assert-FileNotContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "Board Review" -Message "wiki/index.md must not carry the status board."

    # SCHEMA.md and LIFECYCLE.md carry a schema version; SCHEMA.md defines the log format, and pages carry no history dates
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "schema-version: 1" -Message "SCHEMA.md must declare schema-version: 1."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Needle "schema-version: 1" -Message "LIFECYCLE.md must declare schema-version: 1."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## YYYY-MM-DD <operation> | <subject>" -Message "SCHEMA.md must define the log entry format."
    Assert-FileNotContains -Path (Join-Path $Root "knowledge\wiki\features\_FORMAT.md") -Needle "last-updated" -Message "The feature format must not carry a history date."
    Assert-FileNotContains -Path (Join-Path $Root "knowledge\wiki\LIFECYCLE.md") -Needle "last-updated: YYYY-MM-DD" -Message "The feature page format must not carry a history date."

    # SCHEMA.md defines the evidence labels, records and decision supersession, raw sources and the conflict format
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## Evidence labels" -Message "SCHEMA.md must define the evidence labels."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## Records and decision supersession" -Message "SCHEMA.md must define records and decision supersession."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## Conflict quarantine" -Message "SCHEMA.md must define the conflict quarantine format."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## Topic page format" -Message "SCHEMA.md must define the topic page format."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## Ingest: any role, any page kind" -Message "SCHEMA.md must define generic ingest."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## index.md conventions" -Message "SCHEMA.md must define the index conventions."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "Write the current state." -Message "SCHEMA.md must state the current-state operational rule."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\decisions\_FORMAT.md") -Needle "superseded-by: ADR-MMM" -Message "The ADR format must define superseded-by."
    Assert-FileNotContains -Path (Join-Path $Root "knowledge\wiki\decisions\_FORMAT.md") -Needle "superseded-by ADR-XXX" -Message "The ADR format must not carry the inline superseded-by status."
    Assert-FileContains -Path (Join-Path $Root "knowledge\intake\README.md") -Needle "YYYY-MM-DD-slug" -Message "intake/README.md must name the dated intake folder form."
    Assert-FileContains -Path (Join-Path $Root "knowledge\intake\pending\PO_BRIEF_TEMPLATE.md") -Needle "Captured: YYYY-MM-DD" -Message "The PO brief template must carry a Captured line."
    Assert-FileContains -Path (Join-Path $Root "knowledge\intake\pending\DESIGN_HANDOFF_TEMPLATE.md") -Needle "Captured: YYYY-MM-DD" -Message "The design handoff template must carry a Captured line."

    # AGENTS.md must render with setup instructions for all three tools and no unrendered Jinja2
    Assert-FileContains -Path (Join-Path $Root "AGENTS.md") -Needle "setup-project" -Message "Rendered AGENTS.md must reference setup-project."
    Assert-FileContains -Path (Join-Path $Root "AGENTS.md") -Needle "Claude Code" -Message "Rendered AGENTS.md must include Claude Code setup instruction."
    Assert-FileContains -Path (Join-Path $Root "AGENTS.md") -Needle "Codex" -Message "Rendered AGENTS.md must include Codex setup instruction."

    # Cursor project rule must reference knowledge/wiki, not old docs paths
    Assert-FileContains -Path (Join-Path $Root ".cursor\rules\project.mdc") -Needle "knowledge/wiki" -Message "Cursor project rule must reference knowledge/wiki."
    Assert-FileContains -Path (Join-Path $Root ".cursor\rules\project.mdc") -Needle "@AGENTS.md" -Message "Cursor project rule must reference @AGENTS.md."
    Assert-FileNotContains -Path (Join-Path $Root ".cursor\rules\project.mdc") -Needle "docs/advisory-board.md" -Message "Cursor project rule must not reference docs/advisory-board.md."
    Assert-FileNotContains -Path (Join-Path $Root ".cursor\rules\project.mdc") -Needle "Feature docs in" -Message "Cursor project rule must not use old feature-docs-in phrasing."

    # Cursor advisory-review rule must point to knowledge/wiki, not docs/advisory-board.md
    Assert-FileContains -Path (Join-Path $Root ".cursor\rules\advisory-review.mdc") -Needle "knowledge/wiki/advisory/BOARD.md" -Message "Cursor advisory-review rule must reference knowledge/wiki/advisory/BOARD.md."
    Assert-FileNotContains -Path (Join-Path $Root ".cursor\rules\advisory-review.mdc") -Needle "docs/advisory-board.md" -Message "Cursor advisory-review rule must not reference docs/advisory-board.md."

    # Claude board-review skill (directory renamed from advisory-review) must point at wiki
    Assert-PathMissing -Path (Join-Path $Root ".claude\skills\advisory-review") -Message ".claude/skills/advisory-review directory must not exist (renamed to board-review)."
    Assert-FileContains -Path (Join-Path $Root ".claude\skills\board-review\SKILL.md") -Needle "knowledge/wiki/advisory/BOARD.md" -Message ".claude/skills/board-review/SKILL.md must reference knowledge/wiki/advisory/BOARD.md."
    Assert-FileNotContains -Path (Join-Path $Root ".claude\skills\board-review\SKILL.md") -Needle "docs/advisory-board.md" -Message ".claude/skills/board-review/SKILL.md must not reference docs/advisory-board.md."

    # Tree-wide: no generated file should reference the retired commands or paths
    Assert-TreeNotContains -Root $Root -Needle '$scaffold-feature' -Message "Generated output must not reference the retired scaffold-feature skill."
    Assert-TreeNotContains -Root $Root -Needle '$advisory-review' -Message "Generated output must not reference the retired advisory-review skill."
    Assert-TreeNotContains -Root $Root -Needle '/advisory-review' -Message "Generated output must not reference the retired /advisory-review command."
}

function Validate-BackendOnly {
    param(
        [string]$Root,
        [bool]$RunSmoke = $true
    )

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root

    # backend AGENTS.md must have the wiki section and CLAUDE.md must import it with app-specific path
    Assert-FileContains -Path (Join-Path $Root "backend\CLAUDE.md") -Needle "@AGENTS.md" -Message "backend/CLAUDE.md must import AGENTS.md."
    Assert-FileContains -Path (Join-Path $Root "backend\AGENTS.md") -Needle "app-requirements/[feature-id]-backend" -Message "backend/AGENTS.md missing backend app-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "backend\AGENTS.md") -Needle "advisory-review" -Message "backend/AGENTS.md missing advisory-review check."

    # AGENTS.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-android/" -Message "Backend-only AGENTS.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-ios/" -Message "Backend-only AGENTS.md should not reference mobile-ios/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "web-user-app/" -Message "Backend-only AGENTS.md should not reference web-user-app/."

    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Backend-only sample is missing gradlew."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew.bat") -Message "Backend-only sample is missing gradlew.bat."
    Assert-PathExists -Path (Join-Path $Root "backend\gradle\wrapper\gradle-wrapper.jar") -Message "Backend-only sample is missing gradle-wrapper.jar."

    Assert-PathMissing -Path (Join-Path $Root "web-user-app") -Message "Backend-only sample should not generate web-user-app."
    Assert-PathMissing -Path (Join-Path $Root "web-admin-portal") -Message "Backend-only sample should not generate web-admin-portal."
    Assert-PathMissing -Path (Join-Path $Root "docs\deployment\cloudflare-setup.md") -Message "Backend-only sample should not include Cloudflare docs."
    Assert-PathMissing -Path (Join-Path $Root "_templates\page") -Message "Backend-only sample should not include page generators."

    Assert-FileContains -Path (Join-Path $Root ".env.example") -Needle "APPLE_CLIENT_ID=" -Message "Backend-only sample should include Apple env vars when Apple auth is selected."
    Assert-FileContains -Path (Join-Path $Root ".env.example") -Needle "JWT_ACCESS_TOKEN_EXPIRY=" -Message "Backend-only sample should include JWT access expiry env vars."
    Assert-FileContains -Path (Join-Path $Root ".env.example") -Needle "JWT_REFRESH_TOKEN_EXPIRY=" -Message "Backend-only sample should include JWT refresh expiry env vars."

    Assert-FileContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "check -x test" -Message "Backend lint task should use static verification instead of ktlintCheck."
    Assert-FileNotContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "ktlintCheck" -Message "Backend Taskfile should not reference ktlintCheck."
    Assert-FileNotContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle 'basename $(pwd)' -Message "Backend Taskfile should not use Unix-only basename."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle "COPY gradlew gradlew.bat build.gradle.kts settings.gradle.kts ./" -Message "Backend Dockerfile should still use wrapper-based builds."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle 'RUN sed -i ''s/\r$//'' gradlew && chmod +x gradlew' -Message "Backend Dockerfile should normalize gradlew for Linux builds."

    Assert-FileContains -Path (Join-Path $Root "shared\api-contracts\openapi.yml") -Needle "/auth/oauth/callback:" -Message "Backend-only sample should generate the OAuth callback path when Google and Apple are selected."
    Assert-FileContains -Path (Join-Path $Root "backend\docs\entities\user.md") -Needle "local password auth and also supports Google, Apple, Facebook, Microsoft OAuth callback exchange" -Message "User entity doc should reflect the baseline password auth plus selected OAuth providers."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "Implement backend -> web-user-app -> web-admin-portal -> Android -> iOS as applicable" -Message "Root AGENTS guidance should not assume absent platform slices."
    Assert-PathMissing -Path (Join-Path $Root "docs\advisory-board.md") -Message "Generated project must not contain legacy docs/advisory-board.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\auth.md") -Message "Generated project must not contain legacy docs/features/auth.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\example-feature.md") -Message "Generated project must not contain legacy docs/features/example-feature.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\_template.md") -Message "Generated project must not contain legacy docs/features/_template.md."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\app-secrets.env.example") -Needle "JWT_ACCESS_TOKEN_EXPIRY=" -Message "Azure app secrets should use JWT access expiry."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\app-secrets.env.example") -Needle "JWT_REFRESH_TOKEN_EXPIRY=" -Message "Azure app secrets should use JWT refresh expiry."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\app-secrets.env.example") -Needle "APPLE_CLIENT_ID=" -Message "Azure app secrets should include Apple variables when Apple auth is selected."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\06-deploy-backend.sh") -Needle 'JWT_ACCESS_TOKEN_EXPIRY=${JWT_ACCESS_TOKEN_EXPIRY:-3600}' -Message "Azure deploy script should pass JWT access expiry."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\06-deploy-backend.sh") -Needle 'JWT_REFRESH_TOKEN_EXPIRY=${JWT_REFRESH_TOKEN_EXPIRY:-604800}' -Message "Azure deploy script should pass JWT refresh expiry."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\06-deploy-backend.sh") -Needle 'FACEBOOK_CLIENT_SECRET=secretref:facebook-client-secret' -Message "Azure deploy script should use FACEBOOK_CLIENT_SECRET."
    Assert-FileContains -Path (Join-Path $Root "infra\azure\check-secrets.sh") -Needle 'check_var "FACEBOOK_CLIENT_SECRET"' -Message "Azure secret checks should use FACEBOOK_CLIENT_SECRET."

    Assert-TreeNotContains -Root $Root -Needle "JWT_EXPIRATION_MS" -Message "Generated backend-only output should not contain stale JWT_EXPIRATION_MS wiring."
    Assert-TreeNotContains -Root $Root -Needle "FACEBOOK_APP_SECRET" -Message "Generated backend-only output should not use stale Facebook app-secret names."

    Assert-FileUsesLfLineEndings -Path (Join-Path $Root "backend\gradlew") -Message "Generated backend gradlew should use LF line endings for Linux compatibility."
    foreach ($azureScript in Get-ChildItem -LiteralPath (Join-Path $Root "infra\azure") -Filter "*.sh") {
        Assert-FileUsesLfLineEndings -Path $azureScript.FullName -Message "Generated Azure shell scripts should use LF line endings for Bash compatibility."
    }

    $javaCommand = Get-Command java -ErrorAction SilentlyContinue
    if ($RunSmoke -and $null -ne $javaCommand) {
        Write-Host "Running backend Gradle packaging smoke test..."
        Invoke-BackendBootJarSmoke -BackendRoot (Join-Path $Root "backend") -FailureMessage "Generated backend sample failed the Gradle bootJar smoke test."
        Assert-PathExists -Path (Join-Path $Root "backend\build\libs") -Message "Generated backend sample did not produce a bootJar output directory."
    }
    else {
        Write-Host "Skipping backend Gradle smoke test because it is disabled for this mode or Java is not available on PATH."
    }

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($RunSmoke -and $null -ne $dockerCommand) {
        Push-Location (Join-Path $Root "backend")
        try {
            $imageTag = "template-backend-validation:$PID"
            Write-Host "Running backend Docker image smoke test..."
            & docker build -t $imageTag . | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Generated backend sample failed 'docker build'."
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Skipping backend Docker smoke test because it is disabled for this mode or Docker is not available on PATH."
    }
}

function Invoke-BackendBootJarSmoke {
    param(
        [string]$BackendRoot,
        [string]$FailureMessage
    )

    Push-Location $BackendRoot
    try {
        if ($env:OS -eq "Windows_NT") {
            & .\gradlew.bat bootJar --no-daemon -x test | Out-Host
        }
        else {
            & chmod +x ./gradlew | Out-Null
            & ./gradlew bootJar --no-daemon -x test | Out-Host
        }

        if ($LASTEXITCODE -ne 0) {
            throw $FailureMessage
        }
    }
    finally {
        Pop-Location
    }
}

function Remove-TreeIfExists {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $lastError = $null
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        }
        catch [System.IO.DirectoryNotFoundException] {
            return
        }
        catch [System.IO.FileNotFoundException] {
            return
        }
        catch {
            $lastError = $_
            Start-Sleep -Milliseconds 200
        }
    }

    if (Test-Path -LiteralPath $Path) {
        throw $lastError
    }
}

function Validate-BackendPasswordOnly {
    param(
        [string]$Root,
        [bool]$RunSmoke = $false
    )

    Assert-NoCopierPlaceholders -Root $Root

    Assert-FileContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '@PostMapping("/register")' -Message "Password-only backend sample must expose the register endpoint."
    Assert-FileContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '@PostMapping("/login")' -Message "Password-only backend sample must expose the login endpoint."
    Assert-FileContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '@PostMapping("/refresh")' -Message "Password-only backend sample must expose the refresh endpoint."
    Assert-FileContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '@PostMapping("/logout")' -Message "Password-only backend sample must expose the logout endpoint."
    Assert-FileContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '@GetMapping("/me")' -Message "Password-only backend sample must expose the current-user endpoint."
    Assert-FileNotContains -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules\auth\controller\AuthController.kt") -Needle '/oauth/callback' -Message "Password-only backend sample must not render the OAuth callback endpoint."

    Assert-FileContains -Path (Join-Path $Root "shared\api-contracts\openapi.yml") -Needle "/auth/register:" -Message "Password-only backend sample must expose register in OpenAPI."
    Assert-FileContains -Path (Join-Path $Root "shared\api-contracts\openapi.yml") -Needle "/auth/login:" -Message "Password-only backend sample must expose login in OpenAPI."
    Assert-FileNotContains -Path (Join-Path $Root "shared\api-contracts\openapi.yml") -Needle "/auth/oauth/callback:" -Message "Password-only backend sample must not expose OAuth callback in OpenAPI."

    if ($RunSmoke) {
        $javaCommand = Get-Command java -ErrorAction SilentlyContinue
        if ($null -ne $javaCommand) {
            Write-Host "Running password-only backend Gradle packaging smoke test..."
            Invoke-BackendBootJarSmoke -BackendRoot (Join-Path $Root "backend") -FailureMessage "Generated password-only backend sample failed the Gradle bootJar smoke test."
        }
        else {
            Write-Host "Skipping password-only backend Gradle smoke test because Java is not available on PATH."
        }
    }
}

function ConvertTo-ComparableApiPath {
    param([string]$Path)

    $value = $Path.Trim()
    $queryIndex = $value.IndexOf('?')
    if ($queryIndex -ge 0) {
        $value = $value.Substring(0, $queryIndex)
    }

    # Swift interpolation \(id), JavaScript template ${id} and OpenAPI or Retrofit {id} all become {}.
    $value = [regex]::Replace($value, '\\\([^)]*\)', '{}')
    $value = [regex]::Replace($value, '\$?\{[^}/]*\}', '{}')
    if (-not $value.StartsWith('/')) {
        $value = '/' + $value
    }
    if ($value.Length -gt 1) {
        $value = $value.TrimEnd('/')
    }
    return $value
}

function Get-OpenApiPaths {
    param([string]$Content)

    $paths = @()
    $inPaths = $false
    foreach ($line in ($Content -split "\r?\n")) {
        if ($line -match '^paths:\s*$') {
            $inPaths = $true
            continue
        }
        if ($inPaths -and $line -match '^[A-Za-z]') {
            break
        }
        if ($inPaths -and $line -match '^  (/\S*):\s*$') {
            $paths += (ConvertTo-ComparableApiPath -Path $Matches[1])
        }
    }
    return @($paths | Sort-Object -Unique)
}

function Get-AndroidApiPaths {
    param([string]$Content)

    $paths = @()
    foreach ($match in [regex]::Matches($Content, '@(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\(\s*(?:value\s*=\s*)?"([^"]*)"')) {
        $paths += (ConvertTo-ComparableApiPath -Path $match.Groups[1].Value)
    }
    return @($paths)
}

function Get-IosApiPaths {
    param([string]$Content)

    $paths = @()
    foreach ($match in [regex]::Matches($Content, 'APIEndpoint\(\s*path:\s*"((?:[^"\\]|\\.)*)"')) {
        $paths += (ConvertTo-ComparableApiPath -Path $match.Groups[1].Value)
    }
    return @($paths)
}

function Get-WebApiPaths {
    param(
        [string]$Content,
        [bool]$IsRouteMap = $false
    )

    $paths = @()
    if ($IsRouteMap) {
        # PATH_MAPPINGS maps a frontend /api/v1 path to a backend path. Backend paths under /actuator/
        # are infrastructure endpoints outside the OpenAPI contract, so those entries are not API calls.
        foreach ($match in [regex]::Matches($Content, '"(/api/v1/[^"]*)"\s*:\s*"([^"]*)"')) {
            if ($match.Groups[2].Value.StartsWith('/actuator/')) {
                continue
            }
            $paths += (ConvertTo-ComparableApiPath -Path $match.Groups[1].Value.Substring('/api/v1'.Length))
            $backendPath = $match.Groups[2].Value
            if ($backendPath.StartsWith('/api/v1/')) {
                $backendPath = $backendPath.Substring('/api/v1'.Length)
            }
            $paths += (ConvertTo-ComparableApiPath -Path $backendPath)
        }
        return @($paths)
    }

    foreach ($match in [regex]::Matches($Content, '/api/v1(/[A-Za-z][A-Za-z0-9_\-/{}$]*)')) {
        $paths += (ConvertTo-ComparableApiPath -Path $match.Groups[1].Value)
    }
    return @($paths)
}

function Find-ClientPathsMissingFromSpec {
    param(
        [object[]]$ClientPaths,
        [string[]]$SpecPaths
    )

    $missing = @()
    foreach ($clientPath in $ClientPaths) {
        if ($SpecPaths -notcontains $clientPath.Path) {
            $missing += $clientPath
        }
    }
    return @($missing)
}

function Get-ClientApiPaths {
    param([string]$Root)

    $clientPaths = @()
    $sources = @()

    $androidService = @(Get-ChildItem -LiteralPath (Join-Path $Root "mobile-android") -Recurse -Filter "ApiService.kt" -File -ErrorAction SilentlyContinue)
    foreach ($file in $androidService) {
        $sources += [pscustomobject]@{ Client = "android"; File = $file.FullName; Paths = (Get-AndroidApiPaths -Content (Get-Content -Raw -LiteralPath $file.FullName)) }
    }

    $iosEndpoint = @(Get-ChildItem -LiteralPath (Join-Path $Root "mobile-ios") -Recurse -Filter "APIEndpoint.swift" -File -ErrorAction SilentlyContinue)
    foreach ($file in $iosEndpoint) {
        $sources += [pscustomobject]@{ Client = "ios"; File = $file.FullName; Paths = (Get-IosApiPaths -Content (Get-Content -Raw -LiteralPath $file.FullName)) }
    }

    foreach ($webApp in @("web-user-app", "web-admin-portal")) {
        $webRoot = Join-Path $Root $webApp
        if (-not (Test-Path -LiteralPath $webRoot)) {
            continue
        }
        $webFiles = @(Get-ChildItem -LiteralPath $webRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
            $relativePath = $_.FullName.Substring($webRoot.Length)
            ($_.Extension -eq ".ts" -or $_.Extension -eq ".tsx") -and
            $relativePath -notmatch '[\\/](node_modules|\.next|\.open-next|\.wrangler|dist|tests?|__tests__)[\\/]' -and
            $_.Name -notmatch '\.(test|spec)\.tsx?$'
        })
        $routeFiles = @($webFiles | Where-Object { $_.Name -eq "api-routes.ts" })
        if ($routeFiles.Count -eq 0) {
            throw "$webApp is missing lib/config/api-routes.ts, so its API path mappings cannot be checked."
        }
        foreach ($file in $webFiles) {
            $content = Get-Content -Raw -LiteralPath $file.FullName
            $isRouteMap = $file.Name -eq "api-routes.ts"
            $sources += [pscustomobject]@{ Client = $webApp; File = $file.FullName; Paths = (Get-WebApiPaths -Content $content -IsRouteMap $isRouteMap) }
        }
    }

    foreach ($source in $sources) {
        foreach ($path in $source.Paths) {
            $clientPaths += [pscustomobject]@{ Client = $source.Client; File = $source.File; Path = $path }
        }
    }
    return @($clientPaths)
}

function Assert-ClientPathsInOpenApi {
    param([string]$Root)

    $specFile = Join-Path $Root "shared\api-contracts\openapi.yml"
    Assert-PathExists -Path $specFile -Message "Generated project missing shared/api-contracts/openapi.yml, so client paths cannot be checked against the contract."
    $specPaths = @(Get-OpenApiPaths -Content (Get-Content -Raw -LiteralPath $specFile))
    if ($specPaths.Count -eq 0) {
        throw "Could not read any paths from $specFile."
    }

    $clientPaths = @(Get-ClientApiPaths -Root $Root)

    # Each rendered client must yield paths. An empty result would mean the extraction no longer matches the code.
    $expectedClients = @()
    if (Test-Path -LiteralPath (Join-Path $Root "mobile-android")) { $expectedClients += "android" }
    if (Test-Path -LiteralPath (Join-Path $Root "mobile-ios")) { $expectedClients += "ios" }
    if (Test-Path -LiteralPath (Join-Path $Root "web-user-app")) { $expectedClients += "web-user-app" }
    if (Test-Path -LiteralPath (Join-Path $Root "web-admin-portal")) { $expectedClients += "web-admin-portal" }
    foreach ($client in $expectedClients) {
        if (@($clientPaths | Where-Object { $_.Client -eq $client }).Count -eq 0) {
            throw "Found no API paths in the generated $client client, so the contract guard cannot check it."
        }
    }

    $missing = @(Find-ClientPathsMissingFromSpec -ClientPaths $clientPaths -SpecPaths $specPaths)
    if ($missing.Count -gt 0) {
        $details = ($missing | ForEach-Object { "$($_.Client): $($_.Path) ($($_.File))" } | Sort-Object -Unique) -join "; "
        throw "Generated client calls paths that are not in shared/api-contracts/openapi.yml: $details"
    }
    Write-Host "Client API paths match the OpenAPI spec ($($clientPaths.Count) client paths, $($specPaths.Count) spec paths)."
}

function Assert-ClientPathGuardRejectsUnknownPaths {
    # Negative control: the guard must flag a client path that the spec does not define.
    $specPaths = @("/auth/login", "/transactions", "/transactions/{}")

    $plantedAndroid = '@GET("examples/{id}") suspend fun getExample(@Path("id") id: String): ExampleResponse'
    $plantedIos = 'static func listExamples() -> APIEndpoint { APIEndpoint(path: "/examples?page=\(page)", method: .get, requiresAuth: true) }'
    $plantedWeb = 'fetch(`${apiBaseUrl}/api/v1/examples/${id}`)'
    $plantedRouteMap = '"/api/v1/examples": "/api/v1/examples"'

    $cases = @(
        @{ Client = "android"; Paths = (Get-AndroidApiPaths -Content $plantedAndroid) },
        @{ Client = "ios"; Paths = (Get-IosApiPaths -Content $plantedIos) },
        @{ Client = "web"; Paths = (Get-WebApiPaths -Content $plantedWeb) },
        @{ Client = "web route map"; Paths = (Get-WebApiPaths -Content $plantedRouteMap -IsRouteMap $true) }
    )
    foreach ($case in $cases) {
        $clientPaths = @($case.Paths | ForEach-Object { [pscustomobject]@{ Client = $case.Client; File = "planted"; Path = $_ } })
        if ($clientPaths.Count -eq 0) {
            throw "Contract guard self-check failed: the $($case.Client) extraction found no path in the planted sample."
        }
        if (@(Find-ClientPathsMissingFromSpec -ClientPaths $clientPaths -SpecPaths $specPaths).Count -eq 0) {
            throw "Contract guard self-check failed: a planted /examples path in the $($case.Client) client was not flagged."
        }
    }

    $validAndroid = '@GET("transactions") @PUT("transactions/{id}") @POST("auth/login")'
    $validIos = 'APIEndpoint(path: "/transactions?page=\(page)&size=\(size)", method: .get, requiresAuth: true) APIEndpoint(path: "/transactions/\(id)", method: .put, requiresAuth: true)'
    foreach ($valid in @($validAndroid, $validIos)) {
        $extracted = @()
        $extracted += Get-AndroidApiPaths -Content $valid
        $extracted += Get-IosApiPaths -Content $valid
        $clientPaths = @($extracted | ForEach-Object { [pscustomobject]@{ Client = "valid"; File = "sample"; Path = $_ } })
        if ($clientPaths.Count -eq 0 -or @(Find-ClientPathsMissingFromSpec -ClientPaths $clientPaths -SpecPaths $specPaths).Count -ne 0) {
            throw "Contract guard self-check failed: valid sample paths were rejected or not extracted."
        }
    }
    Write-Host "Contract guard self-check passed (planted /examples paths are rejected)."
}

function Validate-WebSample {
    param(
        [string]$Root,
        [bool]$RunSmoke = $true
    )

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root
    Assert-ClientPathsInOpenApi -Root $Root

    # web-user-app and web-admin-portal AGENTS.md must have the wiki section and CLAUDE.md must import it
    foreach ($platform in @("web-user-app", "web-admin-portal")) {
        Assert-FileContains -Path (Join-Path $Root "$platform\CLAUDE.md") -Needle "@AGENTS.md" -Message "$platform/CLAUDE.md must import AGENTS.md."
        Assert-FileContains -Path (Join-Path $Root "$platform\AGENTS.md") -Needle "knowledge/wiki/app-requirements" -Message "$platform/AGENTS.md missing wiki app-requirements reference."
        Assert-FileContains -Path (Join-Path $Root "$platform\AGENTS.md") -Needle "advisory-review" -Message "$platform/AGENTS.md missing advisory-review check."
    }

    # AGENTS.md must not contain platform directories for absent platforms
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-android/" -Message "Web-only AGENTS.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-ios/" -Message "Web-only AGENTS.md should not reference mobile-ios/."

    Assert-PathExists -Path (Join-Path $Root "web-user-app") -Message "Web sample should generate web-user-app."
    Assert-PathExists -Path (Join-Path $Root "web-admin-portal") -Message "Web sample should generate web-admin-portal."
    Assert-PathExists -Path (Join-Path $Root ".github\workflows\web-user-app.yml") -Message "Web sample should generate the user web workflow."
    Assert-PathExists -Path (Join-Path $Root ".github\workflows\web-admin-portal.yml") -Message "Web sample should generate the admin web workflow."
    Assert-PathExists -Path (Join-Path $Root "docs\deployment\cloudflare-setup.md") -Message "Web sample should generate Cloudflare docs."
    Assert-PathExists -Path (Join-Path $Root "_templates\page") -Message "Web sample should include page generators."
    Assert-PathExists -Path (Join-Path $Root "web-user-app\.dev.vars.example") -Message "Web sample should include a Cloudflare preview env example for the user web app."
    Assert-PathExists -Path (Join-Path $Root "web-admin-portal\.dev.vars.example") -Message "Web sample should include a Cloudflare preview env example for the admin portal."

    Assert-PathMissing -Path (Join-Path $Root "docs\advisory-board.md") -Message "Generated project must not contain legacy docs/advisory-board.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\auth.md") -Message "Generated project must not contain legacy docs/features/auth.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\example-feature.md") -Message "Generated project must not contain legacy docs/features/example-feature.md."
    Assert-TreeNotContains -Root $Root -Needle "JWT_EXPIRATION_MS" -Message "Generated web sample should not contain stale JWT_EXPIRATION_MS wiring."
    Assert-FileContains -Path (Join-Path $Root "web-user-app\wrangler.jsonc") -Needle '"observability": {' -Message "User web Wrangler config should enable observability."
    Assert-FileContains -Path (Join-Path $Root "web-user-app\wrangler.jsonc") -Needle '"upload_source_maps": true' -Message "User web Wrangler config should upload source maps."
    Assert-FileContains -Path (Join-Path $Root "web-user-app\wrangler.jsonc") -Needle '"API_BASE_URL": "https://api.review-web.com"' -Message "User web Wrangler config should include API_BASE_URL."
    Assert-FileContains -Path (Join-Path $Root "web-admin-portal\wrangler.jsonc") -Needle '"observability": {' -Message "Admin web Wrangler config should enable observability."
    Assert-FileContains -Path (Join-Path $Root "web-admin-portal\wrangler.jsonc") -Needle '"upload_source_maps": true' -Message "Admin web Wrangler config should upload source maps."
    Assert-FileContains -Path (Join-Path $Root "web-admin-portal\wrangler.jsonc") -Needle '"API_BASE_URL": "https://api.review-web.com"' -Message "Admin web Wrangler config should include API_BASE_URL."
    Assert-FileContains -Path (Join-Path $Root ".github\workflows\web-user-app.yml") -Needle 'run: npx wrangler deploy --dry-run' -Message "User web workflow should smoke-test Wrangler packaging."
    Assert-FileContains -Path (Join-Path $Root ".github\workflows\web-admin-portal.yml") -Needle 'run: npx wrangler deploy --dry-run' -Message "Admin web workflow should smoke-test Wrangler packaging."
    Assert-FileContains -Path (Join-Path $Root "docs\deployment\cloudflare-setup.md") -Needle 'Cloudflare Workers' -Message "Generated Cloudflare docs should describe Workers, not Pages."

    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if ($RunSmoke -and $null -ne $npmCommand) {
        foreach ($webApp in @("web-user-app", "web-admin-portal")) {
            Push-Location (Join-Path $Root $webApp)
            try {
                Write-Host "Running web smoke tests for $webApp..."
                & npm install | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'npm install'."
                }

                & npm run lint | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'npm run lint'."
                }

                & npm run typecheck | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'npm run typecheck'."
                }

                & npm run build | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'npm run build'."
                }

                & npm run build:cloudflare | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'npm run build:cloudflare'."
                }

                & npx wrangler deploy --dry-run | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "Generated $webApp sample failed 'wrangler deploy --dry-run'."
                }
            }
            finally {
                Pop-Location
            }
        }
    }
    else {
        Write-Host "Skipping generated web smoke tests because they are disabled for this mode or npm is not available on PATH."
    }
}

function Validate-AndroidSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root
    Assert-ClientPathsInOpenApi -Root $Root

    # mobile-android AGENTS.md must have the wiki section and CLAUDE.md must import it with app-specific path
    Assert-FileContains -Path (Join-Path $Root "mobile-android\CLAUDE.md") -Needle "@AGENTS.md" -Message "mobile-android/CLAUDE.md must import AGENTS.md."
    Assert-FileContains -Path (Join-Path $Root "mobile-android\AGENTS.md") -Needle "app-requirements/[feature-id]-mobile-android" -Message "mobile-android/AGENTS.md missing mobile-android app-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-android\AGENTS.md") -Needle "advisory-review" -Message "mobile-android/AGENTS.md missing advisory-review check."

    # AGENTS.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-ios/" -Message "Android-only AGENTS.md should not reference mobile-ios/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "web-user-app/" -Message "Android-only AGENTS.md should not reference web-user-app/."

    Assert-PathExists -Path (Join-Path $Root "mobile-android") -Message "Android sample should generate mobile-android."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Android sample should still include backend Gradle wrapper files."
}

function Validate-IosSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root
    Assert-ClientPathsInOpenApi -Root $Root

    # mobile-ios AGENTS.md must have the wiki section and CLAUDE.md must import it with app-specific path
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\CLAUDE.md") -Needle "@AGENTS.md" -Message "mobile-ios/CLAUDE.md must import AGENTS.md."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\AGENTS.md") -Needle "app-requirements/[feature-id]-mobile-ios" -Message "mobile-ios/AGENTS.md missing mobile-ios app-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\AGENTS.md") -Needle "advisory-review" -Message "mobile-ios/AGENTS.md missing advisory-review check."

    # AGENTS.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-android/" -Message "iOS-only AGENTS.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "web-user-app/" -Message "iOS-only AGENTS.md should not reference web-user-app/."

    Assert-PathExists -Path (Join-Path $Root "mobile-ios\review-app") -Message "iOS sample should keep filesystem-safe project_slug directories."
    Assert-PathExists -Path (Join-Path $Root "mobile-ios\review-appTests") -Message "iOS sample should generate a test directory."

    Assert-FileContains -Path (Join-Path $Root "mobile-ios\project.yml") -Needle "  ReviewApp:" -Message "iOS project.yml should use ios_module_name for the app target."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\project.yml") -Needle "  ReviewAppTests:" -Message "iOS project.yml should use ios_module_name for the test target."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\review-app\App.swift") -Needle "struct ReviewAppApp: App" -Message "App.swift should use an iOS-safe app type name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\review-appTests\LoginViewModelTests.swift") -Needle "@testable import ReviewApp" -Message "iOS tests should import the iOS-safe module name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\Taskfile.yml") -Needle 'default "ReviewApp"' -Message "iOS Taskfile should default to the iOS-safe scheme name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\fastlane\Fastfile") -Needle 'project: "Review App.xcodeproj"' -Message "Fastlane should use the generated Xcode project name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\fastlane\Fastfile") -Needle 'scheme: "ReviewApp"' -Message "Fastlane should use the iOS-safe scheme name."

    # xcconfig treats // as a comment start, so URL values must use the $() escape, and CI must be able to create the git-ignored local files.
    foreach ($configName in @("Debug", "Release")) {
        $configPath = Join-Path $Root "mobile-ios\Config\$configName.xcconfig"
        Assert-FileContains -Path $configPath -Needle ':/$()/' -Message "iOS $configName.xcconfig should escape // in API_BASE_URL with the `$() form."
        Assert-FileNotContains -Path $configPath -Needle '= http://' -Message "iOS $configName.xcconfig must not contain an unescaped http:// URL value."
        Assert-FileNotContains -Path $configPath -Needle '= https://' -Message "iOS $configName.xcconfig must not contain an unescaped https:// URL value."
        Assert-PathExists -Path (Join-Path $Root "mobile-ios\Config\$configName.xcconfig.example") -Message "iOS sample should track Config/$configName.xcconfig.example for fresh checkouts."
        Assert-FileContains -Path (Join-Path $Root ".github\workflows\mobile-ios.yml") -Needle "cp Config/$configName.xcconfig.example Config/$configName.xcconfig" -Message "iOS workflow should create Config/$configName.xcconfig before generating the project."
    }
    Assert-FileContains -Path (Join-Path $Root ".github\workflows\mobile-ios.yml") -Needle '-project "Review App.xcodeproj"' -Message "iOS workflow should quote the Xcode project name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\project.yml") -Needle 'name: "Review App"' -Message "iOS project.yml should quote the project name."

    Assert-FileNotContains -Path (Join-Path $Root "mobile-ios\review-app\App.swift") -Needle "Review-appApp" -Message "App.swift should not contain slug-based invalid Swift identifiers."
    Assert-FileNotContains -Path (Join-Path $Root "mobile-ios\review-appTests\LoginViewModelTests.swift") -Needle "@testable import review-app" -Message "iOS tests should not import slug-based invalid module names."
}

Remove-TreeIfExists -Path $OutputRoot
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

switch ($Mode) {
    "backend-smoke" {
        $backendRoot = New-GeneratedProject -Name "backend" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[google, apple, facebook, microsoft, password]"
        )
        Validate-BackendOnly -Root $backendRoot -RunSmoke $true

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[password]"
        )
        Validate-BackendPasswordOnly -Root $passwordOnlyRoot -RunSmoke $true
    }
    "contract" {
        Assert-ClientPathGuardRejectsUnknownPaths

        $backendRoot = New-GeneratedProject -Name "backend" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[google, apple, facebook, microsoft, password]"
        )
        Validate-BackendOnly -Root $backendRoot -RunSmoke $false

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[password]"
        )
        Validate-BackendPasswordOnly -Root $passwordOnlyRoot -RunSmoke $false

        $webRoot = New-GeneratedProject -Name "web" -DataArgs @(
            "project_name=Review Web",
            "platforms=[backend, web-user-app, web-admin-portal]"
        )
        Validate-WebSample -Root $webRoot -RunSmoke $false

        $androidRoot = New-GeneratedProject -Name "android" -DataArgs @(
            "project_name=Review Android",
            "platforms=[backend, mobile-android]"
        )
        Validate-AndroidSample -Root $androidRoot

        $iosRoot = New-GeneratedProject -Name "ios" -DataArgs @(
            "project_name=Review App",
            "platforms=[backend, mobile-ios]"
        )
        Validate-IosSample -Root $iosRoot

        $standaloneRoot = New-GeneratedProject -Name "standalone-web" -DataArgs @(
            "project_name=Standalone Web",
            "platforms=[web-user-app, web-admin-portal]",
            "auth_methods=[password]"
        )
        Validate-WikiStructure -Root $standaloneRoot
        foreach ($excluded in @("backend", "infra", "docker-compose.yml", ".github/workflows/backend.yml", ".cursor/rules/backend.mdc")) {
            Assert-PathMissing -Path (Join-Path $standaloneRoot $excluded) -Message "No-backend selection must omit $excluded."
        }
    }
    "full" {
        Assert-ClientPathGuardRejectsUnknownPaths

        $backendRoot = New-GeneratedProject -Name "backend" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[google, apple, facebook, microsoft, password]"
        )
        Validate-BackendOnly -Root $backendRoot -RunSmoke $true

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -DataArgs @(
            "project_name=Review Backend",
            "platforms=[backend]",
            "auth_methods=[password]"
        )
        Validate-BackendPasswordOnly -Root $passwordOnlyRoot -RunSmoke $true

        $webRoot = New-GeneratedProject -Name "web" -DataArgs @(
            "project_name=Review Web",
            "platforms=[backend, web-user-app, web-admin-portal]"
        )
        Validate-WebSample -Root $webRoot -RunSmoke $false

        $androidRoot = New-GeneratedProject -Name "android" -DataArgs @(
            "project_name=Review Android",
            "platforms=[backend, mobile-android]"
        )
        Validate-AndroidSample -Root $androidRoot

        $iosRoot = New-GeneratedProject -Name "ios" -DataArgs @(
            "project_name=Review App",
            "platforms=[backend, mobile-ios]"
        )
        Validate-IosSample -Root $iosRoot
    }
}

Write-Host ""
Write-Host "Template validation passed."

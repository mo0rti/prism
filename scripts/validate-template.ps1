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
        "{{ platforms"
    )

    foreach ($pattern in $patterns) {
        Assert-TreeNotContains -Root $Root -Needle $pattern -Message "Generated output still contains unresolved Copier placeholders."
    }
}

# The apps the validation generates: the ID, the stack and the display name `prism new` gives each. `admin` is a second
# nextjs-web app, `partner-android` and `partner-ios` are second apps of their stacks at their own paths, and the web and
# iOS apps carry an audience.
$DefaultApps = @{
    "backend"          = @{ Stack = "spring-backend";  Name = "Spring Boot Backend" }
    "web"              = @{ Stack = "nextjs-web";      Name = "Web App";             Audience = "B2C" }
    "admin"            = @{ Stack = "nextjs-web";      Name = "Admin App";           Audience = "internal" }
    "mobile-android"   = @{ Stack = "android-compose"; Name = "Android (Kotlin/Compose)" }
    "partner-android"  = @{ Stack = "android-compose"; Name = "Partner App";         Path = "apps/partner" }
    "mobile-ios"       = @{ Stack = "ios-swiftui";     Name = "iOS (Swift/SwiftUI)"; Audience = "customers" }
    "partner-ios"      = @{ Stack = "ios-swiftui";     Name = "Partner App";         Audience = "internal"; Path = "apps/partner-ios" }
}

function New-GeneratedProject {
    # Generates through the Prism CLI from this checkout, with a preset or an answers file of default apps.
    param(
        [string]$Name,
        [string]$ProjectName,
        [string[]]$Apps = @(),
        [string[]]$AuthMethods = @(),
        [string]$Preset = ""
    )

    $target = Join-Path $OutputRoot $Name
    Remove-TreeIfExists -Path $target

    $arguments = @("-B", "-m", "prism_cli", "new", "--dest", $target, "--yes")
    if ($Preset) {
        $arguments += @("--preset", $Preset, "--project-name", $ProjectName)
    }
    else {
        $lines = @("schema_version: 1", "answers:", "  project_name: `"$ProjectName`"")
        if ($AuthMethods.Count -gt 0) {
            $lines += "  auth_methods: [" + ($AuthMethods -join ", ") + "]"
        }
        if ($Apps.Count -eq 0) {
            $lines += "  apps: []"
        }
        else {
            $lines += "  apps:"
            foreach ($app in $Apps) {
                $lines += "    - id: $app"
                $lines += "      stack: $($DefaultApps[$app].Stack)"
                $lines += "      name: `"$($DefaultApps[$app].Name)`""
                if ($DefaultApps[$app].ContainsKey("Audience")) {
                    $lines += "      audience: $($DefaultApps[$app].Audience)"
                }
                if ($DefaultApps[$app].ContainsKey("Path")) {
                    $lines += "      path: $($DefaultApps[$app].Path)"
                }
            }
        }
        $answersFile = Join-Path $OutputRoot "$Name-answers.yml"
        [System.IO.File]::WriteAllText($answersFile, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
        $arguments += @("--answers", $answersFile)
    }

    # The CLI writes notices to stderr. Windows PowerShell 5.1 turns native stderr
    # output into a terminating error under $ErrorActionPreference = "Stop", so the
    # call runs with "Continue" and only a non-zero exit code fails the generation.
    $generationExitCode = 0
    Push-Location $repoRoot
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        Write-Host "Generating sample: $Name"
        $ErrorActionPreference = "Continue"
        & python @arguments 2>&1 | ForEach-Object { Write-Host "$_" }
        $generationExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
        Pop-Location
    }
    if ($generationExitCode -ne 0) {
        throw "Prism generation failed for $Name."
    }

    if ($Mode -eq "contract") {
        $workflows = @(Get-ChildItem -LiteralPath (Join-Path $target ".github/workflows") -Filter "*.yml" -File | ForEach-Object { $_.FullName })
        & $ActionlintPath '-shellcheck=' '-pyflakes=' @workflows
        if ($LASTEXITCODE -ne 0) {
            throw "Generated workflow validation failed for $Name."
        }
    }
    Assert-PathExists -Path (Join-Path $target ".copier-answers.yml") -Message "Generation must save its answers for future updates."
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

    # Cursor reads AGENTS.md itself: no pointer rule, and the wiki rule is gone
    Assert-PathMissing -Path (Join-Path $Root ".cursor\rules\project.mdc") -Message "Generated project must not contain .cursor/rules/project.mdc (Cursor reads AGENTS.md itself)."
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

function Assert-NoDeploymentArtifacts {
    param([string]$Root)

    # Deployment is a skill, not generated project files: no infra, hosting config or deploy job.
    Assert-PathMissing -Path (Join-Path $Root "infra") -Message "Generated project must not contain infra/."
    Assert-PathMissing -Path (Join-Path $Root "backend\docs\azure-setup.md") -Message "Generated project must not contain backend/docs/azure-setup.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\deployment\cloudflare-setup.md") -Message "Generated project must not contain docs/deployment/cloudflare-setup.md."
    foreach ($webApp in @("web", "admin")) {
        foreach ($hostingFile in @("wrangler.jsonc", "open-next.config.ts", ".dev.vars.example")) {
            Assert-PathMissing -Path (Join-Path $Root "$webApp\$hostingFile") -Message "Generated project must not contain $webApp/$hostingFile."
        }
        $packageJson = Join-Path $Root "$webApp\package.json"
        if (Test-Path -LiteralPath $packageJson) {
            foreach ($hostingNeedle in @("opennextjs", "wrangler", "build:cloudflare")) {
                Assert-FileNotContains -Path $packageJson -Needle $hostingNeedle -Message "$webApp/package.json must not reference $hostingNeedle."
            }
        }
    }
    foreach ($workflow in Get-ChildItem -LiteralPath (Join-Path $Root ".github\workflows") -Filter "*.yml" -File) {
        $text = Get-Content -Raw -LiteralPath $workflow.FullName
        foreach ($deployNeedle in @("secrets.", "wrangler", "az containerapp", "fastlane", "environment: production")) {
            if ($text.Contains($deployNeedle)) {
                throw "Generated workflow $($workflow.Name) must build and test only, but it contains '$deployNeedle'."
            }
        }
    }
    Assert-TreeNotContains -Root $Root -Needle "REDIS_" -Message "Generated output must not contain Redis configuration."
}

function Assert-DeploymentSkill {
    param(
        [string]$Root,
        [bool]$Backend = $false,
        [bool]$Web = $false
    )

    foreach ($layer in @(".claude", ".agents")) {
        $skill = Join-Path $Root "$layer\skills\deployment"
        Assert-PathExists -Path (Join-Path $skill "SKILL.md") -Message "Generated project missing $layer/skills/deployment/SKILL.md."
        Assert-FileContains -Path (Join-Path $skill "SKILL.md") -Needle "name: deployment" -Message "$layer deployment skill must be named deployment."
        Assert-FileContains -Path (Join-Path $skill "SKILL.md") -Needle "belong to the user and their agent" -Message "$layer deployment skill must state who owns the cloud choice, the secrets and the deployment."

        if ($Backend) {
            Assert-PathExists -Path (Join-Path $skill "references\azure-setup.md") -Message "$layer deployment skill missing the Azure guide."
            Assert-FileContains -Path (Join-Path $skill "references\azure\app-secrets.env.example") -Needle "IDENTITY_PROVIDER_ISSUER_URI=" -Message "Azure app secrets should name the identity provider's issuer."
            Assert-FileContains -Path (Join-Path $skill "references\azure\06-deploy-backend.sh") -Needle 'SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI=$IDENTITY_PROVIDER_ISSUER_URI' -Message "Azure deploy script should pass the identity provider's issuer to the backend."
            Assert-FileContains -Path (Join-Path $skill "references\azure\check-secrets.sh") -Needle 'check_var "IDENTITY_PROVIDER_ISSUER_URI"' -Message "Azure secret checks should check the identity provider's issuer."
            foreach ($azureFile in @("06-deploy-backend.sh", "update-backend.sh", "app-secrets.env.example", "check-secrets.sh")) {
                Assert-FileNotContains -Path (Join-Path $skill "references\azure\$azureFile") -Needle "JWT_SECRET" -Message "Azure example $azureFile must not carry a JWT secret."
                Assert-FileNotContains -Path (Join-Path $skill "references\azure\$azureFile") -Needle "CLIENT_SECRET" -Message "Azure example $azureFile must not carry an OAuth provider secret."
            }
            foreach ($azureScript in Get-ChildItem -LiteralPath (Join-Path $skill "references\azure") -Filter "*.sh") {
                Assert-FileUsesLfLineEndings -Path $azureScript.FullName -Message "Deployment skill Azure shell scripts should use LF line endings for Bash compatibility."
            }
        }
        else {
            Assert-PathMissing -Path (Join-Path $skill "references\azure") -Message "$layer deployment skill must not carry the Azure example without a backend."
        }

        if ($Web) {
            Assert-FileContains -Path (Join-Path $skill "references\cloudflare-setup.md") -Needle 'Cloudflare Workers' -Message "Cloudflare guide should describe Workers, not Pages."
            Assert-PathExists -Path (Join-Path $skill "references\cloudflare\open-next.config.ts") -Message "$layer deployment skill missing the OpenNext config example."
            Assert-FileContains -Path (Join-Path $skill "references\cloudflare\wrangler.jsonc") -Needle '"observability": {' -Message "Web Wrangler example should enable observability."
            Assert-FileContains -Path (Join-Path $skill "references\cloudflare\wrangler.jsonc") -Needle '"upload_source_maps": true' -Message "Web Wrangler example should upload source maps."
            Assert-FileContains -Path (Join-Path $skill "references\cloudflare\wrangler.jsonc") -Needle '"API_BASE_URL": "https://api.' -Message "Web Wrangler example should include API_BASE_URL."
            Assert-FileNotContains -Path (Join-Path $skill "references\cloudflare\wrangler.jsonc") -Needle 'AUTH_' -Message "The slice's web apps read no AUTH_ variable, so the Wrangler example must not set one."
            Assert-PathExists -Path (Join-Path $skill "references\cloudflare\dev.vars.example") -Message "$layer deployment skill missing the web preview variables example."
        }
        else {
            Assert-PathMissing -Path (Join-Path $skill "references\cloudflare") -Message "$layer deployment skill must not carry the Cloudflare example without a web app."
        }
    }
    Assert-PathExists -Path (Join-Path $Root ".agents\skills\deployment\agents\openai.yaml") -Message "Generated project missing .agents/skills/deployment/agents/openai.yaml."
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
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "-> Next.js" -Message "Backend-only AGENTS.md should not describe a web app."

    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Backend-only sample is missing gradlew."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew.bat") -Message "Backend-only sample is missing gradlew.bat."
    Assert-PathExists -Path (Join-Path $Root "backend\gradle\wrapper\gradle-wrapper.jar") -Message "Backend-only sample is missing gradle-wrapper.jar."

    # The backend is the spring-backend pack: an app layer with its own answers, workflow and Cursor rule.
    Assert-FileContains -Path (Join-Path $Root "backend\.copier-answers.yml") -Needle "prism_layer: spring-backend" -Message "The backend must record its own pack answers in backend/.copier-answers.yml."
    Assert-FileContains -Path (Join-Path $Root "backend\.copier-answers.yml") -Needle "port: 8080" -Message "The first backend must hold port 8080."
    Assert-PathExists -Path (Join-Path $Root ".github\workflows\backend.yml") -Message "The backend pack must generate its workflow."
    Assert-PathExists -Path (Join-Path $Root ".cursor\rules\backend.mdc") -Message "The backend pack must generate its Cursor rule."
    $sliceRoot = Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\backend"
    foreach ($sliceFile in @(
            "modules\users\controller\MeController.kt",
            "modules\users\service\UserService.kt",
            "modules\users\repository\UserRepository.kt",
            "modules\users\model\User.kt",
            "modules\devidentity\controller\DevIdentityController.kt",
            "bootstrap\SecurityConfig.kt",
            "bootstrap\DevIdentityConfig.kt",
            "bootstrap\DevIdentityGuard.kt",
            "shared\exception\GlobalExceptionHandler.kt")) {
        Assert-PathExists -Path (Join-Path $sliceRoot $sliceFile) -Message "The backend pack must generate its slice file $sliceFile under the app's own package."
    }
    Assert-PathExists -Path (Join-Path $Root "backend\src\main\resources\db\migration\V1__users.sql") -Message "The backend pack must generate the users migration."
    Assert-PathExists -Path (Join-Path $Root "backend\docs\guide.md") -Message "The backend pack must generate its guide."
    Assert-PathExists -Path (Join-Path $Root "backend\README.md") -Message "The backend pack must generate its README."
    Assert-FileContains -Path (Join-Path $Root "backend\README.md") -Needle "local development sign-in" -Message "The backend README must state that the dev identity is local development sign-in."
    Assert-FileContains -Path (Join-Path $Root "backend\AGENTS.md") -Needle "not authentication" -Message "The backend AGENTS.md must state that the dev identity is not authentication."
    Assert-FileContains -Path (Join-Path $Root ".cursor\rules\backend.mdc") -Needle "dev identity" -Message "The backend Cursor rule must describe the dev identity."
    Assert-FileContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "SPRING_PROFILES_ACTIVE: local" -Message "The dev task must set the local profile explicitly."
    Assert-FileNotContains -Path (Join-Path $Root "docker-compose.yml") -Needle "SPRING_PROFILES_ACTIVE" -Message "docker-compose.yml must not set a default Spring profile."
    Assert-FileContains -Path (Join-Path $Root ".github\workflows\backend.yml") -Needle "./gradlew build" -Message "The backend workflow must build and run every test."
    Assert-FileContains -Path (Join-Path $Root "prism.workspace.yml") -Needle "generation: scaffolded" -Message "prism.workspace.yml must record the backend as scaffolded."
    Assert-PathMissing -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\modules") -Message "The retired full backend sample must not be generated."
    Assert-PathMissing -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\backend\modules\health") -Message "The slice has no health module: /actuator/health is the health check."
    Assert-PathMissing -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\backend\modules\auth") -Message "The slice has no auth module: the dev identity and the resource server replace it."
    Assert-PathMissing -Path (Join-Path $Root "backend\src\main\kotlin\com\example\reviewbackend\backend\modules\transactions") -Message "The slice has no transactions module."

    Assert-PathMissing -Path (Join-Path $Root "web") -Message "Backend-only sample should not generate a web app."
    Assert-PathMissing -Path (Join-Path $Root "_templates\page") -Message "Page generators of the retired web samples must not be generated."
    Assert-NoDeploymentArtifacts -Root $Root
    Assert-DeploymentSkill -Root $Root -Backend $true -Web $false
    Assert-PathExists -Path (Join-Path $Root "docker-compose.yml") -Message "A sample with a backend app must generate docker-compose.yml for the local development database."
    Assert-FileContains -Path (Join-Path $Root "docker-compose.yml") -Needle "postgres:16-alpine" -Message "docker-compose.yml must run the PostgreSQL development database."

    Assert-FileContains -Path (Join-Path $Root ".env.example") -Needle "DATABASE_NAME=" -Message "Backend-only sample should include the local database variables."
    foreach ($envFile in @(".env", ".env.example")) {
        foreach ($retired in @("JWT_", "GOOGLE_", "APPLE_", "FACEBOOK_", "MICROSOFT_")) {
            Assert-FileNotContains -Path (Join-Path $Root $envFile) -Needle $retired -Message "$envFile must not carry the retired $retired variables: the template holds no JWT secret and no OAuth provider."
        }
    }

    Assert-FileContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "check -x test" -Message "Backend lint task should use static verification instead of ktlintCheck."
    Assert-FileNotContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "ktlintCheck" -Message "Backend Taskfile should not reference ktlintCheck."
    Assert-FileNotContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle 'basename $(pwd)' -Message "Backend Taskfile should not use Unix-only basename."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle "COPY gradlew gradlew.bat build.gradle.kts settings.gradle.kts ./" -Message "Backend Dockerfile should still use wrapper-based builds."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle 'RUN sed -i ''s/\r$//'' gradlew && chmod +x gradlew' -Message "Backend Dockerfile should normalize gradlew for Linux builds."

    Validate-AuthContract -Root $Root
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "Implement backend -> web -> Android -> iOS as applicable" -Message "Root AGENTS guidance should not assume absent platform slices."
    Assert-PathMissing -Path (Join-Path $Root "docs\advisory-board.md") -Message "Generated project must not contain legacy docs/advisory-board.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\auth.md") -Message "Generated project must not contain legacy docs/features/auth.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\example-feature.md") -Message "Generated project must not contain legacy docs/features/example-feature.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\_template.md") -Message "Generated project must not contain legacy docs/features/_template.md."
    Assert-FileContains -Path (Join-Path $Root ".claude\skills\security-auth\SKILL.md") -Needle "Replacing The Dev Identity With A Real Identity Provider" -Message "The security-auth skill must explain how to replace the dev identity."

    Assert-TreeNotContains -Root $Root -Needle "JWT_EXPIRATION_MS" -Message "Generated backend-only output should not contain stale JWT_EXPIRATION_MS wiring."
    Assert-TreeNotContains -Root $Root -Needle "FACEBOOK_APP_SECRET" -Message "Generated backend-only output should not use stale Facebook app-secret names."
    Assert-TreeNotContains -Root $Root -Needle "JWT_SECRET" -Message "Generated backend-only output must not carry a JWT secret variable."
    Assert-TreeNotContains -Root $Root -Needle "JwtTokenProvider" -Message "Generated backend-only output must not reference the retired token provider of the full sample."

    Assert-FileUsesLfLineEndings -Path (Join-Path $Root "backend\gradlew") -Message "Generated backend gradlew should use LF line endings for Linux compatibility."

    $javaCommand = Get-Command java -ErrorAction SilentlyContinue
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    $dockerRunning = $false
    if ($null -ne $dockerCommand) {
        # On Windows, cmd keeps the daemon's stderr warnings from becoming a terminating error under Windows
        # PowerShell 5.1 ($IsWindows does not exist there, so the check reads $env:OS). Elsewhere the output is discarded.
        if ($env:OS -eq "Windows_NT") {
            & cmd /c "docker info >nul 2>&1"
        }
        else {
            & docker info *> $null
        }
        $dockerRunning = ($LASTEXITCODE -eq 0)
    }
    if ($RunSmoke -and $null -ne $javaCommand -and $dockerRunning) {
        Write-Host "Running backend Gradle test and packaging smoke test (the integration tests start PostgreSQL with Testcontainers)..."
        Invoke-BackendBootJarSmoke -BackendRoot (Join-Path $Root "backend") -FailureMessage "Generated backend failed the Gradle test and bootJar smoke test."
        Assert-PathExists -Path (Join-Path $Root "backend\build\libs") -Message "Generated backend did not produce a bootJar output directory."
    }
    else {
        Write-Host "Skipping backend Gradle smoke test because it is disabled for this mode, or Java or a running Docker daemon (Testcontainers) is not available."
    }

    if ($RunSmoke -and $dockerRunning) {
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
        Write-Host "Skipping backend Docker smoke test because it is disabled for this mode or no Docker daemon is running."
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
            & .\gradlew.bat test bootJar --no-daemon | Out-Host
        }
        else {
            & chmod +x ./gradlew | Out-Null
            & ./gradlew test bootJar --no-daemon | Out-Host
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

function Validate-AuthContract {
    # The auth contract is the dev-identity token route (dev only) and GET /api/me; it does not depend on any auth answer.
    param([string]$Root)

    $spec = Join-Path $Root "shared\api-contracts\openapi.yml"
    Assert-FileContains -Path $spec -Needle "/api/dev-identity/token:" -Message "The contract must define the dev-identity token route."
    Assert-FileContains -Path $spec -Needle "x-prism-dev-only: true" -Message "The token operation must carry x-prism-dev-only."
    Assert-FileContains -Path $spec -Needle "/api/me:" -Message "The contract must define GET /api/me."
    Assert-FileContains -Path $spec -Needle "bearerAuth" -Message "The contract must define bearer JWT security."
    foreach ($retired in @("/auth/register:", "/auth/login:", "/auth/refresh:", "/auth/oauth/callback:", "/auth/oauth/token:", "/transactions:", "OAuthTokenRequest", "RefreshTokenRequest")) {
        Assert-FileNotContains -Path $spec -Needle $retired -Message "The contract must not define the retired $retired of the full backend sample."
    }
}

function Validate-AuthContractWithoutAuthAnswers {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Assert-NoDeploymentArtifacts -Root $Root
    Validate-AuthContract -Root $Root
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

function Get-IosAppRoots {
    # The folders of the ios-swiftui apps of a generated workspace: each holds an answers file that names the layer.
    param([string]$Root)

    $answers = @(Get-ChildItem -LiteralPath $Root -Recurse -Depth 3 -Force -Filter ".copier-answers.yml" -File -ErrorAction SilentlyContinue)
    return @($answers | Where-Object { (Get-Content -Raw -LiteralPath $_.FullName) -match 'prism_layer:\s*ios-swiftui' } | ForEach-Object { $_.DirectoryName })
}

function Get-ClientApiPaths {
    param([string]$Root)

    $clientPaths = @()
    $sources = @()

    # Every android-compose app keeps its client at data/api/ApiService.kt under its package directories.
    $androidService = @(Get-ChildItem -LiteralPath $Root -Recurse -Filter "ApiService.kt" -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'data[\\/]api[\\/]ApiService\.kt$' })
    foreach ($file in $androidService) {
        $sources += [pscustomobject]@{ Client = "android"; File = $file.FullName; Paths = (Get-AndroidApiPaths -Content (Get-Content -Raw -LiteralPath $file.FullName)) }
    }

    $iosEndpoint = @(Get-IosAppRoots -Root $Root | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -Filter "APIEndpoint.swift" -File -ErrorAction SilentlyContinue })
    foreach ($file in $iosEndpoint) {
        $sources += [pscustomobject]@{ Client = "ios"; File = $file.FullName; Paths = (Get-IosApiPaths -Content (Get-Content -Raw -LiteralPath $file.FullName)) }
    }

    foreach ($source in $sources) {
        foreach ($path in $source.Paths) {
            $clientPaths += [pscustomobject]@{ Client = $source.Client; File = $source.File; Path = $path }
        }
    }
    return @($clientPaths)
}

# The contract defines the slice's operations (the dev-identity token and GET /api/me). The android-compose and
# ios-swiftui packs hand-write their clients, so every path of an ApiService.kt or an APIEndpoint.swift must be one the
# contract defines. The nextjs-web pack's client is generated from the contract and type-checked against it by the
# app's own generate:api and typecheck, so it is not path-matched here.

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
    if (@(Get-IosAppRoots -Root $Root).Count -gt 0) { $expectedClients += "ios" }
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
    $specPaths = @("/auth/login", "/transactions", "/transactions/{}", "/api/me", "/api/dev-identity/token")

    $plantedAndroid = '@GET("examples/{id}") suspend fun getExample(@Path("id") id: String): ExampleResponse'
    $plantedIos = 'static func listExamples() -> APIEndpoint { APIEndpoint(path: "/examples?page=\(page)", method: .get, requiresAuth: true) }'

    $cases = @(
        @{ Client = "android"; Paths = (Get-AndroidApiPaths -Content $plantedAndroid) },
        @{ Client = "ios"; Paths = (Get-IosApiPaths -Content $plantedIos) }
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

    # The web apps are the nextjs-web pack: two apps of one stack, each an app layer with its own answers,
    # workflow, Cursor rule, port, package name and session cookie.
    $webApps = @(
        @{ Id = "web"; Port = 3000; Name = "Web App"; Audience = "B2C" },
        @{ Id = "admin"; Port = 3001; Name = "Admin App"; Audience = "internal" }
    )
    foreach ($webApp in $webApps) {
        $app = $webApp.Id
        Assert-PathExists -Path (Join-Path $Root $app) -Message "Web sample should generate the $app app."
        Assert-FileContains -Path (Join-Path $Root "$app\CLAUDE.md") -Needle "@AGENTS.md" -Message "$app/CLAUDE.md must import AGENTS.md."
        Assert-FileContains -Path (Join-Path $Root "$app\AGENTS.md") -Needle "knowledge/wiki/app-requirements/[feature-id]-$app" -Message "$app/AGENTS.md missing the wiki app-requirements reference."
        Assert-FileContains -Path (Join-Path $Root "$app\AGENTS.md") -Needle "advisory-review" -Message "$app/AGENTS.md missing advisory-review check."
        Assert-FileContains -Path (Join-Path $Root "$app\.copier-answers.yml") -Needle "prism_layer: nextjs-web" -Message "$app must record its own pack answers."
        Assert-FileContains -Path (Join-Path $Root "$app\.copier-answers.yml") -Needle "port: $($webApp.Port)" -Message "$app must hold port $($webApp.Port)."
        Assert-PathExists -Path (Join-Path $Root ".github\workflows\$app.yml") -Message "The nextjs-web pack must generate the $app workflow."
        Assert-PathExists -Path (Join-Path $Root ".cursor\rules\$app.mdc") -Message "The nextjs-web pack must generate the $app Cursor rule."
        foreach ($step in @("run: npm ci", "run: npm run lint", "run: npm run typecheck", "run: npm test", "run: npm run build")) {
            Assert-FileContains -Path (Join-Path $Root ".github\workflows\$app.yml") -Needle $step -Message "The $app workflow should run '$step'."
        }
        Assert-FileContains -Path (Join-Path $Root "$app\package.json") -Needle "`"name`": `"review-web-$app`"" -Message "$app must have its own package name."
        Assert-FileContains -Path (Join-Path $Root "$app\package.json") -Needle "--port $($webApp.Port)" -Message "$app must run on port $($webApp.Port)."
        Assert-FileContains -Path (Join-Path $Root "$app\package-lock.json") -Needle "`"name`": `"review-web-$app`"" -Message "$app must commit a lockfile of its own package."
        Assert-FileContains -Path (Join-Path $Root "$app\lib\app-info.ts") -Needle $webApp.Audience -Message "$app must show its audience as display text."
        Assert-FileContains -Path (Join-Path $Root "$app\app\sign-in\page.tsx") -Needle "Local development sign-in" -Message "$app must label its sign-in as the local development sign-in."
        Assert-FileContains -Path (Join-Path $Root "$app\lib\auth\session.ts") -Needle "`"${app}_session`"" -Message "$app must have its own session cookie name."
        Assert-FileContains -Path (Join-Path $Root "$app\lib\api\client.ts") -Needle "/api/dev-identity/token" -Message "$app must sign in through the dev identity."
        Assert-PathExists -Path (Join-Path $Root "$app\tests\session-route.test.ts") -Message "$app must generate the sign-in route handler test."
        Assert-PathMissing -Path (Join-Path $Root "$app\middleware.ts") -Message "$app must not carry the retired NextAuth middleware."
        Assert-PathMissing -Path (Join-Path $Root "$app\auth.ts") -Message "$app must not carry the retired NextAuth configuration."
    }

    # No page generator and no NextAuth.
    Assert-PathMissing -Path (Join-Path $Root "_templates\page") -Message "Page generators of the retired web samples must not be generated."
    Assert-FileNotContains -Path (Join-Path $Root "web\package.json") -Needle "next-auth" -Message "The web app must not depend on NextAuth."
    Assert-NoDeploymentArtifacts -Root $Root
    Assert-DeploymentSkill -Root $Root -Backend $true -Web $true

    Assert-PathMissing -Path (Join-Path $Root "docs\advisory-board.md") -Message "Generated project must not contain legacy docs/advisory-board.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\auth.md") -Message "Generated project must not contain legacy docs/features/auth.md."
    Assert-PathMissing -Path (Join-Path $Root "docs\features\example-feature.md") -Message "Generated project must not contain legacy docs/features/example-feature.md."
    Assert-TreeNotContains -Root $Root -Needle "JWT_EXPIRATION_MS" -Message "Generated web sample should not contain stale JWT_EXPIRATION_MS wiring."

    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if ($RunSmoke -and $null -ne $npmCommand) {
        foreach ($webApp in $webApps) {
            Push-Location (Join-Path $Root $webApp.Id)
            try {
                Write-Host "Running web smoke tests for $($webApp.Id)..."
                foreach ($step in @(@("ci"), @("run", "lint"), @("run", "typecheck"), @("test"), @("run", "build"))) {
                    & npm @step | Out-Host
                    if ($LASTEXITCODE -ne 0) {
                        throw "Generated $($webApp.Id) app failed 'npm $($step -join ' ')'."
                    }
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

    # The Android apps are the android-compose pack: two apps of one stack, each an app layer with its own answers,
    # workflow, Cursor rule, application ID, namespace, package directories and Gradle project name.
    $androidApps = @(
        @{ Id = "mobile-android"; Path = "mobile-android"; Segment = "mobileandroid" },
        @{ Id = "partner-android"; Path = "apps/partner"; Segment = "partnerandroid" }
    )
    $packageRoot = "com.example.reviewandroid"
    foreach ($androidApp in $androidApps) {
        $app = $androidApp.Id
        $dir = $androidApp.Path -replace "/", "\"
        $package = "$packageRoot.$($androidApp.Segment)"
        $packageDir = "com\example\reviewandroid\$($androidApp.Segment)"
        Assert-PathExists -Path (Join-Path $Root $dir) -Message "Android sample should generate the $app app at $($androidApp.Path)."
        Assert-FileContains -Path (Join-Path $Root "$dir\CLAUDE.md") -Needle "@AGENTS.md" -Message "$app/CLAUDE.md must import AGENTS.md."
        Assert-FileContains -Path (Join-Path $Root "$dir\AGENTS.md") -Needle "knowledge/wiki/app-requirements/[feature-id]-$app" -Message "$app/AGENTS.md missing the wiki app-requirements reference."
        Assert-FileContains -Path (Join-Path $Root "$dir\AGENTS.md") -Needle "advisory-review" -Message "$app/AGENTS.md missing advisory-review check."
        Assert-FileContains -Path (Join-Path $Root "$dir\AGENTS.md") -Needle "adb reverse" -Message "$app/AGENTS.md must explain how the app reaches the local backend."
        Assert-FileContains -Path (Join-Path $Root "$dir\.copier-answers.yml") -Needle "prism_layer: android-compose" -Message "$app must record its own pack answers."
        Assert-FileContains -Path (Join-Path $Root "$dir\.copier-answers.yml") -Needle "app_package: $package" -Message "$app must derive its application ID from its app ID."
        Assert-PathExists -Path (Join-Path $Root ".github\workflows\$app.yml") -Message "The android-compose pack must generate the $app workflow."
        Assert-PathExists -Path (Join-Path $Root ".cursor\rules\$app.mdc") -Message "The android-compose pack must generate the $app Cursor rule."
        Assert-FileContains -Path (Join-Path $Root ".github\workflows\$app.yml") -Needle "run: ./gradlew assembleDebug testDebugUnitTest" -Message "The $app workflow should build the debug APK and run the unit tests."
        Assert-FileContains -Path (Join-Path $Root ".github\workflows\$app.yml") -Needle "working-directory: $($androidApp.Path)" -Message "The $app workflow should run in the app's folder."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\build.gradle.kts") -Needle "namespace = `"$package`"" -Message "$app must have its own namespace."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\build.gradle.kts") -Needle "applicationId = `"$package`"" -Message "$app must have its own application ID."
        Assert-FileContains -Path (Join-Path $Root "$dir\settings.gradle.kts") -Needle "rootProject.name = `"$app`"" -Message "$app must have its own Gradle project name."
        Assert-FileContains -Path (Join-Path $Root "$dir\gradle.properties") -Needle "apiBaseUrl=http://localhost:8080/" -Message "$app must call the backend at localhost, which adb reverse reaches."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\src\main\res\values\strings.xml") -Needle "Local development sign-in" -Message "$app must label its sign-in as the local development sign-in."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\src\main\kotlin\$packageDir\data\api\ApiService.kt") -Needle "api/dev-identity/token" -Message "$app must sign in through the dev identity."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\src\main\kotlin\$packageDir\data\api\ApiService.kt") -Needle "api/me" -Message "$app must read GET /api/me."
        Assert-FileContains -Path (Join-Path $Root "$dir\app\src\test\kotlin\$packageDir\ui\signin\SignInScreenTest.kt") -Needle "Local development sign-in" -Message "$app must test that its sign-in carries the local development label."
        foreach ($test in @("ui\signin\SignInViewModelTest.kt", "ui\profile\ProfileViewModelTest.kt", "data\api\RetrofitApiClientTest.kt", "data\api\ApiContractTest.kt")) {
            Assert-PathExists -Path (Join-Path $Root "$dir\app\src\test\kotlin\$packageDir\$test") -Message "$app must generate $test."
        }
        # The debug network policy allows localhost only: the dev identity answers loopback requests only.
        Assert-FileContains -Path (Join-Path $Root "$dir\app\src\debug\res\xml\network_security_config.xml") -Needle ">localhost<" -Message "$app debug builds must allow cleartext to localhost."
        Assert-FileNotContains -Path (Join-Path $Root "$dir\app\src\debug\res\xml\network_security_config.xml") -Needle ">10.0.2.2<" -Message "$app must not allow cleartext to the emulator's host alias."
        Assert-FileNotContains -Path (Join-Path $Root "$dir\app\src\main\AndroidManifest.xml") -Needle "networkSecurityConfig" -Message "$app release builds must stay HTTPS-only."
        # The retired full sample is gone: no Hilt, Room, DataStore, OAuth credentials or Fastlane.
        foreach ($retired in @("hilt", "room", "datastore", "credentials")) {
            Assert-FileNotContains -Path (Join-Path $Root "$dir\gradle\libs.versions.toml") -Needle $retired -Message "$app must not depend on $retired of the retired sample."
        }
        Assert-PathMissing -Path (Join-Path $Root "$dir\fastlane") -Message "$app must not carry the retired Fastlane files."
        Assert-PathMissing -Path (Join-Path $Root "$dir\local.config.properties") -Message "$app must not carry the retired local config file."
        Assert-PathMissing -Path (Join-Path $Root "$dir\app\src\main\kotlin\$packageDir\feature") -Message "$app must not carry the retired example features."
    }

    # Two apps of one stack differ in their identifiers and nothing else.
    Assert-FileContains -Path (Join-Path $Root "Taskfile.yml") -Needle "taskfile: ./apps/partner/Taskfile.yml" -Message "The root Taskfile must include the second Android app."
    Assert-FileContains -Path (Join-Path $Root "Taskfile.yml") -Needle "taskfile: ./mobile-android/Taskfile.yml" -Message "The root Taskfile must include the first Android app."

    # AGENTS.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-ios/" -Message "Android-only AGENTS.md should not reference mobile-ios/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "-> Next.js" -Message "Android-only AGENTS.md should not describe a web app."

    # No full-sample leftovers in the workspace layer.
    Assert-PathMissing -Path (Join-Path $Root "_templates\screen\new\android-screen.kt.ejs.t") -Message "Android hygen templates of the retired sample must not be generated."
    Assert-FileNotContains -Path (Join-Path $Root ".gitignore") -Needle "mobile-android/" -Message "The workspace .gitignore must not carry the retired sample's Android paths."
    Assert-NoDeploymentArtifacts -Root $Root
    Assert-DeploymentSkill -Root $Root -Backend $true -Web $false
    Assert-PathExists -Path (Join-Path $Root ".claude\skills\deployment\references\mobile-store-release.md") -Message "Android sample should carry the mobile store release notes in the deployment skill."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Android sample should still include backend Gradle wrapper files."
}

function Validate-IosSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root
    Assert-ClientPathsInOpenApi -Root $Root

    # AGENTS.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "mobile-android/" -Message "iOS-only AGENTS.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "-> Next.js" -Message "iOS-only AGENTS.md should not describe a web app."

    Assert-NoDeploymentArtifacts -Root $Root
    Assert-DeploymentSkill -Root $Root -Backend $true -Web $false

    # The iOS apps are the ios-swiftui pack: two apps of one stack, each an app layer with its own answers, workflow, Cursor
    # rule, module, target, scheme, Xcode project name and bundle identifier.
    $iosApps = @(
        @{ Id = "mobile-ios"; Path = "mobile-ios"; Module = "MobileIos"; Audience = "customers"; BundleId = "com.example.reviewapp.mobileios" },
        @{ Id = "partner-ios"; Path = "apps/partner-ios"; Module = "PartnerIos"; Audience = "internal"; BundleId = "com.example.reviewapp.partnerios" }
    )
    foreach ($iosApp in $iosApps) {
        $app = $iosApp.Id
        $folder = Join-Path $Root $iosApp.Path
        $module = $iosApp.Module
        $workflow = Join-Path $Root ".github\workflows\$app.yml"
        $project = Join-Path $folder "project.yml"
        Assert-PathExists -Path $folder -Message "iOS sample should generate the $app app."
        Assert-FileContains -Path (Join-Path $folder "CLAUDE.md") -Needle "@AGENTS.md" -Message "$app/CLAUDE.md must import AGENTS.md."
        Assert-FileContains -Path (Join-Path $folder "AGENTS.md") -Needle "app-requirements/[feature-id]-$app" -Message "$app/AGENTS.md missing the app-requirements reference."
        Assert-FileContains -Path (Join-Path $folder "AGENTS.md") -Needle "advisory-review" -Message "$app/AGENTS.md missing advisory-review check."
        Assert-FileContains -Path (Join-Path $folder "AGENTS.md") -Needle "works in the simulator only" -Message "$app/AGENTS.md must state that the dev identity works in the simulator only."
        Assert-FileContains -Path (Join-Path $folder ".copier-answers.yml") -Needle "prism_layer: ios-swiftui" -Message "$app must record its own pack answers."
        Assert-PathExists -Path $workflow -Message "The ios-swiftui pack must generate the $app workflow."
        Assert-PathExists -Path (Join-Path $Root ".cursor\rules\$app.mdc") -Message "The ios-swiftui pack must generate the $app Cursor rule."

        Assert-FileContains -Path $project -Needle "name: $module" -Message "$app project.yml should name the Xcode project after its module."
        Assert-FileContains -Path $project -Needle "  ${module}:" -Message "$app project.yml should use the module name for the app target."
        Assert-FileContains -Path $project -Needle "  ${module}Tests:" -Message "$app project.yml should use the module name for the test target."
        Assert-FileContains -Path $project -Needle "  ${module}UITests:" -Message "$app project.yml should use the module name for the UI test target."
        Assert-FileContains -Path $project -Needle "PRODUCT_BUNDLE_IDENTIFIER: $($iosApp.BundleId)" -Message "$app must have its own bundle identifier."
        Assert-FileContains -Path $project -Needle 'API_BASE_URL: "http://localhost:8080"' -Message "$app Debug must call the local backend."
        Assert-FileContains -Path $project -Needle 'SWIFT_VERSION: "6.0"' -Message "$app must build in the Swift 6 language mode."
        Assert-FileContains -Path (Join-Path $folder "Sources\Info.plist") -Needle "<string>$($iosApp.Audience)</string>" -Message "$app must carry its audience as display text."
        Assert-FileContains -Path (Join-Path $folder "Sources\App.swift") -Needle "struct ${module}App: App" -Message "App.swift should use an iOS-safe app type name."
        Assert-FileContains -Path (Join-Path $folder "Tests\SignInViewModelTests.swift") -Needle "@testable import $module" -Message "iOS tests should import the module of the app."
        Assert-FileContains -Path (Join-Path $folder "Tests\ProfileViewModelTests.swift") -Needle "@testable import $module" -Message "iOS tests should import the module of the app."
        Assert-FileContains -Path (Join-Path $folder "Taskfile.yml") -Needle "-scheme $module " -Message "iOS Taskfile should use the scheme of its app."
        Assert-FileContains -Path (Join-Path $folder "fastlane\Fastfile") -Needle "project: `"$module.xcodeproj`"" -Message "Fastlane should use the generated Xcode project name."
        Assert-FileContains -Path (Join-Path $folder "fastlane\Fastfile") -Needle "scheme: `"$module`"" -Message "Fastlane should use the scheme of its app."

        # The slice: the sign-in is the local development sign-in, the client calls the two contract operations, the token is never logged.
        Assert-FileContains -Path (Join-Path $folder "Sources\SignIn\SignInView.swift") -Needle "Local development sign-in" -Message "$app must label its sign-in as the local development sign-in."
        Assert-FileContains -Path (Join-Path $folder "Sources\Networking\APIEndpoint.swift") -Needle '"/api/dev-identity/token"' -Message "$app must sign in through the dev identity."
        Assert-FileContains -Path (Join-Path $folder "Sources\Networking\APIEndpoint.swift") -Needle '"/api/me"' -Message "$app must read GET /api/me."
        Assert-PathExists -Path (Join-Path $folder "Tests\SignInViewModelTests.swift") -Message "$app must generate the sign-in view model tests."
        Assert-PathExists -Path (Join-Path $folder "Tests\ProfileViewModelTests.swift") -Message "$app must generate the profile view model tests."
        Assert-PathExists -Path (Join-Path $folder "UITests\SignInUITests.swift") -Message "$app must generate the sign-in UI test."
        Assert-FileContains -Path (Join-Path $folder "UITests\SignInUITests.swift") -Needle "TimeInterval = 30" -Message "$app UI tests must allow 30 seconds per screen."
        Assert-FileContains -Path (Join-Path $folder "UITests\SignInUITests.swift") -Needle "hittable == true" -Message "$app UI tests must wait until an element is hittable."
        foreach ($swift in @(Get-ChildItem -LiteralPath (Join-Path $folder "Sources") -Recurse -Filter "*.swift" -File)) {
            $swiftText = Get-Content -Raw -LiteralPath $swift.FullName
            if ($swiftText -match '\b(print|NSLog|os_log|debugPrint)\(') {
                throw "$app must not log: $($swift.FullName)."
            }
        }
        Assert-PathMissing -Path (Join-Path $folder "Config") -Message "$app must not carry the retired xcconfig files."
        Assert-PathMissing -Path (Join-Path $folder "Sources\DI") -Message "$app must not carry the retired dependency container."
        Assert-PathMissing -Path (Join-Path $folder "Sources\Data") -Message "$app must not carry the retired data layer."

        # CI: generate with XcodeGen, build for a simulator and run the tests on macOS.
        $workingDirectory = $iosApp.Path.Replace("\", "/")
        Assert-FileContains -Path $workflow -Needle "runs-on: macos-latest" -Message "The $app workflow must run on macOS."
        Assert-FileContains -Path $workflow -Needle "run: xcodegen generate" -Message "The $app workflow must generate the Xcode project."
        Assert-FileContains -Path $workflow -Needle "xcodebuild build" -Message "The $app workflow must build for a simulator."
        Assert-FileContains -Path $workflow -Needle "xcodebuild test" -Message "The $app workflow must run the tests."
        Assert-FileContains -Path $workflow -Needle "-project `"$module.xcodeproj`"" -Message "The $app workflow should name the Xcode project of its app."
        Assert-FileContains -Path $workflow -Needle "-scheme `"$module`"" -Message "The $app workflow should use the scheme of its app."
        Assert-FileContains -Path $workflow -Needle "working-directory: $workingDirectory" -Message "The $app workflow should work in its app folder."
        Assert-FileNotContains -Path $workflow -Needle "xcpretty" -Message "The $app workflow must not pipe through xcpretty, which the runner lacks."

        Assert-FileContains -Path (Join-Path $Root "Taskfile.yml") -Needle "taskfile: ./$workingDirectory/Taskfile.yml" -Message "The workspace Taskfile must include the $app Taskfile."
        Assert-FileContains -Path (Join-Path $Root "AGENTS.md") -Needle "task ${app}:build" -Message "The workspace AGENTS.md must list the $app build command."
        Assert-FileContains -Path (Join-Path $Root "docs\deployment\ci-cd.md") -Needle "``$app.yml``" -Message "The CI/CD guide must list the $app workflow."
    }

    # No retired sample files, and no iOS rules in the workspace .gitignore (each app ignores its own output).
    Assert-PathMissing -Path (Join-Path $Root "mobile-ios\review-app") -Message "The retired full iOS sample must not be generated."
    Assert-FileNotContains -Path (Join-Path $Root ".gitignore") -Needle "xcodeproj" -Message "The workspace .gitignore must not carry the iOS rules of the retired sample."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\.gitignore") -Needle "*.xcodeproj/" -Message "An iOS app must ignore its generated Xcode project."
    Assert-FileNotContains -Path (Join-Path $Root "Taskfile.yml") -Needle "generate-client-mobile-ios" -Message "The workspace Taskfile must not generate an unused Swift client."
}

Remove-TreeIfExists -Path $OutputRoot
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

$AllAuthMethods = @("google", "apple", "facebook", "microsoft", "password")

switch ($Mode) {
    "backend-smoke" {
        $backendRoot = New-GeneratedProject -Name "backend" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods $AllAuthMethods
        Validate-BackendOnly -Root $backendRoot -RunSmoke $true

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods @("password")
        Validate-AuthContractWithoutAuthAnswers -Root $passwordOnlyRoot
    }
    "contract" {
        Assert-ClientPathGuardRejectsUnknownPaths

        $backendRoot = New-GeneratedProject -Name "backend" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods $AllAuthMethods
        Validate-BackendOnly -Root $backendRoot -RunSmoke $false

        $presetRoot = New-GeneratedProject -Name "backend-preset" -ProjectName "Review Backend" -Preset "backend-only"
        Assert-NoCopierPlaceholders -Root $presetRoot
        Assert-PathExists -Path (Join-Path $presetRoot "backend\.copier-answers.yml") -Message "The backend-only preset must scaffold the backend pack."

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods @("password")
        Validate-AuthContractWithoutAuthAnswers -Root $passwordOnlyRoot

        $webRoot = New-GeneratedProject -Name "web" -ProjectName "Review Web" -Apps @("backend", "web", "admin")
        Validate-WebSample -Root $webRoot -RunSmoke $false

        $androidRoot = New-GeneratedProject -Name "android" -ProjectName "Review Android" -Apps @("backend", "mobile-android", "partner-android")
        Validate-AndroidSample -Root $androidRoot

        $iosRoot = New-GeneratedProject -Name "ios" -ProjectName "Review App" -Apps @("backend", "mobile-ios", "partner-ios")
        Validate-IosSample -Root $iosRoot

        $standaloneRoot = New-GeneratedProject -Name "standalone-web" -ProjectName "Standalone Web" -Apps @("web", "admin") -AuthMethods @("password")
        Validate-WikiStructure -Root $standaloneRoot
        Assert-NoDeploymentArtifacts -Root $standaloneRoot
        Assert-DeploymentSkill -Root $standaloneRoot -Backend $false -Web $true
        foreach ($excluded in @("backend", "infra", "docker-compose.yml", ".github/workflows/backend.yml", ".cursor/rules/backend.mdc")) {
            Assert-PathMissing -Path (Join-Path $standaloneRoot $excluded) -Message "No-backend selection must omit $excluded."
        }
    }
    "full" {
        Assert-ClientPathGuardRejectsUnknownPaths

        $backendRoot = New-GeneratedProject -Name "backend" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods $AllAuthMethods
        Validate-BackendOnly -Root $backendRoot -RunSmoke $true

        $passwordOnlyRoot = New-GeneratedProject -Name "backend-password-only" -ProjectName "Review Backend" -Apps @("backend") -AuthMethods @("password")
        Validate-AuthContractWithoutAuthAnswers -Root $passwordOnlyRoot

        $webRoot = New-GeneratedProject -Name "web" -ProjectName "Review Web" -Apps @("backend", "web", "admin")
        Validate-WebSample -Root $webRoot -RunSmoke $false

        $androidRoot = New-GeneratedProject -Name "android" -ProjectName "Review Android" -Apps @("backend", "mobile-android", "partner-android")
        Validate-AndroidSample -Root $androidRoot

        $iosRoot = New-GeneratedProject -Name "ios" -ProjectName "Review App" -Apps @("backend", "mobile-ios", "partner-ios")
        Validate-IosSample -Root $iosRoot
    }
}

Write-Host ""
Write-Host "Template validation passed."

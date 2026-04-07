param(
    [string]$OutputRoot = (Join-Path $env:TEMP "template-validation")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }

    $arguments = @("copy", "--trust", "--defaults")
    foreach ($dataArg in $DataArgs) {
        $arguments += "--data"
        $arguments += $dataArg
    }
    $arguments += "."
    $arguments += $target

    Push-Location $repoRoot
    try {
        Write-Host "Generating sample: $Name"
        & copier @arguments | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Copier generation failed for $Name."
        }
    }
    finally {
        Pop-Location
    }

    return $target
}

function Validate-WikiStructure {
    param([string]$Root)

    # Knowledge wiki directories
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Message "Generated project missing knowledge/wiki/SCHEMA.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\index.md") -Message "Generated project missing knowledge/wiki/index.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\log.md") -Message "Generated project missing knowledge/wiki/log.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\advisory\BOARD.md") -Message "Generated project missing knowledge/wiki/advisory/BOARD.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\features\_FORMAT.md") -Message "Generated project missing knowledge/wiki/features/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\personas\_FORMAT.md") -Message "Generated project missing knowledge/wiki/personas/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\design\_FORMAT.md") -Message "Generated project missing knowledge/wiki/design/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\platform-requirements\_FORMAT.md") -Message "Generated project missing knowledge/wiki/platform-requirements/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\api-contracts\_FORMAT.md") -Message "Generated project missing knowledge/wiki/api-contracts/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\decisions\_FORMAT.md") -Message "Generated project missing knowledge/wiki/decisions/_FORMAT.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\advisory\_FORMAT.md") -Message "Generated project missing knowledge/wiki/advisory/_FORMAT.md."

    # Intake structure
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\README.md") -Message "Generated project missing knowledge/intake/README.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\pending\PO_BRIEF_TEMPLATE.md") -Message "Generated project missing intake/pending/PO_BRIEF_TEMPLATE.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\pending\DESIGN_HANDOFF_TEMPLATE.md") -Message "Generated project missing intake/pending/DESIGN_HANDOFF_TEMPLATE.md."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\processed\.gitkeep") -Message "Generated project missing intake/processed/.gitkeep."
    Assert-PathExists -Path (Join-Path $Root "knowledge\intake\quarantined\.gitkeep") -Message "Generated project missing intake/quarantined/.gitkeep."

    # CONTEXT.md rendered (no .jinja suffix)
    Assert-PathExists -Path (Join-Path $Root "CONTEXT.md") -Message "Generated project missing rendered CONTEXT.md."

    # All 14 Claude commands present (rendered, no .jinja suffix)
    foreach ($cmd in @("setup-project", "board-review", "po-intake", "po-clarify", "po-handoff",
                       "design-intake", "design-clarify", "design-handoff",
                       "prep-sprint", "dev-done", "feature-status", "ask", "audit-feature", "lint-wiki")) {
        Assert-PathExists -Path (Join-Path $Root ".claude\commands\$cmd.md") -Message "Generated project missing .claude/commands/$cmd.md."
    }

    # Superseded commands must not exist
    Assert-PathMissing -Path (Join-Path $Root ".claude\commands\scaffold-feature.md") -Message "scaffold-feature command should not exist in generated project."
    Assert-PathMissing -Path (Join-Path $Root ".claude\commands\document-feature.md") -Message "document-feature command should not exist in generated project."

    # Codex skills present
    foreach ($skill in @("setup-project", "board-review", "prep-sprint", "feature-status", "lint-wiki")) {
        Assert-PathExists -Path (Join-Path $Root ".agents\skills\$skill\SKILL.md") -Message "Generated project missing .agents/skills/$skill/SKILL.md."
    }

    # Superseded skill must not exist
    Assert-PathMissing -Path (Join-Path $Root ".agents\skills\scaffold-feature") -Message "scaffold-feature skill should not exist in generated project."

    # business-rules/ exists (no _FORMAT.md, only .gitkeep)
    Assert-PathExists -Path (Join-Path $Root "knowledge\wiki\business-rules\.gitkeep") -Message "Generated project missing knowledge/wiki/business-rules/.gitkeep."

    # Cursor wiki rule present
    Assert-PathExists -Path (Join-Path $Root ".cursor\rules\wiki.mdc") -Message "Generated project missing .cursor/rules/wiki.mdc."

    # docs/README.md present
    Assert-PathExists -Path (Join-Path $Root "docs\README.md") -Message "Generated project missing docs/README.md."

    # Root context files must not reference old paths
    Assert-FileNotContains -Path (Join-Path $Root "CLAUDE.md") -Needle "docs/features/" -Message "Root CLAUDE.md should not reference docs/features/."
    Assert-FileNotContains -Path (Join-Path $Root "CLAUDE.md") -Needle "docs/advisory-board.md" -Message "Root CLAUDE.md should not reference docs/advisory-board.md."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle '$scaffold-feature' -Message "Root AGENTS.md should not reference scaffold-feature."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "docs/advisory-board.md" -Message "Root AGENTS.md should not reference docs/advisory-board.md."

    # advisory-review skill must have been renamed to board-review (not present under old name)
    Assert-PathMissing -Path (Join-Path $Root ".agents\skills\advisory-review") -Message "advisory-review skill directory should not exist (it was renamed to board-review)."

    # SCHEMA.md must contain advisory-review field, four-question format, and confirm-before-committing rule
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "advisory-review" -Message "SCHEMA.md must define the advisory-review field."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## 1. Conflicts" -Message "SCHEMA.md must include the four-question pre-dev review format (section 1)."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "## 4. Biggest risk" -Message "SCHEMA.md must include the four-question pre-dev review format (section 4)."
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\SCHEMA.md") -Needle "Confirm before committing" -Message "SCHEMA.md must include the confirm-before-committing operational rule."

    # BOARD.md placeholder must contain setup-project instruction
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\advisory\BOARD.md") -Needle "setup-project" -Message "advisory/BOARD.md placeholder must reference setup-project."

    # index.md must have Board Review column
    Assert-FileContains -Path (Join-Path $Root "knowledge\wiki\index.md") -Needle "Board Review" -Message "wiki/index.md must include a Board Review column."

    # CONTEXT.md must render with setup instructions for all three tools and no unrendered Jinja2
    Assert-FileContains -Path (Join-Path $Root "CONTEXT.md") -Needle "setup-project" -Message "Rendered CONTEXT.md must reference setup-project."
    Assert-FileContains -Path (Join-Path $Root "CONTEXT.md") -Needle "Claude Code" -Message "Rendered CONTEXT.md must include Claude Code setup instruction."
    Assert-FileContains -Path (Join-Path $Root "CONTEXT.md") -Needle "Codex" -Message "Rendered CONTEXT.md must include Codex setup instruction."

    # Cursor project rule must reference knowledge/wiki, not old docs paths
    Assert-FileContains -Path (Join-Path $Root ".cursor\rules\project.mdc") -Needle "knowledge/wiki" -Message "Cursor project rule must reference knowledge/wiki."
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
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root

    # backend CLAUDE.md and AGENTS.md must have wiki section with platform-specific path
    Assert-FileContains -Path (Join-Path $Root "backend\CLAUDE.md") -Needle "platform-requirements/[feature-id]-backend" -Message "backend/CLAUDE.md missing backend platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "backend\CLAUDE.md") -Needle "advisory-review" -Message "backend/CLAUDE.md missing advisory-review check."
    Assert-FileContains -Path (Join-Path $Root "backend\AGENTS.md") -Needle "platform-requirements/[feature-id]-backend" -Message "backend/AGENTS.md missing backend platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "backend\AGENTS.md") -Needle "advisory-review" -Message "backend/AGENTS.md missing advisory-review check."

    # CONTEXT.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-android/" -Message "Backend-only CONTEXT.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-ios/" -Message "Backend-only CONTEXT.md should not reference mobile-ios/."
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "web-user-app/" -Message "Backend-only CONTEXT.md should not reference web-user-app/."

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
    Assert-FileContains -Path (Join-Path $Root "backend\docs\entities\user.md") -Needle "google, apple, facebook, microsoft, password" -Message "User entity doc should reflect selected auth providers."
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
    if ($null -ne $javaCommand) {
        Push-Location (Join-Path $Root "backend")
        try {
            Write-Host "Running backend Gradle packaging smoke test..."
            & .\gradlew.bat bootJar --no-daemon -x test | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Generated backend sample failed 'gradlew.bat bootJar --no-daemon -x test'."
            }
            Assert-PathExists -Path (Join-Path $Root "backend\build\libs") -Message "Generated backend sample did not produce a bootJar output directory."
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Skipping backend Gradle smoke test because Java is not available on PATH."
    }

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand) {
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
        Write-Host "Skipping backend Docker smoke test because Docker is not available on PATH."
    }
}

function Validate-WebSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root

    # web-user-app and web-admin-portal CLAUDE.md and AGENTS.md must have wiki section
    foreach ($platform in @("web-user-app", "web-admin-portal")) {
        Assert-FileContains -Path (Join-Path $Root "$platform\CLAUDE.md") -Needle "knowledge/wiki/platform-requirements" -Message "$platform/CLAUDE.md missing wiki platform-requirements reference."
        Assert-FileContains -Path (Join-Path $Root "$platform\CLAUDE.md") -Needle "advisory-review" -Message "$platform/CLAUDE.md missing advisory-review check."
        Assert-FileContains -Path (Join-Path $Root "$platform\AGENTS.md") -Needle "knowledge/wiki/platform-requirements" -Message "$platform/AGENTS.md missing wiki platform-requirements reference."
        Assert-FileContains -Path (Join-Path $Root "$platform\AGENTS.md") -Needle "advisory-review" -Message "$platform/AGENTS.md missing advisory-review check."
    }

    # CONTEXT.md must not contain platform directories for absent platforms
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-android/" -Message "Web-only CONTEXT.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-ios/" -Message "Web-only CONTEXT.md should not reference mobile-ios/."

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
    if ($null -ne $npmCommand) {
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
        Write-Host "Skipping generated web smoke tests because npm is not available on PATH."
    }
}

function Validate-AndroidSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root

    # mobile-android CLAUDE.md and AGENTS.md must have wiki section with platform-specific path
    Assert-FileContains -Path (Join-Path $Root "mobile-android\CLAUDE.md") -Needle "platform-requirements/[feature-id]-mobile-android" -Message "mobile-android/CLAUDE.md missing mobile-android platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-android\CLAUDE.md") -Needle "advisory-review" -Message "mobile-android/CLAUDE.md missing advisory-review check."
    Assert-FileContains -Path (Join-Path $Root "mobile-android\AGENTS.md") -Needle "platform-requirements/[feature-id]-mobile-android" -Message "mobile-android/AGENTS.md missing mobile-android platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-android\AGENTS.md") -Needle "advisory-review" -Message "mobile-android/AGENTS.md missing advisory-review check."

    # CONTEXT.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-ios/" -Message "Android-only CONTEXT.md should not reference mobile-ios/."
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "web-user-app/" -Message "Android-only CONTEXT.md should not reference web-user-app/."

    Assert-PathExists -Path (Join-Path $Root "mobile-android") -Message "Android sample should generate mobile-android."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Android sample should still include backend Gradle wrapper files."
}

function Validate-IosSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root
    Validate-WikiStructure -Root $Root

    # mobile-ios CLAUDE.md and AGENTS.md must have wiki section with platform-specific path
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\CLAUDE.md") -Needle "platform-requirements/[feature-id]-mobile-ios" -Message "mobile-ios/CLAUDE.md missing mobile-ios platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\CLAUDE.md") -Needle "advisory-review" -Message "mobile-ios/CLAUDE.md missing advisory-review check."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\AGENTS.md") -Needle "platform-requirements/[feature-id]-mobile-ios" -Message "mobile-ios/AGENTS.md missing mobile-ios platform-requirements reference."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\AGENTS.md") -Needle "advisory-review" -Message "mobile-ios/AGENTS.md missing advisory-review check."

    # CONTEXT.md must not contain absent platform directories
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "mobile-android/" -Message "iOS-only CONTEXT.md should not reference mobile-android/."
    Assert-FileNotContains -Path (Join-Path $Root "CONTEXT.md") -Needle "web-user-app/" -Message "iOS-only CONTEXT.md should not reference web-user-app/."

    Assert-PathExists -Path (Join-Path $Root "mobile-ios\review-app") -Message "iOS sample should keep filesystem-safe project_slug directories."
    Assert-PathExists -Path (Join-Path $Root "mobile-ios\review-appTests") -Message "iOS sample should generate a test directory."

    Assert-FileContains -Path (Join-Path $Root "mobile-ios\project.yml") -Needle "  ReviewApp:" -Message "iOS project.yml should use ios_module_name for the app target."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\project.yml") -Needle "  ReviewAppTests:" -Message "iOS project.yml should use ios_module_name for the test target."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\review-app\App.swift") -Needle "struct ReviewAppApp: App" -Message "App.swift should use an iOS-safe app type name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\review-appTests\LoginViewModelTests.swift") -Needle "@testable import ReviewApp" -Message "iOS tests should import the iOS-safe module name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\Taskfile.yml") -Needle 'default "ReviewApp"' -Message "iOS Taskfile should default to the iOS-safe scheme name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\fastlane\Fastfile") -Needle 'project: "Review App.xcodeproj"' -Message "Fastlane should use the generated Xcode project name."
    Assert-FileContains -Path (Join-Path $Root "mobile-ios\fastlane\Fastfile") -Needle 'scheme: "ReviewApp"' -Message "Fastlane should use the iOS-safe scheme name."

    Assert-FileNotContains -Path (Join-Path $Root "mobile-ios\review-app\App.swift") -Needle "Review-appApp" -Message "App.swift should not contain slug-based invalid Swift identifiers."
    Assert-FileNotContains -Path (Join-Path $Root "mobile-ios\review-appTests\LoginViewModelTests.swift") -Needle "@testable import review-app" -Message "iOS tests should not import slug-based invalid module names."
}

if (Test-Path -LiteralPath $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

$backendRoot = New-GeneratedProject -Name "backend" -DataArgs @(
    "project_name=Review Backend",
    "platforms=[backend]",
    "auth_methods=[google, apple, facebook, microsoft, password]"
)
Validate-BackendOnly -Root $backendRoot

$webRoot = New-GeneratedProject -Name "web" -DataArgs @(
    "project_name=Review Web",
    "platforms=[backend, web-user-app, web-admin-portal]"
)
Validate-WebSample -Root $webRoot

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

Write-Host ""
Write-Host "Template validation passed."

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

function Validate-BackendOnly {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root

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
    Assert-FileNotContains -Path (Join-Path $Root "backend\Taskfile.yml") -Needle "basename $(pwd)" -Message "Backend Taskfile should not use Unix-only basename."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle "COPY gradlew gradlew.bat build.gradle.kts settings.gradle.kts ./" -Message "Backend Dockerfile should still use wrapper-based builds."
    Assert-FileContains -Path (Join-Path $Root "backend\Dockerfile") -Needle "RUN sed -i 's/\r$//' gradlew && chmod +x gradlew" -Message "Backend Dockerfile should normalize gradlew for Linux builds."

    Assert-FileContains -Path (Join-Path $Root "shared\api-contracts\openapi.yml") -Needle "/auth/oauth/callback:" -Message "Backend-only sample should generate the OAuth callback path when Google and Apple are selected."
    Assert-FileContains -Path (Join-Path $Root "backend\docs\entities\user.md") -Needle "google, apple, facebook, microsoft, password" -Message "User entity doc should reflect selected auth providers."
    Assert-FileNotContains -Path (Join-Path $Root "AGENTS.md") -Needle "Implement backend -> web-user-app -> web-admin-portal -> Android -> iOS as applicable" -Message "Root AGENTS guidance should not assume absent platform slices."
    Assert-FileNotContains -Path (Join-Path $Root "docs\features\auth.md") -Needle "### User Web App" -Message "Backend-only auth doc should not describe absent web slices."
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

    Assert-PathExists -Path (Join-Path $Root "web-user-app") -Message "Web sample should generate web-user-app."
    Assert-PathExists -Path (Join-Path $Root "web-admin-portal") -Message "Web sample should generate web-admin-portal."
    Assert-PathExists -Path (Join-Path $Root ".github\workflows\web-user-app.yml") -Message "Web sample should generate the user web workflow."
    Assert-PathExists -Path (Join-Path $Root ".github\workflows\web-admin-portal.yml") -Message "Web sample should generate the admin web workflow."
    Assert-PathExists -Path (Join-Path $Root "docs\deployment\cloudflare-setup.md") -Message "Web sample should generate Cloudflare docs."
    Assert-PathExists -Path (Join-Path $Root "_templates\page") -Message "Web sample should include page generators."

    Assert-FileContains -Path (Join-Path $Root "docs\features\auth.md") -Needle "### User Web App" -Message "Web sample auth doc should include user web guidance."
    Assert-FileContains -Path (Join-Path $Root "docs\features\auth.md") -Needle "### Admin Web Portal" -Message "Web sample auth doc should include admin web guidance."
    Assert-TreeNotContains -Root $Root -Needle "JWT_EXPIRATION_MS" -Message "Generated web sample should not contain stale JWT_EXPIRATION_MS wiring."
}

function Validate-AndroidSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root

    Assert-PathExists -Path (Join-Path $Root "mobile-android") -Message "Android sample should generate mobile-android."
    Assert-PathExists -Path (Join-Path $Root "backend\gradlew") -Message "Android sample should still include backend Gradle wrapper files."
}

function Validate-IosSample {
    param([string]$Root)

    Assert-NoCopierPlaceholders -Root $Root

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

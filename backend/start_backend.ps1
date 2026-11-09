$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $name = $Matches[1]
            $value = $Matches[2]
            if ($value.Length -ge 2 -and
                (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                 ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

if ([string]::IsNullOrWhiteSpace($env:GROQ_API_KEY)) {
    throw "GROQ_API_KEY is empty. Create a key in GroqCloud, paste it after GROQ_API_KEY= in backend\.env, save, and run this script again."
}

Write-Host "Starting the backend on http://localhost:8000 ..."
try {
    python -m uvicorn app:app --port 8000
    if ($LASTEXITCODE -ne 0) {
        throw "Backend exited with code $LASTEXITCODE."
    }
} finally {
    Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
}

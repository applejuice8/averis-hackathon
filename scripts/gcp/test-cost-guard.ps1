# Offline deployment test. Every gcloud call goes to the temporary fake below.
$ErrorActionPreference = 'Stop'
$temp = Join-Path ([IO.Path]::GetTempPath()) ("sdoc-guard-test-" + [Guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $temp)
$fake = Join-Path $temp 'fake-gcloud.ps1'
$log = Join-Path $temp 'calls.jsonl'
$env:SDOC_GUARD_TEST_LOG = $log
$fixture = @'
$global:LASTEXITCODE = 0
$items = @($args | ForEach-Object { [string]$_ })
if ('--project=averis-email-system' -notin $items) { throw 'Missing explicit project' }
Add-Content -LiteralPath $env:SDOC_GUARD_TEST_LOG -Value (ConvertTo-Json -InputObject $items -Compress)
$command = ($items | Select-Object -First 3) -join ' '
$budget = @{
  name='billingAccounts/015CE1-381F1A-582702/budgets/test-budget'; displayName='sdoc-verifier-killswitch'
  budgetFilter=@{ projects=@('projects/969206696114'); calendarPeriod='MONTH'; creditTypesTreatment='INCLUDE_ALL_CREDITS' }
  amount=@{ specifiedAmount=@{ units='20'; nanos=0; currencyCode='MYR' } }
  notificationsRule=@{ pubsubTopic='projects/averis-email-system/topics/sdoc-budget-alerts' }
}
$function = @{
  name='projects/averis-email-system/locations/asia-southeast1/functions/sdoc-billing-killswitch'
  updateTime='2026-09-20T01:00:00Z'
  serviceConfig=@{
    service='projects/averis-email-system/locations/asia-southeast1/services/sdoc-billing-killswitch'
    environmentVariables=@{ DRY_RUN='true'; EXPECTED_BUDGET_ID='test-budget'; COST_LIMIT='20.00'
      TARGET_PROJECT_ID='averis-email-system'; EXPECTED_BILLING_ACCOUNT='015CE1-381F1A-582702'; BUDGET_CURRENCY='MYR' }
  }
}
if ($env:SDOC_GUARD_TEST_ARMED -eq 'true') { $function.serviceConfig.environmentVariables.DRY_RUN='false' }
switch -Wildcard ($command) {
  'projects describe *' { @{projectNumber='969206696114'} | ConvertTo-Json; break }
  'billing projects describe' {
    @{billingEnabled=($env:SDOC_GUARD_TEST_MODE -ne 'disabled'); billingAccountName='billingAccounts/015CE1-381F1A-582702'} | ConvertTo-Json
    break
  }
  'billing accounts describe' { @{currencyCode='MYR'} | ConvertTo-Json; break }
  'billing budgets list' {
    if ($env:SDOC_GUARD_TEST_MODE -in @('arm-ready','arm-no-proof')) { ConvertTo-Json -InputObject @($budget) -Depth 8 }
    else { '[]' }
    break
  }
  'billing budgets create' { $budget | ConvertTo-Json -Depth 8; break }
  'pubsub topics list' { '[]'; break }
  'functions list *' {
    if ($env:SDOC_GUARD_TEST_MODE -in @('arm-ready','arm-no-proof')) { ConvertTo-Json -InputObject @($function) -Depth 8 }
    else { '[]' }
    break
  }
  'logging read *' {
    if ($env:SDOC_GUARD_TEST_MODE -eq 'arm-ready') {
      '[{"timestamp":"2026-09-20T01:01:00Z","jsonPayload":{"budget_id":"test-budget","limit":"20.00","project":"averis-email-system","dry_run":true}}]'
    } else { '[]' }
    break
  }
  'functions deploy *' {
    if ('--trigger-topic=sdoc-budget-alerts' -notin $items) { throw 'functions deploy requires a topic ID, not a resource path' }
    if (($items -join ' ') -match 'DRY_RUN=false') { $env:SDOC_GUARD_TEST_ARMED='true' }
    '{}'; break
  }
  'iam service-accounts list' { '[]'; break }
  'iam roles list' { '[]'; break }
  'functions describe *' { $function | ConvertTo-Json -Depth 8; break }
  'pubsub topics publish' {
    $flagPath = ($items | Where-Object { $_.StartsWith('--flags-file=') }).Substring(13)
    $flags = Get-Content -LiteralPath $flagPath -Raw | ConvertFrom-Json
    $body = $flags.'--message' | ConvertFrom-Json
    if ($body.costAmount -ne 20 -or $body.currencyCode -ne 'MYR') { throw 'Invalid dry-run payload' }
    if ($flags.'--attribute' -notmatch 'budgetId=test-budget') { throw 'Missing budget identity' }
    '{}'
    break
  }
  default { '{}' }
}
'@
try {
    [IO.File]::WriteAllText($fake, $fixture, [Text.UTF8Encoding]::new($false))
    $deploy = Join-Path $PSScriptRoot 'deploy-cost-guard.ps1'
    $env:SDOC_GUARD_TEST_MODE = 'normal'
    & $deploy -Limit 20 -Currency MYR -GcloudPath $fake 6>$null | Out-Null
    $calls = Get-Content -LiteralPath $log -Raw
    if ($calls -notmatch 'DRY_RUN=true' -or $calls -match 'DRY_RUN=false') { throw 'Dry-run setup could arm billing' }
    if ($calls -notmatch '--notifications-rule-pubsub-topic=') { throw 'Missing supported budget topic flag' }
    if ($calls -notmatch 'deleteBillingAssignment' -or $calls -match 'roles/billing.admin') { throw 'Unexpected IAM scope' }
    if ($calls -notmatch '--retry' -or $calls -notmatch '--trigger-service-account=') { throw 'Missing reliable private trigger' }

    foreach ($mode in @('disabled', 'wrong-currency', 'arm-without-dry-run', 'arm-no-proof')) {
        [IO.File]::WriteAllText($log, '')
        $env:SDOC_GUARD_TEST_MODE = $mode
        $currency = if ($mode -eq 'wrong-currency') { 'USD' } else { 'MYR' }
        $shouldArm = $mode.StartsWith('arm-')
        $rejected = $false
        try { & $deploy -Limit 20 -Currency $currency -Arm:$shouldArm -GcloudPath $fake 6>$null | Out-Null }
        catch { $rejected = $true }
        if (-not $rejected) { throw "Unsafe setup accepted: $mode" }
        $calls = Get-Content -LiteralPath $log -Raw
        if ($calls -match 'DRY_RUN=false' -or $calls -match '"billing","projects","link"') {
            throw "Unsafe billing mutation: $mode"
        }
        if (-not $shouldArm -and $calls -match '"services","enable"') {
            throw "Preflight performed mutations: $mode"
        }
    }
    [IO.File]::WriteAllText($log, '')
    $env:SDOC_GUARD_TEST_MODE = 'arm-ready'
    & $deploy -Limit 20 -Currency MYR -Arm -GcloudPath $fake 6>$null | Out-Null
    $calls = Get-Content -LiteralPath $log -Raw
    if ($calls -notmatch 'DRY_RUN=false' -or $calls -match '"pubsub","topics","publish"') {
        throw 'Arming must use delivery evidence and never publish a synthetic threshold event.'
    }
    Write-Host 'PASS: dry-run deployment, MYR budget, private/retrying trigger, billing-disabled and currency preflights, no premature arming or relink.'
} finally {
    Remove-Item Env:SDOC_GUARD_TEST_LOG -ErrorAction SilentlyContinue
    Remove-Item Env:SDOC_GUARD_TEST_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:SDOC_GUARD_TEST_ARMED -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log }
    if (Test-Path -LiteralPath $fake) { Remove-Item -LiteralPath $fake }
    Remove-Item -LiteralPath $temp
}

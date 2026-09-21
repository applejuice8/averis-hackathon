# Run without -Arm first. A successful synthetic DRY-RUN event is required to arm.
# This script never links billing, prints credentials, or sends an armed test event.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(0.01, 1000000)]
    [decimal]$Limit,
    [ValidatePattern('^[A-Z]{3}$')]
    [string]$Currency = 'MYR',
    [switch]$Arm,
    [string]$GcloudPath = 'gcloud'
)
$ErrorActionPreference = 'Stop'
$Project = 'averis-email-system'
$ProjectNumber = '969206696114'
$Account = '015CE1-381F1A-582702'
$Region = 'asia-southeast1'
$Name = 'sdoc-billing-killswitch'
$BudgetName = 'sdoc-verifier-killswitch'
$TopicId = 'sdoc-budget-alerts'
$Topic = "projects/$Project/topics/$TopicId"
$RuntimeSA = "sdoc-killswitch@$Project.iam.gserviceaccount.com"
$TriggerSA = "sdoc-budget-trigger@$Project.iam.gserviceaccount.com"
$BuildSA = "sdoc-budget-build@$Project.iam.gserviceaccount.com"
$Amount = $Limit.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
if ($Limit -ne [decimal]$Amount) { throw 'Use a cutoff with at most two decimal places.' }
$Source = Join-Path $PSScriptRoot 'killswitch'

function Invoke-SdocGcloud {
    $result = & $GcloudPath @args "--project=$Project" --quiet
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed ($LASTEXITCODE); no automatic recovery or billing relink." }
    $result
}
function Read-SdocGcloudJson { (Invoke-SdocGcloud @args --format=json) | ConvertFrom-Json }

# Inspect the exact target. The user's default gcloud project is irrelevant.
$projectInfo = Read-SdocGcloudJson projects describe $Project
if ([string]$projectInfo.projectNumber -ne $ProjectNumber) { throw 'Project identity mismatch.' }
$billing = Read-SdocGcloudJson billing projects describe $Project
if (-not $billing.billingEnabled -or $billing.billingAccountName -ne "billingAccounts/$Account") {
    throw 'Expected billing link is absent. Recovery must be deliberate and manual; refusing to relink.'
}
$accountInfo = Read-SdocGcloudJson billing accounts describe $Account
if ($accountInfo.currencyCode -and $accountInfo.currencyCode -ne $Currency) {
    throw "Account currency is $($accountInfo.currencyCode), not $Currency. Choose a threshold in that currency."
}

$requiredServices = @('cloudbilling.googleapis.com', 'billingbudgets.googleapis.com', 'pubsub.googleapis.com',
    'cloudfunctions.googleapis.com', 'run.googleapis.com', 'cloudbuild.googleapis.com', 'artifactregistry.googleapis.com',
    'eventarc.googleapis.com', 'iam.googleapis.com', 'logging.googleapis.com', 'cloudresourcemanager.googleapis.com')
$enabledServices = @(Read-SdocGcloudJson services list --enabled)
$enabledNames = @($enabledServices | ForEach-Object { $_.config.name })
$missingServices = @($requiredServices | Where-Object { $_ -notin $enabledNames })
if ($missingServices.Count -gt 0) { Invoke-SdocGcloud services enable @missingServices }

$topics = @(Read-SdocGcloudJson pubsub topics list)
if ($Topic -notin $topics.name) { Invoke-SdocGcloud pubsub topics create $Topic }
Invoke-SdocGcloud pubsub topics add-iam-policy-binding $Topic `
    --member=serviceAccount:billing-budget-alert@system.gserviceaccount.com --role=roles/pubsub.publisher --format=none

$budgets = @(Read-SdocGcloudJson billing budgets list "--billing-account=$Account")
$budgetMatches = @($budgets | Where-Object displayName -eq $BudgetName)
if ($budgetMatches.Count -gt 1) { throw 'Duplicate kill-switch budget names; resolve explicitly first.' }
if ($budgetMatches.Count -eq 0) {
    if ($Arm) { throw 'Deploy and test dry-run mode before arming.' }
    $budget = Read-SdocGcloudJson billing budgets create "--billing-account=$Account" "--display-name=$BudgetName" `
        "--budget-amount=$Amount$Currency" "--filter-projects=projects/$ProjectNumber" `
        --calendar-period=month --credit-types-treatment=include-all-credits `
        --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0 `
        "--notifications-rule-pubsub-topic=$Topic"
} else { $budget = $budgetMatches[0] }

# Never reuse an account-wide or otherwise filtered budget, or silently change a cutoff.
$scope = $budget.budgetFilter
$budgetProjects = @($scope.projects)
$specified = $budget.amount.specifiedAmount
$notifications = if ($budget.notificationsRule) { $budget.notificationsRule } else { $budget.allUpdatesRule }
$actualAmount = [decimal]$specified.units + ([decimal]$specified.nanos / 1000000000)
if ($budgetProjects.Count -ne 1 -or $budgetProjects[0] -ne "projects/$ProjectNumber" -or
    $scope.calendarPeriod -ne 'MONTH' -or $scope.services -or $scope.subaccounts -or $scope.labels -or
    $scope.resourceAncestors -or $scope.creditTypes -or
    $scope.creditTypesTreatment -ne 'INCLUDE_ALL_CREDITS' -or
    $specified.currencyCode -ne $Currency -or $actualAmount -ne $Limit -or
    $notifications.pubsubTopic -ne $Topic) {
    throw 'Existing budget does not exactly match the requested project, month, amount, currency and topic. Inspect it explicitly.'
}
$BudgetId = $budget.name.Split('/')[-1]

$functions = @(Read-SdocGcloudJson functions list "--regions=$Region")
$existing = @($functions | Where-Object { $_.name.Split('/')[-1] -eq $Name })
if ($Arm) {
    if ($existing.Count -ne 1) { throw 'Deploy and test dry-run mode before arming.' }
    $previous = Read-SdocGcloudJson functions describe $Name --gen2 "--region=$Region"
    $envConfig = $previous.serviceConfig.environmentVariables
    if ($envConfig.DRY_RUN -ne 'true' -or $envConfig.EXPECTED_BUDGET_ID -ne $BudgetId -or
        $envConfig.COST_LIMIT -ne $Amount -or $envConfig.TARGET_PROJECT_ID -ne $Project -or
        $envConfig.EXPECTED_BILLING_ACCOUNT -ne $Account -or $envConfig.BUDGET_CURRENCY -ne $Currency) {
        throw 'Arming requires a matching dry-run deployment. Deploy without -Arm first.'
    }
    # Keep quoted timestamps/amounts out of gcloud.cmd argument parsing on Windows.
    # Validate every field locally against the retrieved log entries instead.
    $logFilter = "resource.type=cloud_run_revision AND resource.labels.service_name=$Name AND jsonPayload.event=would_disable_billing"
    $events = @(Read-SdocGcloudJson logging read $logFilter --limit=50 --freshness=1d)
    $proof = @($events | Where-Object {
        $_.jsonPayload.budget_id -eq $BudgetId -and $_.jsonPayload.limit -eq $Amount -and
        $_.jsonPayload.project -eq $Project -and $_.jsonPayload.dry_run -eq $true -and
        [DateTimeOffset]$_.timestamp -ge [DateTimeOffset]$previous.updateTime
    })
    if ($proof.Count -lt 1) { throw 'No successful above-threshold dry-run event for this deployment. Inspect logs and retry later.' }
} elseif ($existing.Count -eq 1) {
    $previous = Read-SdocGcloudJson functions describe $Name --gen2 "--region=$Region"
    if ($previous.serviceConfig.environmentVariables.DRY_RUN -eq 'false') {
        throw 'An armed guard exists. This setup command will not silently disarm it.'
    }
}

$serviceAccounts = @(Read-SdocGcloudJson iam service-accounts list)
foreach ($id in @('sdoc-killswitch', 'sdoc-budget-trigger', 'sdoc-budget-build')) {
    if ("$id@$Project.iam.gserviceaccount.com" -notin $serviceAccounts.email) {
        Invoke-SdocGcloud iam service-accounts create $id "--display-name=$id"
    }
}
$roleId = 'sdocBillingDisconnect'
$roleName = "projects/$Project/roles/$roleId"
$roles = @(Read-SdocGcloudJson iam roles list)
if ($roleName -notin $roles.name) {
    Invoke-SdocGcloud iam roles create $roleId --title='SDOC billing disconnect only' --stage=GA `
        '--permissions=resourcemanager.projects.get,resourcemanager.projects.deleteBillingAssignment'
} else {
    $role = Read-SdocGcloudJson iam roles describe $roleId
    $expectedPermissions = @('resourcemanager.projects.get', 'resourcemanager.projects.deleteBillingAssignment')
    if (@(Compare-Object $expectedPermissions @($role.includedPermissions)).Count -ne 0) {
        throw 'Existing custom role differs; inspect its permissions before deployment.'
    }
}
Invoke-SdocGcloud projects add-iam-policy-binding $Project "--member=serviceAccount:$RuntimeSA" "--role=$roleName" --format=none
Invoke-SdocGcloud projects add-iam-policy-binding $Project "--member=serviceAccount:$TriggerSA" --role=roles/eventarc.eventReceiver --format=none
Invoke-SdocGcloud projects add-iam-policy-binding $Project "--member=serviceAccount:$BuildSA" --role=roles/cloudbuild.builds.builder --format=none

$dryRun = if ($Arm) { 'false' } else { 'true' }
$armedAt = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$environment = "TARGET_PROJECT_ID=$Project,EXPECTED_BILLING_ACCOUNT=$Account,EXPECTED_BUDGET_ID=$BudgetId,BUDGET_CURRENCY=$Currency,COST_LIMIT=$Amount,DRY_RUN=$dryRun,ARMED_AT=$armedAt"
Invoke-SdocGcloud functions deploy $Name --gen2 "--region=$Region" --runtime=python313 "--source=$Source" `
    --entry-point=stop_billing "--service-account=$RuntimeSA" `
    "--build-service-account=projects/$Project/serviceAccounts/$BuildSA" `
    "--trigger-topic=$TopicId" "--trigger-service-account=$TriggerSA" `
    "--set-env-vars=$environment" --memory=256Mi --timeout=90s --concurrency=1 `
    --min-instances=0 --max-instances=1 --retry --no-allow-unauthenticated --format=none
$deployed = Read-SdocGcloudJson functions describe $Name --gen2 "--region=$Region"
$serviceName = $deployed.serviceConfig.service.Split('/')[-1]
Invoke-SdocGcloud run services add-iam-policy-binding $serviceName "--region=$Region" `
    "--member=serviceAccount:$TriggerSA" --role=roles/run.invoker --format=none
if ($deployed.serviceConfig.environmentVariables.DRY_RUN -ne $dryRun -or
    $deployed.serviceConfig.environmentVariables.EXPECTED_BUDGET_ID -ne $BudgetId) {
    throw 'Deployment configuration readback failed.'
}

if (-not $Arm) {
    # Real delivery and billing GET, but no billing PUT in dry-run mode.
    $periodStart = [DateTime]::UtcNow.ToString('yyyy-MM-01T00:00:00Z')
    $payload = @{
        costAmount = $Limit; budgetAmount = $Limit; budgetAmountType = 'SPECIFIED_AMOUNT'
        currencyCode = $Currency; costIntervalStart = $periodStart
    } | ConvertTo-Json -Compress
    # A flags file avoids JSON quote loss through gcloud.cmd / Windows PowerShell.
    $publishFlags = [IO.Path]::GetTempFileName()
    try {
        $flagsJson = @{
            '--message' = $payload
            '--attribute' = "billingAccountId=$Account,budgetId=$BudgetId,schemaVersion=1.0"
        } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($publishFlags, $flagsJson, [Text.UTF8Encoding]::new($false))
        Invoke-SdocGcloud pubsub topics publish $Topic "--flags-file=$publishFlags"
    } finally { Remove-Item -LiteralPath $publishFlags -Force }
    Write-Host 'Dry-run deployed. Allow event delivery, then inspect logs for would_disable_billing.'
    Write-Host "To arm this exact monthly cutoff: rerun with -Limit $Amount -Currency $Currency -Arm."
} else {
    Write-Host "Armed: $Project, reported monthly cost >= $Amount $Currency. Reporting lag can cause overshoot."
}
Write-Host 'This covers GCP only. Vercel, Neon and OpenRouter have independent billing controls.'

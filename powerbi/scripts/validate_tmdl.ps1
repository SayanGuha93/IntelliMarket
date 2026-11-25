param(
    [Parameter(Mandatory)]
    [string]$AssemblyDirectory
)
$ErrorActionPreference = 'Stop'
$assemblies = (Resolve-Path -LiteralPath $AssemblyDirectory).Path
foreach ($name in @('Core', 'Runtime.Core', 'Runtime.Windows', 'Tabular.Json', 'Tabular')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $assemblies "Microsoft.AnalysisServices.$name.dll")) | Out-Null
}
$definition = Join-Path $PSScriptRoot '../IntelliMarket.SemanticModel/definition'
$database = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder(
    (Resolve-Path -LiteralPath $definition).Path
)
$database.Model.Tables | Format-Table Name, @{n='Columns';e={$_.Columns.Count}}, @{n='Measures';e={$_.Measures.Count}}
$database.Model.Relationships | Format-Table Name, IsActive, FromCardinality, ToCardinality, CrossFilteringBehavior
$count = 0
foreach ($table in $database.Model.Tables) {
    $calculated = @($table.Columns | Where-Object Type -EQ Calculated)
    foreach ($item in $calculated + @($table.Measures)) {
        if ([string]::IsNullOrWhiteSpace($item.Expression) -or
            $item.Expression -match '(?m)^\s*(dataType|summarizeBy|formatString|sortByColumn|lineageTag)\s*:') {
            throw "Missing or contaminated expression for $($table.Name).$($item.Name)"
        }
        $count++
    }
}
$category = $database.Model.Tables['dim_category'].Columns['comparison_category']
if ($category.DataType -ne 'String' -or $category.SummarizeBy -ne 'None') {
    throw 'comparison_category must retain String and None metadata'
}
Write-Output "Checked $count parsed DAX expressions for TMDL metadata leakage."

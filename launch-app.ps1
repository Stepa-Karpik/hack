param(
  [int]$Port=8502,
  [string]$Adapter='models\unified-experimental-natural-v5',
  [string]$MarkHead='models\unified-experimental-mark-patches-v1',
  [string]$AssistantModel='qwen3.5:4b',
  [switch]$Cpu
)
# Онлайн-деканат: accounts, history, API keys, assistant. One PaddleOCR-VL reader (GPU per page),
# local Ollama chat model. Data lives in work\app-v1 (SQLite + files).
$ErrorActionPreference='Stop'
$project=$PSScriptRoot
$work=if ($env:DEKANAT_WORK) { $env:DEKANAT_WORK } else { (Join-Path $PSScriptRoot 'work') }
$python=Join-Path $work 'paddle-vl-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Paddle-окружение не найдено: ' + $python }
$cli=@('-m','scripts.app.server','--port',$Port,'--adapter',$Adapter,'--assistant-model',$AssistantModel,
  '--work',(Join-Path $work 'app-v1'))
if (Test-Path -LiteralPath (Join-Path $project $MarkHead)) { $cli+=@('--mark-head',$MarkHead) }
if ($Cpu) { $cli+='--cpu' }
Set-Location -LiteralPath $project
Write-Host "Онлайн-деканат: http://127.0.0.1:$Port"
& $python @cli

param(
  [int]$Port=8502,
  [string]$Adapter='models\unified-experimental-natural-v5',
  [string]$AdapterLabel='LoRA v5',
  [string]$AssistantModel='qwen3.5:4b',
  [switch]$AssistantCpu
)
# Local page: one PaddleOCR-VL model for recognition (CPU) + local Ollama chat model.
$ErrorActionPreference='Stop'
$project=$PSScriptRoot
$work=if ($env:DEKANAT_WORK) { $env:DEKANAT_WORK } else { (Join-Path $PSScriptRoot 'work') }
$python=Join-Path $work 'paddle-vl-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Paddle-окружение не найдено: ' + $python }
$cli=@('-m','scripts.unified.local_native_web','--base',(Join-Path $work 'paddle-vl-base-v1'),
  '--head','models\unified-experimental-graphic-head-fp32-v3','--adapter',$Adapter,'--adapter-label',$AdapterLabel,
  '--study-prose','--literal-layout','--literal-layout-v2','--work',(Join-Path $work 'native-local-web-assistant'),'--port',$Port,
  '--assistant-model',$AssistantModel,'--web-root','web-native','--persistent-worker','--worker-gpu')
if ($AssistantCpu) { $cli+='--assistant-cpu' }
Set-Location -LiteralPath $project
Write-Host "Онлайн-деканат: http://127.0.0.1:$Port  (ассистент: $AssistantModel через локальную Ollama)"
& $python @cli

param(
  [string]$Server='wss://dekanat.karpovprod.ru/agent/ws',
  [string]$AssistantModel='qwen3.5:4b'
)
# GPU agent for the public server: connects outbound, runs recognition on this GPU and chat in local Ollama.
# Token: work\agent-v1\agent-token (same value as /opt/online-dekanat/app-state/agent-token on the server).
$ErrorActionPreference='Stop'
$project=$PSScriptRoot
$work=if ($env:DEKANAT_WORK) { $env:DEKANAT_WORK } else { (Join-Path $PSScriptRoot 'work') }
$python=Join-Path $work 'paddle-vl-venv\Scripts\python.exe'
$token=Join-Path $work 'agent-v1\agent-token'
if (-not (Test-Path -LiteralPath $python)) { throw 'Paddle-окружение не найдено: ' + $python }
if (-not (Test-Path -LiteralPath $token)) { throw 'Нет токена агента: ' + $token }
$env:PYTHONIOENCODING='utf-8'
Set-Location -LiteralPath $project
Write-Host "GPU-агент -> $Server"
& $python -m scripts.app.agent --server $Server --token-file $token --assistant-model $AssistantModel --work (Join-Path $work 'agent-v1')

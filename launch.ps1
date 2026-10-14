param([int]$Port=8501)
$ErrorActionPreference='Stop'
$taskProject=$PSScriptRoot
$taskPython=if ($env:DEKANAT_PYTHON) { $env:DEKANAT_PYTHON } elseif (Test-Path -LiteralPath (Join-Path $taskProject 'work\venv\Scripts\python.exe')) { Join-Path $taskProject 'work\venv\Scripts\python.exe' } else { Join-Path $taskProject '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Окружение не найдено. Выполните установку по README.' }
if (-not $env:DEKANAT_CACHE) { $env:DEKANAT_CACHE=Join-Path $taskProject 'models\cache' }
if (-not $env:YOLO_CONFIG_DIR) { $env:YOLO_CONFIG_DIR=Join-Path $taskProject 'models\ultralytics-config'; New-Item -ItemType Directory -Force -Path $env:YOLO_CONFIG_DIR | Out-Null }
Set-Location -LiteralPath $taskProject
& $taskPython -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false


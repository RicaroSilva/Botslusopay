@echo off
rem Arranca o Bot Manager (backend + worker) e abre http://localhost:8000/admin. Nao atualiza nada
rem (para atualizar: arrancar.bat). O token do worker fica em worker.token, nesta pasta (fora do Git).
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"

if not exist "backend\.venv\Scripts\activate.bat" (
  echo Nao encontrei backend\.venv. Instale primeiro o backend.
  pause
  exit /b 1
)

if not exist "worker.token" (
  echo Primeira vez: falta o token do worker.
  set /p "TOKEN=Cole aqui o token do worker e carregue Enter: "
  call :gravar_token
)

rem backend (janela "Bot Manager - backend")
start "Bot Manager - backend" cmd /k "cd /d "%ROOT%backend" && call .venv\Scripts\activate.bat && python -m uvicorn --factory botmanager.main:create_app --port 8000"

echo A aguardar que o backend arranque...
set /a TENTATIVAS=0
:esperar
timeout /t 2 /nobreak >nul
curl -s -o nul http://127.0.0.1:8000/ && goto pronto
set /a TENTATIVAS+=1
if %TENTATIVAS% lss 30 goto esperar
echo O backend nao respondeu em 60 s. Veja a janela "Bot Manager - backend".
pause
exit /b 1

:pronto
rem worker (janela "Bot Manager - worker")
start "Bot Manager - worker" cmd /k "cd /d "%ROOT%worker" && call ..\backend\.venv\Scripts\activate.bat && set WORKER_BACKEND_URL=http://127.0.0.1:8000&& set WORKER_ALLOW_HTTP=1&& set WORKER_ADAPTERS=flow&& set WORKER_TOKEN_FILE=%ROOT%worker.token&& python -m lusopay_worker.main"

start "" http://localhost:8000/admin
exit /b 0

:gravar_token
if "%TOKEN%"=="" (
  echo Token vazio. Crie um worker: cd backend, .venv\Scripts\activate,
  echo python -m botmanager.cli create-worker --name worker-pc --capabilities flow
  pause
  exit 1
)
> "worker.token" echo %TOKEN%
echo Token gravado em %ROOT%worker.token
exit /b 0

@echo off
rem Atualiza o Bot Manager (git pull, dependencias, base de dados, frontend) e arranca o backend e o worker,
rem cada um na sua janela. O token do worker fica em worker.token, nesta pasta (fora do Git).
rem Corre a partir de uma copia temporaria: o git pull pode alterar este ficheiro enquanto corre.
if not "%~1"=="_copia" (
  copy /y "%~f0" "%TEMP%\bm-arrancar.bat" >nul
  "%TEMP%\bm-arrancar.bat" _copia "%~dp0"
  exit /b
)
setlocal
set "ROOT=%~2"
cd /d "%ROOT%"

if not exist "worker.token" (
  echo Falta o ficheiro worker.token nesta pasta.
  echo Crie um worker:  cd backend ^&^& .venv\Scripts\activate ^&^& python -m botmanager.cli create-worker --name worker-pc --capabilities flow
  echo e grave o token num ficheiro chamado worker.token em %ROOT%
  pause
  exit /b 1
)

echo === A atualizar o codigo ===
git pull || goto erro

call backend\.venv\Scripts\activate.bat || goto erro
echo === A instalar dependencias ===
python -m pip install -q -e backend -e worker || goto erro

echo === A atualizar a base de dados ===
pushd backend
alembic upgrade head || (popd & goto erro)
popd

echo === A compilar o frontend ===
pushd frontend
call npm install --no-audit --no-fund || (popd & goto erro)
call npm run build || (popd & goto erro)
popd

echo === A arrancar ===
start "Bot Manager - backend" cmd /k "cd /d "%ROOT%backend" && call .venv\Scripts\activate.bat && python -m uvicorn --factory botmanager.main:create_app --port 8000"
timeout /t 5 /nobreak >nul
start "Bot Manager - worker" cmd /k "cd /d "%ROOT%worker" && call ..\backend\.venv\Scripts\activate.bat && set WORKER_BACKEND_URL=http://127.0.0.1:8000&& set WORKER_ALLOW_HTTP=1&& set WORKER_ADAPTERS=flow&& set WORKER_TOKEN_FILE=%ROOT%worker.token&& python -m lusopay_worker.main"
echo Pronto: abra http://127.0.0.1:8000
timeout /t 5 >nul
exit /b 0

:erro
echo.
echo ERRO: o passo acima falhou. Nada foi arrancado.
pause
exit /b 1

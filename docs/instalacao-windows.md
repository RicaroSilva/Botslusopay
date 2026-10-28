# Instalação e execução em Windows

> Estas instruções foram escritas para Windows Server 2019/2022 e **ainda não foram executadas num servidor da LUSOPAY**.
> Os comandos são standard (Python, PostgreSQL, Agendador de Tarefas), mas validem-nos num ambiente de teste.

Há dois papéis, que podem ou não estar na mesma máquina:

- **Servidor de aplicação**: backend web + scheduler + PostgreSQL.
- **Servidor de bots**: o atual, com o taskt/OpenBots e os XML. Aqui corre **apenas** o worker.

Recomenda-se separá-los: o servidor de bots não deve alojar a aplicação web.

## 1. Servidor de aplicação

### Pré-requisitos
- Python 3.11 ou superior (64 bits) — https://www.python.org/downloads/windows/ ("Add to PATH").
- PostgreSQL 14 ou superior (ou uma instância gerida pela equipa de IT).
- Node.js 20 LTS **só para compilar o frontend** (a compilação pode ser feita noutra máquina).
- Um certificado TLS e um proxy reverso (IIS com ARR, ou nginx) para HTTPS.

### Base de dados
```sql
CREATE USER botmanager WITH PASSWORD '<gerar>';
CREATE DATABASE botmanager OWNER botmanager;
```

### Backend
```powershell
cd C:\LusopayBotManager
git clone <repositorio> app
cd app\backend
py -3.11 -m venv C:\LusopayBotManager\venv
C:\LusopayBotManager\venv\Scripts\pip install .
copy ..\config\backend.env.example .env      # editar: BM_DATABASE_URL, BM_SECRET_KEY, …
C:\LusopayBotManager\venv\Scripts\alembic upgrade head
C:\LusopayBotManager\venv\Scripts\python -m botmanager.cli validate-registry
C:\LusopayBotManager\venv\Scripts\python -m botmanager.cli sync-registry
C:\LusopayBotManager\venv\Scripts\python -m botmanager.cli create-user --username admin --role admin
```

Gerar `BM_SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

O `.env` contém segredos. Restrinja-o à conta do serviço:
`icacls .env /inheritance:r /grant:r "<conta>:R" "Administrators:F"`.

### Frontend
```powershell
cd ..\frontend
npm ci
npm run build          # gera frontend\dist, servido pelo backend
```

### Serviços
O backend e o scheduler são processos de consola. Para os correr como serviços do Windows, use um *service wrapper*
(ex.: NSSM, WinSW) ou tarefas agendadas "ao arrancar o sistema", com uma conta de serviço sem privilégios:

```
backend:   C:\LusopayBotManager\venv\Scripts\uvicorn.exe --factory botmanager.main:create_app --host 127.0.0.1 --port 8000
           (diretório de trabalho: C:\LusopayBotManager\app\backend)
scheduler: C:\LusopayBotManager\venv\Scripts\python.exe -m botmanager.scheduler
```

O backend escuta apenas em `127.0.0.1`; o proxy reverso termina o TLS e encaminha para lá. Exponha apenas:
- a aplicação, aos utilizadores internos;
- `/api/worker/*`, ao servidor de bots;
- `/api/hooks/*`, apenas aos sistemas que enviam webhooks (se usados).

## 2. Servidor de bots (worker)

### Conta Windows
Use uma conta **dedicada** (ex.: `svc-lusopay-bots`), sem privilégios de administrador, com:
- leitura e escrita nas pastas dos bots (`Documents\taskt`, `Documents\Ficheiro config robots`,
  `Documents\OpenBotsStudio`) e acesso às partilhas usadas (ex.: `\\REALTIME\logs`);
- acesso de rede apenas ao necessário (backend do Bot Manager, Cyclos, SMTP, SQL Server, listas externas).

Em princípio deve ser a conta onde os bots já correm hoje. Se mudar de conta, as pastas `Documents\…`, `%APPDATA%\taskt`
e o `Config.txt` têm de ser migrados.

**Sessão interativa**: o taskt é uma aplicação gráfica e vários bots usam o browser, o teclado e o rato. O worker tem de
correr **na sessão iniciada** dessa conta, com o ecrã desbloqueado (por exemplo, auto-logon numa VM dedicada, sem
bloqueio de ecrã, e acesso por consola em vez de RDP desligado, porque ao desligar o RDP a sessão gráfica fica
inválida). Não instale o worker como serviço do Windows (sessão 0), porque não tem desktop.

### Instalação
```powershell
py -3.11 -m venv C:\LusopayWorker\venv
C:\LusopayWorker\venv\Scripts\pip install C:\LusopayBotManager\app\worker
```

Registe o worker na aplicação (Administração → Workers → Registar). Guarde o token mostrado num ficheiro protegido:
```powershell
New-Item -ItemType Directory C:\LusopayWorker\secret
Set-Content C:\LusopayWorker\secret\worker.token "<token>"
icacls C:\LusopayWorker\secret /inheritance:r /grant:r "svc-lusopay-bots:R" "Administrators:F"
```

Configuração: copie `config\worker.env.example` para `C:\LusopayWorker\worker.cmd` e ajuste-o:
```bat
@echo off
set WORKER_BACKEND_URL=https://botmanager.lusopay.local
set WORKER_TOKEN_FILE=C:\LusopayWorker\secret\worker.token
set WORKER_ADAPTERS=taskt_cli
set WORKER_TASKT_EXE=C:\Program Files (x86)\taskt\taskt.exe
set WORKER_TASKT_SCRIPTS_DIR=C:\Users\svc-lusopay-bots\Documents\taskt\My Scripts
set WORKER_TASKT_LOGS_DIR=C:\Users\svc-lusopay-bots\Documents\taskt\Logs
set WORKER_STATE_FILE=C:\LusopayWorker\worker-state.json
C:\LusopayWorker\venv\Scripts\python.exe -m lusopay_worker.main >> C:\LusopayWorker\worker.log 2>&1
```
(Os caminhos do taskt são exemplos: confirme-os conforme [validacao-piloto.md](validacao-piloto.md).)

### Arranque automático na sessão
Agendador de Tarefas → Criar tarefa:
- Geral: conta `svc-lusopay-bots`, **"Executar apenas quando o utilizador tiver sessão iniciada"**, sem privilégios
  elevados.
- Acionadores: "Ao iniciar sessão" desta conta.
- Ações: `C:\LusopayWorker\worker.cmd`.
- Definições: "Se a tarefa falhar, reiniciar a cada 1 minuto"; **não** "parar a tarefa se exceder…".

### Coexistência com o Agendador atual
Enquanto um bot continuar a ser disparado pelo Agendador de Tarefas (ex.: o orquestrador diário), **não** crie uma
regra automática para esse bot no Bot Manager. O recurso exclusivo `taskt-desktop` só protege execuções lançadas pelo
Bot Manager.

## 3. Verificação
1. `https://<servidor>/api/health` → `{"status":"ok"}`.
2. Login com o administrador; Dashboard → o worker aparece "online" (bola verde).
3. Seguir [validacao-piloto.md](validacao-piloto.md).

## 4. Operação

| Tarefa | Como |
|---|---|
| Atualizar a aplicação | `git pull`; `pip install .`; `alembic upgrade head`; `npm ci && npm run build`; reiniciar o backend e o scheduler |
| Atualizar o worker | parar a tarefa (espera que a execução em curso termine com Ctrl+C / fim de sessão), `pip install`, iniciar |
| Pausar todos os disparos automáticos | Administração → Configurações |
| Retirar um bot de serviço | Administração → Bots → Desativar / Manutenção |
| Revogar um worker | Administração → Workers → Desativar (o token deixa de funcionar) |
| Cópias de segurança | backup diário do PostgreSQL (`pg_dump`) |
| Auditoria | página Auditoria (aprovadores e administradores) ou tabela `audit_events` |
| Execuções "Rever" | Dashboard → Por rever; verificar os efeitos (Cyclos, emails, ficheiros) antes de repetir |

## 5. Desenvolvimento local (qualquer SO)

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
export BM_ENVIRONMENT=development BM_COOKIE_SECURE=false BM_DATABASE_URL=sqlite:///./dev.db \
       BM_EXTRA_REGISTRY_DIRS='["../bots/registry-dev"]'
alembic upgrade head && python -m botmanager.cli sync-registry && python -m botmanager.cli create-user --username admin --role admin
uvicorn --factory botmanager.main:create_app --reload --port 8000
# noutro terminal
cd frontend && npm ci && npm run dev          # http://localhost:5173
# worker com o adaptador simulado
cd worker && pip install -e . && WORKER_BACKEND_URL=http://127.0.0.1:8000 WORKER_ALLOW_HTTP=1 \
  WORKER_TOKEN=<token> WORKER_ADAPTERS=simulated python -m lusopay_worker.main
```
Os bots `[SIMULADO]` (pasta `bots/registry-dev`) só são carregados quando esta pasta está em `BM_EXTRA_REGISTRY_DIRS`.
Não a configure em produção.

**Windows, num clique:** `arrancar.bat` (na raiz do repositório) faz `git pull`, instala as dependências, corre
`alembic upgrade head`, compila o frontend e abre duas janelas, uma com o backend e outra com o worker (adaptador `flow`). O token
do worker é lido de `worker.token`, na raiz, ficheiro ignorado pelo Git. Feche antes um backend que já esteja a correr
(a porta 8000 tem de estar livre).

Testes: `cd backend && pytest`, `cd worker && pytest`, `cd frontend && npm test`. Para correr os testes do backend
contra PostgreSQL: `BM_TEST_DATABASE_URL=postgresql+psycopg://… pytest`.

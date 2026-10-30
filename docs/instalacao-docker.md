# Instalação com Docker

Contentores (rede interna `internal`):

| Serviço | Imagem | Função |
|---|---|---|
| `api` | `docker/api.Dockerfile` | aplicação web + API; aplica as migrações no arranque |
| `scheduler` | mesma imagem (`command: scheduler`) | agendamentos, consultas periódicas, recolha de execuções perdidas (uma só instância ativa) |
| `runner` | `docker/runner.Dockerfile` | executa os robôs nativos (fluxos e Java/Groovy; inclui o Java 21 e o Groovy); pode ser escalado |
| `db` | `postgres:16-alpine` | base de dados (substituível por um PostgreSQL externo) |

Testado: build das duas imagens, `docker compose up`, migrações, criação de fluxo, execução manual no runner com
ficheiro produzido e execução disparada por agendamento.

## 1. Configurar
```bash
cp docker/.env.example .env
```
Preencher no `.env`:
- `POSTGRES_PASSWORD`, `BM_SECRET_KEY` e `BM_RUNNER_TOKEN`: valores aleatórios longos
  (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- `BM_VAULT_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  **Guardar esta chave num cofre/local seguro.** Sem ela, as credenciais gravadas não podem ser decifradas.
- `BM_BOOTSTRAP_ADMIN_USERNAME` / `BM_BOOTSTRAP_ADMIN_PASSWORD`: primeiro administrador (só é criado com a base vazia;
  apagar a password do `.env` depois do primeiro login).
- `BM_FLOW_ALLOWED_HOSTS`: hosts que os fluxos podem chamar.
- `BM_COOKIE_SECURE=false` **só** para testar em `http://localhost`; em produção a aplicação deve estar atrás de HTTPS.

## 2. Arrancar
```bash
docker compose up -d --build
docker compose ps
```
Abrir `http://localhost:8080` (porta `BM_HTTP_PORT`).

## 3. Operação
| Tarefa | Comando |
|---|---|
| Logs | `docker compose logs -f api runner scheduler` |
| Mais capacidade de execução | `docker compose up -d --scale runner=3` |
| Atualizar | `git pull && docker compose up -d --build` (as migrações correm no arranque da api) |
| Criar utilizador pela linha de comandos | `docker compose exec api python -m botmanager.cli create-user --username x --role operator` |
| Backup da BD | `docker compose exec db pg_dump -U botmanager botmanager > backup.sql` |
| Parar tudo | `docker compose down` (os dados ficam no volume `pgdata`; `down -v` apaga-os) |

## Produção
- Colocar um proxy reverso com HTTPS à frente da `api` (Traefik, nginx, o que já usam para as outras aplicações) e
  definir `BM_FORWARDED_ALLOW_IPS` com o IP do proxy, para os IPs nos registos de auditoria serem os reais.
- Não publicar a porta da `db`. O `runner` não precisa de portas publicadas.
- PostgreSQL externo: definir `BM_DATABASE_URL` no `.env` e remover o serviço `db` do compose.
- O runner fala com a API por HTTP dentro da rede interna do Docker (`WORKER_ALLOW_HTTP=1`). Se o runner correr
  noutra máquina, use `https://` e remova essa variável.
- Os bots taskt que ainda não foram migrados continuam a precisar do worker Windows
  ([instalacao-windows.md](instalacao-windows.md)), que se liga a esta mesma API.

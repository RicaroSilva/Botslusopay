# LUSOPAY Bot Manager

Aplicação interna para criar, executar, agendar e monitorizar as automações da LUSOPAY, com controlo de acessos,
aprovações e auditoria. Os **fluxos nativos** (pedidos à API, CSV, email, SQL Server) correm na própria plataforma, em
Docker, e substituem gradualmente os robots **taskt/OpenBots**; os robots ainda não migrados podem continuar a ser
geridos através do worker Windows.

> **Estado:** MVP. Os fluxos nativos foram testados ponta a ponta em Docker (API, runner, scheduler, PostgreSQL) com
> serviços simulados; **ainda não contra o Cyclos, o SMTP ou o SQL Server reais**. Os robots taskt registados estão
> "Por validar" até à validação no servidor de bots ([docs/validacao-piloto.md](docs/validacao-piloto.md)).

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/fluxos.md](docs/fluxos.md) | Fluxos nativos: passos, modelos, credenciais, versões, migração dos bots taskt |
| [docs/instalacao-docker.md](docs/instalacao-docker.md) | Instalação e operação com Docker (api, scheduler, runner, db) |
| [docs/inventario-bots.md](docs/inventario-bots.md) | Fase A: o que são os scripts, mecanismo de execução confirmado, bots, dependências |
| [docs/inventario-detalhado.md](docs/inventario-detalhado.md) | Tabela gerada dos 64 XML (APIs, emails, BD, UI, bloqueios, contagem de segredos) |
| [docs/arquitetura.md](docs/arquitetura.md) | Fase B: arquitetura, decisões, adaptadores, estados, concorrência, disparos, modelo de dados, segurança |
| [docs/validacao-piloto.md](docs/validacao-piloto.md) | Como validar o runtime no servidor e o piloto (smoke test → Recolher Cyclos ID) |
| [docs/instalacao-windows.md](docs/instalacao-windows.md) | Instalação e operação em Windows; desenvolvimento local |
| [docs/registar-novos-bots.md](docs/registar-novos-bots.md) | Registar bots, novos tipos de disparo e novos adaptadores sem reescrever o backend |
| [docs/riscos.md](docs/riscos.md) | Credenciais encontradas, riscos, limitações e questões em aberto |

## Estrutura

```
backend/            FastAPI + SQLAlchemy + Alembic (API, regras, scheduler, auditoria)
  botmanager/       código
  alembic/          migrações
  tests/            testes (SQLite; também correm em PostgreSQL)
worker/             worker: motor de fluxos nativos (runner Docker) e adaptadores taskt / OpenBots (Windows)
docker/             Dockerfiles e .env de exemplo; docker-compose.yml na raiz
frontend/           React + TypeScript (Vite)
bots/registry/      definições YAML dos bots reais (controladas por revisão)
bots/registry-dev/  bots simulados, só desenvolvimento
config/             ficheiros de configuração de exemplo (sem segredos)
tools/inventory/    analisador estático dos XML taskt
docs/               documentação
```

Os XML dos bots **não** estão no repositório (contêm credenciais). Ficam no servidor de bots.

## Início rápido com Docker

```bash
cp docker/.env.example .env      # preencher os segredos
docker compose up -d --build     # http://localhost:8080
```

## Início rápido (desenvolvimento)

Ver [docs/instalacao-windows.md § 5](docs/instalacao-windows.md#5-desenvolvimento-local-qualquer-so).

```bash
cd backend && pytest        # 117 testes (auth, permissões, registo, execuções, worker, disparos, fluxos, cofre, migrações)
cd worker && pytest         # 51 testes (motor de fluxos, log do taskt, adaptadores, integração ponta a ponta)
cd frontend && npm test     # testes de interface
```

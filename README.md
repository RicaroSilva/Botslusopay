# LUSOPAY Bot Manager

Aplicação interna para consultar, executar, agendar e monitorizar os robots de automação da LUSOPAY (scripts
**taskt** e projetos **OpenBots Studio**), com controlo de acessos, aprovações e auditoria.

> **Estado:** MVP (fases A–D implementadas, fase E documentada). **Nenhum bot real foi ainda executado pelo Bot
> Manager.** Todos os bots estão "Por validar" até à validação no servidor de bots ([docs/validacao-piloto.md](docs/validacao-piloto.md)).
> Os testes automáticos usam um adaptador simulado e não provam que os bots reais funcionam.

## Documentação

| Documento | Conteúdo |
|---|---|
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
worker/             Windows Worker (adaptadores taskt / OpenBots / simulado)
frontend/           React + TypeScript (Vite)
bots/registry/      definições YAML dos bots reais (controladas por revisão)
bots/registry-dev/  bots simulados, só desenvolvimento
config/             ficheiros de configuração de exemplo (sem segredos)
tools/inventory/    analisador estático dos XML taskt
docs/               documentação
```

Os XML dos bots **não** estão no repositório (contêm credenciais). Ficam no servidor de bots.

## Início rápido (desenvolvimento)

Ver [docs/instalacao-windows.md § 5](docs/instalacao-windows.md#5-desenvolvimento-local-qualquer-so).

```bash
cd backend && pytest        # 105 testes (auth, permissões, registo, execuções, worker, disparos, redação, migrações)
cd worker && pytest         # 35 testes (log do taskt, adaptadores, integração worker↔backend)
cd frontend && npm test     # testes de interface
```

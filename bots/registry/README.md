# Registo de bots externos (taskt/OpenBots)

Pasta carregada por omissão (`BM_REGISTRY_DIR`). Está **vazia de propósito**: as automações passam a ser fluxos
nativos, criados ou importados na aplicação (Catálogo → Importar robô).

As definições dos robôs taskt antigos estão em `../registry-taskt/`. Para os voltar a mostrar no catálogo (por
exemplo, no servidor de bots, enquanto não são migrados), defina:

    BM_REGISTRY_DIR=<caminho>/bots/registry-taskt

Formato dos ficheiros: ver `docs/registar-novos-bots.md`.

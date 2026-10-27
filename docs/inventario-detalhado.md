# Inventário detalhado dos scripts (gerado automaticamente)

> Gerado por `tools/inventory/render_inventory.py`. Não editar à mão.
> Os segredos encontrados são apenas **contados por tipo**; nenhum valor é reproduzido.

| Estado | Nº |
|---|---|
| OK (produção) | 36 |
| Obsoleto (old_/OLD) | 11 |
| Sem prefixo | 8 |
| REVER | 4 |
| Teste | 3 |
| Substituído por OpenBots | 2 |

| Ficheiro | Estado | Cmds ativos | Sub-scripts (Run Task) | APIs / HTTP | Email | BD | UI (Selenium/teclado) | Bloqueios interativos | Segredos (contagem) |
|---|---|---|---|---|---|---|---|---|---|
| Análise de percentagem de fraudes nas transações LUSOPAY.xml | Sem prefixo | 42 | — | 2 (0 escrita) | sim | — | — | 6 MessageBox sem auto-fecho | http_auth_header_literal: 2, smtp_password_plaintext: 1 |
| Compara 2 ficheiros e elimina dados comuns.xml | Sem prefixo | 31 | — | — | — | — | — | 3 MessageBox sem auto-fecho | — |
| Cálculo de comissões de 1 parceiro em período especificado.xml | Sem prefixo | 205 | — | 4 (0 escrita) | sim | — | — | 2 Prompt for Input | http_auth_header_literal: 4, smtp_password_plaintext: 2 |
| Cálculo de comissões de parceiros.xml | Sem prefixo | 238 | — | 4 (0 escrita) | sim | — | — | — | http_auth_header_literal: 5, smtp_password_plaintext: 1 |
| Fazer relatório sobre clientes de risco BCFT alto.xml | Sem prefixo | 82 | — | 2 (0 escrita) | — | — | — | — | http_auth_header_literal: 2 |
| OK Abrir Cyclos produtivo.xml | OK (produção) | 6 | — | — | — | — | 6 | — | password_typed_literal_in_browser: 1 |
| OK Analisa se clientes desabilitados receberam fundos.xml | OK (produção) | 21 | — | 1 (0 escrita) | sim | — | — | 1 MessageBox sem auto-fecho | http_auth_header_literal: 1, smtp_password_plaintext: 2 |
| OK Análise Listas ONU e UE - criaçao de listas.xml | OK (produção) | 191 | {Folder.ScriptPath}OK Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay por API.xml | 2 (0 escrita) | — | — | — | — | — |
| OK Análise Listas ONU e UE - criação de relatório e envio para Cyclos.xml | OK (produção) | 81 | — | — | sim | — | 27 | — | password_typed_literal_in_browser: 1, smtp_password_plaintext: 1 |
| OK Análise Listas ONU e UE - fazer analise das listas (menos eficiente).xml | OK (produção) | 156 | — | — | sim | — | — | 7 MessageBox sem auto-fecho | smtp_password_plaintext: 1 |
| OK Análise Listas ONU e UE - fazer analise das listas.xml | OK (produção) | 103 | ONU nomes completos.csv, {Folder.ScriptPath}OK Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay por API.xml | — | sim | — | — | 3 MessageBox sem auto-fecho | smtp_password_plaintext: 1 |
| OK Análise Listas ONU e UE.xml | OK (produção) | 245 | — | 2 (0 escrita) | sim | — | — | 6 MessageBox sem auto-fecho | smtp_password_plaintext: 1 |
| OK Análise Listas PEP - criação de relatório e envio para Cyclos.xml | OK (produção) | 63 | — | — | — | — | 18 | — | password_typed_literal_in_browser: 1 |
| OK Análise Listas PEP por API (menos eficiente).xml | OK (produção) | 245 | — | 4 (0 escrita) | sim | — | — | — | http_auth_header_literal: 3, smtp_password_plaintext: 1 |
| OK Análise Listas PEP por API.xml | OK (produção) | 131 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 1 (0 escrita) | sim | — | — | — | — |
| OK Análise Listas PEP.xml | OK (produção) | 61 | — | — | — | — | — | 6 MessageBox sem auto-fecho | — |
| OK Análise de desempenho, operações e fraudes nas transações LUSOPAY.xml | OK (produção) | 184 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 3 (0 escrita) | sim | — | — | — | http_auth_header_from_variable: 8 |
| OK Análise de percentagem de fraudes nas transações LUSOPAY.xml | OK (produção) | 88 | — | 3 (0 escrita) | sim | — | — | — | http_auth_header_literal: 5, smtp_password_plaintext: 1 |
| OK Atribuir Tarifa MB Way.xml | OK (produção) | 120 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 3 (0 escrita) | sim | — | — | — | http_auth_header_from_variable: 3 |
| OK Cria registo de documento com data de ontem.xml | OK (produção) | 126 | — | 12 (5 escrita) | — | 1 | — | — | db_password: 1, db_username_in_connection_string: 1, http_auth_header_from_variable: 15 |
| OK Cálculo de comissões de parceiros (muito lento).xml | OK (produção) | 237 | — | 4 (0 escrita) | sim | — | — | — | http_auth_header_literal: 5, smtp_password_plaintext: 1 |
| OK Enviar Extrato de Comissões Pessoas Coletivas.xml | OK (produção) | 250 | — | 3 (0 escrita) | — | — | 53 | — | http_auth_header_literal: 4, password_typed_literal_in_browser: 1 |
| OK Enviar Extrato de Comissões Pessoas Singulares e ENI.xml | OK (produção) | 249 | — | 3 (0 escrita) | — | — | 53 | — | http_auth_header_literal: 4, password_typed_literal_in_browser: 1 |
| OK Envio de mensagem sobre expiraçao de documentos dos clientes.xml | OK (produção) | 27 | — | — | — | — | 12 | — | password_typed_literal_in_browser: 1 |
| OK Guardar relatórios Sanções e PEP no Cyclos.xml | OK (produção) | 45 | — | — | — | — | 16 | — | password_typed_literal_in_browser: 1 |
| OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário SEMANAL.xml | OK (produção) | 163 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 2 (1 escrita) | sim | 1 | — | 1 MessageBox sem auto-fecho; 1 Prompt for Input | db_password: 1, db_username_in_connection_string: 1, http_auth_header_from_variable: 3 |
| OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário.xml | OK (produção) | 157 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 2 (1 escrita) | sim | 1 | — | 1 MessageBox sem auto-fecho; 1 Prompt for Input | db_password: 1, db_username_in_connection_string: 1, http_auth_header_from_variable: 3, variable_default_value_for_secret_like_name: 1 |
| OK Lista de nifs de clientes pendentes e verifica no sicae.xml | OK (produção) | 92 | — | 2 (0 escrita) | sim | — | 9 | — | http_auth_header_literal: 2, smtp_password_plaintext: 2 |
| OK Origem e destino dos fundos.xml | OK (produção) | 82 | — | 2 (0 escrita) | — | — | — | — | http_auth_header_literal: 2 |
| OK Recolhe senha API de RPAtaskt.xml | OK (produção) | 2 | — | — | — | — | — | — | — |
| OK Recolhe transações de clientes aleatórios do mês anterior.xml | OK (produção) | 37 | — | 3 (0 escrita) | sim | — | — | — | http_auth_header_literal: 2, smtp_password_plaintext: 2 |
| OK Reenviar notificações de callback falhadas 2 horas antes.xml | OK (produção) | 151 | — | 1 (0 escrita) | sim | — | — | — | smtp_password_plaintext: 3 |
| OK Reenviar notificações de callback falhadas 5 a 1 horas antes.xml | OK (produção) | 151 | — | 1 (0 escrita) | sim | — | — | — | smtp_password_plaintext: 3 |
| OK Saldos de clientes no Cyclos no final do mês.xml | OK (produção) | 13 | {Folder.ScriptPath}Ok Recolha das Configurações.xml | 2 (0 escrita) | sim | — | — | — | http_auth_header_from_variable: 2 |
| OK Teste de envio de email.xml | Teste | 1 | — | — | sim | — | — | — | smtp_password_plaintext: 1 |
| OK Verifica se pagamentos foram carregados no Cyclos através do número de documento.xml | OK (produção) | 18 | — | 1 (0 escrita) | sim | — | — | 1 MessageBox sem auto-fecho; 1 Prompt for Input | http_auth_header_literal: 1, smtp_password_plaintext: 1 |
| OK ligação a API Cyclos de teste.xml | OK (produção) | 3 | — | 1 (0 escrita) | — | — | — | 2 MessageBox sem auto-fecho | http_auth_header_literal: 1 |
| OK ligação a API Cyclos produtiva.xml | OK (produção) | 12 | — | 1 (0 escrita) | — | — | — | 2 MessageBox sem auto-fecho | http_auth_header_literal: 1 |
| OK processos diarios do servidor de bots.xml | OK (produção) | 51 | {Folder.ScriptPath}OK Análise Listas PEP por API.xml, {Folder.ScriptPath}OK Análise de desempenho, operações e fraudes nas transações LUSOPAY.xml, {Folder.ScriptPath}OK Atribuir Tarifa MB Way.xml, {Folder.ScriptPath}OK Saldos de clientes no Cyclos no final do mês.xml, {Folder.ScriptPath}Ok Recolha das Configurações.xml | — | — | — | — | — | — |
| OK processos fim de semana do servidor de bots.xml | OK (produção) | 33 | {Folder.ScriptPath}OK Análise Listas PEP por API.xml, {Folder.ScriptPath}OK Análise de desempenho, operações e fraudes nas transações LUSOPAY.xml, {Folder.ScriptPath}OK Saldos de clientes no Cyclos no final do mês.xml | — | — | — | — | — | — |
| OK recolher Cyclos ID por API.xml | OK (produção) | 7 | — | 1 (0 escrita) | — | — | — | — | http_auth_header_literal: 1 |
| OLD OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário SEMANAL.xml | Obsoleto (old_/OLD) | 30 | — | — | sim | 1 | — | 1 MessageBox sem auto-fecho; 1 Prompt for Input | db_password: 1, db_username_in_connection_string: 1, smtp_password_plaintext: 2 |
| OLD OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário.xml | Obsoleto (old_/OLD) | 28 | — | — | sim | 1 | — | 1 MessageBox sem auto-fecho; 1 Prompt for Input | db_password: 1, db_username_in_connection_string: 1, smtp_password_plaintext: 2 |
| Ok Recolha das Configurações.xml | OK (produção) | 23 | — | — | sim | — | — | — | smtp_password_plaintext: 1 |
| REVER Alterar perfil de risco BCFT via API.xml | REVER | 96 | — | 4 (0 escrita) | — | — | — | 2 MessageBox sem auto-fecho | http_auth_header_literal: 4 |
| REVER Alterar perfil de risco BCFT.xml | REVER | 296 | — | 3 (0 escrita) | — | — | 61 | 3 MessageBox sem auto-fecho | http_auth_header_literal: 4 |
| REVER Análise Listas ONU e UE via API.xml | REVER | 221 | — | 4 (0 escrita) | — | — | 34 | 2 MessageBox sem auto-fecho | http_auth_header_literal: 4, password_typed_literal_in_browser: 1 |
| REVER Fechar contas de clientes com saldo zero há 12 meses OTIMIZADO 2.xml | REVER | 125 | — | — | — | — | 21 | 3 MessageBox sem auto-fecho | password_typed_literal_in_browser: 1 |
| Recolher nomes de embaixadores para listas PEP.xml | Sem prefixo | 36 | — | — | — | — | 8 | — | — |
| SUBSTITUÍDO POR OPENBOTS Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay por API.xml | Substituído por OpenBots | 264 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 4 (0 escrita) | sim | — | — | — | http_auth_header_from_variable: 4, smtp_password_plaintext: 1 |
| SUBSTITUÍDO POR OPENBOTS Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay.xml | Substituído por OpenBots | 16 | — | — | sim | — | — | — | smtp_password_plaintext: 1 |
| Sanções.xml | Sem prefixo | 4 | — | — | — | — | 1 | — | — |
| Teste replace text.xml | Teste | 12 | — | — | — | — | — | 1 MessageBox sem auto-fecho | — |
| Validação diária de valores carregados no Cyclos.xml | Sem prefixo | 7 | — | 1 (0 escrita) | — | — | — | 2 MessageBox sem auto-fecho | http_auth_header_literal: 1 |
| old_Alterar perfil de risco BCFT.xml | Obsoleto (old_/OLD) | 330 | — | — | sim | — | 89 | 2 MessageBox sem auto-fecho | password_typed_literal_in_browser: 1, smtp_password_plaintext: 1 |
| old_OK Alterar perfil de risco BCFT via API - ServidotBots1 - 1 cliente.xml | Obsoleto (old_/OLD) | 125 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | 3 MessageBox sem auto-fecho | http_auth_header_from_variable: 6, smtp_password_plaintext: 2 |
| old_OK Alterar perfil de risco BCFT via API - ServidotBots1.xml | Obsoleto (old_/OLD) | 215 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | 2 MessageBox sem auto-fecho | http_auth_header_from_variable: 6, smtp_password_plaintext: 3 |
| old_OK Alterar perfil de risco BCFT via API - ServidotBots2.xml | Obsoleto (old_/OLD) | 209 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | — | http_auth_header_from_variable: 6, smtp_password_plaintext: 3 |
| old_OK Alterar perfil de risco BCFT via API - recolhe cyclosid e grava em txt.xml | Obsoleto (old_/OLD) | 9 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 1 (0 escrita) | — | — | — | — | http_auth_header_from_variable: 1 |
| old_OK Alterar perfil de risco BCFT via API - verificar risco Alto.xml | Obsoleto (old_/OLD) | 187 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | — | http_auth_header_from_variable: 7, smtp_password_plaintext: 3 |
| old_OK Alterar perfil de risco BCFT via API 1 cliente.xml | Obsoleto (old_/OLD) | 190 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | 10 MessageBox sem auto-fecho | http_auth_header_from_variable: 7, smtp_password_plaintext: 2 |
| old_OK Alterar perfil de risco BCFT via API.xml | Obsoleto (old_/OLD) | 210 | {Folder.ScriptPath}OK Recolhe senha API de RPAtaskt.xml | 5 (1 escrita) | sim | — | — | — | http_auth_header_from_variable: 7, smtp_password_plaintext: 3 |
| old_OK Atribuir Tarifa MB Way.xml | Obsoleto (old_/OLD) | 102 | — | 2 (0 escrita) | sim | — | — | — | http_auth_header_from_variable: 2, smtp_password_plaintext: 4 |
| teste.xml | Teste | 1 | — | — | — | — | — | 1 MessageBox sem auto-fecho | — |

## Endpoints por script

**Análise de percentagem de fraudes nas transações LUSOPAY.xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoEventualFraude`
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoFraudes`

**Cálculo de comissões de 1 parceiro em período especificado.xml**
- `GET https://app.lusopay.com:8443/web/api/transfers`
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443web/api/users/{vBrokersCyclosId}`
- `GET https://app.lusopay.com:8443web/api/users/{vCyclosId}`

**Cálculo de comissões de parceiros.xml**
- `GET https://app.lusopay.com:8443/web/api/transfers`
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443web/api/users/{vBrokersCyclosId}`
- `GET https://app.lusopay.com:8443web/api/users/{vCyclosId}`

**Fazer relatório sobre clientes de risco BCFT alto.xml**
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/accounts/EUR/balances-history`

**OK Analisa se clientes desabilitados receberam fundos.xml**
- `GET https://app.lusopay.com:8443/web/api/transfers`

**OK Análise Listas ONU e UE - criaçao de listas.xml**
- `HTTP https://scsanctions.un.org/resources/xml/en/consolidated.xml`
- `HTTP https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/files//csvFullSanctionsList/content`

**OK Análise Listas ONU e UE.xml**
- `HTTP https://scsanctions.un.org/resources/xml/en/consolidated.xml`
- `HTTP https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/files//csvFullSanctionsList/content`

**OK Análise Listas PEP por API (menos eficiente).xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/BeneficiariosEfetivos`
- `GET https://app.lusopay.com:8443/web/api/general-records/DadosGerentes`
- `GET https://app.lusopay.com:8443/web/api/users`
- `HTTP https://services.lusopay.com/PEP.csv`

**OK Análise Listas PEP por API.xml**
- `HTTP https://services.lusopay.com/PEP.csv`

**OK Análise de desempenho, operações e fraudes nas transações LUSOPAY.xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoEventualFraude`
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoFraudes`
- `GET https://app.lusopay.com:8443/web/api/transfers`

**OK Análise de percentagem de fraudes nas transações LUSOPAY.xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoEventualFraude`
- `GET https://app.lusopay.com:8443/web/api/general-records/RegistoFraudes`
- `GET https://app.lusopay.com:8443/web/api/transfers`

**OK Atribuir Tarifa MB Way.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}`
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}/data-for-edit`

**OK Cria registo de documento com data de ontem.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/record-types/AtaEleicao`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/record-types/BeneficiariosEfetivos`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/record-types/ComprovativoMorada`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/record-types/ComprovativoRegistoPessoaColetiva`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/record-types/DadosGerentes`
- `POST https://app.lusopay.com:8443/web/api/{vCyclosId}/records/AtaEleicao`
- `POST https://app.lusopay.com:8443/web/api/{vCyclosId}/records/BeneficiariosEfetivos`
- `POST https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComprovativoMorada`
- `POST https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComprovativoRegistoPessoaColetiva`
- `POST https://app.lusopay.com:8443/web/api/{vCyclosId}/records/DadosGerentes`

**OK Cálculo de comissões de parceiros (muito lento).xml**
- `GET https://app.lusopay.com:8443/web/api/transfers`
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443web/api/users/{vBrokersCyclosId}`
- `GET https://app.lusopay.com:8443web/api/users/{vCyclosId}`

**OK Enviar Extrato de Comissões Pessoas Coletivas.xml**
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/accounts/EUR/history`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/addresses/list-data`

**OK Enviar Extrato de Comissões Pessoas Singulares e ENI.xml**
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/accounts/EUR/history`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/addresses/list-data`

**OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário SEMANAL.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `POST https://app.lusopay.com:8443/web/api/system/records/TransacoesAnalisadas`

**OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `POST https://app.lusopay.com:8443/web/api/system/records/TransacoesAnalisadas`

**OK Lista de nifs de clientes pendentes e verifica no sicae.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosIdList}/data-for-edit`

**OK Origem e destino dos fundos.xml**
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/accounts/EUR/balances-history`

**OK Recolhe transações de clientes aleatórios do mês anterior.xml**
- `GET http://www.randomnumberapi.com/api/v1.0/random`
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/history`

**OK Reenviar notificações de callback falhadas 2 horas antes.xml**
- `HTTP {vURLcallback}`

**OK Reenviar notificações de callback falhadas 5 a 1 horas antes.xml**
- `HTTP {vURLcallback}`

**OK Saldos de clientes no Cyclos no final do mês.xml**
- `GET https://app.lusopay.com:8443/web/api/accounts/EUR/user-balances`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}`

**OK Verifica se pagamentos foram carregados no Cyclos através do número de documento.xml**
- `GET https://app.lusopay.com:8443web/api/{vIPC}/accounts/EUR/history`

**OK ligação a API Cyclos de teste.xml**
- `GET http://185.15.20.221:8080/web_dev/api/_cliente1/accounts`

**OK ligação a API Cyclos produtiva.xml**
- `GET https://app.lusopay.com:8443/web/api/[vUsernamesList]/accounts`

**OK recolher Cyclos ID por API.xml**
- `GET https://app.lusopay.com:8443/web/api/users`

**REVER Alterar perfil de risco BCFT via API.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesList}/records/ComunicacoesUIF`

**REVER Alterar perfil de risco BCFT.xml**
- `GET https://app.lusopay.com:8443/web/api/dreamx/records/ComunicacoesUIF`
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vUsernamesLists}/accounts/EUR/balances-history`

**REVER Análise Listas ONU e UE via API.xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/BeneficiariosEfetivos`
- `GET https://app.lusopay.com:8443/web/api/general-records/DadosGerentes`
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`

**SUBSTITUÍDO POR OPENBOTS Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay por API.xml**
- `GET https://app.lusopay.com:8443/web/api/general-records/BeneficiariosEfetivos`
- `GET https://app.lusopay.com:8443/web/api/general-records/DadosGerentes`
- `GET https://app.lusopay.com:8443/web/api/system/records/ListaDiligenciaAcrescidaBdP`
- `GET https://app.lusopay.com:8443/web/api/users`

**Validação diária de valores carregados no Cyclos.xml**
- `GET https://app.lusopay.com:8443/web/api/transactions`

**old_OK Alterar perfil de risco BCFT via API - ServidotBots1 - 1 cliente.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosIdLista}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosIdLista}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosIdLista}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosIdLista}`

**old_OK Alterar perfil de risco BCFT via API - ServidotBots1.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosIdLista}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosIdLista}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosIdLista}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosIdLista}`

**old_OK Alterar perfil de risco BCFT via API - ServidotBots2.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosId}`

**old_OK Alterar perfil de risco BCFT via API - recolhe cyclosid e grava em txt.xml**
- `GET https://app.lusopay.com:8443/web/api/users`

**old_OK Alterar perfil de risco BCFT via API - verificar risco Alto.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosId}`

**old_OK Alterar perfil de risco BCFT via API 1 cliente.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosId}`

**old_OK Alterar perfil de risco BCFT via API.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vCyclosId}/data-for-edit`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/accounts/EUR/balances-history`
- `GET https://app.lusopay.com:8443/web/api/{vCyclosId}/records/ComunicacoesUIF`
- `PUT https://app.lusopay.com:8443/web/api/users/{vCyclosId}`

**old_OK Atribuir Tarifa MB Way.xml**
- `GET https://app.lusopay.com:8443/web/api/users`
- `GET https://app.lusopay.com:8443/web/api/users/{vUsernamesList}/data-for-edit`

## Primeiros comentários (descrição) por script

- **Análise de percentagem de fraudes nas transações LUSOPAY.xml**: Definir variáveis: vDataInicio e vDataFim / Recolher dados de eventuais fraudes
- **Compara 2 ficheiros e elimina dados comuns.xml**: Comparar 2 ficheiros e eliminar dados comuns / Lê CSV de usernames
- **Cálculo de comissões de 1 parceiro em período especificado.xml**: Recolher configurações / Data de início do cálculo das comissões (primeiro dia do trimestre anterior) / Definir cyclos IDs do parceiro
- **Cálculo de comissões de parceiros.xml**: Recolher configurações / Ler ficheiro anterior Valores pendentes.csv e criar variavel do tipo lista / Data de início do cálculo das comissões (primeiro dia do trimestre anterior)
- **Fazer relatório sobre clientes de risco BCFT alto.xml**: Alterar o ficheiro / Imported From OK recolher Cyclos ID por API.xml @ 25-02-2020 10:34:40 / recolher CyclosID por API dos grupos envios de fundos, penhoras e docs caducados
- **OK Análise Listas ONU e UE - criaçao de listas.xml**: Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Baixa lista consolidada de sanções da ONU (atual)
- **OK Análise Listas ONU e UE - criação de relatório e envio para Cyclos.xml**: Criação do relatório
- **OK Análise Listas ONU e UE - fazer analise das listas (menos eficiente).xml**: Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Recolhe lista consolidada de sanções da ONU (atual) ja tratada / Recolher ficheiro das sanções da União Europeia.
- **OK Análise Listas ONU e UE - fazer analise das listas.xml**: Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Recolhe lista consolidada de sanções da ONU (atual) ja tratada / Recolher ficheiro das sanções da União Europeia.
- **OK Análise Listas ONU e UE.xml**: Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Baixa lista consolidada de sanções da ONU (atual)
- **OK Análise Listas PEP - criação de relatório e envio para Cyclos.xml**: Criação do relatório
- **OK Análise Listas PEP por API (menos eficiente).xml**: Recolhe PEP
- **OK Análise Listas PEP por API.xml**: Recolhe PEP
- **OK Análise Listas PEP.xml**: Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Lê o ficheiro PEP.csv / Analisa os nomes completos dos clientes face aos nomes das listas de PEP
- **OK Análise de desempenho, operações e fraudes nas transações LUSOPAY.xml**: End Import From OK Recolhe senha API de RPAtaskt.xml @ 17/06/2022 10:44:21 / Definir variáveis: vDataInicio e vDataFim. Se necessitar de alterar os dias (deixar de ser dia 14), precisamos também de alterar no bot de processos diários do servidor de bots (no IF para saber se hoje é dia de correr este bot) / Inserir datas nas variáveis para efeitos de testes
- **OK Análise de percentagem de fraudes nas transações LUSOPAY.xml**: Definir variáveis: vDataInicio e vDataFim. Se necessitar de alterar os dias, precisamos de alterar no bot de processos diarios do servidor de bots (no IF para saber se hoje eh dia de correr este bot) / Inserir datas nas variaveis para efeitos de teste / Recolher dados de eventuais fraudes
- **OK Atribuir Tarifa MB Way.xml**: Vai buscar os utilizadores que nao tem a tarifa MB Way atribuida, excluindo o utilizador gerallusopay.
- **OK Cria registo de documento com data de ontem.xml**: Cria variável vOntem e vData2AnosAtras / Testes
- **OK Cálculo de comissões de parceiros (muito lento).xml**: Recolher configurações / Ler ficheiro anterior Valores pendentes.csv e criar variavel do tipo lista / Data de início do cálculo das comissões (primeiro dia do trimestre anterior)
- **OK Enviar Extrato de Comissões Pessoas Coletivas.xml**: Abrir Cyclos / Recolhe IPC de clientes com preço alterado o ano passado / Copiar Identificadores públicos de conta para variável
- **OK Enviar Extrato de Comissões Pessoas Singulares e ENI.xml**: Abrir Cyclos / Recolhe IPC de clientes com preço alterado o ano passado / Copiar Identificadores públicos de conta para variável
- **OK Envio de mensagem sobre expiraçao de documentos dos clientes.xml**: Abrir Cyclos / Clicar submenu Notificar Docs Expirados / Clicar no Ok da janela de confirmação de ação
- **OK Guardar relatórios Sanções e PEP no Cyclos.xml**: Abre Cyclos / Enviar relatório de análise de sanções ONU e UE para Cyclos / Enviar relatório de análise PEP para Cyclos
- **OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário SEMANAL.xml**: Analisar BCFT MB Way entre pagadores e beneficiários do pagamento / Imported From OK Recolhe senha API de RPAtaskt.xml @ 21/08/2024 16:29:01 / End Import From OK Recolhe senha API de RPAtaskt.xml @ 21/08/2024 16:29:01
- **OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário.xml**: Analisar BCFT MB Way entre pagadores e beneficiários do pagamento
- **OK Lista de nifs de clientes pendentes e verifica no sicae.xml**: Verifica se existe o ficheiro
- **OK Origem e destino dos fundos.xml**: Alterar o ficheiro / Imported From OK recolher Cyclos ID por API.xml @ 25-02-2020 10:34:40 / recolher CyclosID por API dos grupos envios de fundos, penhoras e docs caducados
- **OK Recolhe transações de clientes aleatórios do mês anterior.xml**: Define as datas de início e fim do mês anterior ao atual / Recolhe cyclos id e IPC de todos os clientes / Solicita as transações do mês anterior deste cliente
- **OK Reenviar notificações de callback falhadas 2 horas antes.xml**: MUITO IMPORTANTE:  É necessário garantir que todos os sites/software de faturação que não possam ser novamente notificados, constem do ficheiro: C:\Users\Utilizador\Documents\taskt\My Scripts\Listas\Notificaçoes callback falhadas\Sites excluidos do bot de callback.txt  Basta colocar o domínio. Não é / Tratar apenas a penúltima hora
- **OK Reenviar notificações de callback falhadas 5 a 1 horas antes.xml**: MUITO IMPORTANTE:  É necessário garantir que todos os sites/software de faturação que não possam ser novamente notificados, constem do ficheiro: C:\Users\Utilizador\Documents\taskt\My Scripts\Listas\Notificaçoes callback falhadas\Sites excluidos do bot de callback.txt  Basta colocar o domínio. Não é / Tratar apenas entre as 5 e 1 horas antes
- **OK Saldos de clientes no Cyclos no final do mês.xml**: Demora cerca de 2 segundos por cliente, o que dá 3 horas e meia para 6000 clientes.
- **OK Verifica se pagamentos foram carregados no Cyclos através do número de documento.xml**: Dados para testes
- **OK ligação a API Cyclos produtiva.xml**: Alterar o ficheiro / Apagar o proximo passo em ambientes produtivos
- **OK processos diarios do servidor de bots.xml**: Verifica se hoje corre o bot de análise do perfil de risco dos clientes LUSOPAY / Verifica se hoje o bot deve correr mais algum bot
- **OK processos fim de semana do servidor de bots.xml**: Processo que vão correr nos fins de semanas / Verifica se hoje o corre o bot que cria o reporte de análise de desempenho, operações e fraude
- **OK recolher Cyclos ID por API.xml**: recolher CyclosID por API dos grupos envios de fundos, penhoras e docs caducados
- **OLD OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário SEMANAL.xml**: Analisar BCFT MB Way entre pagadores e beneficiários do pagamento
- **OLD OK LUSOPAY Análise BCFT MB Way pagamentos entre pagador e beneficiário.xml**: Analisar BCFT MB Way entre pagadores e beneficiários do pagamento
- **Ok Recolha das Configurações.xml**: Vai buscar as configuraçoes que se encontram no ficheiro Config.txt
- **REVER Alterar perfil de risco BCFT via API.xml**: recolher CyclosID por API dos grupos envios de fundos, penhoras e docs caducados / Verifica se cliente é PEP (fazer lista com cyclos ID dos PEP) / Define endereço API para fazer o PUT
- **REVER Alterar perfil de risco BCFT.xml**: Se comunicado à UIF há menos de 1 ano = Alto / Abrir Cyclos
- **REVER Análise Listas ONU e UE via API.xml**: Baixar ficheiros de nomes de clientes e de dados de gerentes. Retirar as linhas em branco existentes nas últimas linhas dos ficheiros de dados de gerentes e nomes de clientes. / Elimina ficheiros previamente existentes e verifica a existência de ficheiros obrigatórios. / Abre Chrome para ir buscar nova lista de sanções da ONU
- **REVER Fechar contas de clientes com saldo zero há 12 meses OTIMIZADO 2.xml**: É necessário ter 2 ficheiros: um de utilizadores com conta aberta há mais de 12 meses e outro de agregadores. Estes ficheiros só têm os usernames. / Lê CSV de usernames
- **SUBSTITUÍDO POR OPENBOTS Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay por API.xml**: Recolhe senha API / Recolhe clientes Lusopay
- **SUBSTITUÍDO POR OPENBOTS Análise de lista de entidades sujeitas a diligência reforçada por ordem do BdP e clientes Lusopay.xml**: Ler ficheiro com entidades sujeitas a diligência reforçada pelo BdP / Recolhe clientes Lusopay / Criar ficheiro de relatorio
- **Sanções.xml**: Abri XML de sanções
- **Validação diária de valores carregados no Cyclos.xml**: Detetar se valores carregados no Cyclos são iguais aos recebidos da entidade 11024
- **old_Alterar perfil de risco BCFT.xml**: Abrir Cyclos
- **old_OK Alterar perfil de risco BCFT via API - ServidotBots1 - 1 cliente.xml**: Recolher utilizadores cyclos / Recolhe Cyclos ID de clientes PEP para variavel / Recolhe Empresas cotadas em bolsa
- **old_OK Alterar perfil de risco BCFT via API - ServidotBots1.xml**: Regista a data em que o robô correu / Recolher utilizadores cyclos / Ver se existe ficheiro com cyclos id ja tratados
- **old_OK Alterar perfil de risco BCFT via API - ServidotBots2.xml**: Imported From OK Alterar perfil de risco BCFT via API.xml @ 28/06/2024 13:44:28 / Regista a data em que o robô correu / Recolher utilizadores cyclos
- **old_OK Alterar perfil de risco BCFT via API - recolhe cyclosid e grava em txt.xml**: Recolher utilizadores cyclos
- **old_OK Alterar perfil de risco BCFT via API - verificar risco Alto.xml**: Ver se existe ficheiro com cyclos id ja tratados / recolher CyclosID por API dos clientes dos grupos envios de fundos, penhoras e docs caducados
- **old_OK Alterar perfil de risco BCFT via API 1 cliente.xml**: Ver se existe ficheiro com cyclos id ja tratados / recolher CyclosID por API dos clientes dos grupos envios de fundos, penhoras e docs caducados / Recolhe Cyclos ID de clientes PEP para variavel
- **old_OK Alterar perfil de risco BCFT via API.xml**: Regista a data em que o robô correu / Recolher utilizadores cyclos / Ver se existe ficheiro com cyclos id ja tratados
- **old_OK Atribuir Tarifa MB Way.xml**: Imported From OK Recolhe senha API de RPAtaskt.xml @ 20/06/2022 11:59:55 / End Import From OK Recolhe senha API de RPAtaskt.xml @ 20/06/2022 11:59:55

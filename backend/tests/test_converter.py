"""Conversor taskt/OpenBots → fluxo nativo (ficheiros de exemplo sintéticos, sem segredos reais)."""
import base64
import json

import pytest

from botmanager.flows.converters import convert, read_robot
from botmanager.flows.converters.readers import RobotFormatError
from botmanager.flows.converters.translate import dotnet_date_format
from botmanager.flows.schema import validate_flow

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema"'


def cmd(type_, line, comment="", children="", **attrs):
    a = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    c = f' v_Comment="{comment}"' if comment else ""
    return (f'<ScriptAction><ScriptCommand xsi:type="{type_}" CommandName="{type_}" IsCommented="false" '
            f'LineNumber="{line}" CommandEnabled="true"{c} {a}>{children}</ScriptCommand></ScriptAction>')


def table(name, rows):
    def tag(k):
        return k.replace(" ", "_x0020_")

    body = "".join("<R>" + "".join(f"<{tag(k)}>{v}</{tag(k)}>" for k, v in r.items()) + "</R>" for r in rows)
    return (f'<{name}><diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">'
            f"<DocumentElement>{body}</DocumentElement></diffgr:diffgram></{name}>")


def script(*cmds, variables=("vJson", "vLista", "vHoje", "vSenhaApi")):
    vs = "".join(f'<ScriptVariable><VariableName>{v}</VariableName><VariableValue xsi:type="xsd:string">'
                 f"{'valor-secreto' if 'Senha' in v else ''}</VariableValue></ScriptVariable>" for v in variables)
    return (f'<?xml version="1.0" encoding="utf-8"?><Script {XSI}><Commands>{"".join(cmds)}</Commands>'
            f"<Variables>{vs}</Variables></Script>").encode()


SALDOS = script(
    cmd("CommentCommand", 1, "Recolhe saldos"),
    cmd("RunTaskCommand", 2, v_taskPath="{Folder.ScriptPath}Ok Recolha das Configurações.xml"),
    cmd("FormatDataCommand", 3, v_InputValue="{DateTime.Now}", v_FormatType="Date", v_ToStringFormat="yyyy-MM-dd",
        v_applyToVariableName="vHoje"),
    cmd("RESTCommand", 4, v_BaseURL="https://app.lusopay.com:8443",
        v_APIEndPoint="/web/api/accounts/EUR/user-balances?pageSize=99999", v_APIMethodType="GET",
        v_userVariableName="vJson",
        children=table("v_AdvancedParameters", [
            {"Parameter Name": "Authorization", "Parameter Value": "Basic ZmFrZTpmYWtl", "Parameter Type": "HttpHeader"},
            {"Parameter Name": "accept", "Parameter Value": "application/json", "Parameter Type": "HttpHeader"}])),
    cmd("ParseJSONArrayCommand", 5, v_InputValue="{vJson}", v_applyToVariableName="vLista"),
    cmd("VariableCommand", 6, v_userVariableName="vTotal", v_Input="0"),
    cmd("WriteTextFileCommand", 7, v_FilePath="{Folder.ScriptPath}Listas\\Saldos\\Saldos a {vHoje}.csv",
        v_TextToWrite="Nome;Saldo[crLF]", v_Overwrite="Overwrite"),
    cmd("BeginListLoopCommand", 8, v_LoopParameter="{vLista}"),
    cmd("ParseJsonModelCommand", 9, v_InputValue="{vLista}",
        children=table("v_ParseObjects", [{"Json Selector": "$.id", "Output Variable": "vId"},
                                          {"Json Selector": "$.balance", "Output Variable": "vSaldo"}])),
    cmd("BeginIfCommand", 10, v_IfActionType="Value",
        children=table("v_IfActionParameterTable", [{"Parameter Name": "Value1", "Parameter Value": "{vSaldo}"},
                                                    {"Parameter Name": "Operand", "Parameter Value": "is greater than"},
                                                    {"Parameter Name": "Value2", "Parameter Value": "1"}])),
    cmd("MathCalculationCommand", 11, v_InputValue="{vTotal}+1", v_applyToVariableName="vTotal"),
    cmd("WriteTextFileCommand", 12, v_FilePath="{Folder.ScriptPath}Listas\\Saldos\\Saldos a {vHoje}.csv",
        v_TextToWrite="{vId};{vSaldo}[crLF]", v_Overwrite="Append"),
    cmd("EndIfCommand", 13),
    cmd("EndLoopCommand", 14),
    cmd("SMTPSendEmailCommand", 15, v_SMTPHost="mail.lusopay.com", v_SMTPPort="587", v_SMTPUserName="geral@lusopay.com",
        v_SMTPPassword="NaoCopiar123", v_SMTPFromEmail="geral@lusopay.com",
        v_SMTPToEmail="jar@lusopay.com,geral@lusopay.com", v_SMTPSubject="Saldos {vHoje} ({vTotal})",
        v_SMTPBody="Olá,[crLF]segue anexo", v_SMTPAttachment="{Folder.ScriptPath}Listas\\Saldos\\Saldos a {vHoje}.csv"),
    cmd("SeleniumBrowserCreateCommand", 16, "Abrir Chrome"),
)


def test_dotnet_date_formats():
    assert dotnet_date_format("yyyy-MM-dd") == "%Y-%m-%d"
    assert dotnet_date_format("yyyy-MM-01") == "%Y-%m-01"
    assert dotnet_date_format("dd/MM/yyyy HH:mm:ss") == "%d/%m/%Y %H:%M:%S"
    assert dotnet_date_format("yyyyMMdd") == "%Y%m%d"


def test_convert_taskt_saldos_like_script():
    res = convert(read_robot(SALDOS, "OK Saldos.xml"), test_email="teste@lusopay.com")
    validate_flow(res.definition, res.credentials, [])
    flat = json.dumps(res.definition, ensure_ascii=False)
    # credenciais nunca copiadas
    assert "ZmFrZTpmYWtl" not in flat and "NaoCopiar123" not in flat and "valor-secreto" not in flat
    assert res.credentials == {"cyclos-producao": "http_basic", "smtp-lusopay": "smtp"}
    steps = res.definition["steps"]
    assert [s["type"] for s in steps] == ["set", "http_request", "set", "set", "text_write", "set", "foreach", "email", "fail"]
    # o comentário dá nome ao passo seguinte que é gerado (o sub-robô de configuração é removido)
    assert steps[0]["name"] == "Recolhe saldos"
    http = steps[1]
    assert http["credential"] == "cyclos-producao"
    assert "Authorization" not in http.get("headers", {})
    loop = steps[6]
    assert steps[5]["variable"] == "vLista_colecao" and loop["items_expr"] == "vLista_colecao"
    assert loop["item_variable"] == "vLista" and "vTotal" in loop["carry"]
    email = steps[7]
    assert "email_teste" in email["to"][0] and email["attachments"] == ["Saldos a {{ vHoje }}.csv"]
    assert res.definition["variables"]["email_teste"] == "teste@lusopay.com"
    assert steps[-1]["type"] == "fail" and "Selenium" in steps[-1]["message"]
    assert {"convertido", "nao_convertivel", "ignorado"} <= {r.level for r in res.report}
    assert res.risk_level == "medium"


def test_converted_flow_runs_in_engine(tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker"))
    import httpx
    from lusopay_worker.flowengine import Engine

    res = convert(read_robot(SALDOS, "OK Saldos.xml"), test_email="teste@lusopay.com")
    res.definition["steps"] = res.definition["steps"][:-1]  # retira o passo Selenium não convertível
    sent = []

    class SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            pass

        def send_message(self, m):
            sent.append(m)

    data = [{"id": "a", "balance": "0.5"}, {"id": "b", "balance": "7"}, {"id": "c", "balance": "12,5"}]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=data))
    creds = {"cyclos-producao": {"kind": "http_basic", "username": "u", "password": "p"},
             "smtp-lusopay": {"kind": "smtp", "host": "h", "port": 587, "username": "a@b.pt", "password": "p",
                              "from_address": "a@b.pt"}}
    eng = Engine({"run_id": "r", "flow": {"version": 1, "definition": res.definition}, "credentials": creds,
                  "allowed_hosts": []}, tmp_path, emit=lambda line: None,
                 http_client=httpx.Client(transport=transport), smtp_factory=SMTP)
    out = eng.run()
    assert out["status"] == "SUCCEEDED", out
    csv = (tmp_path / out["files"][0]).read_text(encoding="utf-8")
    assert csv.splitlines() == ["Nome;Saldo", "b;7", "c;12,5"]
    # destinatário de testes e contador alterado dentro do ciclo propagado para fora (semântica do taskt)
    assert sent[0]["To"] == "teste@lusopay.com" and sent[0]["Subject"].endswith("(2)")


def test_without_test_email_keeps_original_recipients():
    res = convert(read_robot(SALDOS, "x.xml"))
    email = [s for s in res.definition["steps"] if s["type"] == "email"][0]
    assert email["to"] == ["jar@lusopay.com,geral@lusopay.com"]


def test_unsupported_and_http_without_tls():
    xml = script(cmd("RESTCommand", 1, v_BaseURL="http://www.randomnumberapi.com", v_APIEndPoint="/api",
                     v_APIMethodType="GET", v_userVariableName="vJson"),
                 cmd("StartProcessCommand", 2, v_ProgramName="C:\\x\\app.exe"),
                 cmd("RunTaskCommand", 3, v_taskPath="{Folder.ScriptPath}OK Outro.xml"))
    res = convert(read_robot(xml, "x.xml"))
    assert [s["type"] for s in res.definition["steps"]] == ["fail", "fail", "fail"]
    msgs = [r.message for r in res.report if r.level == "nao_convertivel"]
    assert any("http sem TLS" in m for m in msgs) and any("OK Outro.xml" in m for m in msgs)


def test_write_methods_make_flow_high_risk():
    xml = script(cmd("RESTCommand", 1, v_BaseURL="https://app.lusopay.com:8443", v_APIEndPoint="/web/api/users/{vId}",
                     v_APIMethodType="PUT", v_userVariableName="vR"))
    assert convert(read_robot(xml, "x.xml")).risk_level == "high"


def test_sql_query_uses_parameters():
    xml = script(cmd("DatabaseDefineConnectionCommand", 1,
                     v_ConnectionString="Data Source=1.2.3.4;User ID=x;Password=#pwd", v_ConnectionStringPassword="cifrado"),
                 cmd("DatabaseExecuteQueryCommand", 2, v_Query="select top 1 x from T where contato='{vContacto}'",
                     v_DatasetName="{vTabela}"))
    res = convert(read_robot(xml, "x.xml"))
    q = res.definition["steps"][0]
    assert q["type"] == "sql_query" and q["query"] == "select top 1 x from T where contato=%(vContacto)s"
    assert q["params"] == {"vContacto": "{{ vContacto | text }}"} and q["read_only"] is True
    assert "1.2.3.4" not in json.dumps(res.definition) and res.credentials == {"sql-magnimeios": "mssql"}


def test_multi_if_and_loop_controls():
    cond = json.dumps({"v_IfActionType": "Value", "v_IfActionParameterTable": [
        {"Parameter Name": "Value1", "Parameter Value": "{vA}"},
        {"Parameter Name": "Operand", "Parameter Value": "contains"},
        {"Parameter Name": "Value2", "Parameter Value": "MB"}]})
    xml = script(cmd("BeginNumberOfTimesLoopCommand", 1, v_LoopParameter="5", v_LoopStart="0"),
                 cmd("BeginMultiIfCommand", 2,
                     children=table("v_IfConditionsTable", [{"Statement": "x", "CommandData": cond}] * 2)),
                 cmd("ExitLoopCommand", 3), cmd("ElseCommand", 4), cmd("NextLoopCommand", 5), cmd("EndIfCommand", 6),
                 cmd("EndLoopCommand", 7), variables=("vA",))
    res = convert(read_robot(xml, "x.xml"))
    validate_flow(res.definition, {}, [])
    loop = res.definition["steps"][0]
    assert loop["items_expr"].startswith("range(")
    iff = loop["steps"][0]
    assert iff["condition"].count("taskt_compare") == 2 and " and " in iff["condition"]
    assert iff["then"][0]["type"] == "break" and iff["otherwise"][0]["type"] == "continue"


def test_openbots_json_is_read():
    doc = {"Commands": [
        {"ScriptCommand": {"$type": "OpenBots.Commands.Variable.SetVariableCommand, OpenBots.Commands.Variable",
                           "CommandName": "SetVariableCommand", "v_userVariableName": "vX", "v_Input": "olá {vY}",
                           "IsCommented": False, "LineNumber": 1}},
        {"ScriptCommand": {"CommandName": "ShowMessageCommand", "v_Message": "{vX}", "LineNumber": 2}},
    ], "Variables": [{"VariableName": "vY", "VariableValue": "mundo"}]}
    res = convert(read_robot(json.dumps(doc).encode(), "Main.obscript"))
    assert res.source_format == "openbots"
    assert [s["type"] for s in res.definition["steps"]] == ["set", "log"]
    assert res.definition["steps"][0]["value"] == "olá {{ vY }}" and res.definition["variables"]["vY"] == "mundo"


def test_openbots_zip_project():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Proj/project.obconfig", json.dumps({"ProjectName": "Proj", "Main": "Main.obscript"}))
        z.writestr("Proj/Main.obscript", json.dumps({"Commands": [{"ScriptCommand": {"CommandName": "PauseCommand"}}]}))
        z.writestr("Proj/Outro.obscript", json.dumps({"Commands": []}))
    robot = read_robot(buf.getvalue(), "Proj.zip")
    assert robot.name == "Proj" and "outro.obscript" in robot.subscripts


def test_rejects_garbage_and_xxe():
    with pytest.raises(RobotFormatError):
        read_robot(b"ola", "x.txt")
    xxe = b'<?xml version="1.0"?><!DOCTYPE s [<!ENTITY x SYSTEM "file:///etc/passwd">]><Script><Commands>&x;</Commands></Script>'
    with pytest.raises(Exception):
        read_robot(xxe, "x.xml")


def test_convert_api_and_import(env, clients):
    a = clients["admin"]
    body = {"filename": "OK Saldos.xml", "content_b64": base64.b64encode(SALDOS).decode(), "test_email": "teste@lusopay.com"}
    assert clients["operator"].post("/api/flows/convert", json=body).status_code == 403
    r = a.post("/api/flows/convert", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["valid"] and out["key"] == "saldos-importado"
    assert {c["name"]: c["exists"] for c in out["credentials"]} == {"cyclos-producao": False, "smtp-lusopay": False}
    imp = {"key": out["key"], "name": out["name"], "risk_level": out["risk_level"], "definition": out["definition"]}
    assert "credencial inexistente" in a.post("/api/flows/import", json=imp).text
    a.post("/api/admin/credentials", json={"name": "cyclos-producao", "kind": "http_basic",
                                           "fields": {"username": "u", "password": "p-123456"}})
    a.post("/api/admin/credentials", json={"name": "smtp-lusopay", "kind": "smtp", "fields": {
        "host": "mail.lusopay.com", "port": 587, "username": "a@lusopay.com", "password": "p-123456",
        "from_address": "a@lusopay.com"}})
    assert a.post("/api/flows/import", json=imp).status_code == 200
    assert a.post("/api/flows/convert", json=body).json()["key_taken"] is True


def test_delete_flow(env, clients):
    from conftest import run_bot

    a = clients["admin"]
    a.post("/api/flows", json={"key": "apagar-me", "name": "Apagar", "risk_level": "low",
                               "definition": {"steps": [{"id": "l", "type": "log", "message": "x"}]}})
    assert clients["operator"].delete("/api/flows/apagar-me").status_code == 403
    assert a.delete("/api/flows/apagar-me").json() == {"result": "deleted"}
    assert a.get("/api/flows/apagar-me").status_code == 404
    # com histórico fica arquivado
    a.post("/api/flows", json={"key": "com-historico", "name": "Hist", "risk_level": "low",
                               "definition": {"steps": [{"id": "l", "type": "log", "message": "x"}]}})
    a.patch("/api/admin/bots/com-historico", json={"enabled": True})
    rid = run_bot(clients["operator"], "com-historico").json()["run_id"]
    assert a.delete("/api/flows/com-historico").status_code == 409  # execução em curso
    clients["operator"].post(f"/api/runs/{rid}/cancel")
    assert a.delete("/api/flows/com-historico").json() == {"result": "archived"}
    assert "com-historico" not in [b["key"] for b in a.get("/api/bots").json()]
    assert a.get(f"/api/runs/{rid}").status_code == 200  # o histórico mantém-se


CONTROLO = script(
    cmd("BeginIfCommand", 1, v_IfActionType="File Exists",
        children=table("v_IfActionParameterTable", [
            {"Parameter Name": "File Path", "Parameter Value": "{Folder.ScriptPath}Listas\\ultimo id.txt"},
            {"Parameter Name": "True When", "Parameter Value": "It Does Not Exist"}])),
    cmd("StopTaskCommand", 2),
    cmd("EndIfCommand", 3),
    cmd("ReadTextFileCommand", 4, v_FilePath="{Folder.ScriptPath}Listas\\ultimo id.txt", v_userVariableName="vUltimo"),
    cmd("RESTCommand", 5, v_BaseURL="https://dev.lusopay.com:8444", v_APIEndPoint="/web_dev/api/users?after={vUltimo}",
        v_APIMethodType="GET", v_userVariableName="vJson"),
    cmd("ParseJSONArrayCommand", 6, v_InputValue="{vJson}", v_applyToVariableName="vLista"),
    cmd("VariableCommand", 7, v_userVariableName="vIndex", v_Input="0"),
    cmd("BeginListLoopCommand", 8, v_LoopParameter="{vLista}"),
    # dentro do ciclo, {vLista} continua a designar a lista inteira (como no taskt)
    cmd("GetListItemCommand", 9, v_ListName="{vLista}", v_ItemIndex="{vIndex}", v_UserVariableName="vId"),
    cmd("WriteTextFileCommand", 10, v_FilePath="{Folder.ScriptPath}Listas\\ultimo id.txt", v_TextToWrite="{vId}",
        v_Overwrite="Overwrite"),
    cmd("MathCalculationCommand", 11, v_InputValue="{vIndex}+1", v_applyToVariableName="vIndex"),
    cmd("EndLoopCommand", 12),
    variables=("vUltimo", "vJson", "vLista", "vIndex", "vId"),
)


def test_control_files_become_persistent(tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker"))
    import httpx
    from lusopay_worker.flowengine import Engine

    res = convert(read_robot(CONTROLO, "OK Controlo.xml"))
    assert res.definition["persistent_files"] == ["ultimo id.txt"]
    assert "Ficheiros persistentes" in res.report[0].message
    validate_flow(res.definition, res.credentials, [])
    (tmp_path / "ultimo id.txt").write_text("5", encoding="utf-8")
    seen = []

    def api(r):
        seen.append(str(r.url))
        return httpx.Response(200, json=["6", "7"])

    creds = {"cyclos-dev": {"kind": "http_basic", "username": "u", "password": "p"}}
    eng = Engine({"run_id": "r", "flow": {"version": 1, "definition": res.definition}, "credentials": creds,
                  "allowed_hosts": []}, tmp_path, emit=lambda line: None, http_client=httpx.Client(transport=httpx.MockTransport(api)))
    out = eng.run()
    assert out["status"] == "SUCCEEDED", out
    assert seen[0].endswith("after=5")
    assert (tmp_path / "ultimo id.txt").read_text(encoding="utf-8") == "7"


def _ob(name, line, **attrs):
    return {"ScriptCommand": {"$type": f"OpenBots.Commands.X.{name}, OpenBots.Commands.Core", "CommandName": name,
                              "LineNumber": line, "IsCommented": False, "CommandEnabled": True, **attrs}}


def _ob_block(begin, children):
    return {**begin, "AdditionalScriptCommands": children}


def _openbots_project(zip_names_cp850=False):
    import io
    import zipfile

    out = "v_OutputUserVariableName"
    main = {"Commands": [
        _ob("AddCodeCommentCommand", 1, v_Comment="Projeto de teste"),
        _ob("RunTaskCommand", 2, v_TaskPath="{Folder.ScriptPath}\\Recolha das Configurações\\Main.obscript"),
        _ob("NewSecureStringCommand", 3, v_Input="segredo-literal", **{out: "{vSenha}"}),
        _ob("ReadTextFileCommand", 4, v_FilePath="{ProjectPath}\\Relatórios\\Último id.txt", **{out: "{vUltimo}"}),
        _ob("RunTaskCommand", 5, v_TaskPath="{ProjectPath}\\Processa.obscript", v_AssignArguments=True,
            v_ArgumentAssignments=[
                {"ArgumentName": "{vInicio}", "ArgumentValue": "{vUltimo}", "ArgumentDirection": "In"},
                {"ArgumentName": "{vFim}", "ArgumentValue": "{vUltimo}", "ArgumentDirection": "Out"}]),
        _ob("WriteCreateTextFileCommand", 6, v_FilePath="{ProjectPath}\\Relatórios\\Último id.txt",
            v_TextToWrite="{vUltimo}", v_Overwrite="Overwrite"),
    ], "Variables": [{"VariableName": "{vUltimo}", "VariableValue": ""}]}
    sub = {"Commands": [
        _ob("ExecuteRESTAPICommand", 1, v_BaseURL="https://dev.lusopay.com:8444",
            v_APIEndPoint="/web_dev/api/users?after={vInicio}", v_APIMethodType="GET", v_RESTParameters=[],
            v_AdvancedParameters=[{"Parameter Name": "Authorization", "Parameter Value": "{vSenha}",
                                   "Parameter Type": "HttpHeader"}], **{out: "{vJson}"}),
        _ob("RegexReplaceCommand", 2, v_InputText="{vJson}", v_Regex="[\\[\\]\"]", v_ReplacementText="",
            **{out: "{vTexto}"}),
        _ob("SplitTextCommand", 3, v_InputText="{vTexto}", v_SplitCharacter=",", **{out: "{vIds}"}),
        _ob("SetVariableCommand", 4, v_Input="{vInicio}", **{out: "{vFim}"}),
        _ob_block(_ob("LoopCollectionCommand", 5, v_LoopParameter="{vIds}", **{out: "{vId}"}), [
            _ob_block(_ob("BeginSwitchCommand", 6, v_SwitchValue="{vId}"), [
                _ob("CaseCommand", 7, v_CaseValue="13"),
                _ob("ThrowCommand", 8, v_ExceptionMessage="id 13 proibido"),
                _ob("CaseCommand", 9, v_CaseValue="Default"),
                _ob("SetVariableCommand", 10, v_Input="{vId}", **{out: "{vFim}"}),
                _ob("EndSwitchCommand", 11)]),
            _ob("EndLoopCommand", 12)]),
    ]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Robots/Projeto X/project.obconfig", json.dumps({"ProjectName": "Projeto X", "Main": "Main.obscript"}))
        z.writestr("Robots/Projeto X/Main.obscript", json.dumps(main))
        z.writestr("Robots/Projeto X/Processa.obscript", json.dumps(sub))
        rel = "Robots/Projeto X/Relatórios/Último id.txt"
        if zip_names_cp850:  # como a "Pasta comprimida" do Windows: nomes em cp850, sem a marca UTF-8
            class Cp850Info(zipfile.ZipInfo):
                def _encodeFilenameFlags(self):  # noqa: N802
                    return self.filename.encode("cp850"), self.flag_bits & ~0x800

            z.writestr(Cp850Info(rel), "10")
        else:
            z.writestr(rel, "10")
        z.writestr("Robots/Config.txt", "RPATaskt,Basic nao-ler,")
        z.writestr("Robots/OK Outro.xml", script(cmd("PauseCommand", 1)).decode())
    return buf.getvalue()


@pytest.mark.parametrize("cp850", [False, True])
def test_openbots_project_with_subscript_runs(tmp_path, cp850):
    import sys
    from pathlib import Path

    from botmanager.flows.converters.batch import split_robots

    robots = dict(split_robots(_openbots_project(cp850)))
    assert sorted(robots) == ["OK Outro.xml", "Projeto X.zip"]
    res = convert(read_robot(robots["Projeto X.zip"], "Projeto X.zip"))
    assert res.name == "Projeto X" and res.key == "projeto-x-importado"
    assert res.definition["persistent_files"] == ["Último id.txt"] and res.data_files == {"Último id.txt": b"10"}
    assert "segredo-literal" not in json.dumps(res.definition)
    assert res.stats.get("nao_convertivel", 0) == 0, [r for r in res.report if r.level == "nao_convertivel"]
    validate_flow(res.definition, res.credentials, [])

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker"))
    import httpx
    from lusopay_worker.flowengine import Engine

    seen = []

    def api(r):
        seen.append(str(r.url))
        return httpx.Response(200, json=["11", "12"])

    (tmp_path / "Último id.txt").write_text("10", encoding="utf-8")
    creds = {"cyclos-dev": {"kind": "http_basic", "username": "u", "password": "p"}}
    out = Engine({"run_id": "r", "flow": {"version": 1, "definition": res.definition}, "credentials": creds,
                  "allowed_hosts": []}, tmp_path, emit=lambda line: None,
                 http_client=httpx.Client(transport=httpx.MockTransport(api))).run()
    assert out["status"] == "SUCCEEDED", out
    assert seen[0].endswith("after=10")
    assert (tmp_path / "Último id.txt").read_text(encoding="utf-8") == "12"


def test_batch_import_endpoint(env, clients):
    a = clients["admin"]
    a.post("/api/admin/credentials", json={"name": "cyclos-dev", "kind": "http_basic",
                                           "fields": {"username": "u", "password": "p"}})
    body = {"content_b64": base64.b64encode(_openbots_project()).decode(), "test_email": "t@lusopay.com"}
    rows = {r["file"]: r for r in a.post("/api/flows/import-batch", json=body).json()}
    assert rows["Projeto X.zip"]["status"] == "criado" and rows["OK Outro.xml"]["status"] == "criado"
    url = "/api/flows/projeto-x-importado/files/Último id.txt"
    assert a.get(url).content == b"10"
    assert clients["admin"].get("/api/bots/projeto-x-importado").json()["enabled"] is False
    # reimportar: nova versão e o ficheiro persistente atual não é substituído
    a.put(url, json={"content_b64": base64.b64encode(b"55").decode()})
    rows = {r["file"]: r for r in a.post("/api/flows/import-batch", json=body).json()}
    assert rows["Projeto X.zip"]["status"] == "nova_versao" and a.get(url).content == b"55"
    assert clients["operator"].post("/api/flows/import-batch", json=body).status_code == 403

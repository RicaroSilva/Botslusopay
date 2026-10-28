"""Normalização dos comandos OpenBots (Studio 1.x) para os nomes e atributos equivalentes do taskt.

O OpenBots herdou a maior parte dos comandos do taskt, mas mudou nomes (ExecuteRESTAPICommand, SetVariableCommand…)
e atributos (v_OutputUserVariableName para a variável de saída, v_InputText para o texto de entrada…). Depois de
normalizado, cada comando é traduzido pelo mesmo código que os robôs taskt. Mapeamento confirmado com projetos reais.
"""
from __future__ import annotations

from .model import Command

OUT = "v_OutputUserVariableName"

# tipo OpenBots → (tipo taskt, {atributo OpenBots: atributo taskt})
MAP: dict[str, tuple[str, dict[str, str]]] = {
    "AddCodeCommentCommand": ("CommentCommand", {}),
    "SetVariableCommand": ("VariableCommand", {OUT: "v_userVariableName"}),
    "ExecuteRESTAPICommand": ("RESTCommand", {OUT: "v_userVariableName"}),
    "ParseJSONModelCommand": ("ParseJsonModelCommand", {"v_JsonObject": "v_InputValue"}),
    "ParseJSONArrayCommand": ("ParseJSONArrayCommand", {"v_JsonArrayName": "v_InputValue", OUT: "v_applyToVariableName"}),
    "GetListItemCommand": ("GetListItemCommand", {OUT: "v_UserVariableName"}),
    "GetListCountCommand": ("GetListCountCommand", {OUT: "v_UserVariableName"}),
    "ReadTextFileCommand": ("ReadTextFileCommand", {OUT: "v_userVariableName"}),
    "WriteCreateTextFileCommand": ("WriteTextFileCommand", {}),
    "LoopCollectionCommand": ("BeginListLoopCommand", {OUT: "v_LoopItemVariable"}),
    "LoopNumberOfTimesCommand": ("BeginNumberOfTimesLoopCommand", {}),
    "LoopContinuouslyCommand": ("BeginContinousLoopCommand", {}),
    "FormatDateCommand": ("FormatDataCommand", {"v_InputData": "v_InputValue", "v_InputDate": "v_InputValue",
                                                OUT: "v_applyToVariableName"}),
    "DateCalculationCommand": ("DateCalculationCommand", {"v_InputDate": "v_InputValue", OUT: "v_applyToVariableName"}),
    "MathCalculationCommand": ("MathCalculationCommand", {"v_MathExpression": "v_InputValue", OUT: "v_applyToVariableName",
                                                          "v_DecimalSeparator": "v_DecimalSeperator"}),
    "ReplaceTextCommand": ("StringReplaceCommand", {"v_InputText": "v_userVariableName", "v_OldText": "v_replacementText",
                                                    "v_NewText": "v_replacementValue", OUT: "v_applyToVariableName"}),
    "SplitTextCommand": ("StringSplitCommand", {"v_InputText": "v_userVariableName", "v_SplitCharacter": "v_splitCharacter",
                                                OUT: "v_applyConvertToUserVariableName"}),
    "ModifyStringCommand": ("ModifyVariableCommand", {"v_InputText": "v_userVariableName", "v_TextOperation": "v_ConvertType",
                                                      OUT: "v_applyToVariableName"}),
    "TextExtractionCommand": ("TextExtractorCommand", {"v_InputText": "v_InputValue", OUT: "v_applyToVariableName"}),
    "RegexReplaceCommand": ("RegexReplaceCommand", {"v_InputText": "v_InputValue", OUT: "v_applyToVariableName"}),
    "RegexSplitCommand": ("RegexSplitCommand", {"v_InputText": "v_InputValue", OUT: "v_applyToVariableName"}),
    "GetFilesCommand": ("GetFilesCommand", {OUT: "v_UserVariableName"}),
    "ExecuteDatabaseQueryCommand": ("DatabaseExecuteQueryCommand", {OUT: "v_DatasetName"}),
    "DefineDatabaseConnectionCommand": ("DatabaseDefineConnectionCommand", {}),
    "GetDataRowCountCommand": ("GetDataRowCountCommand", {"v_DataTable": "v_DataTableName", OUT: "v_UserVariableName"}),
    "GetDataRowCommand": ("GetDataRowCommand", {"v_DataTable": "v_DataTableName", OUT: "v_UserVariableName"}),
    "GetDataRowValueCommand": ("GetDataRowValueCommand", {"v_DataRow": "v_DataRowName", OUT: "v_UserVariableName"}),
    "CreateDataTableCommand": ("CreateDataTableCommand", {OUT: "v_applyToVariableName"}),
    "FilterDataTableCommand": ("FilterDataTableCommand", {OUT: "v_applyToVariableName"}),
    "SendSMTPEmailCommand": ("SMTPSendEmailCommand", {"v_SMTPRecipients": "v_SMTPToEmail",
                                                      "v_SMTPAttachments": "v_SMTPAttachment"}),
    "LogMessageCommand": ("LogDataCommand", {}),
    "ShowMessageCommand": ("MessageBoxCommand", {}),
    "PauseScriptCommand": ("PauseCommand", {}),
    "GetExceptionMessageCommand": ("GetExceptionMessageCommand", {OUT: "v_applyToVariableName"}),
    "NewSecureStringCommand": ("NewSecureStringCommand", {OUT: "v_applyToVariableName"}),
    "BeginTryCommand": ("TryCommand", {}),
    "CatchCommand": ("CatchExceptionCommand", {}),
    "StopCurrentTaskCommand": ("StopTaskCommand", {}),
    "MoveCopyFileCommand": ("MoveFileCommand", {}),
    "RunTaskCommand": ("RunTaskCommand", {"v_TaskPath": "v_taskPath"}),
}

CONDITION_KINDS = {"Value Compare": "Value"}


def normalize(cmd: Command) -> Command:
    new_type, attr_map = MAP.get(cmd.type, (cmd.type, {}))
    cmd.type = new_type
    cmd.attrs = {attr_map.get(k, k): v for k, v in cmd.attrs.items()}
    if "v_ActionParameterTable" in cmd.tables:  # Begin If / Loop Condition
        cmd.tables["v_IfActionParameterTable"] = cmd.tables.pop("v_ActionParameterTable")
    if new_type == "FormatDataCommand":
        cmd.attrs.setdefault("v_FormatType", "Date")
    if cmd.attrs.get("v_IfActionType") in CONDITION_KINDS:
        cmd.attrs["v_IfActionType"] = CONDITION_KINDS[cmd.attrs["v_IfActionType"]]
    return cmd

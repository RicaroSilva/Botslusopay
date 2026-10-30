from pathlib import Path

from lusopay_worker.tasktlog import LogTailer, parse_result

S = Path(r"C:\Users\bot\Documents\taskt\My Scripts\OK Saldos.xml")


def L(t, msg):
    return f"2026-10-27 10:00:{t} +00:00 [INF] {msg}"


def test_success():
    lines = [L("00.000", f"Script Path: {S}"), L("01.000", "Running Line 1"), L("02.000", "Result Code: Successful"),
             L("02.001", "Error: None")]
    r = parse_result(lines, S)
    assert r.result_code == "Successful" and r.errors == []


def test_error_message_collected():
    lines = [L("00.000", f"Script Path: {S}"), L("02.000", "Result Code: Error"),
             L("02.001", "Error: System.IO.FileNotFoundException: Config.txt")]
    r = parse_result(lines, S)
    assert r.result_code == "Error"


def test_nested_run_task_in_other_file_sorted_by_time():
    parent = [L("00.000", f"Script Path: {S}"), L("05.000", "Running Line 9"), L("09.000", "Result Code: Error")]
    child = [L("01.000", r"Script Path: C:\x\Ok Recolha das Configurações.xml"), L("02.000", "Result Code: Successful")]
    r = parse_result(parent + child, S)
    assert r.result_code == "Error" and r.nested_scripts == ["Ok Recolha das Configurações.xml"]


def test_previous_runs_ignored_and_missing_result_undetermined():
    lines = [L("00.000", r"Script Path: C:\x\Outro.xml"), L("00.500", "Result Code: Successful"),
             L("01.000", f"Script Path: {S}"), L("02.000", "Running Line 3")]
    r = parse_result(lines, S)
    assert r.matched_script and r.result_code is None and "Result Code" in r.reason


def test_script_not_found():
    r = parse_result([L("00.000", "Engine Class has been initialized")], S)
    assert not r.matched_script and r.result_code is None


def test_handled_errors():
    lines = [L("00.000", f"Script Path: {S}"), L("01.000", "Error Occured at Line 12:System.Exception: x"),
             L("02.000", "Result Code: Successful")]
    assert parse_result(lines, S).handled_error_lines == [12]


def test_tailer_reads_only_new_complete_lines(tmp_path):
    f = tmp_path / "taskt Engine Logs20261027.txt"
    f.write_text("antigo 1\nantigo 2\n", encoding="utf-8")
    t = LogTailer(tmp_path)
    t.snapshot()
    with f.open("a", encoding="utf-8") as fh:
        fh.write("novo 1\nnovo parcial")
    assert t.read_new() == ["novo 1"]
    with f.open("a", encoding="utf-8") as fh:
        fh.write(" fim\n")
    (tmp_path / "taskt Engine Logs20261027_001.txt").write_text("filho\n", encoding="utf-8")
    assert sorted(t.read_new()) == ["filho", "novo parcial fim"]

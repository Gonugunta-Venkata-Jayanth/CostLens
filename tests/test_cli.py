import json

from costlens.__main__ import main


def test_cli_generate_seed_ingest_report(tmp_path, capsys):
    db = str(tmp_path / "c.duckdb")
    csv = str(tmp_path / "cur.csv")
    assert main(["generate", csv, "--days", "40"]) == 0
    assert main(["seed", "--db", db, "--days", "40"]) == 0
    assert main(["seed", "--db", db, "--if-empty"]) == 0
    assert "skipping" in capsys.readouterr().out
    assert main(["ingest", csv, "--db", db]) == 0
    capsys.readouterr()
    assert main(["report", "--db", db]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {"summary", "forecast", "anomalies"} <= set(report)

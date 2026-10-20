def test_cli_run_and_approve_roundtrip(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out1 = capsys.readouterr().out
    assert "pending_review" in out1
    assert "AI Agent 一周动态" in out1

    draft_id = out1.split("draft_id=")[1].split()[0]
    cli.main(["approve", draft_id])
    out2 = capsys.readouterr().out
    assert "published" in out2
    assert (tmp_path / "demo_published.json").exists()

from types import SimpleNamespace

from finagent import cli


def test_tools_demo_does_not_create_orders(monkeypatch, capsys):
    calls = []

    def fake_call_tool(name, args):
        calls.append(name)
        return {"ok": True}, 0.0

    monkeypatch.setattr(cli, "call_tool", fake_call_tool)
    cli.tools_demo()
    capsys.readouterr()
    assert "draft_order" not in calls


def test_ask_returns_nonzero_when_model_fails(monkeypatch, capsys):
    trace = SimpleNamespace(
        stop_reason="llm_error",
        final_answer="",
        steps=[SimpleNamespace(error="provider unavailable")],
    )

    class FakeAgent:
        def run(self, query):
            return trace

    monkeypatch.setattr(cli, "make_agent", lambda: FakeAgent())
    monkeypatch.setattr(cli, "print_trace", lambda _: None)
    assert cli.main(["ask", "test query"]) == 1
    assert "provider unavailable" in capsys.readouterr().err

from worker.rpc.protocol import Request, Response


def test_request_serializes_with_unique_ids():
    a, b = Request(method="ping"), Request(method="ping")
    ja, jb = a.to_json(), b.to_json()
    assert ja["jsonrpc"] == "2.0" and ja["method"] == "ping"
    assert ja["id"] != jb["id"]  # correlation id 全局递增


def test_response_parses_result_and_error():
    ok = Response.from_json({"jsonrpc": "2.0", "id": 7, "result": {"x": 1}})
    err = Response.from_json({"jsonrpc": "2.0", "id": 8, "error": "boom"})
    assert ok.id == 7 and ok.result == {"x": 1} and ok.error is None
    assert err.error == "boom" and err.result is None

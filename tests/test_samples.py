import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

import python.mcp_server.server as policy_server
from python.mcp_server.server import create_app, search_policy
from python.loop.loop_demo import validate_url


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def dotnet_mcp_server(settings=None, assembly=None):
    assembly = assembly or ROOT / "dotnet/mcp_server/bin/Debug/net10.0/PolicyMcpServer.dll"
    assert assembly.exists(), "Run dotnet build dotnet/mcp_server first"
    environment = os.environ | {
        "MCP_AUTH_TOKEN": "test-token-not-a-secret", "MCP_HOST": "127.0.0.1",
        "MCP_PUBLIC_HOST": "policy.example.test", "PORT": "0", "DOTNET_ENVIRONMENT": "Production",
    } | (settings or {})
    environment = {name: value for name, value in environment.items() if value is not None}
    with subprocess.Popen(["dotnet", str(assembly)], cwd=ROOT, env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
        started = queue.Queue()
        output = []

        def read_output():
            for line in process.stdout:
                output.append(line)
                if "Now listening on: " in line:
                    started.put(line.split("Now listening on: ", 1)[1].strip() + "/mcp")

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            try:
                url = started.get(timeout=15)
            except queue.Empty:
                pytest.fail(".NET MCP server did not start: " + "".join(output))
            yield url
        finally:
            process.terminate()
            process.wait(timeout=10)
            reader.join(timeout=10)
        assert "test-token-not-a-secret" not in "".join(output)


@pytest.fixture(params=["python", "dotnet"])
def mcp_url(request, monkeypatch):
    if request.param == "dotnet":
        with dotnet_mcp_server() as url:
            yield url
        return
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token-not-a-secret")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "policy.example.test")
    ready = threading.Event()

    class TestServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = TestServer(uvicorn.Config(create_app(), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        assert ready.wait(10), "MCP server did not start"
        try:
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@contextmanager
def model_endpoint(fail_request=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if fail_request:
                self.send_error(400, "Scripted model failure")
                return
            identifier = f"resp_{len(requests)}"
            if self.path.endswith("chat/completions"):
                messages = body["messages"]
                if messages[-1]["role"] == "tool":
                    message = {"role": "assistant", "content": "USD 200 hotel limit [TRAVEL-002]. Exceptions need Finance approval [TRAVEL-003]."}
                    finish = "stop"
                else:
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": f"call_{len(requests)}", "type": "function",
                        "function": {"name": "search_policy", "arguments": '{"query":"hotel exceptions"}'},
                    }]}
                    finish = "tool_calls"
                response = {"id": identifier, "object": "chat.completion", "created": 1, "model": "test-model",
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
            else:
                tools = body.get("tools", [])
                hosted = any(tool["type"] == "mcp" for tool in tools)
                inputs = body.get("input", [])
                approval = next((item for item in inputs if item.get("type") == "mcp_approval_response"), None)
                tool_result = any(item.get("type") == "function_call_output" for item in inputs)
                if hosted and tools[0].get("require_approval") == "always" and not approval:
                    output = [{"type": "mcp_approval_request", "id": f"approval_{len(requests)}",
                               "server_label": "policy_kb", "name": "search_policy", "arguments": '{"query":"hotel exceptions"}'}]
                elif hosted or tool_result:
                    text = "Tool denied." if approval and not approval["approve"] else "USD 200 hotel limit [TRAVEL-002]. Exceptions need Finance approval [TRAVEL-003]."
                    output = [{"type": "message", "id": f"msg_{len(requests)}", "role": "assistant", "status": "completed",
                               "content": [{"type": "output_text", "text": text, "annotations": []}]}]
                else:
                    output = [{"type": "function_call", "id": f"fc_{len(requests)}", "call_id": f"call_{len(requests)}",
                               "name": "search_policy", "arguments": '{"query":"hotel exceptions"}', "status": "completed"}]
                response = {"id": identifier, "object": "response", "created_at": 1, "status": "completed",
                            "model": "test-model", "output": output, "error": None, "incomplete_details": None,
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if self.path.endswith("chat/completions"):
                    delta = dict(message)
                    if "tool_calls" in delta:
                        delta["tool_calls"] = [dict(call, index=index) for index, call in enumerate(delta["tool_calls"])]
                    for content, reason in [(delta, None), ({}, finish)]:
                        chunk = {"id": identifier, "object": "chat.completion.chunk", "created": 1,
                                 "model": "test-model", "choices": [{"index": 0, "delta": content, "finish_reason": reason}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    events = [{"type": "response.created", "response": dict(response, status="in_progress", output=[])}]
                    for index, item in enumerate(response["output"]):
                        initial = dict(item, arguments="", status="in_progress") if item["type"] == "function_call" else item
                        events.append({"type": "response.output_item.added", "output_index": index, "item": initial})
                        if item["type"] == "message":
                            part = item["content"][0]
                            events.extend([
                                {"type": "response.content_part.added", "output_index": index, "content_index": 0,
                                 "item_id": item["id"], "part": dict(part, text="")},
                                {"type": "response.output_text.delta", "output_index": index, "content_index": 0,
                                 "item_id": item["id"], "delta": part["text"], "logprobs": []},
                                {"type": "response.output_text.done", "output_index": index, "content_index": 0,
                                 "item_id": item["id"], "text": part["text"], "logprobs": []},
                                {"type": "response.content_part.done", "output_index": index, "content_index": 0,
                                 "item_id": item["id"], "part": part},
                            ])
                        elif item["type"] == "function_call":
                            events.append({"type": "response.function_call_arguments.delta", "output_index": index,
                                           "item_id": item["id"], "delta": item["arguments"]})
                            events.append({"type": "response.function_call_arguments.done", "output_index": index,
                                           "item_id": item["id"], "arguments": item["arguments"], "name": item["name"]})
                        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
                    events.append({"type": "response.completed", "response": response})
                    for sequence, event in enumerate(events):
                        event["sequence_number"] = sequence
                        self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
                return
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_sample(language, mode, mcp_url, base_url, extra=(), stdin="", expect_success=True,
               configuration_directory=None, development=False, deployment_override=None):
    if language == "dotnet":
        if not shutil.which("dotnet"):
            pytest.skip(".NET SDK not installed")
        assembly = ROOT / "dotnet/loop/bin/Debug/net10.0/LoopDemo.dll"
        assert assembly.exists(), "Run dotnet build dotnet/loop first"
        command = ["dotnet", str(assembly)]
    else:
        command = [sys.executable, str(ROOT / "python/loop/loop_demo.py")]
    environment = os.environ | {
        "AZURE_OPENAI_API_KEY": "test-model-key", "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_ENDPOINT": base_url, "MCP_SERVER_URL": mcp_url,
        "OPENAI_API_KEY": "unused-openai-key", "OPENAI_MODEL": "unused-openai-model",
        "OPENAI_BASE_URL": "http://127.0.0.1:1/unused/",
        "MCP_AUTH_TOKEN": "test-token-not-a-secret", "PYTHONUTF8": "1",
        "DOTNET_ENVIRONMENT": "Production", "PYTHON_DOTENV_DISABLED": "1",
    }
    if configuration_directory is not None:
        settings = {name: environment.pop(name) for name in (
            "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME", "AZURE_OPENAI_ENDPOINT",
            "MCP_SERVER_URL", "MCP_AUTH_TOKEN",
        )}
        if language == "dotnet":
            shutil.copytree(assembly.parent, configuration_directory, dirs_exist_ok=True)
            command = ["dotnet", str(configuration_directory / "LoopDemo.dll")]
            (configuration_directory / "appsettings.json").write_text(
                json.dumps(settings | ({"AZURE_OPENAI_ENDPOINT": "invalid-base-endpoint"} if development else {})),
                encoding="utf-8",
            )
            (configuration_directory / "appsettings.development.json").write_text(
                json.dumps(settings if development else {"AZURE_OPENAI_ENDPOINT": "must-not-load"}), encoding="utf-8",
            )
            environment.update(DOTNET_ENVIRONMENT="Development" if development else "Production",
                               APPDATA=str(configuration_directory / "user-data"), HOME=str(configuration_directory / "home"))
        else:
            script_directory = configuration_directory / "python/loop"
            script_directory.mkdir(parents=True)
            shutil.copy2(ROOT / "python/loop/loop_demo.py", script_directory / "loop_demo.py")
            command = [sys.executable, str(script_directory / "loop_demo.py")]
            (script_directory / ".env").write_text(
                "\n".join(f"{name}={value}" for name, value in settings.items()), encoding="utf-8",
            )
            environment["PYTHON_DOTENV_DISABLED"] = "0"
    if deployment_override is not None:
        environment["AZURE_OPENAI_DEPLOYMENT_NAME"] = deployment_override
    result = subprocess.run(command + ([mode] if mode is not None else []) + list(extra), cwd=ROOT, env=environment,
                            input=stdin, capture_output=True, text=True, timeout=45)
    assert (result.returncode == 0) == expect_success, result.stdout + result.stderr
    assert "test-model-key" not in result.stdout + result.stderr
    assert "test-token-not-a-secret" not in result.stdout + result.stderr
    assert "\x1b[" not in result.stdout + result.stderr, "Redirected output must not contain color codes"
    if expect_success:
        assert_turn_timings(result.stdout, result.stdout.count("[turn]"))
    return result


def assert_turn_timings(output, expected_count):
    starts = re.findall(r"\[timing start\] mode=([^;]+); start_utc=(\S+)", output)
    summaries = re.findall(
        r"\[timing\] mode=([^;]+); start_utc=(\S+); end_utc=(\S+); elapsed_seconds=(\d+\.\d{3}) \(includes approval wait\)",
        output,
    )
    assert len(starts) == len(summaries) == expected_count, output
    for (start_mode, start_value), (mode, start, end, elapsed) in zip(starts, summaries):
        assert mode == start_mode
        assert mode in {"chat", "responses", "hosted-mcp"}
        assert start == start_value
        started_at, ended_at = datetime.fromisoformat(start), datetime.fromisoformat(end)
        assert started_at.utcoffset() == ended_at.utcoffset() == timedelta(0)
        assert ended_at >= started_at
        assert float(elapsed) >= 0
        assert abs((ended_at - started_at).total_seconds() - float(elapsed)) < 0.1


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("stream", [False, True])
def test_timing_on_model_failure(language, stream):
    with model_endpoint(fail_request=True) as (base_url, requests):
        result = run_sample(language, "hosted-mcp", "https://mcp.example.com/mcp", base_url,
                            ["--stream"] if stream else [], expect_success=False)
    assert len(requests) == 1
    assert_turn_timings(result.stdout, 1)


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("choice", ["1", "2", "3"])
def test_menu_repeats_with_fresh_sessions(language, choice, mcp_url):
    hosted = choice in {"2", "3"}
    selections = {"1": "1\n1\n4\n", "2": "2\ny\ny\n2\nn\nn\n4\n", "3": "3\n3\n4\n"}[choice]
    with model_endpoint() as (base_url, requests):
        result = run_sample(language, None, "https://mcp.example.com/mcp" if hosted else mcp_url,
                            base_url, stdin=selections)
    assert result.stdout.count("4 - Exit") == 3
    assert result.stdout.count("Provider: Azure OpenAI") == 2
    # Approval adds a second Responses request per turn; auto-approve does not.
    assert len(requests) == (4 if choice == "3" else 8)
    assert all(body["stream"] for _, body in requests)
    if hosted:
        first_requests = (0, 2) if choice == "3" else (0, 4)
        follow_ups = (1, 3) if choice == "3" else (2, 6)
        assert all(path == "/openai/v1/responses" for path, _ in requests)
        assert all(body["tools"][0]["type"] == "mcp" for _, body in requests)
        assert all(body["tools"][0]["require_approval"] == ("never" if choice == "3" else "always") for _, body in requests)
        assert not any(requests[index][1].get("previous_response_id") for index in first_requests)
        assert all(requests[index][1].get("previous_response_id") for index in follow_ups)
        assert "[app -> MCP]" not in result.stderr
        assert result.stdout.count("app MCP HTTP requests=0") == 4
        assert result.stdout.count("MCP approval: auto" if choice == "3" else "MCP approval: prompt") == 2
        approvals = [item for _, body in requests for item in body.get("input", [])
                     if item.get("type") == "mcp_approval_response"]
        assert [item["approve"] for item in approvals] == ([] if choice == "3" else [True, True, False, False])
        assert ("Allow search_policy" in result.stdout) == (choice == "2")
    else:
        assert all(path == "/openai/v1/chat/completions" for path, _ in requests)
        assert all(body["tools"][0]["type"] == "function" for _, body in requests)
        assert "[app -> MCP]" in result.stderr
        for index in (0, 4):
            assert sum(message["role"] == "user" for message in requests[index][1]["messages"]) == 1
            assert not any(message["role"] == "tool" for message in requests[index][1]["messages"])


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("selections", ["4\n", "", "invalid\n\n4\n"])
def test_menu_exit_and_invalid_selection(language, selections):
    result = run_sample(language, None, "", "", stdin=selections)
    assert "4 - Exit" in result.stdout
    assert "[model]" not in result.stderr
    assert "Demo failed" not in result.stderr
    if selections.startswith("invalid"):
        assert result.stdout.count("Select 1, 2, 3, or 4.") == 2


@pytest.mark.parametrize("language", ["python", "dotnet"])
def test_menu_recovers_from_configuration_errors(language):
    result = run_sample(language, None, "", "", stdin="1\n2\n3\n4\n")
    assert result.stdout.count("4 - Exit") == 4
    assert result.stderr.count("Demo failed") == 3
    assert "[model]" not in result.stderr


@pytest.mark.parametrize(("language", "development"), [("dotnet", False), ("dotnet", True), ("python", False)])
@pytest.mark.parametrize("deployment_override", [None, "environment-deployment"])
def test_file_configuration(language, development, deployment_override, tmp_path):
    with model_endpoint() as (base_url, requests):
        result = run_sample(language, "hosted-mcp", "https://mcp.example.com/mcp", base_url,
                            ["--auto-approve"], configuration_directory=tmp_path, development=development,
                            deployment_override=deployment_override)
    assert "TRAVEL-002" in result.stdout
    assert len(requests) == 2
    assert all(path == "/openai/v1/responses" and body["model"] == (deployment_override or "test-deployment")
               for path, body in requests)


def test_mcp_server_file_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    (tmp_path / "mcp_server").mkdir()
    (tmp_path / "mcp_server/.env").write_text("MCP_HOST=127.0.0.1\nPORT=8123\nMCP_AUTH_TOKEN=test-env-token\n", encoding="utf-8")
    monkeypatch.setattr(policy_server, "__file__", str(tmp_path / "mcp_server/server.py"))
    monkeypatch.setattr(sys, "argv", ["server.py"])
    for name in ("MCP_HOST", "MCP_AUTH_TOKEN", "MCP_PUBLIC_HOST", "PORT", "PYTHON_DOTENV_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))
    policy_server.main()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["app"].token == "test-env-token"


@pytest.mark.parametrize("development", [False, True])
@pytest.mark.parametrize("token_override", [None, "environment-token"])
def test_dotnet_mcp_server_file_configuration(tmp_path, development, token_override):
    output = ROOT / "dotnet/mcp_server/bin/Debug/net10.0"
    shutil.copytree(output, tmp_path, dirs_exist_ok=True)
    (tmp_path / "appsettings.json").write_text(json.dumps({
        "MCP_HOST": "127.0.0.1", "PORT": "0", "MCP_PUBLIC_HOST": "",
        "MCP_AUTH_TOKEN": "base-file-token",
    }), encoding="utf-8")
    (tmp_path / "appsettings.development.json").write_text(json.dumps({
        "MCP_AUTH_TOKEN": "development-file-token",
    }), encoding="utf-8")
    settings = {
        "MCP_HOST": None, "PORT": None, "MCP_PUBLIC_HOST": None, "MCP_AUTH_TOKEN": token_override,
        "DOTNET_ENVIRONMENT": "Development" if development else "Production",
        "APPDATA": str(tmp_path / "user-data"), "HOME": str(tmp_path / "home"),
    }
    expected_token = token_override or ("development-file-token" if development else "base-file-token")
    with dotnet_mcp_server(settings, tmp_path / "PolicyMcpServer.dll") as url:
        assert httpx.post(url, json={}).status_code == 401
        headers = {"Authorization": f"Bearer {expected_token}", "Accept": "application/json, text/event-stream"}
        assert httpx.post(url, json=initialize_request(), headers=headers).status_code == 200


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize(("settings", "message"), [
    ({"MCP_HOST": "0.0.0.0"}, "MCP_AUTH_TOKEN"),
    ({"MCP_PUBLIC_HOST": "policy.example.test"}, "MCP_AUTH_TOKEN"),
    ({"MCP_PUBLIC_HOST": "https://policy.example.test/mcp", "MCP_AUTH_TOKEN": "test-token"}, "MCP_PUBLIC_HOST"),
])
def test_mcp_rejects_unsafe_startup(language, settings, message):
    command = (["dotnet", str(ROOT / "dotnet/mcp_server/bin/Debug/net10.0/PolicyMcpServer.dll")]
               if language == "dotnet" else [sys.executable, str(ROOT / "python/mcp_server/server.py")])
    environment = os.environ | {
        "MCP_HOST": "127.0.0.1", "PORT": "0", "MCP_AUTH_TOKEN": "", "MCP_PUBLIC_HOST": "",
        "DOTNET_ENVIRONMENT": "Production", "PYTHON_DOTENV_DISABLED": "1",
    } | settings
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert message in result.stderr
    assert "test-token" not in result.stdout + result.stderr


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("mode", ["chat", "responses", "hosted-mcp"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("endpoint_suffix", ["", "/openai/v1/"])
def test_two_turn_tool_loop(language, mode, stream, endpoint_suffix, mcp_url):
    hosted = mode == "hosted-mcp"
    with model_endpoint() as (base_url, requests):
        result = run_sample(language, mode, "https://mcp.example.com/mcp" if hosted else mcp_url,
                            base_url + endpoint_suffix, (["--auto-approve"] if hosted else []) + (["--stream"] if stream else []))
    assert "TRAVEL-002" in result.stdout
    assert "Provider: Azure OpenAI" in result.stdout
    expected_path = "/openai/v1/chat/completions" if mode == "chat" else "/openai/v1/responses"
    assert all(path == expected_path and body["model"] == "test-deployment" for path, body in requests)
    assert len(requests) == (2 if hosted else 4)
    if hosted:
        for _, body in requests:
            tool = body["tools"][0]
            assert tool["type"] == "mcp"
            assert tool["server_url"] == "https://mcp.example.com/mcp"
            allowed = tool["allowed_tools"]
            assert (allowed.get("tool_names") if isinstance(allowed, dict) else allowed) == ["search_policy"]
            assert tool["require_approval"] == "never"
            assert tool["headers"]["Authorization"] == "Bearer test-token-not-a-secret"
        assert "app MCP HTTP requests=0" in result.stdout
    elif mode == "chat":
        assert any(message["role"] == "tool" and "TRAVEL-002" in message["content"] for message in requests[1][1]["messages"])
        assert len([message for message in requests[2][1]["messages"] if message["role"] == "user"]) == 2
    else:
        assert any(item.get("type") == "function_call_output" and "TRAVEL-002" in json.dumps(item["output"]) for item in requests[1][1]["input"])
    if mode != "chat":
        assert requests[-1][1].get("previous_response_id"), "Follow-up must chain service-managed state"


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("mode", ["chat", "hosted-mcp"])
def test_long_run_reports_request_growth(language, mode, mcp_url):
    hosted = mode == "hosted-mcp"
    with model_endpoint() as (base_url, requests):
        result = run_sample(language, mode, "https://mcp.example.com/mcp" if hosted else mcp_url, base_url,
                            ["--long"] + (["--auto-approve"] if hosted else []))
    turn_bytes = [int(value) for value in re.findall(r"model request bytes=(\d+)", result.stdout)]
    assert len(turn_bytes) == 8
    assert len(requests) == (8 if hosted else 16)
    assert f"[summary] mode={mode}" in result.stdout
    total = re.search(r"^total\s+[\d.]+\s+(\d+)\s+([\d,]+)\s+(\d+)\s*$", result.stdout, re.MULTILINE)
    assert total, result.stdout
    assert int(total[1]) == len(requests)
    assert int(total[2].replace(",", "")) == sum(turn_bytes)
    if hosted:
        # previous_response_id: each request carries only the new turn.
        assert max(turn_bytes) < 2 * min(turn_bytes)
        assert int(total[3]) == 0
    else:
        # History replay: every request re-sends the whole conversation.
        assert all(later > earlier for earlier, later in zip(turn_bytes, turn_bytes[1:]))
        assert turn_bytes[-1] > 3 * turn_bytes[0]
        assert int(total[3]) > 0


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("answer", ["y", "n"])
@pytest.mark.parametrize("stream", [False, True])
def test_hosted_approval(language, answer, stream):
    with model_endpoint() as (base_url, requests):
        result = run_sample(language, "hosted-mcp", "https://mcp.example.com/mcp", base_url,
                            ["--stream"] if stream else [], stdin=f"{answer}\n{answer}\n")
    approvals = [item for _, body in requests for item in body.get("input", []) if item.get("type") == "mcp_approval_response"]
    assert len(approvals) == 2
    assert all(item["approve"] == (answer == "y") for item in approvals)
    assert ("TRAVEL-002" if answer == "y" else "Tool denied") in result.stdout


def initialize_request():
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "parity-test", "version": "1.0"},
    }}


def test_http_auth_and_host_protection(mcp_url):
    health = httpx.get(mcp_url.replace("/mcp", "/healthz"), headers={"Host": "health-probe.internal"})
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert httpx.post(mcp_url, json={}).status_code == 401
    assert httpx.post(mcp_url, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    headers = {"Authorization": "Bearer test-token-not-a-secret", "Host": "attacker.example", "Accept": "application/json, text/event-stream"}
    assert httpx.post(mcp_url, json={}, headers=headers).status_code == 421
    headers.pop("Host")
    headers["Origin"] = "https://attacker.example"
    assert httpx.post(mcp_url, json={}, headers=headers).status_code == 403
    for host, origin in (("policy.example.test", "https://policy.example.test"),
                         ("localhost:8000", "http://localhost:8000"),
                         ("127.0.0.1:8000", "http://127.0.0.1:8000")):
        headers.update(Host=host, Origin=origin)
        assert httpx.post(mcp_url, json=initialize_request(), headers=headers).status_code == 200


async def assert_policy_contract(session):
    initialized = await session.initialize()
    assert initialized.serverInfo.name == "Who Runs the Loop - Policy KB"
    tools = (await session.list_tools()).tools
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "search_policy"
    assert tool.description == search_policy.__doc__
    assert tool.inputSchema["type"] == "object"
    assert tool.inputSchema["required"] == ["query"]
    assert set(tool.inputSchema["properties"]) == {"query"}
    assert tool.inputSchema["properties"]["query"]["type"] == "string"
    assert tool.outputSchema is None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    for query in ("hotel exceptions", "TRAVEL", "the and", "unfindablexyz", "MEAL\tlimits",
                  "approval", "x" * 500, "\U0001f600" * 500):
        result = await session.call_tool("search_policy", {"query": query})
        assert not result.isError
        assert result.structuredContent is None
        assert json.loads(result.content[0].text) == search_policy(query)
    for query in ("", " \t\n", "x" * 501):
        result = await session.call_tool("search_policy", {"query": query})
        assert result.isError
        assert "query must contain between 1 and 500 characters" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_policy_contract(mcp_url):
    async with httpx.AsyncClient(headers={"Authorization": "Bearer test-token-not-a-secret"}) as client:
        async with streamable_http_client(mcp_url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await assert_policy_contract(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["python", "dotnet"])
async def test_mcp_stdio_contract(language):
    command = "dotnet" if language == "dotnet" else sys.executable
    script = ROOT / ("dotnet/mcp_server/bin/Debug/net10.0/PolicyMcpServer.dll" if language == "dotnet"
                     else "python/mcp_server/server.py")
    parameters = StdioServerParameters(command=command, args=[str(script), "--stdio"], env=os.environ | {
        "MCP_PUBLIC_HOST": "", "MCP_AUTH_TOKEN": "", "DOTNET_ENVIRONMENT": "Production",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await assert_policy_contract(session)


def test_policy_and_binding_validation(monkeypatch):
    assert search_policy("exceptions")["matches"][0]["id"] == "TRAVEL-003"
    assert not search_policy("unfindablexyz")["matches"]
    for query in ("", " " * 4, "x" * 501):
        with pytest.raises(ValueError):
            search_policy(query)
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        create_app()


@pytest.mark.parametrize("url", ["http://public.example/mcp", "https://user:password@example.com/mcp", "https://example.com/mcp?token=secret", "http://localhost:8000/mcp"])
def test_hosted_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_url(url, public_only=True)


@pytest.mark.parametrize("language", ["python", "dotnet"])
@pytest.mark.parametrize("endpoint", ["", "https://demo.services.ai.azure.com/api/projects/demo", "https://demo.openai.azure.com/openai/deployments/demo", "https://demo.openai.azure.com/?api-version=2025-01-01-preview"])
def test_invalid_azure_configuration(language, endpoint):
    result = run_sample(language, "hosted-mcp", "https://mcp.example.com/mcp", endpoint, expect_success=False)
    assert "[model]" not in result.stderr
import argparse
import logging
import os
import secrets
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


POLICIES = (
    {"id": "TRAVEL-001", "title": "Booking and approval", "text": "Book economy flights at least 14 days before departure. Manager approval is required before booking business travel."},
    {"id": "TRAVEL-002", "title": "Hotel and meal limits", "text": "The fictional company reimburses hotels up to USD 200 per night and meals up to USD 75 per day. Itemized receipts are required."},
    {"id": "TRAVEL-003", "title": "Travel exceptions", "text": "Accessibility needs, documented medical needs, and destinations with no hotels under the limit qualify for exceptions. Obtain written Finance approval before booking; emergency travel may be approved retrospectively within 2 business days."},
    {"id": "TRAVEL-004", "title": "Expense submission", "text": "Submit travel expenses with receipts within 30 days of return. Personal entertainment and companion travel are not reimbursable."},
)


def create_server() -> FastMCP:
    public_host = os.getenv("MCP_PUBLIC_HOST", "").strip()
    allowed_hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    if public_host:
        if any(character in public_host for character in "/@* "):
            raise ValueError("MCP_PUBLIC_HOST must be a hostname, optionally with a port, not a URL or wildcard.")
        allowed_hosts.append(public_host)
    server = FastMCP(
        "Who Runs the Loop - Policy KB",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"]
            + ([f"https://{public_host}"] if public_host else []),
        ),
    )
    server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )(search_policy)
    return server


def search_policy(query: str) -> dict:
    """Search the fictional travel policy KB. Returns policy IDs and source text for citations. Never changes data."""
    if not query.strip() or len(query) > 500:
        raise ValueError("query must contain between 1 and 500 characters")
    words = set(query.lower().split()) - {"the", "a", "an", "and", "or", "is", "what", "are", "for", "of", "to", "in"}
    matches = [
        policy for policy in POLICIES
        if any(word in (policy["title"] + " " + policy["text"]).lower() for word in words)
    ]
    logging.getLogger("policy_mcp").info("Executed search_policy; matches=%d", len(matches))
    return {"fictional": True, "matches": matches}


class BearerAuth:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if scope["path"] == "/healthz":
                await JSONResponse({"status": "ok"})(scope, receive, send)
                return
            headers = dict(scope["headers"])
            provided = headers.get(b"authorization", b"")
            expected = f"Bearer {self.token}".encode()
            if self.token and not secrets.compare_digest(provided, expected):
                await JSONResponse(
                    {"error": "Unauthorized"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app() -> ASGIApp:
    token = os.getenv("MCP_AUTH_TOKEN", "")
    host = os.getenv("MCP_HOST", "127.0.0.1")
    if (host not in {"localhost", "127.0.0.1", "::1"} or os.getenv("MCP_PUBLIC_HOST")) and not token:
        raise ValueError("Set MCP_AUTH_TOKEN before exposing the server beyond loopback.")
    return BearerAuth(create_server().streamable_http_app(), token)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    parser = argparse.ArgumentParser(description="Read-only fictional travel-policy MCP server")
    parser.add_argument("--stdio", action="store_true", help="Use local stdio instead of HTTP")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.stdio:
        create_server().run(transport="stdio")
    else:
        uvicorn.run(create_app(), host=os.getenv("MCP_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
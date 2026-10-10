"""
HalalReady MCP Connector
Proposal §6: Custom MCP server registered in WorkBuddy's Connectors.

Tools exposed:
  post_event, create_task, get_my_tasks, complete_task,
  get_case, save_ingredients, save_certificate, list_certificates,
  save_finding, save_document, save_site_finding, request_approval

Each tool proxies to the FastAPI backend on localhost:8000.
"""

import os, json, sys, logging
from datetime import datetime, timezone, timedelta
import httpx

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("connector")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
MYT = timezone(timedelta(hours=8))


# ── helpers ─────────────────────────────────────────────────────────

def _url(path: str) -> str:
    return f"{BACKEND_URL}{path}"


def _call(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    """Synchronous HTTP call to the backend."""
    with httpx.Client(timeout=30) as client:
        if method == "GET":
            resp = client.get(_url(path), params=params)
        elif method == "POST":
            resp = client.post(_url(path), json=body)
        elif method == "PATCH":
            resp = client.patch(_url(path), json=body)
        else:
            raise ValueError(f"Unsupported method: {method}")
    resp.raise_for_status()
    return resp.json()


# ═══════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS  (MCP tool schema)
# ═══════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "post_event",
        "description": "Post an event for a run. Call after every agent step, with a label of 8 words or fewer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id":     {"type": "integer", "description": "The run ID"},
                "agent":      {"type": "string", "description": "Agent name: coordinator, certificate_checker, supplier_chaser, document_writer, onsite_inspector, renewal_watch"},
                "label":      {"type": "string", "description": "Short label, 8 words max"},
                "status":     {"type": "string", "enum": ["ok","problem","attention","action","info"]},
                "finding_id": {"type": "integer", "description": "Optional finding ID"},
                "handed_to":  {"type": "string", "description": "Agent name this event hands work to"},
            },
            "required": ["run_id", "agent", "label", "status"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a task (always as draft). The owner approves in the dashboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id":  {"type": "integer"},
                "type":        {"type": "string", "enum": ["supplier_message", "site_fix"]},
                "supplier_id": {"type": "integer"},
                "channel":     {"type": "string", "enum": ["whatsapp", "telegram", "manual"], "default": "manual"},
                "body_ms":     {"type": "string", "description": "Message body in Malay"},
                "body_en":     {"type": "string", "description": "Message body in English"},
                "assignee":    {"type": "string", "description": "Agent or person assigned"},
                "due_date":    {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["type"],
        },
    },
    {
        "name": "get_my_tasks",
        "description": "Get tasks assigned to this agent that are draft or approved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Your agent name"},
            },
            "required": ["agent"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as done.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_case",
        "description": "Get the full case: business, products, ingredients with cert status, suppliers, files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {"type": "integer"},
                "sim_date":    {"type": "string", "description": "Optional YYYY-MM-DD override for today"},
            },
            "required": ["business_id"],
        },
    },
    {
        "name": "save_ingredients",
        "description": "Save a batch of ingredients with optional supplier and product links.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {"type": "integer"},
                "ingredients": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":          {"type": "string"},
                            "brand":         {"type": "string"},
                            "supplier_name": {"type": "string"},
                            "kind":          {"type": "string", "enum": ["processed", "natural"]},
                            "proof_type":    {"type": "string", "enum": ["halal_certificate", "source_document"]},
                            "product_names": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "kind", "proof_type"],
                    },
                },
            },
            "required": ["business_id", "ingredients"],
        },
    },
    {
        "name": "save_certificate",
        "description": "Save a certificate for an ingredient. Returns the cert ID and calculated status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ingredient_id":     {"type": "integer"},
                "issuer":            {"type": "string"},
                "cert_number":       {"type": "string"},
                "expiry_date":       {"type": "string", "description": "YYYY-MM-DD or null"},
                "issuer_recognised": {"type": "boolean"},
                "file_id":           {"type": "integer"},
            },
            "required": ["ingredient_id", "issuer", "cert_number"],
        },
    },
    {
        "name": "list_certificates",
        "description": "List every ingredient with certificate status and days to expiry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {"type": "integer"},
                "sim_date":    {"type": "string"},
            },
            "required": ["business_id"],
        },
    },
    {
        "name": "save_finding",
        "description": "Save a finding (certificate, site, or upkeep issue).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id":        {"type": "integer"},
                "agent":         {"type": "string"},
                "category":      {"type": "string", "enum": ["certificate", "site", "upkeep"]},
                "severity":      {"type": "string", "enum": ["problem", "attention", "info"]},
                "title":         {"type": "string"},
                "detail":        {"type": "string"},
                "ingredient_id": {"type": "integer"},
                "area":          {"type": "string", "enum": ["receiving", "dry_store", "production", "packing"]},
            },
            "required": ["run_id", "agent", "category", "severity", "title"],
        },
    },
    {
        "name": "save_document",
        "description": "Save a draft document (halal policy, procedures, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {"type": "integer"},
                "title":       {"type": "string"},
                "body":        {"type": "string"},
            },
            "required": ["business_id", "title"],
        },
    },
    {
        "name": "save_site_finding",
        "description": "Save a site inspection finding for a specific area.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id":   {"type": "integer"},
                "run_id":        {"type": "integer"},
                "area":          {"type": "string", "enum": ["receiving", "dry_store", "production", "packing"]},
                "severity":      {"type": "string", "enum": ["problem", "attention", "info"]},
                "title":         {"type": "string"},
                "detail":        {"type": "string"},
                "photo_file_id": {"type": "integer"},
            },
            "required": ["business_id", "area", "severity", "title"],
        },
    },
    {
        "name": "request_approval",
        "description": "Request owner approval for a task or document. Nothing is sent without approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_type": {"type": "string", "enum": ["task", "document", "message"]},
                "item_id":   {"type": "integer"},
                "comment":   {"type": "string"},
            },
            "required": ["item_type", "item_id"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════
# TOOL HANDLERS
# ═══════════════════════════════════════════════════════════════════

def handle_post_event(args: dict) -> dict:
    return _call("POST", "/events", args)

def handle_create_task(args: dict) -> dict:
    return _call("POST", "/tasks", args)

def handle_get_my_tasks(args: dict) -> dict:
    return _call("GET", f"/tasks/agent/{args['agent']}")

def handle_complete_task(args: dict) -> dict:
    return _call("POST", f"/tasks/{args['task_id']}/complete")

def handle_get_case(args: dict) -> dict:
    params = {}
    if args.get("sim_date"):
        params["sim_date"] = args["sim_date"]
    return _call("GET", f"/business/{args['business_id']}/case", params=params)

def handle_save_ingredients(args: dict) -> dict:
    return _call("POST", "/ingredients/batch", args)

def handle_save_certificate(args: dict) -> dict:
    return _call("POST", "/certificates", args)

def handle_list_certificates(args: dict) -> dict:
    params = {}
    if args.get("sim_date"):
        params["sim_date"] = args["sim_date"]
    return _call("GET", f"/business/{args['business_id']}/certificates", params=params)

def handle_save_finding(args: dict) -> dict:
    return _call("POST", "/findings", args)

def handle_save_document(args: dict) -> dict:
    return _call("POST", "/documents", args)

def handle_save_site_finding(args: dict) -> dict:
    return _call("POST", "/site-findings", args)

def handle_request_approval(args: dict) -> dict:
    return _call("POST", "/approvals/request", args)


HANDLERS = {
    "post_event":        handle_post_event,
    "create_task":       handle_create_task,
    "get_my_tasks":      handle_get_my_tasks,
    "complete_task":     handle_complete_task,
    "get_case":          handle_get_case,
    "save_ingredients":  handle_save_ingredients,
    "save_certificate":  handle_save_certificate,
    "list_certificates": handle_list_certificates,
    "save_finding":      handle_save_finding,
    "save_document":     handle_save_document,
    "save_site_finding": handle_save_site_finding,
    "request_approval":  handle_request_approval,
}


# ═══════════════════════════════════════════════════════════════════
# MCP STDIO TRANSPORT  (JSON-RPC 2.0 over stdin/stdout)
# ═══════════════════════════════════════════════════════════════════

def _jsonrpc_response(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def main():
    """Run the MCP connector as a stdio JSON-RPC server."""
    log.info("HalalReady MCP Connector starting on stdio...")
    log.info("Backend URL: %s", BACKEND_URL)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")

        if method == "initialize":
            resp = _jsonrpc_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "halalready-connector", "version": "0.1.0"},
            })

        elif method == "notifications/initialized":
            continue  # no response needed

        elif method == "tools/list":
            resp = _jsonrpc_response(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name", "")
            tool_args = msg.get("params", {}).get("arguments", {})

            handler = HANDLERS.get(tool_name)
            if not handler:
                resp = _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
            else:
                try:
                    result = handler(tool_args)
                    resp = _jsonrpc_response(req_id, {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    })
                except httpx.HTTPStatusError as e:
                    resp = _jsonrpc_response(req_id, {
                        "content": [{"type": "text", "text": f"Backend error {e.response.status_code}: {e.response.text}"}],
                        "isError": True,
                    })
                except Exception as e:
                    resp = _jsonrpc_response(req_id, {
                        "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                        "isError": True,
                    })

        else:
            resp = _jsonrpc_error(req_id, -32601, f"Unknown method: {method}")

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

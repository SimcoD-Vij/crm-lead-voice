# ---------------------------------------------------------
# ai/mcp_server.py
# MCP Server for XOptimus Agent - replaces agent/mcp_server.js
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    ListResourcesRequest,
    ListToolsRequest,
    ReadResourceRequest,
    Resource,
    TextContent,
    Tool,
)

from ai.memory import get_memory, upsert_memory
from ai.sales_bot import generate_response

# CONFIG
_CS_ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = _CS_ROOT / 'agent' / 'data' / 'sample_product_facts.txt'

def _read_product_facts() -> str:
    if FACTS_PATH.exists():
        return FACTS_PATH.read_text(encoding='utf-8')
    return "XOptimus Product Knowledge base is currently unavailable."

# 1. Initialize MCP Server
app = Server("xoptimus-sales-agent")

# ---------------------------------------------------------
# 2. EXPOSE RESOURCES (Data)
# ---------------------------------------------------------
@app.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="xoptimus://data/product_facts",
            name="XOptimus Product Knowledge",
            mimeType="text/plain",
            description="Technical specs and features of the XOptimus Smart Charger"
        )
    ]

@app.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "xoptimus://data/product_facts":
        return _read_product_facts()
    raise ValueError(f"Resource not found: {uri}")

# ---------------------------------------------------------
# 3. EXPOSE TOOLS (Functions)
# ---------------------------------------------------------
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="consultative_chat",
            description="Chat with the XOptimus Sales Agent (Handles objections, specs, and pricing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The user's message or question"
                    },
                    "sessionId": {
                        "type": "string",
                        "description": "Unique ID for conversation memory (optional)"
                    }
                },
                "required": ["message"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "consultative_chat":
        message = arguments.get("message")
        session_id = arguments.get("sessionId", "mcp_user_default")

        if not message:
            raise ValueError("Message is required")

        # Reuse existing Logic!
        memory = await get_memory(session_id) or {}
        
        try:
            ai_result = await generate_response({
                "userMessage": message,
                "memory": memory,
                "mode": 'CONSULTATIVE'
            })
            
            reply = ai_result.get("response", "") if isinstance(ai_result, dict) else str(ai_result)

            # Update Memory (Basic tracking)
            await upsert_memory(session_id, {"last_user_message": message, "last_bot_message": reply})

            return [TextContent(type="text", text=reply)]
            
        except Exception as e:
            return [TextContent(type="text", text=f"Error in agent processing: {str(e)}")]

    raise ValueError(f"Tool not found: {name}")

# 4. START SERVER (StdIO Mode)
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())

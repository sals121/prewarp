"""End-to-end: launch the MCP server over stdio and call it like Claude would."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _session_calls():
    params = StdioServerParameters(command=sys.executable, args=["-m", "prewarp.mcp_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            mats = await session.call_tool("list_materials", {})
            val = await session.call_tool("nist_validation", {})
            return tools, mats, val


def _payload(result):
    return json.loads(result.content[0].text)


def test_mcp_server_exposes_tools_and_answers():
    tools, mats, val = asyncio.run(_session_calls())
    assert {"analyze_part", "compensate_part", "rank_orientations", "list_materials", "nist_validation"} <= tools
    names = [m["name"] for m in _payload(mats)["materials"]]
    assert "IN718" in names
    assert _payload(val)["AMB2018"]["tip_only_calibration_predicting_other_10"]["rms_um"] < 20

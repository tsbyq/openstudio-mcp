"""Integration tests for ingest_file and list_inputs tools.

Requires RUN_OPENSTUDIO_INTEGRATION=1 and a running MCP server.
"""
import asyncio
import os
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

_FIXTURE_OSM = Path(__file__).parent / "assets" / "SystemD_baseline.osm"


def _unique(prefix="pytest_ingest"):
    token = uuid.uuid4().hex[:8]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    return f"{prefix}_{worker}_{token}" if worker else f"{prefix}_{token}"


@pytest.mark.integration
def test_ingest_osm_then_load():
    """ingest_file writes an OSM to /inputs/ and load_osm_model succeeds on the returned path."""
    # Validates: ingest_file + load_osm_model round-trip with a real fixture OSM
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")
    if not _FIXTURE_OSM.exists():
        pytest.skip(f"Fixture not found: {_FIXTURE_OSM}")

    osm_content = _FIXTURE_OSM.read_text(encoding="utf-8")
    ingest_name = f"{_unique()}.osm"

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Ingest the fixture OSM
                ingest_resp = await session.call_tool(
                    "ingest_file", {"filename": ingest_name, "content": osm_content}
                )
                ingest_result = unwrap(ingest_resp)
                print("ingest_file:", ingest_result)
                assert ingest_result["ok"] is True, ingest_result
                assert ingest_result["path"] == f"/inputs/{ingest_name}"
                assert ingest_result["size_bytes"] > 0

                # list_inputs must include the new file
                list_resp = await session.call_tool("list_inputs", {})
                list_result = unwrap(list_resp)
                print("list_inputs:", list_result)
                assert list_result["ok"] is True, list_result
                assert ingest_name in list_result["files"]

                # load_osm_model must succeed on the returned path
                load_resp = await session.call_tool(
                    "load_osm_model", {"osm_path": ingest_result["path"]}
                )
                load_result = unwrap(load_resp)
                print("load_osm_model:", load_result)
                assert load_result["ok"] is True, load_result
                assert load_result["osm_path"] == ingest_result["path"]

    asyncio.run(_run())


@pytest.mark.integration
def test_ingest_rejects_bad_filename():
    """ingest_file returns ok=False for path traversal and disallowed extensions."""
    # Validates: server-side validation blocks ../etc/passwd and .py filenames
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    bad_inputs = [
        ("../etc/passwd", "content"),
        ("subdir/model.osm", "content"),
        ("model.py", "content"),
        ("model.rb", "content"),
        ("model.osm", ""),
    ]

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for filename, content in bad_inputs:
                    resp = await session.call_tool(
                        "ingest_file", {"filename": filename, "content": content}
                    )
                    result = unwrap(resp)
                    print(f"ingest_file({filename!r}):", result)
                    assert result["ok"] is False, f"Expected rejection for filename={filename!r}"
                    assert result.get("error"), "Expected non-empty error message"

    asyncio.run(_run())

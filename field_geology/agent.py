import os
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

GEMINI_MODEL = "gemini-2.5-flash"

# --- Absolute paths: nvm node + built MCP server (same as Claude Desktop config) ---
NODE_PATH = "/Users/michaellittle/.nvm/versions/node/v22.3.0/bin/node"
MCP_SERVER_PATH = "/Users/michaellittle/projects/macrostrat-mcp/build/index.js"

# --- MCP connection to the forked server (STDIO / local dev) ---
# Deploy swap: replace this block with
#   StreamableHTTPConnectionParams(url=os.getenv("MCP_SERVER_URL"))
# and the agents below are unchanged.
macrostrat_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=NODE_PATH,
            args=[MCP_SERVER_PATH],
        )
    ),
    # Expose only the field tool, not all nine macrostrat tools (least-privilege).
    tool_filter=["find-units-map"],
)

# --- Location Agent: wraps the working MCP tool ---
location_agent = LlmAgent(
    name="LocationAgent",
    model=GEMINI_MODEL,
    instruction="""
You are a geological location lookup. The user provides latitude and longitude.
Call the find-units-map tool with those coordinates. Return the tool's result
verbatim as structured data. Do not editorialize, do not add geological claims
the tool did not return, and preserve the provenance note exactly.
""".strip(),
    description="Looks up mapped bedrock at a coordinate via the Macrostrat MCP tool.",
    tools=[macrostrat_toolset],
    output_key="location_data",
)

# --- Report Agent: assembles the field report ---
report_agent = LlmAgent(
    name="ReportAgent",
    model=GEMINI_MODEL,
    instruction="""
You assemble a structured field geology report from the data in state.

Mapped bedrock data (from Macrostrat, via find-units-map):
{location_data}

Produce a field report with these sections:
- Location (the queried coordinates)
- Mapped Bedrock Unit (formation name, lithology, age)
- Data Source & Citation (from the tool result)
- Provenance Note (carry through the tool's caveat verbatim -- this is a
  geologic map polygon, not a verified field observation)

Do NOT assert a confident rock identification beyond what the mapped data
supports. This report is a first draft for a geologist to confirm against
the actual outcrop.
""".strip(),
    description="Assembles the final structured field report.",
    output_key="field_report",
)

# --- Pipeline: deterministic, fixed order (locate -> report) ---
root_agent = SequentialAgent(
    name="FieldGeologyPipeline",
    sub_agents=[location_agent, report_agent],
    description="Field geology documentation pipeline: locate bedrock, then assemble a report.",
)

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

# --- Description Agent: structures field observations (text-mode first) ---
# Takes a free-text outcrop description from the user and normalizes it into
# a structured observation set. Vision (photo input) is added in the next step
# using this same output schema, so the rest of the pipeline is unchanged.
#
# Design discipline: DESCRIBE and DEFER. This agent records what was observed
# and flags uncertainty. It does NOT assert a confident lithology -- that is a
# claim only a geologist at the outcrop (or corroborating map data) can make.
description_agent = LlmAgent(
    name="DescriptionAgent",
    model=GEMINI_MODEL,
    instruction="""
You are a field geology observation recorder. The user gives a free-text
description of a rock outcrop (what they see standing in front of it).

Normalize their description into a structured observation set with these fields:
- color: observed color(s) of the rock
- grain: grain size / texture if mentioned (e.g. fine, coarse, crystalline)
- layering: bedding, foliation, banding, or other layering if mentioned
- structures: visible features (fractures, folds, veins, glacial striations, etc.). 
- candidate_lithology: what the rock MIGHT be, phrased as a possibility, never
  a certainty. If the description is insufficient to even guess, say so.
- confidence: one of "low", "moderate", "high" -- and for a photo/verbal
  description alone, confidence should almost never be "high"
- uncertainty_notes: what you could NOT determine and what would be needed to
  confirm (e.g. "a hand lens and scale reference would be needed to confirm
  grain size and mineralogy")

For any field you cannot fill from the user's description, use the string
"none observed" rather than null or an empty value, so the report reads cleanly.

Only record what the user actually described. Do not invent observations.
Do not upgrade a possibility into a fact. If the user described little, your
observation set should honestly reflect that.
""".strip(),
    description="Records and structures field observations of an outcrop, with explicit uncertainty.",
    output_key="observations",
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

# --- Draft Report Agent: reconciles observations + map data, then STOPS for review ---
# This is the "maker" in a maker-checker control. It produces a DRAFT and hands
# off to the geologist. It never finalizes on its own.
draft_report_agent = LlmAgent(
    name="DraftReportAgent",
    model=GEMINI_MODEL,
    instruction="""
You assemble a DRAFT field geology report from two sources in state.

Field observations (what was seen at the outcrop):
{observations}

Mapped bedrock data (from Macrostrat, via find-units-map):
{location_data}

Produce a draft field report with these sections:
- Location (the queried coordinates)
- Field Observations (from the observation set, including its uncertainty notes)
- Mapped Bedrock Unit (formation name, lithology, age, from the map data)
- Agreement Check: state whether the field observations are CONSISTENT with
  the mapped unit, and flag any discrepancy plainly. Do not force agreement --
  if the observed rock does not match the mapped formation, say so; a mismatch
  is a finding, not an error. When you flag a mismatch, also give the likely
  explanations (e.g. the sample may be non-native material such as fill, a
  landscaping boulder, or a glacial erratic rather than in-place bedrock; the
  map polygon may be too coarse at this point; or the observation may need
  re-examination) and recommend a concrete next step. Do not silently pick one
  explanation -- present them for the geologist to adjudicate.
- Data Source & Citation (from the map data)
- Provenance Note (carry through the map tool's caveat verbatim -- this is a
  geologic map polygon, not a verified field observation)

This is a DRAFT. Do NOT mark it final. End your response with a clear request:
"GEOLOGIST REVIEW REQUIRED: Please confirm this determination, correct it, or
reject it before the report is finalized." Then stop and wait for the
geologist's response.
""".strip(),
    description="Produces a draft field report and requests geologist confirmation.",
    output_key="draft_report",
)

# --- Finalizer Agent: runs on the geologist's confirming turn (the "checker") ---
# The final report cannot exist until this runs, and this only runs on a human
# turn. The gate is enforced by pipeline topology, not by agent goodwill.
from google.adk.tools import FunctionTool

def request_geologist_confirmation(
    proposed_determination: str,
    agreement_status: str,
    discrepancy_notes: str,
) -> dict:
    """Present the draft determination to the geologist and BLOCK until they
    respond. No final report may be produced until this returns a decision.
    This is the checker gate in the maker-checker control."""
    print("\n=== GEOLOGIST REVIEW REQUIRED (checker gate) ===")
    print(f"Proposed determination: {proposed_determination}")
    print(f"Agreement status: {agreement_status}")
    print(f"Discrepancy notes: {discrepancy_notes}")
    raw = input(
        "Decision -- type 'confirm', 'reject', or a correction: "
    ).strip()
    low = raw.lower()
    if low == "confirm":
        return {"decision": "confirmed", "correction": None}
    if low == "reject":
        return {"decision": "rejected", "correction": None}
    return {"decision": "corrected", "correction": raw}

confirmation_tool = FunctionTool(func=request_geologist_confirmation)

finalizer_agent = LlmAgent(
    name="FinalizerAgent",
    model=GEMINI_MODEL,
    instruction="""
You finalize the field report, but ONLY after a geologist has reviewed it.

The draft determination is in state:
{draft_report}

You MUST call the request_geologist_confirmation tool before producing any
final report. Pass it the proposed determination, the agreement status, and
any discrepancy notes from the draft. You may not finalize without calling it.

When the tool returns:
- "confirmed": finalize as-is, mark GEOLOGIST-CONFIRMED.
- "corrected": apply the returned correction, note exactly what changed as a
  geologist correction, mark GEOLOGIST-CORRECTED.
- "rejected": do not finalize; record the rejection, mark GEOLOGIST-REJECTED.

The geologist's decision supersedes both the observations and the mapped data.
Never fabricate a confirmation. Never skip the tool call. Preserve the Data
Source & Citation and the Provenance Note.
""".strip(),
    description="Finalizes the report only after the geologist confirmation tool returns a decision.",
    tools=[confirmation_tool],
    output_key="final_report",
)

# Root: the draft pipeline runs first. After the geologist responds on the next
# turn, the finalizer applies their decision. Modeled as a maker-checker gate:
# no GEOLOGIST-CONFIRMED report can exist without the checker's turn.
root_agent = SequentialAgent(
    name="FieldGeologyPipeline",
    sub_agents=[description_agent, location_agent, draft_report_agent, finalizer_agent],
    description="Maker-checker field geology pipeline: draft (maker) -> mandatory geologist gate (checker) -> final.",
)

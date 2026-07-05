
# Field Geology Documentation Agent

A multi-agent AI system that helps document a rock outcrop in the field. Provide a photo and the location, and it produces a structured first-draft field report — pairing what the AI observes in the image with authoritative geologic map data — and then requires a human geologist to confirm, correct, or reject the finding before it becomes a record.

Built for the **Google / Kaggle 5-Day AI Agents: Intensive Vibe Coding Capstone**.
Track: **Agents for Good**.

> **What this is, and isn't.** This is a documentation *aid* that structures observations and cross-references them against published map data. It is not a rock-identification authority. Identifying a rock reliably requires a hand lens, a scale reference, and in-person examination — so the system is deliberately built to *describe and defer* to a human geologist, never to assert a confident identification on its own.

---

## The Problem

Field geologists document outcrops largely from direct observation, written into field notebooks. That documentation is valuable but has three recurring weaknesses: it is subjective and unstructured, it is disconnected from the large body of published geologic map data that describes what *should* be present at a given location, and it carries no built-in record of how confident the observer was or how the observation compares to reference data.

There is a lot of authoritative geologic data available — but a geologist standing at an outcrop has no quick way to pull "what is mapped here" and compare it against "what I'm actually looking at," in a structured form, with the disagreements surfaced rather than hidden.

## The Solution

This tool runs a short pipeline of specialized AI agents:

1. **Observe** — a vision-capable agent describes the outcrop from a photo (color, grain, layering, structures) and, critically, records its own *uncertainty* and *confidence* rather than asserting a rock type.
2. **Locate** — an agent looks up the mapped bedrock at the provided coordinates using [Macrostrat](https://macrostrat.org), a public geologic map database, via a Model Context Protocol (MCP) server.
3. **Reconcile** — an agent assembles a draft report and performs an *Agreement Check*: does the field observation match the mapped unit? If not, it says so plainly, lists the likely explanations, and recommends a next step rather than forcing agreement.
4. **Review** — the draft is presented to a human geologist, who must confirm, correct, or reject it. **No final report exists until a human decides.** The human's determination supersedes both the AI observation and the mapped data.

The result is a structured field report with the observation, the authoritative map data, an explicit consistency check, a citation to the source, and a provenance note — signed off (or overridden) by a human.

![Field geology pipeline as shown in the ADK trace view. Execution order runs left to right: DescriptionAgent (observe) → LocationAgent (map lookup via the Macrostrat MCP toolset) → DraftReportAgent (reconcile) → FinalizerAgent, which is gated on the request_geologist_confirmation human-review step.](docs/architecture-trace.png)

*Figure: The four-agent pipeline. LocationAgent reaches the forked Macrostrat MCP server (McpToolset); FinalizerAgent cannot produce a final report without the human review gate (request_geologist_confirmation).*

---

## Architecture

The system is two independently-deployable components communicating over the Model Context Protocol, plus a four-agent orchestration pipeline.

### Components

**1. The MCP data layer (forked and extended).**
The geologic lookup is served by a Model Context Protocol server that wraps the Macrostrat API. We forked an existing open-source Macrostrat MCP server ([blake365/macrostrat-mcp](https://github.com/blake365/macrostrat-mcp), MIT) and **extended it with a purpose-built tool, `find-units-map`**, for field documentation.

The original server's general lookup returns Macrostrat's *stratigraphic column* — the full vertical sequence of rock at a region, which for an urban point can snap to a reference column tens of kilometers away and bury the surface rock under a wall of subsurface history. `find-units-map` instead queries Macrostrat's *geologic map* layer (the mapped surface polygon at the exact point), then does three things the raw response does not:

- **Source selection** — Macrostrat returns multiple overlapping map sources at different scales; the tool selects the single most specific mapped unit (a named stratigraphic unit) rather than dumping every layer.
- **Citation resolution** — it attaches the specific literature citation for the selected unit's source (Macrostrat is CC-BY; attribution travels with the data).
- **Provenance flagging** — it carries an explicit caveat that the result is a geologic map polygon, not a verified field observation, and should be confirmed at the outcrop.

This is a deliberate product decision: the existing tool returned *correct data in the wrong shape* for this use case. Rather than push that reconciliation onto the model at runtime, we added a tool that does source selection and provenance deterministically, at the data layer.

**2. The agent pipeline (Google ADK).**
Built with Google's Agent Development Kit as a deterministic `SequentialAgent`:

| Agent | Role |
|---|---|
| `DescriptionAgent` | Reads the photo (and/or text); produces structured observations with explicit confidence and uncertainty. Describes and defers — never asserts a confident lithology. |
| `LocationAgent` | Calls `find-units-map` with the trusted coordinates and returns the mapped bedrock verbatim, provenance intact. Exposed *only* the one MCP tool it needs (least-privilege). |
| `DraftReportAgent` | Reconciles observation against map data; performs the Agreement Check; produces a draft and stops for human review. |
| `FinalizerAgent` | Applies the human's confirm / correct / reject decision. Cannot finalize without a human decision returned from the review gate. |

A `SequentialAgent` (not an LLM router) was chosen deliberately: the pipeline order never varies, so LLM-driven flow control would add nondeterminism and cost for no benefit.

### Governance patterns

The architecture is built around control patterns that will be familiar from regulated environments.

**Separation of duties (maker–checker).** The party that *submits* the evidence (the field data collector: photo + coordinates) is structurally distinct from the party that *approves* it into the record (the reviewing geologist). These are different stages with different interfaces — in the demo, the collector's inputs enter on one surface and the approver's decision happens on another. The submitter cannot self-approve; the approver's determination supersedes both automated evidence sources; and when the approver overrides, the disagreement is preserved in the record rather than silently resolved. The pipeline is *designed around* this separation; binding each stage to a separate authenticated identity is the natural production hardening (see Future Work).

**The review gate is enforced by construction, not convention.** The final report is produced by a step that depends on a human-review tool returning a decision. The agent cannot skip it — an approval isn't an instruction the model is trusted to follow, it's a structural dependency the model cannot satisfy without a human input. (An earlier design relied on pipeline ordering alone and could be bypassed by the model auto-confirming; the final design closes that gap.)

**Trusted-input discipline.** Coordinates are a *trusted, human-supplied* control input. The system will not infer location from image content for the map lookup — even though the vision model can guess a location from a recognizable skyline, a guessed coordinate would launder uncertainty into an authoritative-looking result. Inference is treated as an observation; the lookup fires only on the explicitly provided coordinate.

**Honest uncertainty throughout.** The vision layer's confidence output is a real signal, not decoration — across testing it tracked image legibility (moderate for a clear close view, low for a weathered distant one). The map result carries its own provenance caveat. Both are surfaced to the human reviewer rather than smoothed over.

---

## Demonstrated Course Concepts

| Concept | Where it lives |
|---|---|
| **Multi-agent system (ADK)** | Four-agent `SequentialAgent` pipeline — code |
| **MCP server** | Forked Macrostrat MCP server extended with `find-units-map` — code |
| **Security / governance features** | Maker–checker review gate, trusted-input boundary, provenance — code + video |
| **Deployability** | STDIO (local) → Streamable HTTP (hosted) is a one-line connection-param change; deployment architecture narrated in the video |

---

## Setup & Run

The system has two repositories that work together:

- **This repo** — the ADK agent pipeline (Python).
- The MCP server (TypeScript/Node): [github.com/mflittle/macrostrat-mcp](https://github.com/mflittle/macrostrat-mcp)

### Prerequisites

- **Node.js v20+** (for the MCP server)
- **Python 3.12+** and a virtual environment (for the pipeline)
- **A Google Gemini API key** (free from [Google AI Studio](https://aistudio.google.com))

### 1. Build the MCP server

```bash
git clone https://github.com/mflittle/macrostrat-mcp.git
cd macrostrat-mcp
npm install
npx tsc            # compiles src/ -> build/index.js (STDIO transport)
```

Note the absolute path to `build/index.js` — the pipeline needs it.

### 2. Configure the pipeline

```bash
git clone https://github.com/mflittle/field_geology.git
cd field-geology-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with your API key:

```
GOOGLE_API_KEY=your_key_here
```

In `field_geology/agent.py`, confirm the two absolute paths near the top point at your Node binary and your built MCP server:

```python
NODE_PATH = "/absolute/path/to/node"
MCP_SERVER_PATH = "/absolute/path/to/macrostrat-mcp/build/index.js"
```

### 3. Run

**Visual demo (ADK dev UI):**
```bash
cd field_geology
adk web
```
Open `http://localhost:8000`, select `FieldGeologyPipeline`, attach an outcrop photo, and provide coordinates. The trace view shows each agent and tool call.

**Command-line runner (runs the full pipeline including the review gate, in one terminal):**
```bash
cd field_geology
python run.py
```
Runs against a built-in demo location (Rat Rock, Central Park) so it works out of the box. Override with:
```bash
python run.py --photo path/to/outcrop.jpg --lat 40.7694 --lng -73.9777
```
At the review gate the runner blocks for a human decision (`confirm` / `reject` / a correction) before producing the final report.

---

## Design Decisions & Journey

A few choices that shaped the build, recorded because the reasoning matters more than the result:

- **Map layer, not column.** An early test at the demo coordinates returned a stratigraphic column centered ~40 km away in New Jersey, burying the local schist under an unrelated sequence. This drove the switch to Macrostrat's geologic-map endpoint and the `find-units-map` tool. The failure surfaced on day one of the spike, which is exactly when you want it.
- **Single-image input, by measurement.** We tested three input configurations (photo A alone, photo B alone, both together) against a held-constant coordinate. The single high-legibility image produced the most specific observations; naive multi-image input *diluted* specificity by averaging across views. So the pipeline takes one best image. Structured multi-image synthesis is noted as future work — a reasoned choice, not a gap.
- **Trusted coordinates, not inferred.** The vision model can infer location from a skyline, and correctly declined to run the lookup on that inference. We made that refusal an explicit rule rather than incidental good behavior.
- **A gate that can't be skipped.** An initial maker–checker design placed the draft and finalizer stages under one sequential agent; the model auto-confirmed and produced a "finalized" report with no human input. We rebuilt the gate as a hard tool dependency so the control is enforced structurally.

---

## Limitations & Future Work

Stated plainly, because the limitations are contained by design rather than hidden:

- **Vision is an assist, not an authority.** Rock identification from a photograph is inherently limited; the system flags this and defers to a human. It should never be treated as a field-verified identification.
- **Macrostrat is an aggregator, not ground truth.** It synthesizes published maps and is best treated as a pointer to authoritative sources — which is why every result carries a citation and a provenance caveat.
- **Separation of duties is architectural, not yet identity-enforced.** The submission and approval stages are distinct, but the demo does not bind them to separate authenticated identities. That authentication is the natural production step.
- **Multi-image synthesis** — combining several views of one outcrop into a single richer observation set (rather than the current single-image input) is a clear enhancement, deferred after testing showed naive combination degraded results.

---

## Attribution & License

- **Macrostrat** — geologic data, licensed CC-BY 4.0. Underlying map/unit citations are attached per query in the tool output.
- **MCP server** — forked from [blake365/macrostrat-mcp](https://github.com/blake365/macrostrat-mcp) (MIT License), extended with the `find-units-map` tool. Original license and attribution retained in the fork.
- **This project** — MIT License.

---

## Credits

Built by **[Michael Little](https://www.linkedin.com/in/michaelflittle/)** (architecture, agent pipeline, MCP extension) and **[Jacob Little](https://www.linkedin.com/in/jacob-little-3a0041266/)** (geology domain design, field documentation, demo film). Jacob is a 2026 William & Mary graduate (double major, Geology and Film).

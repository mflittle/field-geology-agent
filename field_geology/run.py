"""
CLI runner for the Field Geology Documentation pipeline.

Drives the proven maker-checker pipeline (agent.py) with a single outcrop
photo plus a TRUSTED, human-supplied coordinate. The coordinate is a control
input -- it is never inferred from the image. The geologist confirmation gate
(inside FinalizerAgent's tool) blocks in this same terminal.

Run with defaults (Rat Rock, Central Park):
    python run.py

Override:
    python run.py --photo /path/to/outcrop.jpg --lat 40.7694 --lng -73.9777
"""


import argparse
import asyncio
import os

from dotenv import load_dotenv
load_dotenv()  # read GOOGLE_API_KEY (and others) from .env, like adk web does

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent  # the proven maker-checker pipeline

# --- Hardcoded demo defaults: Rat Rock (Umpire Rock), Central Park ---
# A judge who clones and runs `python run.py` gets a working result with no setup.
DEFAULT_PHOTO = os.path.join(os.path.dirname(__file__), "demo", "rat_rock.jpg")
DEFAULT_LAT = 40.7694
DEFAULT_LNG = -73.9777

APP_NAME = "field_geology"
USER_ID = "geologist"
SESSION_ID = "field-session"


def load_image_part(path: str) -> types.Part:
    """Read a local image file into a genai Part for multimodal input.
    Single-image input by design: an input-selection eval showed naive
    multi-image blending diluted observation specificity, so the pipeline
    takes one high-legibility image (see README)."""
    with open(path, "rb") as f:
        image_bytes = f.read()
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return types.Part(inline_data=types.Blob(mime_type=mime, data=image_bytes))


def build_input(photo_path: str | None, lat: float, lng: float) -> types.Content:
    """Assemble the user turn: coordinates as TRUSTED text input, photo (if any)
    as an image part. The two are kept distinct on purpose -- the coordinate is
    a control input, the image is observational evidence."""
    parts = [
        types.Part(
            text=(
                f"Document the bedrock outcrop at the provided coordinates. "
                f"TRUSTED COORDINATES (use these for the map lookup, do not infer "
                f"location from the photo): latitude {lat}, longitude {lng}."
            )
        )
    ]
    if photo_path and os.path.exists(photo_path):
        parts.append(load_image_part(photo_path))
        print(f"[input] photo: {photo_path}")
    else:
        if photo_path:
            print(f"[input] photo not found at {photo_path} -- running text-only.")
        else:
            print("[input] no photo -- running text-only.")
    print(f"[input] trusted coordinates: {lat}, {lng}")
    return types.Content(role="user", parts=parts)


async def run(photo_path: str | None, lat: float, lng: float) -> None:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )
    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )

    user_content = build_input(photo_path, lat, lng)

    print("\n[running pipeline: describe -> locate -> draft -> geologist gate -> final]\n")

    final_text = None
    async for event in runner.run_async(
        user_id=USER_ID, session_id=SESSION_ID, new_message=user_content
    ):
        # Capture the most recent final-response text, but don't print yet --
        # the DraftReportAgent also emits a "final response" (the draft), and
        # printing every one causes the draft to appear before the gate.
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                final_text = text

    # Print only the true final artifact, after the gate has run.
    if final_text:
        print("\n" + "=" * 60)
        print("FINAL REPORT")
        print("=" * 60)
        print(final_text)

def main() -> None:
    parser = argparse.ArgumentParser(description="Field Geology Documentation runner.")
    parser.add_argument("--photo", default=DEFAULT_PHOTO, help="Path to outcrop photo.")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT, help="Trusted latitude.")
    parser.add_argument("--lng", type=float, default=DEFAULT_LNG, help="Trusted longitude.")
    args = parser.parse_args()
    asyncio.run(run(args.photo, args.lat, args.lng))


if __name__ == "__main__":
    main()
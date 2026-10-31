"""Write the Rewind 2009 study to the frontend's offline fixture, so mock mode shows the same numbers.

Run from backend/: python scripts/build_collision_fixture.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.casestudy import collision  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "collisionStudyFixture.json"
OUT.write_text(json.dumps(collision.build().model_dump(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")

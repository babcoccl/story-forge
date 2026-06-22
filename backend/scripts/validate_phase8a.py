"""Phase 8a validation — import and schema construction only.

Tests:
- stream.py imports without error
- sse_starlette is importable
- CORSMiddleware is importable
- config.cors_origins_list parses correctly
- main.py imports without error (includes CORS middleware wiring)

NO asyncio.run(), NO DB connections, NO HTTP calls, NO LLM calls.
Cline must not run any demo or integration script.
"""

from __future__ import annotations

import sys


def test_sse_starlette_importable() -> None:
    """Verify sse-starlette package is installed and importable."""
    from sse_starlette.sse import EventSourceResponse  # noqa: F401
    print("  [OK] sse_starlette.sse.EventSourceResponse importable")


def test_cors_middleware_importable() -> None:
    """Verify FastAPI CORSMiddleware is importable."""
    from fastapi.middleware.cors import CORSMiddleware  # noqa: F401
    print("  [OK] fastapi.middleware.cors.CORSMiddleware importable")


def test_config_cors_origins() -> None:
    """Verify cors_origins_list property parses correctly."""
    from backend.app.config import Settings

    # Test default value
    s = Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        database_url_sync="postgresql+psycopg2://x:x@localhost/x",
        cors_origins="http://localhost:3000,http://127.0.0.1:3000",
    )
    origins = s.cors_origins_list
    assert "http://localhost:3000" in origins, f"Expected localhost:3000 in {origins}"
    assert "http://127.0.0.1:3000" in origins, f"Expected 127.0.0.1:3000 in {origins}"
    assert len(origins) == 2

    # Test single origin
    s2 = Settings.model_construct(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        database_url_sync="postgresql+psycopg2://x:x@localhost/x",
        cors_origins="http://localhost:3000",
    )
    assert s2.cors_origins_list == ["http://localhost:3000"]

    print("  [OK] config.cors_origins_list parses correctly")


def test_stream_module_imports() -> None:
    """Verify stream.py imports without error."""
    import backend.app.api.v1.stream  # noqa: F401
    print("  [OK] backend.app.api.v1.stream imports successfully")


def test_router_imports() -> None:
    """Verify updated router.py imports without error."""
    import backend.app.api.v1.router  # noqa: F401
    print("  [OK] backend.app.api.v1.router imports successfully")


def test_main_imports() -> None:
    """Verify main.py imports without error (CORS wiring)."""
    import backend.app.main  # noqa: F401
    print("  [OK] backend.app.main imports successfully")


def main() -> None:
    print("=== Phase 8a Validation ===")
    print()

    tests = [
        ("sse_starlette importable", test_sse_starlette_importable),
        ("CORSMiddleware importable", test_cors_middleware_importable),
        ("config.cors_origins_list", test_config_cors_origins),
        ("stream module imports", test_stream_module_imports),
        ("router imports", test_router_imports),
        ("main imports", test_main_imports),
    ]

    failed = 0
    for name, fn in tests:
        print(f"Testing: {name}")
        try:
            fn()
        except Exception as exc:
            print(f"  [FAIL] {exc}")
            failed += 1

    print()
    if failed:
        print(f"FAILED: {failed} test(s) failed.")
        sys.exit(1)
    else:
        print("All Phase 8a validation checks passed.")
        print()
        print("Next step (run manually):")
        print("  cd /home/aihub/Code/story-forge")
        print("  .venv/bin/ruff check \\")
        print("    backend/app/config.py \\")
        print("    backend/app/main.py \\")
        print("    backend/app/api/v1/stream.py \\")
        print("    backend/app/api/v1/router.py")


if __name__ == "__main__":
    main()
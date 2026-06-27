"""Pytest fixtures and shared configuration for project3136859-388917 tests."""

import os
import sys
import pytest
from pathlib import Path

# Ensure project root is in Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Disable API key check for local tests
os.environ.setdefault("SKIP_API_KEY_CHECK", "1")
os.environ.setdefault("MILVUS_FORCE_FAISS", "1")

# Fixtures directory
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ═══════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_dmesg(fixtures_dir, request):
    """Load a specific dmesg fixture by name.

    Usage:
        def test_hardlockup(sample_dmesg):
            content = sample_dmesg("dmesg_hardlockup.txt")
    """
    def _load(name: str) -> str:
        path = fixtures_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        return path.read_text(encoding="utf-8")
    return _load


@pytest.fixture
def all_dmesg_fixtures(fixtures_dir):
    """List all available dmesg fixture file paths."""
    if not fixtures_dir.exists():
        return []
    return sorted(fixtures_dir.glob("dmesg_*.txt"))


# ═══════════════════════════════════════════════════════════
# Pytest markers
# ═══════════════════════════════════════════════════════════

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_git_repo: marks tests requiring a Linux kernel git repo"
    )
    config.addinivalue_line(
        "markers", "requires_model: marks tests requiring BGE model weights"
    )

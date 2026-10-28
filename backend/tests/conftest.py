import os
import tempfile
from pathlib import Path

# Isolated database and no network LLM calls for every test run.
_tmp = tempfile.mkdtemp()
os.environ["JOBMATCH_DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["JOBMATCH_USE_LLM"] = "false"
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402

from app.facts import get_facts  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def facts():
    return get_facts()


@pytest.fixture
def soc_jd():
    return (FIXTURES / "soc_analyst.txt").read_text()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

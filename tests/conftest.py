from pathlib import Path

import pytest

from solver import playbook

FIXTURES = Path(__file__).parent / "fixtures"
PLAYBOOK_MIN = FIXTURES / "playbook_min.md"


@pytest.fixture(scope="session")
def min_playbook() -> playbook.Playbook:
    return playbook.load_playbook(PLAYBOOK_MIN)

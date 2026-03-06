import os

import pytest


@pytest.fixture
def blob():
    return os.urandom(300_000)


@pytest.fixture
def sample_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("ReelVault test file\n" * 200)
    return path

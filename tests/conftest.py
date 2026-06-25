from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cairn_data_agent.api import create_app
from cairn_data_agent.config import Settings


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path, project_root: Path) -> Settings:
    return Settings(
        model_mode="fake",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_root=tmp_path / "storage",
        scenarios_root=project_root / "scenarios",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    response = client.post("/api/projects", json={"name": "测试项目"})
    assert response.status_code == 201
    return str(response.json()["id"])

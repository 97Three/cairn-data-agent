from __future__ import annotations

from .assets import AssetService
from .config import Settings
from .database import Database
from .executor import PlanExecutor
from .model import create_model
from .registry import ScenarioRegistry, SkillRegistry
from .service import DataAgentService
from .skill_runner import TrustedSkillRunner
from .storage import LocalBlobStore


def build_service(settings: Settings) -> DataAgentService:
    """Compose the service without importing the module-level ASGI application."""
    database = Database(settings)
    blobs = LocalBlobStore(settings.storage_root)
    assets = AssetService(settings, blobs)
    skills = SkillRegistry(settings.skills_root)
    return DataAgentService(
        database=database,
        assets=assets,
        scenarios=ScenarioRegistry(settings.scenarios_root, settings.skills_root),
        skills=skills,
        executor=PlanExecutor(assets, blobs, TrustedSkillRunner(skills)),
        model=create_model(settings),
    )

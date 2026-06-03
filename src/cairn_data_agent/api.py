from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .assets import AssetError
from .bootstrap import build_service
from .config import Settings, get_settings
from .contracts import AskRequest, ConversationCreate, ProjectCreate
from .logging import configure_logging
from .registry import RegistryError
from .service import NotFoundError, ServiceError


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    service = build_service(active_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        service.database.create_schema()
        yield

    app = FastAPI(
        title="Cairn Data Agent",
        version="0.1.0",
        description="Teaching-first, evidence-grounded Data Agent",
        lifespan=lifespan,
    )
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(_: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(RegistryError)
    async def registry_error_handler(_: Request, error: RegistryError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "modelMode": active_settings.model_mode}

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        try:
            return service.list_scenarios()
        except RegistryError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @app.post("/api/projects", status_code=201)
    def create_project(request: ProjectCreate) -> dict[str, Any]:
        return service.create_project(request)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return service.get_project(project_id)

    @app.post("/api/projects/{project_id}/conversations", status_code=201)
    def create_conversation(project_id: str, request: ConversationCreate) -> dict[str, Any]:
        return service.create_conversation(project_id, request)

    @app.post("/api/projects/{project_id}/assets", status_code=201)
    async def upload_asset(project_id: str, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        content = await file.read(active_settings.max_upload_bytes + 1)
        if len(content) > active_settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="文件超过教学版上传上限")
        try:
            return service.ingest_asset(
                project_id=project_id,
                filename=file.filename or "unnamed",
                media_type=file.content_type or "application/octet-stream",
                content=content,
            )
        except AssetError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/assets/{asset_id}/preview")
    def preview_asset(asset_id: str) -> dict[str, Any]:
        return service.preview_asset(asset_id)

    @app.post("/api/projects/{project_id}/ask")
    def ask(project_id: str, request: AskRequest) -> dict[str, Any]:
        return service.ask(project_id, request)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return service.get_run(run_id)

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict[str, Any]:
        return service.get_artifact(artifact_id)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("cairn_data_agent.api:app", host="127.0.0.1", port=8000, reload=False)

from contextlib import asynccontextmanager

from fastapi import FastAPI

from dstack._internal.server.background import start_background_tasks
from dstack._internal.server.db import migrate
from dstack._internal.server.routers import backends, logs, projects, repos, runs, secrets, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    await migrate()
    scheduler = start_background_tasks()
    yield
    scheduler.shutdown()


app = FastAPI(docs_url="/api/docs", lifespan=lifespan)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(backends.root_router)
app.include_router(backends.project_router)
app.include_router(repos.router)
app.include_router(runs.router)
app.include_router(logs.router)
app.include_router(secrets.router)
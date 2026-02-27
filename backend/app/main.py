import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ALLOWED_ROOT = Path(os.getenv("DOCS_ALLOWED_ROOT", "/workspace")).resolve()
GENERATED_ROOT = Path(os.getenv("DOCS_GENERATED_ROOT", "/tmp/generated_docs")).resolve()
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)


class GenerateDocsRequest(BaseModel):
    source_path: str = Field(min_length=1)


class TaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "success", "error"]
    result_url: str | None = None
    error: str | None = None


@dataclass
class TaskState:
    task_id: str
    source_path: Path
    status: Literal["pending", "running", "success", "error"] = "pending"
    logs: list[str] = field(default_factory=list)
    result_url: str | None = None
    error: str | None = None
    subscribers: set[asyncio.Queue[str]] = field(default_factory=set)


app = FastAPI(title="UI for ai-docs-generate")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/generated", StaticFiles(directory=str(GENERATED_ROOT), html=True), name="generated")

TASKS: dict[str, TaskState] = {}


def validate_source_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = (ALLOWED_ROOT / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Path must stay inside {ALLOWED_ROOT}") from exc

    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Source path does not exist or is not a directory")
    return resolved


async def publish_log(task: TaskState, message: str) -> None:
    task.logs.append(message)
    for queue in list(task.subscribers):
        await queue.put(message)


async def set_final_state(task: TaskState, status: Literal["success", "error"], message: str) -> None:
    task.status = status
    await publish_log(task, message)
    if status == "success":
        await publish_log(task, f"__FINISHED__|{task.result_url}")
    else:
        await publish_log(task, "__FAILED__")


async def run_generator_task(task_id: str) -> None:
    task = TASKS[task_id]
    task.status = "running"
    await publish_log(task, f"Running ai-docs-generate for {task.source_path}")

    process = await asyncio.create_subprocess_exec(
        "ai-docs-generate",
        str(task.source_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        await publish_log(task, line.decode(errors="replace").rstrip("\n"))

    return_code = await process.wait()
    if return_code != 0:
        task.error = f"Generator failed with exit code {return_code}"
        await set_final_state(task, "error", task.error)
        return

    docs_index = task.source_path / "docs" / "index.html"
    if not docs_index.exists():
        task.error = "Generation completed, but docs/index.html not found"
        await set_final_state(task, "error", task.error)
        return

    target = GENERATED_ROOT / task.task_id
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    os.symlink((task.source_path / "docs").resolve(), target, target_is_directory=True)
    task.result_url = f"/generated/{task.task_id}/index.html"
    await set_final_state(task, "success", "Documentation generated successfully")


@app.post("/api/generate-docs")
async def generate_docs(request: GenerateDocsRequest, background_tasks: BackgroundTasks) -> JSONResponse:
    source_path = validate_source_path(request.source_path)
    task_id = str(uuid.uuid4())
    TASKS[task_id] = TaskState(task_id=task_id, source_path=source_path)
    background_tasks.add_task(run_generator_task, task_id)
    return JSONResponse(status_code=202, content={"task_id": task_id})


@app.get("/api/result/{task_id}", response_model=TaskStatusResponse)
async def get_result(task_id: str) -> TaskStatusResponse:
    task = TASKS.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        result_url=task.result_url,
        error=task.error,
    )


@app.websocket("/ws/logs/{task_id}")
async def logs_ws(websocket: WebSocket, task_id: str) -> None:
    task = TASKS.get(task_id)
    if task is None:
        await websocket.close(code=4404, reason="Task not found")
        return

    await websocket.accept()
    queue: asyncio.Queue[str] = asyncio.Queue()
    task.subscribers.add(queue)

    try:
        for log in task.logs:
            await websocket.send_text(log)

        while True:
            message = await queue.get()
            await websocket.send_text(message)
            if message.startswith("__FINISHED__") or message == "__FAILED__":
                break
    except WebSocketDisconnect:
        pass
    finally:
        task.subscribers.discard(queue)

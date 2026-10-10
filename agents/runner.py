r"""
HalalReady agent runner: seven Gemini agents working off the backend's task board.

    .venv\Scripts\python -m agents.runner            # watch: run agents whenever tasks appear (the demo)
    .venv\Scripts\python -m agents.runner --once     # run until the board is quiet, then exit

An agent runs when it has open tasks. Up to three run at the same time. Each
gets its instructions (agents/prompts), its open tasks and only its own tools,
and works until it has closed every task. When the board goes quiet after
some work, the Coordinator is asked to update the owner's status and the pack.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from google.genai import types  # noqa: E402

from . import tools  # noqa: E402
from .gemini import MODEL, pool  # noqa: E402

log = logging.getLogger("runner")

PROMPTS = ROOT / "agents" / "prompts"
MAX_PARALLEL = int(os.getenv("AGENT_PARALLEL", "3"))
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "30"))
HEARTBEAT = ROOT / ".cache" / "runner.json"   # read by the backend to show whether the agents are running
RETRY_AFTER = 60                               # seconds before a crashed agent tries its tasks again
MAX_RETRIES = 3                                # then its tasks close as failed, with a card for the owner
REQUEST_BUDGET = int(os.getenv("RUN_REQUEST_BUDGET", "400"))   # Gemini requests per run, then the run pauses
WRAP_UP_TITLE = "Update the owner's status and assemble the pack"


def instructions(agent: str) -> str:
    return (PROMPTS / "_shared.md").read_text(encoding="utf-8") + "\n\n" + \
        (PROMPTS / f"{agent}.md").read_text(encoding="utf-8")


def declarations(agent: str) -> list[types.FunctionDeclaration]:
    return [types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in (tools.TOOLS[n] for n in tools.AGENT_TOOLS[agent])]


def brief(tasks: list[dict], today: str) -> str:
    lines = [f"Today is {today}. Your open tasks:"]
    for t in tasks:
        item = {"task_id": t["id"], "from": t["from_agent"], "title": t["title"]}
        if t.get("detail"):
            item["detail"] = t["detail"]
        if t.get("payload"):
            item["payload"] = t["payload"]
        lines.append(json.dumps(item, ensure_ascii=False))
    lines.append("Do the steps for each task, then close it with complete_task.")
    return "\n".join(lines)


async def run_agent(agent: str, backend: tools.Backend) -> int:
    """One turn for one agent: pick up its open tasks and work until they are closed. Returns tasks handled."""
    tasks = await backend.call("GET", "/agent/tasks", params={"agent": agent, "business_id": tools.BUSINESS_ID})
    if not tasks:
        return 0
    clock = await backend.call("GET", "/clock")
    ctx = tools.Ctx(agent=agent, backend=backend, task_ids=[t["id"] for t in tasks], tasks={t["id"]: t for t in tasks})
    config = types.GenerateContentConfig(
        system_instruction=instructions(agent), temperature=0,
        tools=[types.Tool(function_declarations=declarations(agent))],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=brief(tasks, clock["today"]))])]
    log.info("%s: %d task(s): %s", agent, len(tasks), "; ".join(t["title"] for t in tasks))
    for t in tasks:   # visible pick-up, so every handoff reads ask -> on it -> answer
        if t["from_agent"] in tools.AGENTS:
            await backend.event(agent, f"On it: {t['title']}", "action", handed_to=t["from_agent"],
                                message="On it.")

    nudged = False
    for step in range(MAX_STEPS):
        resp = await pool().generate(contents, config)
        if not resp.candidates or not resp.candidates[0].content:
            log.warning("%s: empty response", agent)
            break
        contents.append(resp.candidates[0].content)
        calls = resp.function_calls or []
        if not calls:
            still_open = await _open_ids(backend, agent, ctx.task_ids)
            if still_open and not nudged:
                nudged = True
                contents.append(types.Content(role="user", parts=[types.Part(text=(
                    f"Tasks {still_open} are still open. Finish their steps now and close each with complete_task."))]))
                continue
            break
        for c in calls:
            log.info("%s -> %s(%s)", agent, c.name, json.dumps(c.args, ensure_ascii=False)[:160])
        results = await tools.call_many(ctx, [(c.name, dict(c.args or {})) for c in calls])
        for c, r in zip(calls, results):
            if "error" in r:
                log.warning("%s: %s failed: %s", agent, c.name, r["error"])
        if any(c.name == "complete_task" for c in calls) and not await _open_ids(backend, agent, ctx.task_ids):
            break   # every task is closed: no need to ask the model again just to hear "done"
        contents.append(types.Content(role="user", parts=[
            types.Part.from_function_response(name=c.name, response=r) for c, r in zip(calls, results)]))
        # Gemini 3 needs each function response tied to its call id.
        for part, c in zip(contents[-1].parts, calls):
            if c.id:
                part.function_response.id = c.id

    # Safety net: never leave a task hanging on the board.
    for task_id in await _open_ids(backend, agent, ctx.task_ids):
        log.warning("%s: closing task %s that the agent left open", agent, task_id)
        await backend.call("POST", f"/agent/tasks/{task_id}/complete",
                           {"agent": agent, "result": "Closed by the runner; the agent stopped early"})
        await backend.event(agent, "Stopped early; task needs a re-run", "attention")
    return len(tasks)


async def _open_ids(backend: tools.Backend, agent: str, ids: list[int]) -> list[int]:
    rows = await backend.call("GET", f"/business/{tools.BUSINESS_ID}/tasks", params={"assignee": agent})
    return [t["id"] for t in rows if t["id"] in ids and t["status"] != "done"]


async def _waiting_agents(backend: tools.Backend) -> list[str]:
    rows = await backend.call("GET", f"/business/{tools.BUSINESS_ID}/tasks", params={"status": "open"})
    order = {a: i for i, a in enumerate(tools.AGENTS)}
    return sorted({t["assignee"] for t in rows}, key=lambda a: (order.get(a, 99)))


async def _current_run(backend: tools.Backend) -> int | None:
    rows = await backend.call("GET", f"/business/{tools.BUSINESS_ID}/tasks")
    return max((t["run_id"] or 0 for t in rows), default=None)


async def _give_up(backend: tools.Backend, agent: str, error: str):
    """After the last retry: close the agent's tasks as failed and tell the owner. Nothing is left hanging or hidden."""
    rows = await backend.call("GET", f"/business/{tools.BUSINESS_ID}/tasks", params={"assignee": agent})
    for t in rows:
        if t["status"] != "done":
            await backend.call("POST", f"/agent/tasks/{t['id']}/complete",
                               {"agent": agent, "result": f"FAILED after {MAX_RETRIES} retries: {error}"[:500]})
            await backend.call("POST", "/agent/approvals", {
                "business_id": tools.BUSINESS_ID, "kind": "question", "agent": agent,
                "title": f"Needs attention: {t['title']}"[:120],
                "body_en": f"The {agent.replace('_', ' ')} failed {MAX_RETRIES} times on this task ({error[:160]}). "
                           "Please start the run again, or check the files."})
    await backend.event(agent, f"Gave up after {MAX_RETRIES} retries", "problem", message=error[:400])


def _heartbeat(error: str | None):
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps({"at": time.time(), "pid": os.getpid(), "model": MODEL,
                                         "keys": pool().size, "requests": pool().sent, "error": error}),
                             encoding="utf-8")
    except OSError:
        pass


async def _stuck_agents(backend: tools.Backend) -> set[str]:
    rows = await backend.call("GET", f"/business/{tools.BUSINESS_ID}/tasks", params={"status": "in_progress"})
    return {t["assignee"] for t in rows}


async def _maybe_wrap_up(backend: tools.Backend, worked_since_wrap_up: bool) -> bool:
    """Ask the Coordinator for a status update once the board is quiet after real work."""
    if not worked_since_wrap_up:
        return False
    await backend.call("POST", "/agent/tasks", {
        "business_id": tools.BUSINESS_ID, "from_agent": "system", "assignee": "coordinator",
        "title": WRAP_UP_TITLE})
    return True


async def run(once: bool, poll_seconds: float = 2.0, idle_exit_seconds: float = 6.0):
    backend = tools.Backend()
    running: dict[str, asyncio.Task] = {}
    worked = False          # any agent other than a wrap-up has worked since the last wrap-up
    quiet_since: float | None = None
    retry_at: dict[str, float] = {}   # crashed agents, and when to try their tasks again
    retries: dict[str, int] = {}
    last_error: str | None = None
    run_id, run_start_sent, over_budget = None, 0, False
    loop = asyncio.get_running_loop()
    log.info("Runner up: model %s, %d key(s), up to %d agents at once", MODEL, pool().size, MAX_PARALLEL)
    # Tasks left "in progress" by a runner that stopped are picked up again.
    try:
        resume = await _stuck_agents(backend)
    except Exception:
        resume = set()
    if resume:
        log.info("Resuming unfinished tasks for: %s", ", ".join(sorted(resume)))

    while True:
        for agent, task in list(running.items()):
            if task.done():
                running.pop(agent)
                try:
                    handled = task.result()
                    log.info("%s finished (%d task(s))", agent, handled)
                    last_error = None
                except Exception as exc:
                    log.exception("%s crashed", agent)
                    last_error = str(exc)[:300]
                    quota = "daily quota" in last_error
                    retries[agent] = retries.get(agent, 0) + (0 if quota else 1)
                    if retries[agent] > MAX_RETRIES:
                        await _give_up(backend, agent, last_error)
                        retries.pop(agent)
                    else:
                        retry_at[agent] = loop.time() + RETRY_AFTER
                        await backend.event(agent, "Out of Gemini quota; paused" if quota else
                                            f"Hit an error; retry {retries[agent]} of {MAX_RETRIES}", "attention")
        _heartbeat(last_error)

        try:
            waiting = await _waiting_agents(backend)
            current = await _current_run(backend)
        except Exception as exc:
            log.warning("Backend not reachable: %s", exc)
            await asyncio.sleep(poll_seconds)
            continue

        if current != run_id:      # a new run: a fresh request budget
            run_id, run_start_sent, over_budget = current, pool().sent, False
        if pool().sent - run_start_sent >= REQUEST_BUDGET:
            if not over_budget:
                over_budget = True
                last_error = f"Request budget for this run reached ({REQUEST_BUDGET}); paused"
                await backend.event("coordinator", "Request budget reached; paused", "problem",
                                    message="The run used its Gemini request budget. Start a new run to continue.")
            waiting, resume = [], set()
        for a in list(resume):
            resume.discard(a)
            if a not in waiting:
                waiting.append(a)
        if retry_at:
            due = {a for a, t in retry_at.items() if t <= loop.time()}
            stuck = await _stuck_agents(backend) if due else set()
            for a in due:
                retry_at.pop(a)
                if a in stuck and a not in waiting:
                    waiting.append(a)
        for agent in waiting:
            if agent in retry_at:
                continue
            if agent not in running and len(running) < MAX_PARALLEL:
                running[agent] = asyncio.create_task(run_agent(agent, backend))
                if agent != "coordinator":
                    worked = True

        if running or waiting:
            quiet_since = None
        else:
            quiet_since = quiet_since or loop.time()
            if loop.time() - quiet_since >= 1.5 and await _maybe_wrap_up(backend, worked):
                worked = False
                quiet_since = None
            elif once and loop.time() - quiet_since >= idle_exit_seconds:
                log.info("Board is quiet; stopping (%d Gemini requests)", pool().sent)
                return
        await asyncio.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="exit when the task board is quiet")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()

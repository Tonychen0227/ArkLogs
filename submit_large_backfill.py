"""Submit unique Ark Nova table IDs in resumable Azure Batch jobs.

The tobiko-done.json ledger reserves IDs when tasks are submitted and records
completed IDs after Batch reports exit code 0. This prevents overlapping jobs
from scraping the same table while allowing failed tasks to be retried.
"""

import argparse
import json
import os
import re
import time
from collections.abc import Iterable
from pathlib import Path

from azure.batch import BatchClient
from azure.batch.models import (
    AutoUserSpecification,
    BatchJobCreateOptions,
    BatchPoolInfo,
    BatchTaskCreateOptions,
    ElevationLevel,
    UserIdentity,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

BATCH_URL = "https://arknovastats.eastus.batch.azure.com"
POOL_ID = "arknovalogspool"
WORK_DIR = "/arklogs/ArkLogs-main"
SOURCE_FILE = Path("tobiko-backfill.json")
LEDGER_FILE = Path("tobiko-done.json")
TABLES_PER_TASK = 100
TASK_TABLE_IDS = re.compile(r"run_batch\.py ([0-9,]+)")


def load_ledger() -> dict[str, dict[str, str]]:
    if not LEDGER_FILE.exists():
        return {}
    with LEDGER_FILE.open(encoding="utf-8") as ledger_file:
        document = json.load(ledger_file)
    if document.get("version") != 1 or not isinstance(document.get("tables"), dict):
        raise ValueError(f"Unsupported ledger format: {LEDGER_FILE}")
    return document["tables"]


def save_ledger(ledger: dict[str, dict[str, str]]) -> None:
    temporary_file = LEDGER_FILE.with_suffix(".tmp")
    with temporary_file.open("w", encoding="utf-8") as ledger_file:
        json.dump({"version": 1, "tables": ledger}, ledger_file, separators=(",", ":"))
    temporary_file.replace(LEDGER_FILE)


def task_table_ids(command_line: str | None) -> list[str]:
    match = TASK_TABLE_IDS.search(command_line or "")
    return match.group(1).split(",") if match else []


def reconcile_batch_jobs(client: BatchClient, ledger: dict[str, dict[str, str]]) -> None:
    """Add submitted jobs to the ledger and promote successful tasks to completed."""
    for job in client.list_jobs():
        if not job.id.startswith("backfill-"):
            continue
        for task in client.list_tasks(job_id=job.id):
            table_ids = task_table_ids(task.command_line)
            if not table_ids:
                continue
            is_success = task.state.value == "completed" and task.execution_info.exit_code == 0
            is_failed = task.state.value == "completed" and not is_success
            for table_id in table_ids:
                if is_success:
                    ledger[table_id] = {"status": "completed", "job_id": job.id, "task_id": task.id}
                elif not is_failed and ledger.get(table_id, {}).get("status") != "completed":
                    ledger[table_id] = {"status": "submitted", "job_id": job.id, "task_id": task.id}


def select_table_ids(ledger: dict[str, dict[str, str]], count: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    with SOURCE_FILE.open(encoding="utf-8") as source_file:
        for line in source_file:
            if not line.strip():
                continue
            table_id = str(json.loads(line)["table_id"])
            if not table_id.isdigit() or table_id in seen or table_id in ledger:
                continue
            seen.add(table_id)
            selected.append(table_id)
            if len(selected) == count:
                return selected
    raise ValueError(f"Only found {len(selected)} unreserved unique table IDs; requested {count}")


def batches(table_ids: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(table_ids), size):
        yield table_ids[start:start + size]


def build_command(table_ids: list[str], email: str, password: str) -> str:
    refresh_command = (
        "flock /tmp/arklogs-refresh.lock /bin/bash -c "
        "'curl -fsSL https://github.com/Tonychen0227/arklogs/archive/refs/heads/main.zip -o /tmp/arklogs.zip && "
        "unzip -oq /tmp/arklogs.zip -d /arklogs && rm /tmp/arklogs.zip'"
    )
    return (
        f'/bin/bash -c "{refresh_command} && '
        f'bash {WORK_DIR}/vpn-connect.sh && cd {WORK_DIR} && '
        f'export BGA_EMAIL={email} && export BGA_PASSWORD={password} && '
        f'export GOOGLE_APPLICATION_CREDENTIALS={WORK_DIR}/resources/gcp-sa-key.json && '
        "export PLAYWRIGHT_BROWSERS_PATH=/mnt/batch/tasks/startup/wd/.cache/ms-playwright && "
        f'export PYTHONUNBUFFERED=1 && python3 -u run_batch.py {",".join(table_ids)}"'
    )


def submit_job(
    client: BatchClient,
    ledger: dict[str, dict[str, str]],
    table_ids: list[str],
    job_number: int,
    email: str,
    password: str,
) -> str:
    job_id = f"backfill-100k-{int(time.time())}-{job_number:02d}"
    client.create_job(BatchJobCreateOptions(
        id=job_id,
        pool_info=BatchPoolInfo(pool_id=POOL_ID),
        priority=-10,
    ))
    print(f"Created {job_id} with {len(table_ids)} tables")

    for task_number, task_ids in enumerate(batches(table_ids, TABLES_PER_TASK), start=1):
        task_id = f"scrape-{task_number:04d}"
        client.create_task(job_id, BatchTaskCreateOptions(
            id=task_id,
            command_line=build_command(task_ids, email, password),
            user_identity=UserIdentity(auto_user=AutoUserSpecification(elevation_level=ElevationLevel.ADMIN)),
        ))
        for table_id in task_ids:
            ledger[table_id] = {"status": "submitted", "job_id": job_id, "task_id": task_id}
        if task_number % 100 == 0:
            save_ledger(ledger)
            print(f"  Submitted {task_number} tasks")

    save_ledger(ledger)
    return job_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500_000)
    parser.add_argument("--tables-per-job", type=int, default=100_000)
    parser.add_argument("--submit", action="store_true", help="Create jobs; otherwise only report the plan.")
    args = parser.parse_args()

    if args.count <= 0 or args.tables_per_job <= 0:
        raise ValueError("--count and --tables-per-job must be positive")
    if args.count % TABLES_PER_TASK or args.tables_per_job % TABLES_PER_TASK:
        raise ValueError(f"Counts must be divisible by {TABLES_PER_TASK}")

    load_dotenv()
    client = BatchClient(endpoint=BATCH_URL, credential=DefaultAzureCredential())
    ledger = load_ledger()
    reconcile_batch_jobs(client, ledger)
    save_ledger(ledger)

    selected = select_table_ids(ledger, args.count)
    job_count = (len(selected) + args.tables_per_job - 1) // args.tables_per_job
    print(f"Ledger: {len(ledger)} reserved/completed table IDs")
    print(f"Plan: {len(selected)} unique table IDs across {job_count} job(s)")
    if not args.submit:
        return

    email = os.environ["BGA_EMAIL"]
    password = os.environ["BGA_PASSWORD"]
    for job_number, job_table_ids in enumerate(batches(selected, args.tables_per_job), start=1):
        submit_job(client, ledger, job_table_ids, job_number, email, password)


if __name__ == "__main__":
    main()
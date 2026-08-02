"""Submit 100 Azure Batch tasks containing 100 backfill table IDs each."""
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
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

TABLE_IDS = (
    "500036750,500359582,500619489,500888125,500891114,500891706,501636545,501731387,"
    "501841168,501851291,501957619,501992211,502020802,502223194,502445731,502464251,"
    "502477730,502700272,503096709,503272561,503434880,503445705,503931195,504220695,"
    "504280513,504551893,504916653,505119116,505275697,505304199,505454199,505721419,"
    "505768540,505804199,505894683,505928453,506419088,506419088,506428404,506608817,"
    "507075736,507157739,507161600,507345298,507419465,508107920,508129862,508134385,"
    "508139934,508277357,508353730,508604940,508688868,508890467,508893030,508989279,"
    "509159141,509490833,509816025,509855507,510394175,510401113,510561122,510993117,"
    "511020722,511071719,511076862,511120814,511201133,511214103,511460170,511509594,"
    "511522010,511760940,511835735,511959792,511975225,511978947,512126177,512174883,"
    "512192199,512370897,512470556,512711502,512758013,512764079,512830445,513174046,"
    "513251107,513422431,513575563,513937128,513966374,514004207,514114490,514368552,"
    "514949330,515016150,515117487,515265717"
)

BATCH_URL = "https://arknovastats.eastus.batch.azure.com"
POOL_ID = "arknovalogspool"
JOB_ID = f"backfill-10k-{int(time.time())}"
WORK_DIR = "/arklogs/ArkLogs-main"
SOURCE_FILE = "tobiko-backfill.json"
TASK_COUNT = 100
TABLES_PER_TASK = 100


def load_table_batches():
    table_ids = []
    with open(SOURCE_FILE, encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            table_id = str(json.loads(line)["table_id"])
            if not table_id.isdigit():
                raise ValueError(f"Invalid table ID: {table_id!r}")
            table_ids.append(table_id)
            if len(table_ids) == TASK_COUNT * TABLES_PER_TASK:
                break

    expected_count = TASK_COUNT * TABLES_PER_TASK
    if len(table_ids) != expected_count:
        raise ValueError(f"Expected {expected_count} table IDs, found {len(table_ids)}")

    return [table_ids[start:start + TABLES_PER_TASK] for start in range(0, expected_count, TABLES_PER_TASK)]

cred = DefaultAzureCredential()
client = BatchClient(endpoint=BATCH_URL, credential=cred)

table_batches = load_table_batches()

# Create job
job = BatchJobCreateOptions(
    id=JOB_ID,
    pool_info=BatchPoolInfo(pool_id=POOL_ID),
)
client.create_job(job)
print(f"Created job: {JOB_ID}")

# Build command — set env vars and run scraper
# Running as admin so we can refresh code from GitHub
bga_email = os.environ["BGA_EMAIL"]
bga_password = os.environ["BGA_PASSWORD"]

REFRESH_CMD = (
    "curl -fsSL https://github.com/Tonychen0227/arklogs/archive/refs/heads/main.zip -o /tmp/arklogs.zip && "
    "unzip -oq /tmp/arklogs.zip -d /arklogs && "
    "rm /tmp/arklogs.zip"
)

VPN_CONNECT = f"bash {WORK_DIR}/vpn-connect.sh"

def build_command(table_ids):
    return (
        f'/bin/bash -c "'
        f'{REFRESH_CMD} && '
        f'{VPN_CONNECT} && '
        f'cd {WORK_DIR} && '
        f'export BGA_EMAIL={bga_email} && '
        f'export BGA_PASSWORD={bga_password} && '
        f'export GOOGLE_APPLICATION_CREDENTIALS={WORK_DIR}/gcp-sa-key.json && '
        f'export PLAYWRIGHT_BROWSERS_PATH=/mnt/batch/tasks/startup/wd/.cache/ms-playwright && '
        f'export PYTHONUNBUFFERED=1 && '
        f'python3 -u run_batch.py {",".join(table_ids)}"'
    )


for index, table_ids in enumerate(table_batches, start=1):
    task = BatchTaskCreateOptions(
        id=f"scrape-{index:03d}",
        command_line=build_command(table_ids),
        user_identity=UserIdentity(
            auto_user=AutoUserSpecification(elevation_level=ElevationLevel.ADMIN)
        ),
    )
    client.create_task(JOB_ID, task)

print(f"Created {len(table_batches)} tasks with {TABLES_PER_TASK} tables each")
print(f"Monitor: az batch task list --job-id {JOB_ID} --account-name arknovastats --account-endpoint {BATCH_URL}")

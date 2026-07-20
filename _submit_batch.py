"""Create an Azure Batch job + task to scrape 100 tables starting with 5XX."""
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
JOB_ID = "backfill-5xx-008"
WORK_DIR = r"C:\arklogs\arklogs-main"

cred = DefaultAzureCredential()
client = BatchClient(endpoint=BATCH_URL, credential=cred)

# Delete old jobs if they exist
for old_id in ["backfill-5xx-001", "backfill-5xx-002", "backfill-5xx-003", "backfill-5xx-004", "backfill-5xx-005", "backfill-5xx-006"]:
    try:
        client.delete_job(old_id)
        print(f"Deleted old job {old_id}")
    except Exception:
        pass

# Create job
job = BatchJobCreateOptions(
    id=JOB_ID,
    pool_info=BatchPoolInfo(pool_id=POOL_ID),
)
client.create_job(job)
print(f"Created job: {JOB_ID}")

# Build command — re-download latest code, set env vars, run scraper
bga_email = os.environ["BGA_EMAIL"]
bga_password = os.environ["BGA_PASSWORD"]

# Re-download repo zip to get latest code before running
REFRESH_CMD = (
    "powershell -Command \""
    "Invoke-WebRequest -Uri 'https://github.com/Tonychen0227/arklogs/archive/refs/heads/main.zip' "
    "-OutFile '%TEMP%\\arklogs.zip' -UseBasicParsing; "
    "Expand-Archive -Path '%TEMP%\\arklogs.zip' -DestinationPath 'C:\\arklogs' -Force"
    "\""
)

cmd = (
    f'cmd /c "{REFRESH_CMD} && '
    f'cd /d {WORK_DIR} && '
    f'set BGA_EMAIL={bga_email} && '
    f'set BGA_PASSWORD={bga_password} && '
    f'set GOOGLE_APPLICATION_CREDENTIALS={WORK_DIR}\\gcp-sa-key.json && '
    f'set PYTHONUNBUFFERED=1 && '
    f'python -u run_batch.py {TABLE_IDS}"'
)

task = BatchTaskCreateOptions(
    id="scrape-5xx",
    command_line=cmd,
    user_identity=UserIdentity(
        auto_user=AutoUserSpecification(
            elevation_level=ElevationLevel.ADMIN,
        )
    ),
)
client.create_task(JOB_ID, task)
print(f"Created task: scrape-5xx ({len(TABLE_IDS.split(','))} tables)")
print(f"Monitor: az batch task show --job-id {JOB_ID} --task-id scrape-5xx --account-name arknovastats --account-endpoint {BATCH_URL}")

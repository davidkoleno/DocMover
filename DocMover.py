import sqlite3
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock


# =========================
# CONFIG
# =========================

SOURCE_ROOT = Path(r"\\server\share\source")
DESTINATION_ROOT = Path(r"\\server\share\backup")

DB_PATH = Path(r"C:\Temp\backup_index.db")

# Number of folders copied simultaneously
MAX_WORKERS = 4

# Robocopy threads per folder
ROBOCOPY_THREADS = 8

# Retry settings
RETRIES = 2
WAIT_SECONDS = 1


# Used so console messages don't overlap badly
print_lock = Lock()


# =========================
# DATABASE SETUP
# =========================

def prepare_database(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS copied_folders (
            folder_path TEXT PRIMARY KEY,
            completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            robocopy_exit_code INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_folders (
            folder_path TEXT PRIMARY KEY,
            last_attempt TEXT DEFAULT CURRENT_TIMESTAMP,
            robocopy_exit_code INTEGER,
            error_message TEXT
        )
    """)

    conn.commit()


# =========================
# GET FOLDERS TO COPY
# =========================

def get_folders(conn):

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(files)")
    }

    # If the verifier has already been run,
    # only process folders containing something
    # that isn't verified.
    if "size_matches" in columns:

        print("Verification data found.")
        print("Only folders containing unverified files will be queued.")
        print()

        rows = conn.execute("""
            SELECT DISTINCT folder_path
            FROM files
            WHERE COALESCE(size_matches, 0) = 0
            ORDER BY folder_path
        """).fetchall()

    else:

        print("No verification data found.")
        print("All indexed folders will be considered.")
        print("Robocopy will skip files already present.")
        print()

        rows = conn.execute("""
            SELECT folder_path
            FROM indexed_folders
            ORDER BY folder_path
        """).fetchall()

    folders = [row[0] for row in rows]

    # Remove folders already completed by this copier
    completed = {
        row[0]
        for row in conn.execute("""
            SELECT folder_path
            FROM copied_folders
        """)
    }

    folders = [
        folder
        for folder in folders
        if folder not in completed
    ]

    return folders


# =========================
# ROBOCOPY
# =========================

def copy_folder(folder_path):

    source_folder = Path(folder_path)

    relative_folder = source_folder.relative_to(SOURCE_ROOT)

    destination_folder = DESTINATION_ROOT / relative_folder

    command = [
        "robocopy",
        str(source_folder),
        str(destination_folder),
        "/E",
        f"/MT:{ROBOCOPY_THREADS}",
        f"/R:{RETRIES}",
        f"/W:{WAIT_SECONDS}",
        "/COPY:DAT",
        "/DCOPY:T",
        "/NP",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS"
    ]

    start_time = time.time()

    try:

        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )

        elapsed = time.time() - start_time

        return {
            "folder": folder_path,
            "destination": str(destination_folder),
            "exit_code": result.returncode,
            "elapsed": elapsed,
            "error": result.stderr.strip()
        }

    except Exception as e:

        return {
            "folder": folder_path,
            "destination": str(destination_folder),
            "exit_code": -1,
            "elapsed": time.time() - start_time,
            "error": str(e)
        }


# =========================
# DATABASE RESULTS
# =========================

def mark_complete(folder, exit_code):

    conn = sqlite3.connect(DB_PATH)

    try:

        conn.execute("""
            INSERT OR REPLACE INTO copied_folders (
                folder_path,
                completed_at,
                robocopy_exit_code
            )
            VALUES (
                ?,
                CURRENT_TIMESTAMP,
                ?
            )
        """, (
            folder,
            exit_code
        ))

        # Remove old failure record if this folder
        # previously failed but now succeeded.
        conn.execute("""
            DELETE FROM failed_folders
            WHERE folder_path = ?
        """, (
            folder,
        ))

        conn.commit()

    finally:

        conn.close()


def mark_failed(folder, exit_code, error):

    conn = sqlite3.connect(DB_PATH)

    try:

        conn.execute("""
            INSERT OR REPLACE INTO failed_folders (
                folder_path,
                last_attempt,
                robocopy_exit_code,
                error_message
            )
            VALUES (
                ?,
                CURRENT_TIMESTAMP,
                ?,
                ?
            )
        """, (
            folder,
            exit_code,
            error
        ))

        conn.commit()

    finally:

        conn.close()


# =========================
# COPY PROCESS
# =========================

def run_copy():

    conn = sqlite3.connect(DB_PATH)

    try:

        prepare_database(conn)

        folders = get_folders(conn)

    finally:

        conn.close()

    total = len(folders)

    if total == 0:

        print("No folders need to be copied.")
        return

    print(f"Folders queued:     {total:,}")
    print(f"Folder workers:     {MAX_WORKERS}")
    print(f"Threads per folder: {ROBOCOPY_THREADS}")
    print(
        f"Potential copy threads: "
        f"{MAX_WORKERS * ROBOCOPY_THREADS}"
    )
    print()

    completed = 0
    failed = 0

    start_time = time.time()

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                copy_folder,
                folder
            ): folder
            for folder in folders
        }

        for future in as_completed(futures):

            result = future.result()

            folder = result["folder"]
            exit_code = result["exit_code"]

            # Robocopy exit codes 0-7 are considered
            # successful / non-fatal.
            if 0 <= exit_code < 8:

                mark_complete(
                    folder,
                    exit_code
                )

                completed += 1

                status = "OK"

            else:

                mark_failed(
                    folder,
                    exit_code,
                    result["error"]
                )

                failed += 1

                status = "FAILED"

            finished = completed + failed

            elapsed = time.time() - start_time

            folders_per_minute = (
                finished / elapsed * 60
                if elapsed else 0
            )

            with print_lock:

                print(
                    f"[{finished:,}/{total:,}] "
                    f"{status} | "
                    f"Code {exit_code} | "
                    f"{result['elapsed']:.1f}s | "
                    f"{folders_per_minute:.1f} folders/min | "
                    f"{folder}"
                )

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("COPY SESSION COMPLETE")
    print("=" * 60)
    print(f"Folders attempted: {total:,}")
    print(f"Successful:        {completed:,}")
    print(f"Failed:            {failed:,}")
    print(f"Elapsed:           {elapsed / 60:,.1f} minutes")
    print("=" * 60)


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    run_copy()

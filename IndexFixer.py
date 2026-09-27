import sqlite3
import time
from pathlib import Path


# =========================
# CONFIG
# =========================

DB_PATH = Path(r"C:\Temp\backup_index.db")


# =========================
# MAIN
# =========================

def main():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database does not exist: {DB_PATH}"
        )

    print(f"Database: {DB_PATH}")
    print()
    print("Checking existing indexed folders...")

    conn = sqlite3.connect(DB_PATH)

    try:

        # Create folder tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_folders (
                folder_path TEXT PRIMARY KEY,
                file_count INTEGER,
                indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

        # Count files already indexed
        total_files = conn.execute("""
            SELECT COUNT(*)
            FROM files
        """).fetchone()[0]

        # Count distinct folders already represented
        distinct_folders = conn.execute("""
            SELECT COUNT(DISTINCT folder_path)
            FROM files
        """).fetchone()[0]

        print(f"Existing indexed files:   {total_files:,}")
        print(f"Existing indexed folders: {distinct_folders:,}")
        print()
        print("Building folder completion table...")

        start_time = time.time()

        conn.execute("""
            INSERT OR IGNORE INTO indexed_folders (
                folder_path,
                file_count
            )
            SELECT
                folder_path,
                COUNT(*)
            FROM files
            GROUP BY folder_path
        """)

        conn.commit()

        completed_folders = conn.execute("""
            SELECT COUNT(*)
            FROM indexed_folders
        """).fetchone()[0]

        elapsed = time.time() - start_time

        print()
        print("Recovery complete.")
        print(f"Folders marked complete: {completed_folders:,}")
        print(f"Elapsed:                 {elapsed:,.1f} seconds")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

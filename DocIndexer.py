import os
import sqlite3
import sys
import time
from pathlib import Path

# =========================
# CONFIG
# =========================

SOURCE_ROOT = Path(r"\\server\share\source")
DB_PATH = Path(r"C:\Temp\backup_index.db")

COMMIT_EVERY = 10_000
PRINT_EVERY = 10_000


# =========================
# DATABASE SETUP
# =========================

def create_database(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            relative_path TEXT NOT NULL UNIQUE,
            full_path TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            top_level_folder TEXT,
            filename TEXT NOT NULL,
            extension TEXT,
            size_bytes INTEGER,
            modified_time REAL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_files_folder_path
        ON files(folder_path)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_files_top_level_folder
        ON files(top_level_folder)
    """)

    conn.commit()


# =========================
# INDEXING
# =========================

def index_files(source_root, conn):
    source_root = Path(source_root)

    if not source_root.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_root}")

    cursor = conn.cursor()

    processed = 0
    inserted = 0
    errors = 0

    start_time = time.time()

    print(f"Indexing: {source_root}")
    print(f"Database: {DB_PATH}")
    print()

    for root, dirs, files in os.walk(source_root):
        root_path = Path(root)

        for filename in files:
            processed += 1

            try:
                full_path = root_path / filename
                relative_path = full_path.relative_to(source_root)

                stat = full_path.stat()

                parts = relative_path.parts
                top_level_folder = parts[0] if len(parts) > 1 else ""

                cursor.execute("""
                    INSERT OR IGNORE INTO files (
                        relative_path,
                        full_path,
                        folder_path,
                        top_level_folder,
                        filename,
                        extension,
                        size_bytes,
                        modified_time
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(relative_path),
                    str(full_path),
                    str(root_path),
                    top_level_folder,
                    filename,
                    full_path.suffix,
                    stat.st_size,
                    stat.st_mtime
                ))

                if cursor.rowcount > 0:
                    inserted += 1

            except Exception as e:
                errors += 1
                print(f"\nERROR: {full_path}")
                print(f"       {e}")

            if processed % COMMIT_EVERY == 0:
                conn.commit()

            if processed % PRINT_EVERY == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed else 0

                print(
                    f"\rProcessed: {processed:,} | "
                    f"Inserted: {inserted:,} | "
                    f"Errors: {errors:,} | "
                    f"{rate:,.0f} files/sec",
                    end="",
                    flush=True
                )

    conn.commit()

    elapsed = time.time() - start_time

    print("\n")
    print("Index complete.")
    print(f"Processed: {processed:,}")
    print(f"Inserted:  {inserted:,}")
    print(f"Errors:    {errors:,}")
    print(f"Elapsed:   {elapsed / 60:,.1f} minutes")


# =========================
# MAIN
# =========================

def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    try:
        create_database(conn)
        index_files(SOURCE_ROOT, conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

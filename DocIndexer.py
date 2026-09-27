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

    processed_files = 0
    processed_folders = 0
    inserted = 0
    errors = 0

    start_time = time.time()

    print(f"Indexing: {source_root}")
    print(f"Database: {DB_PATH}")
    print()

    # Get top-level folders first
    print("Finding folders...")

    folders = []

    with os.scandir(source_root) as entries:
        for entry in entries:
            try:
                if entry.is_dir():
                    folders.append(entry.path)
            except OSError as e:
                print(f"Unable to inspect: {entry.path}")
                print(e)

    total_folders = len(folders)

    print(f"Found {total_folders:,} folders.")
    print()
    print("Beginning file indexing...")
    print()

    for folder_path in folders:

        processed_folders += 1

        try:
            with os.scandir(folder_path) as entries:

                for entry in entries:

                    try:
                        if not entry.is_file():
                            continue

                        processed_files += 1

                        full_path = Path(entry.path)
                        relative_path = full_path.relative_to(source_root)

                        # scandir gives us cached stat information on many systems
                        stat = entry.stat()

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
                            str(folder_path),
                            Path(folder_path).name,
                            entry.name,
                            full_path.suffix,
                            stat.st_size,
                            stat.st_mtime
                        ))

                        if cursor.rowcount > 0:
                            inserted += 1

                    except Exception as e:
                        errors += 1
                        print(f"\nFILE ERROR: {entry.path}")
                        print(f"            {e}")

        except Exception as e:
            errors += 1
            print(f"\nFOLDER ERROR: {folder_path}")
            print(f"              {e}")

        # Commit after each folder
        conn.commit()

        elapsed = time.time() - start_time
        rate = processed_files / elapsed if elapsed else 0

        print(
            f"\rFolder: {processed_folders:,}/{total_folders:,} "
            f"({processed_folders / total_folders * 100:.2f}%) | "
            f"Files: {processed_files:,} | "
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
    print(f"Folders:   {processed_folders:,}")
    print(f"Files:     {processed_files:,}")
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

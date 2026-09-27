import os
import sqlite3
import time
from pathlib import Path


# =========================
# CONFIG
# =========================

SOURCE_ROOT = Path(r"\\server\share\source")
DB_PATH = Path(r"C:\Temp\backup_index.db")


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

    # NEW - tracks folders that have been completely indexed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_folders (
            folder_path TEXT PRIMARY KEY,
            file_count INTEGER,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()


# =========================
# INDEXING
# =========================

def index_files(source_root, conn):

    source_root = Path(source_root)

    if not source_root.exists():
        raise FileNotFoundError(
            f"Source path does not exist: {source_root}"
        )

    cursor = conn.cursor()

    processed_files = 0
    processed_folders = 0
    skipped_folders = 0
    inserted = 0
    errors = 0

    start_time = time.time()

    print(f"Indexing: {source_root}")
    print(f"Database: {DB_PATH}")
    print()

    # =========================
    # FIND TOP-LEVEL FOLDERS
    # =========================

    print("Finding folders...")

    folders = []

    with os.scandir(source_root) as entries:

        for entry in entries:

            try:

                if entry.is_dir():
                    folders.append(entry.path)

            except OSError as e:

                print(f"\nUnable to inspect: {entry.path}")
                print(f"                   {e}")

    total_folders = len(folders)

    print(f"Found {total_folders:,} folders.")

    # Count how many are already complete
    already_complete = cursor.execute("""
        SELECT COUNT(*)
        FROM indexed_folders
    """).fetchone()[0]

    print(f"Folders already indexed: {already_complete:,}")
    print()

    remaining = max(
        total_folders - already_complete,
        0
    )

    print(f"Approximately {remaining:,} folders remaining.")
    print()
    print("Beginning file indexing...")
    print()

    # =========================
    # PROCESS FOLDERS
    # =========================

    for folder_path in folders:

        # -------------------------
        # CHECK FOR COMPLETED FOLDER
        # -------------------------

        already_indexed = cursor.execute("""
            SELECT 1
            FROM indexed_folders
            WHERE folder_path = ?
        """, (
            str(folder_path),
        )).fetchone()

        if already_indexed:

            skipped_folders += 1
            continue

        processed_folders += 1

        folder_file_count = 0
        folder_had_error = False

        try:

            with os.scandir(folder_path) as entries:

                for entry in entries:

                    try:

                        if not entry.is_file():
                            continue

                        folder_file_count += 1
                        processed_files += 1

                        full_path = Path(entry.path)

                        relative_path = full_path.relative_to(
                            source_root
                        )

                        # DirEntry.stat() is generally more efficient
                        # than calling Path.stat() separately.
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

                        folder_had_error = True
                        errors += 1

                        print()
                        print(f"FILE ERROR: {entry.path}")
                        print(f"            {e}")

        except Exception as e:

            folder_had_error = True
            errors += 1

            print()
            print(f"FOLDER ERROR: {folder_path}")
            print(f"              {e}")

        # =========================
        # MARK FOLDER COMPLETE
        # =========================

        if not folder_had_error:

            cursor.execute("""
                INSERT OR REPLACE INTO indexed_folders (
                    folder_path,
                    file_count,
                    indexed_at
                )
                VALUES (
                    ?,
                    ?,
                    CURRENT_TIMESTAMP
                )
            """, (
                str(folder_path),
                folder_file_count
            ))

        # Commit entire folder
        conn.commit()

        # =========================
        # PROGRESS DISPLAY
        # =========================

        elapsed = time.time() - start_time

        rate = (
            processed_files / elapsed
            if elapsed else 0
        )

        total_done = skipped_folders + processed_folders

        percent = (
            total_done / total_folders * 100
            if total_folders else 0
        )

        print(
            f"\rOverall: {total_done:,}/{total_folders:,} "
            f"({percent:.2f}%) | "
            f"New folders: {processed_folders:,} | "
            f"Skipped: {skipped_folders:,} | "
            f"New files scanned: {processed_files:,} | "
            f"Inserted: {inserted:,} | "
            f"Errors: {errors:,} | "
            f"{rate:,.0f} files/sec",
            end="",
            flush=True
        )

    conn.commit()

    # =========================
    # FINAL STATS
    # =========================

    elapsed = time.time() - start_time

    completed_folders = conn.execute("""
        SELECT COUNT(*)
        FROM indexed_folders
    """).fetchone()[0]

    total_files = conn.execute("""
        SELECT COUNT(*)
        FROM files
    """).fetchone()[0]

    print("\n")
    print("=" * 60)
    print("INDEX COMPLETE")
    print("=" * 60)

    print(f"Folders available:     {total_folders:,}")
    print(f"Folders completed:     {completed_folders:,}")
    print(f"Folders skipped:       {skipped_folders:,}")
    print(f"Folders processed now: {processed_folders:,}")
    print(f"Files processed now:   {processed_files:,}")
    print(f"Files inserted now:    {inserted:,}")
    print(f"Total files indexed:   {total_files:,}")
    print(f"Errors:                {errors:,}")
    print(f"Elapsed:               {elapsed / 60:,.1f} minutes")

    print("=" * 60)


# =========================
# MAIN
# =========================

def main():

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(DB_PATH)

    try:

        create_database(conn)

        index_files(
            SOURCE_ROOT,
            conn
        )

    finally:

        conn.close()


if __name__ == "__main__":
    main()

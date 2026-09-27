import os
import sqlite3
import time
from pathlib import Path


# =========================
# CONFIG
# =========================

DESTINATION_ROOT = Path(r"\\server\share\backup")
DB_PATH = Path(r"C:\Temp\backup_index.db")

COMMIT_EVERY = 10_000
PRINT_EVERY = 10_000


# =========================
# DATABASE SETUP
# =========================

def column_exists(conn, table_name, column_name):
    cursor = conn.execute(f"PRAGMA table_info({table_name})")

    return any(
        row[1] == column_name
        for row in cursor.fetchall()
    )


def prepare_database(conn):

    # Add verification columns to source file table
    if not column_exists(conn, "files", "destination_exists"):
        conn.execute("""
            ALTER TABLE files
            ADD COLUMN destination_exists INTEGER DEFAULT 0
        """)

    if not column_exists(conn, "files", "size_matches"):
        conn.execute("""
            ALTER TABLE files
            ADD COLUMN size_matches INTEGER DEFAULT 0
        """)

    if not column_exists(conn, "files", "verified_at"):
        conn.execute("""
            ALTER TABLE files
            ADD COLUMN verified_at TEXT
        """)

    # Temporary-ish persistent table containing the latest destination scan
    conn.execute("""
        CREATE TABLE IF NOT EXISTS destination_scan (
            relative_path TEXT PRIMARY KEY,
            size_bytes INTEGER
        )
    """)

    conn.commit()


# =========================
# DESTINATION SCAN
# =========================

def scan_destination(destination_root, conn):
    destination_root = Path(destination_root)

    print(f"Scanning destination:")
    print(destination_root)
    print()

    conn.execute("DELETE FROM destination_scan")
    conn.commit()

    cursor = conn.cursor()

    processed_files = 0
    processed_folders = 0
    errors = 0

    start_time = time.time()

    # =========================
    # FIND TOP-LEVEL FOLDERS
    # =========================

    print("Finding destination folders...")

    folders = []

    with os.scandir(destination_root) as entries:
        for entry in entries:
            try:
                if entry.is_dir():
                    folders.append(entry.path)

            except OSError as e:
                errors += 1
                print(f"\nUnable to inspect: {entry.path}")
                print(f"                   {e}")

    total_folders = len(folders)

    print(f"Found {total_folders:,} folders.")
    print()
    print("Beginning destination scan...")
    print()

    batch = []

    # =========================
    # SCAN EACH FOLDER
    # =========================

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
                        relative_path = full_path.relative_to(destination_root)

                        stat = entry.stat()

                        batch.append((
                            str(relative_path),
                            stat.st_size
                        ))

                    except Exception as e:

                        errors += 1

                        print(f"\nFILE ERROR: {entry.path}")
                        print(f"            {e}")

        except Exception as e:

            errors += 1

            print(f"\nFOLDER ERROR: {folder_path}")
            print(f"              {e}")

        # Write database batch when large enough
        if len(batch) >= COMMIT_EVERY:

            cursor.executemany("""
                INSERT OR REPLACE INTO destination_scan (
                    relative_path,
                    size_bytes
                )
                VALUES (?, ?)
            """, batch)

            conn.commit()

            batch.clear()

        # Progress display
        elapsed = time.time() - start_time
        rate = processed_files / elapsed if elapsed else 0

        percent = (
            processed_folders / total_folders * 100
            if total_folders else 0
        )

        print(
            f"\rFolder: {processed_folders:,}/{total_folders:,} "
            f"({percent:.2f}%) | "
            f"Files: {processed_files:,} | "
            f"Errors: {errors:,} | "
            f"{rate:,.0f} files/sec",
            end="",
            flush=True
        )

    # =========================
    # FINAL DATABASE WRITE
    # =========================

    if batch:

        cursor.executemany("""
            INSERT OR REPLACE INTO destination_scan (
                relative_path,
                size_bytes
            )
            VALUES (?, ?)
        """, batch)

        conn.commit()

    elapsed = time.time() - start_time

    print("\n")
    print("Destination scan complete.")
    print(f"Folders scanned: {processed_folders:,}")
    print(f"Files scanned:   {processed_files:,}")
    print(f"Errors:          {errors:,}")
    print(f"Elapsed:         {elapsed / 60:,.1f} minutes")


# =========================
# VERIFY
# =========================

def verify_files(conn):

    print()
    print("Comparing destination against source index...")

    start_time = time.time()

    # Reset verification state
    conn.execute("""
        UPDATE files
        SET
            destination_exists = 0,
            size_matches = 0,
            verified_at = NULL
    """)

    conn.commit()

    # Mark anything found at destination
    conn.execute("""
        UPDATE files
        SET destination_exists = 1
        WHERE relative_path IN (
            SELECT relative_path
            FROM destination_scan
        )
    """)

    conn.commit()

    # Mark files whose size also matches
    conn.execute("""
        UPDATE files
        SET
            size_matches = 1,
            verified_at = CURRENT_TIMESTAMP
        WHERE EXISTS (
            SELECT 1
            FROM destination_scan d
            WHERE d.relative_path = files.relative_path
              AND d.size_bytes = files.size_bytes
        )
    """)

    conn.commit()

    elapsed = time.time() - start_time

    print(
        f"Database comparison finished in "
        f"{elapsed:,.1f} seconds."
    )


# =========================
# SUMMARY
# =========================

def print_summary(conn):

    total = conn.execute("""
        SELECT COUNT(*)
        FROM files
    """).fetchone()[0]

    destination_exists = conn.execute("""
        SELECT COUNT(*)
        FROM files
        WHERE destination_exists = 1
    """).fetchone()[0]

    verified = conn.execute("""
        SELECT COUNT(*)
        FROM files
        WHERE size_matches = 1
    """).fetchone()[0]

    size_mismatch = conn.execute("""
        SELECT COUNT(*)
        FROM files
        WHERE destination_exists = 1
          AND size_matches = 0
    """).fetchone()[0]

    missing = conn.execute("""
        SELECT COUNT(*)
        FROM files
        WHERE destination_exists = 0
    """).fetchone()[0]

    extra_destination = conn.execute("""
        SELECT COUNT(*)
        FROM destination_scan d
        WHERE NOT EXISTS (
            SELECT 1
            FROM files f
            WHERE f.relative_path = d.relative_path
        )
    """).fetchone()[0]

    print()
    print("=" * 50)
    print("VERIFICATION SUMMARY")
    print("=" * 50)

    print(f"Source files indexed:      {total:,}")
    print(f"Found at destination:      {destination_exists:,}")
    print(f"Verified size match:       {verified:,}")
    print(f"Size mismatch:             {size_mismatch:,}")
    print(f"Missing at destination:    {missing:,}")
    print(f"Destination-only files:    {extra_destination:,}")

    if total:

        percent = (verified / total) * 100

        print()
        print(f"Backup complete:           {percent:.2f}%")

    print("=" * 50)


# =========================
# MAIN
# =========================

def main():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database does not exist: {DB_PATH}"
        )

    if not DESTINATION_ROOT.exists():
        raise FileNotFoundError(
            f"Destination does not exist: {DESTINATION_ROOT}"
        )

    conn = sqlite3.connect(DB_PATH)

    try:

        prepare_database(conn)

        scan_destination(
            DESTINATION_ROOT,
            conn
        )

        verify_files(conn)

        print_summary(conn)

    finally:

        conn.close()


if __name__ == "__main__":
    main()

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

    print(f"Scanning destination:")
    print(destination_root)
    print()

    # Clear results from previous scan
    conn.execute("DELETE FROM destination_scan")
    conn.commit()

    cursor = conn.cursor()

    processed = 0
    errors = 0

    start_time = time.time()

    batch = []

    for root, dirs, files in os.walk(destination_root):

        root_path = Path(root)

        for filename in files:

            processed += 1

            full_path = root_path / filename

            try:

                relative_path = full_path.relative_to(destination_root)

                stat = full_path.stat()

                batch.append((
                    str(relative_path),
                    stat.st_size
                ))

            except Exception as e:

                errors += 1

                print()
                print(f"ERROR: {full_path}")
                print(f"       {e}")

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

            if processed % PRINT_EVERY == 0:

                elapsed = time.time() - start_time

                rate = processed / elapsed if elapsed else 0

                print(
                    f"\rScanned: {processed:,} | "
                    f"Errors: {errors:,} | "
                    f"{rate:,.0f} files/sec",
                    end="",
                    flush=True
                )

    # Write final incomplete batch
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

    print()
    print()
    print("Destination scan complete.")
    print(f"Files scanned: {processed:,}")
    print(f"Errors:        {errors:,}")
    print(f"Elapsed:       {elapsed / 60:,.1f} minutes")


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

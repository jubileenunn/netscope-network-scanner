import os
import hashlib
import argparse
from collections import defaultdict
from pathlib import Path

def hash_file(path, chunk_size=8192):
    """Return the SHA256 hash of a file."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha.update(chunk)
    return sha.hexdigest()

def find_duplicates(root_dir):
    """
    Walk through the directory and group files by their hash.
    Returns:
        {hash_value: [list_of_paths_with_that_hash]}
    """
    root = Path(root_dir)
    duplicates = defaultdict(list)

    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                file_hash = hash_file(file_path)
                duplicates[file_hash].append(file_path)
            except (PermissionError, OSError) as e:
                print(f"⚠️  Skipping {file_path}: {e}")

    # Only return groups that actually contain duplicates
    return {h: paths for h, paths in duplicates.items() if len(paths) > 1}

def summarize_duplicates(dupe_map):
    """Print a summary of all detected duplicate groups."""
    total_groups = len(dupe_map)
    total_files = sum(len(paths) for paths in dupe_map.values())

    print(f"\n🔍 Found {total_groups} duplicate groups ({total_files} files total).\n")

    for i, (hash_value, paths) in enumerate(dupe_map.items(), start=1):
        print(f"Group {i} — hash: {hash_value[:12]}...")
        for p in paths:
            print(f"   • {p}")
        print()

def delete_duplicates(dupe_map, keep_first=True, dry_run=True):
    """
    Delete duplicates while keeping one file per group.
    If dry_run=True, only prints what would be deleted.
    """
    files_to_delete = []

    for paths in dupe_map.values():
        # Sort for predictable behavior
        sorted_paths = sorted(paths, key=lambda p: str(p))
        file_to_keep = sorted_paths[0] if keep_first else None

        for p in sorted_paths:
            if keep_first and p == file_to_keep:
                continue
            files_to_delete.append(p)

    if not files_to_delete:
        print("✨ No files to delete.")
        return

    print("🗑️  Files marked for deletion:")
    for p in files_to_delete:
        print(f"   • {p}")

    if dry_run:
        print("\n(Dry run enabled — no files were deleted.)")
        return

    print("\nDeleting files...")
    for p in files_to_delete:
        try:
            os.remove(p)
            print(f"✔️  Deleted: {p}")
        except (PermissionError, OSError) as e:
            print(f"❌ Failed to delete {p}: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Smart File Deduplicator — safely detect and remove duplicate files."
    )

    parser.add_argument("directory", help="Directory to scan for duplicates")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete duplicates (keeps one copy per group)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually delete files instead of previewing",
    )

    args = parser.parse_args()

    print(f"📁 Scanning directory: {args.directory}")
    duplicates = find_duplicates(args.directory)

    if not duplicates:
        print("🎉 No duplicates found!")
        return

    summarize_duplicates(duplicates)

    if args.delete:
        delete_duplicates(
            duplicates,
            keep_first=True,
            dry_run=not args.no_dry_run
        )
    else:
        print("ℹ️  Run again with --delete to remove duplicates (dry run by default).")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import argparse
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from datetime import datetime

# -----------------------------
# Hashing Utility
# -----------------------------
def hash_file(path, block_size=65536):
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                sha.update(block)
        return sha.hexdigest()
    except Exception as e:
        logging.error(f"Failed to hash {path}: {e}")
        return None

# -----------------------------
# Duplicate Scanner
# -----------------------------
def scan_for_duplicates(root, exclude_dirs=None, threads=8):
    size_map = {}
    hash_map = {}

    # Normalize exclude list
    exclude_dirs = set(os.path.abspath(d) for d in (exclude_dirs or []))

    # First pass: group by file size
    for dirpath, _, filenames in os.walk(root):
        if any(os.path.abspath(dirpath).startswith(ex) for ex in exclude_dirs):
            continue

        for name in filenames:
            full_path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full_path)
                size_map.setdefault(size, []).append(full_path)
            except OSError:
                continue

    # Second pass: hash only size-matched groups
    candidates = [paths for paths in size_map.values() if len(paths) > 1]
    total_files = sum(len(group) for group in candidates)

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {}
        with tqdm(total=total_files, desc="Hashing files", unit="file") as bar:
            for group in candidates:
                for path in group:
                    futures[executor.submit(hash_file, path)] = path

            for future in as_completed(futures):
                path = futures[future]
                digest = future.result()
                if digest:
                    hash_map.setdefault(digest, []).append(path)
                bar.update(1)

    # Filter only true duplicates
    return {h: p for h, p in hash_map.items() if len(p) > 1}

# -----------------------------
# Duplicate Deletion
# -----------------------------
def delete_duplicates(dupes, force=False):
    deleted = []
    for digest, paths in dupes.items():
        keep = paths[0]
        dups = paths[1:]

        print(f"\nDuplicate group (keeping): {keep}")
        for p in dups:
            print(f"  - {p}")

        if not force:
            confirm = input("Delete duplicates? [y/N]: ").strip().lower()
            if confirm != "y":
                continue

        for p in dups:
            try:
                os.remove(p)
                deleted.append(p)
                logging.info(f"Deleted {p}")
            except Exception as e:
                logging.error(f"Failed to delete {p}: {e}")

    return deleted

# -----------------------------
# Main CLI
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Smart File Deduplicator")
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--delete", action="store_true", help="Delete duplicates")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--exclude", nargs="*", help="Directories to exclude")
    parser.add_argument("--threads", type=int, default=8, help="Hashing threads")
    parser.add_argument("--log-file", help="Write actions to a log file")
    args = parser.parse_args()

    # Setup logging
    if args.log_file:
        logging.basicConfig(
            filename=args.log_file,
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )
    else:
        logging.basicConfig(level=logging.ERROR)

    root = os.path.abspath(args.directory)
    print(f"Scanning: {root}")

    duplicates = scan_for_duplicates(root, args.exclude, args.threads)

    if not duplicates:
        print("No duplicates found.")
        return

    print("\nDuplicates detected:")
    for digest, paths in duplicates.items():
        print(f"\nHash: {digest}")
        for p in paths:
            print(f"  - {p}")

    if args.delete:
        deleted = delete_duplicates(duplicates, args.force)
        print(f"\nDeleted {len(deleted)} files.")

if __name__ == "__main__":
    main()

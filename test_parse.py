import sys
from pathlib import Path
from src.semantic_organizer.extraction.engine import process_document_fast

try:
    process_document_fast(Path("test_dir/test_file.txt"))
except Exception as e:
    print("ERROR CAUGHT IN TEST_PARSE:", e)

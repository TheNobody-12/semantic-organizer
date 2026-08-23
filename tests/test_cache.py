import pytest
from pathlib import Path
import tempfile
import json

from semantic_organizer.cache import CacheManager
from semantic_organizer.taxonomy import get_taxonomy_hash, load_taxonomy
from semantic_organizer.parser import compute_file_hash
from semantic_organizer.llm import PROMPT_VERSION

def test_cache_manager_basic(tmp_path):
    db_path = tmp_path / "test_cache.db"
    cache = CacheManager(db_path)
    
    assert db_path.exists()
    stats = cache.get_stats()
    assert stats["parsed_documents"] == 0
    assert stats["semantic_analyses"] == 0
    
    # Test parsed document caching
    content_hash = "dummyhash123"
    markdown_content = "# Title\nSome content"
    cache.set_parsed_document(content_hash, markdown_content, pages=2)
    
    cached_doc = cache.get_parsed_document(content_hash)
    assert cached_doc is not None
    assert cached_doc["markdown"] == markdown_content
    assert cached_doc["pages"] == 2
    
    # Test cache miss on unknown hash
    assert cache.get_parsed_document("nonexistent") is None
    
    # Test semantic analysis caching
    taxonomy_hash = "taxhash456"
    model_name = "test-model"
    payload = {
        "category_id": "technology",
        "document_type": "research_paper",
        "summary": "A paper on databases.",
        "entities": [{"name": "Relational Model", "type": "Concept"}],
        "tags": ["Databases", "SQL"],
        "confidence": 0.99
    }
    
    cache.set_semantic_analysis(
        content_hash=content_hash,
        taxonomy_hash=taxonomy_hash,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        payload_dict=payload
    )
    
    cached_analysis = cache.get_semantic_analysis(
        content_hash=content_hash,
        taxonomy_hash=taxonomy_hash,
        model_name=model_name,
        prompt_version=PROMPT_VERSION
    )
    assert cached_analysis is not None
    assert cached_analysis["category_id"] == "technology"
    assert cached_analysis["document_type"] == "research_paper"
    assert cached_analysis["confidence"] == 0.99
    
    # Test cache miss when taxonomy changes
    assert cache.get_semantic_analysis(
        content_hash=content_hash,
        taxonomy_hash="different_taxonomy_hash",
        model_name=model_name,
        prompt_version=PROMPT_VERSION
    ) is None
    
    # Test cache miss when model changes
    assert cache.get_semantic_analysis(
        content_hash=content_hash,
        taxonomy_hash=taxonomy_hash,
        model_name="different_model",
        prompt_version=PROMPT_VERSION
    ) is None
    
    # Test stats
    stats = cache.get_stats()
    assert stats["parsed_documents"] == 1
    assert stats["semantic_analyses"] == 1
    
    # Test clear
    cache.clear()
    stats = cache.get_stats()
    assert stats["parsed_documents"] == 0
    assert stats["semantic_analyses"] == 0

def test_taxonomy_hash(tmp_path):
    tax_file = tmp_path / "taxonomy.yaml"
    tax_file.write_text("categories:\n  - id: tech\n    label: Tech\n    description: Tech docs\n    primary_folder: Tech\n", encoding="utf-8")
    
    hash1 = get_taxonomy_hash(tax_file)
    assert len(hash1) == 64
    
    # Modify taxonomy
    tax_file.write_text("categories:\n  - id: science\n    label: Science\n    description: Science docs\n    primary_folder: Science\n", encoding="utf-8")
    hash2 = get_taxonomy_hash(tax_file)
    assert len(hash2) == 64
    assert hash1 != hash2

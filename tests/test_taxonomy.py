# pyrefly: ignore [missing-import]
import pytest
from pathlib import Path
import json

from semantic_organizer.taxonomy import load_taxonomy
from semantic_organizer.llm import generate_payload_model

def test_dynamic_json_schema():
    # Load the taxonomy from the project root
    taxonomy_path = Path(__file__).parent.parent / "taxonomy.yaml"
    taxonomy = load_taxonomy(taxonomy_path)
    
    assert len(taxonomy.categories) > 0
    
    # Generate the dynamic Pydantic model
    DynamicModel = generate_payload_model(taxonomy)
    
    # Get the JSON schema
    schema = DynamicModel.model_json_schema()
    
    # Verify that the category_id field is an enum restricted to our taxonomy IDs
    category_id_prop = schema["properties"]["category_id"]
    
    # Pydantic may structure the Literal as an 'enum' or 'anyOf' depending on version
    # Let's check for enum values in either structure
    has_enum = False
    enum_values = []
    
    if "enum" in category_id_prop:
        has_enum = True
        enum_values = category_id_prop["enum"]
    elif "anyOf" in category_id_prop:
        for item in category_id_prop["anyOf"]:
            if "enum" in item:
                has_enum = True
                enum_values.extend(item["enum"])
                
    assert has_enum, f"category_id is missing 'enum' constraint in schema: {category_id_prop}"
    
    # Verify some expected categories are in the enum
    assert "technology" in enum_values
    assert "healthcare" in enum_values
    assert "uncategorized" in enum_values
    
    print("\nSchema generated successfully with correct category_id constraints.")
    print("Enum values:", enum_values)

from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional

class Entity(BaseModel):
    model_config = {'is_entity': True, 'graph_id_fields': ['name', 'type']}
    name: str = Field(description="The exact name of the entity.")
    type: str = Field(description="The category of the entity (e.g., Person, Organization, Location, Concept).")

class Tag(BaseModel):
    model_config = {'is_entity': True, 'graph_id_fields': ['name']}
    name: str = Field(description="A single lowercase word tag.")

class OSMetadata(BaseModel):
    size_bytes: int
    last_accessed: float
    last_modified: float
    original_folder: str

class SemanticPayload(BaseModel):
    model_config = {'is_entity': True}
    summary: str = Field(description="A brief 1-sentence summary of this specific text chunk.")
    entities: list[Entity] = Field(default_factory=list, description="All key entities mentioned in the text.", json_schema_extra={"edge_label": "MENTIONS"})
    tags: list[Tag] = Field(default_factory=list, description="Relevant descriptive tags for the text.", json_schema_extra={"edge_label": "TAGGED_AS"})
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")

class DocumentChunk(BaseModel):
    chunk_index: int
    text: str
    metadata: dict = Field(default_factory=dict)
    
class ParsedDocument(BaseModel):
    document_id: str
    source_path: Path
    markdown: str
    pages: Optional[int] = None
    content_hash: str
    chunks: Optional[list[DocumentChunk]] = None
    os_metadata: Optional[OSMetadata] = None

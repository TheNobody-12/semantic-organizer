import os
from pathlib import Path
from pydantic import BaseModel, Field
import yaml

class Neo4jConfig(BaseModel):
    uri: str = Field(default="bolt://localhost:7687")
    user: str = Field(default="neo4j")
    password: str = Field(default="password")

class LLMConfig(BaseModel):
    base_url: str = Field(default="http://localhost:1234/v1")
    api_key: str = Field(default="lm-studio")
    fast_extraction_model: str = Field(default="google/gemma-4-e2b", description="Small model for fast entity extraction")
    graph_extraction_model: str = Field(default="google/gemma-4-12b", description="Large model for deep graph extraction")
    clustering_model: str = Field(default="google/gemma-4-e4b", description="Medium model for reasoning and clustering")
    
class AppConfig(BaseModel):
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    taxonomy_path: Path = Field(default=Path("taxonomy.yaml"))
    cache_path: Path = Field(default=Path(".semantic_cache.db"))
    concurrency: int = Field(default=2)

def load_config(config_path: Path | None = None) -> AppConfig:
    """Loads configuration from a YAML file if provided, else returns defaults."""
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data:
                return AppConfig(**data)
    
    # Check for default config locations
    default_locations = [Path("semantic-organizer.yaml"), Path.home() / ".semantic-organizer.yaml"]
    for loc in default_locations:
        if loc.exists():
            with open(loc, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    return AppConfig(**data)
                    
    return AppConfig()

# Global settings instance
settings = load_config()

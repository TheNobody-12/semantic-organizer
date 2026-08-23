import json
import shutil
from pathlib import Path
import structlog
from openai import OpenAI
from pydantic import BaseModel

from ..config import settings

logger = structlog.get_logger(__name__)

def auto_structure(target_dir: Path, apply: bool = False):
    """
    Reads all .semantic.json sidecars in target_dir, asks the LLM to design an optimal
    directory structure, and either previews or applies the moves.
    """
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError(f"Target directory {target_dir} does not exist.")

    sidecars = list(target_dir.rglob("*.semantic.json"))
    if not sidecars:
        logger.warning("No semantic sidecars found. Nothing to restructure.")
        return

    documents = []
    file_map = {}
    
    for i, sidecar in enumerate(sidecars):
        try:
            data = json.loads(sidecar.read_text())
            original_file = sidecar.with_name(sidecar.name.replace(".semantic.json", ""))
            
            if not original_file.exists():
                continue
                
            rel_path = original_file.relative_to(target_dir)
            file_id = f"file_{i}"
            
            documents.append({
                "id": file_id,
                "filename": original_file.name,
                "current_path": str(rel_path),
                "summary": data.get("summary", ""),
                "tags": data.get("tags", [])
            })
            file_map[file_id] = original_file
        except Exception as e:
            logger.error(f"Failed to read sidecar {sidecar}: {e}")

    if not documents:
        logger.warning("No valid documents found.")
        return

    prompt = (
        "You are an intelligent file organizer. Below is a list of documents with their summaries and tags.\n"
        "Your task is to design an optimal, intuitive, and cohesive folder hierarchy for these files. "
        "Group related files together logically (e.g., 'Career/Applications', 'Finance/2024 Statements', 'Academic Research', etc.).\n\n"
        "Output a JSON object with a 'moves' array containing the new folder path for each file.\n\n"
        f"Documents:\n{json.dumps(documents, indent=2)}"
    )

    client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key)

    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "auto_structure_moves",
            "schema": {
                "type": "object",
                "properties": {
                    "moves": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_id": {"type": "string"},
                                "new_folder_path": {"type": "string"}
                            },
                            "required": ["file_id", "new_folder_path"]
                        }
                    }
                },
                "required": ["moves"]
            }
        }
    }

    try:
        response = client.chat.completions.create(
            model=settings.llm.clustering_model,
            messages=[
                {"role": "system", "content": "You are a helpful file organizer assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            response_format=schema
        )
        response_content = response.choices[0].message.content
        
        try:
            results = json.loads(response_content.strip())
            mapping = {item["file_id"]: item["new_folder_path"] for item in results.get("moves", [])}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON. Raw LLM response was:\n{response_content}")
            raise e
    except Exception as e:
        logger.error(f"LLM request or parsing failed: {e}")
        return

    moves = []
    for file_id, new_folder in mapping.items():
        if file_id not in file_map:
            continue
            
        original_file = file_map[file_id]
        new_folder_path = target_dir / Path(new_folder)
        new_file_path = new_folder_path / original_file.name
        
        if original_file != new_file_path:
            moves.append((original_file, new_file_path))

    if not moves:
        logger.info("No moves required. The structure is already optimal.")
        return

    if not apply:
        from rich.console import Console
        console = Console()
        console.print("[bold cyan]Preview of auto-structure moves:[/bold cyan]")
        for src, dst in moves:
            console.print(f"  [yellow]{src.relative_to(target_dir)}[/yellow] -> [green]{dst.relative_to(target_dir)}[/green]")
        console.print("\n[dim]Run with --apply to execute these changes.[/dim]")
    else:
        from rich.console import Console
        console = Console()
        console.print("[bold cyan]Applying auto-structure moves...[/bold cyan]")
        
        for src, dst in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            
            # Move sidecars
            for ext in [".semantic.md", ".semantic.json"]:
                src_sidecar = src.with_suffix(src.suffix + ext)
                dst_sidecar = dst.with_suffix(dst.suffix + ext)
                if src_sidecar.exists():
                    shutil.move(str(src_sidecar), str(dst_sidecar))
                    
        console.print("[bold green]Auto-structure complete![/bold green]")

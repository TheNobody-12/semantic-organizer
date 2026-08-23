import logging
import warnings
import time
import shutil
import sys
from pathlib import Path
from typing import Annotated

import os
os.environ["TQDM_DISABLE"] = "1"  # Fix: Suppress Docling's loading weights progress bar

# ── Fix 3: Centralized third-party log/warning suppression ──
# Must happen before any library imports trigger noisy output.
for _noisy in ("docling", "litellm", "httpx", "httpcore",
               "openai", "openai._base_client", "LiteLLM", "urllib3",
               "torch", "PIL"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# Fix: RapidOCR uses its own root-attached logger, we must wipe its handlers
rapid_logger = logging.getLogger("RapidOCR")
rapid_logger.setLevel(logging.ERROR)
rapid_logger.handlers = []
rapid_logger.propagate = False

warnings.filterwarnings("ignore", module=r"docling|torch|rapidocr")
import typer
import structlog
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.logging import RichHandler
from datetime import datetime
from openai import OpenAI

from .config import settings
from .extraction.engine import process_document
from .graph.store import GraphManager
from .graph.clustering import ClusteringEngine

console = Console()

# ── Logging setup: console shows only warnings+, file gets everything ──
_console_handler = RichHandler(
    console=console, show_path=False, rich_tracebacks=True,
    markup=False, show_time=False, show_level=False
)
_console_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
    processor=structlog.dev.ConsoleRenderer(colors=True, pad_event=22),
))
_console_handler.setLevel(logging.WARNING)

_file_handler = logging.FileHandler("semantic_organizer.log")
_file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
    processor=structlog.processors.JSONRenderer()
))
_file_handler.setLevel(logging.DEBUG)

logging.basicConfig(level=logging.DEBUG, handlers=[_console_handler, _file_handler], force=True)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()
app = typer.Typer(help="Semantic Organizer CLI")

@app.command()
def doctor():
    """Check if LM Studio is reachable."""
    console.print("\n[bold blue]Running Semantic Organizer Doctor...[/bold blue]\n")
    try:
        client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key, max_retries=1)
        models = client.models.list()
        if models.data:
            model_names = [m.id for m in models.data]
            console.print(f"✅ [green]LM Studio:[/green] Reachable. Available models: {', '.join(model_names)}")
        else:
            console.print("⚠️  [yellow]LM Studio:[/yellow] Reachable, but no models loaded.")
    except Exception as e:
        console.print(f"❌ [red]LM Studio:[/red] Connection failed. ({e})")

@app.command()
def organize(
    source_dir: Path = typer.Argument(..., help="Directory containing documents to organize", exists=True, file_okay=False, dir_okay=True),
    target_dir: Path = typer.Argument("semantic_output", help="Directory to copy organized documents to"),
    threads: int = typer.Option(1, help="Number of concurrent documents to process"),
    method: str = typer.Option("fast", help="Extraction method to use: 'fast', 'graph', or 'auto'"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    rebuild: bool = typer.Option(False, "--rebuild", help="Wipe existing graph and rebuild from scratch"),
):
    """Semantically analyze, cluster, and organize documents into folders."""
    start_time = time.time()
    
    files = [f for f in source_dir.rglob("*") if f.is_file() and not f.name.startswith(".")]
    console.print(f"\nScanning... found [bold cyan]{len(files)}[/bold cyan] documents to analyze.\n")
    
    # ── Fix 7: Friendly graph rebuild messaging ──
    gm = GraphManager(target_dir)
    existing = gm.graph.number_of_nodes()
    if rebuild or existing == 0:
        if existing > 0:
            gm.wipe_db()
            console.print(f"[dim]Rebuilding knowledge graph ({existing} existing entries cleared)[/dim]")
        else:
            console.print("[dim]Building knowledge graph (fresh)[/dim]")
    else:
        console.print(f"[dim]Appending to existing graph ({existing} nodes). Use --rebuild to start fresh.[/dim]")
    
    import concurrent.futures
    import threading
    graph_lock = threading.Lock()
    done_count = 0
    fallback_count = 0
    fallback_files = []
    
    # ── Fix 4: Per-file progress with current filename ──
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        overall = progress.add_task("[cyan]Analyzing documents", total=len(files))
        current = progress.add_task("[dim]  starting...", total=None)
        
        def process_file(file):
            nonlocal done_count, fallback_count
            rel_path = file.name  # Show only filename, not full path (Fix: privacy)
            progress.update(current, description=f"[dim]  ⟳ {rel_path}")
            try:
                ctx = process_document(file, method=method)
                if not ctx.extracted_models:
                    fallback_count += 1
                    fallback_files.append(rel_path)
                with graph_lock:
                    gm.upsert_document_graph(ctx, file)
                done_count += 1
            except Exception as e:
                fallback_count += 1
                fallback_files.append(rel_path)
                logger.debug("extraction_failed", file=rel_path, error=str(e))
            finally:
                progress.advance(overall)
                
        if threads == 1:
            for file in files:
                process_file(file)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
                executor.map(process_file, files)
        
        progress.update(current, description=f"[green]  ✓ {done_count} analyzed" + 
                        (f"  •  {fallback_count} fallback" if fallback_count else ""))
            
    # ── Clustering ──
    console.print("\n[cyan]Running Contextual Clustering & AI Naming...[/cyan]")
    engine = ClusteringEngine(gm)
    mapping = engine.organize_files()
    
    # ── Fix 5: Plan table with confidence ──
    cluster_summary = {}
    for doc_id, info in mapping.items():
        folder = info["folder"]
        conf = info["confidence"]
        if folder not in cluster_summary:
            cluster_summary[folder] = {"count": 0, "low_conf": 0}
        cluster_summary[folder]["count"] += 1
        if conf < 0.3:
            cluster_summary[folder]["low_conf"] += 1
    
    console.print("\n[bold]Proposed organization:[/bold]")
    plan_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    plan_table.add_column("Cluster", style="cyan")
    plan_table.add_column("Files", justify="right")
    plan_table.add_column("Confidence", min_width=12)
    
    for folder, stats in sorted(cluster_summary.items(), key=lambda x: x[1]["count"], reverse=True):
        count = stats["count"]
        low = stats["low_conf"]
        
        if folder == "Unsorted":
            conf_display = "[dim]—[/dim]"
        elif low > 0:
            conf_display = f"[yellow]⚠ {low} low-confidence[/yellow]"
        else:
            conf_display = "[green]high[/green]"
            
        plan_table.add_row(f"  {folder}/", str(count), conf_display)
    
    console.print(plan_table)
    console.print(f"\n[dim]Originals stay untouched. Copies go to: {target_dir}/[/dim]")
    
    if not yes:
        if not typer.confirm("\nApply this plan?", default=True):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    
    # ── Copy files ──
    copied_count = 0
    for doc_id, info in mapping.items():
        folder_name = info["folder"]
        doc_node = gm.graph.nodes[doc_id]
        src_path = Path(doc_node["path"])
        dest_folder = target_dir / folder_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / src_path.name
        
        if src_path.exists():
            shutil.copy(str(src_path), str(dest_path))
            copied_count += 1
    
    # ── Fix 6: End-of-run summary table ──
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    console.print(f"\n[bold green]✔ Organized {copied_count} documents into {len(cluster_summary)} clusters in {minutes}m {seconds}s[/bold green]\n")
    
    for folder, stats in sorted(cluster_summary.items(), key=lambda x: x[1]["count"], reverse=True):
        suffix = ""
        if folder == "Unsorted":
            suffix = "  [dim]← review: semantic-organizer chat[/dim]"
        console.print(f"  {folder + '/':.<40s} {stats['count']} files{suffix}")
    
    console.print(f"\n  [dim]Output:[/dim]   {target_dir}/")
    console.print(f"  [dim]Graph:[/dim]    .semantic_graph.json ({gm.graph.number_of_nodes()} nodes, {gm.graph.number_of_edges()} edges)")
    console.print()

@app.command()
def visualize(
    target_dir: Path = typer.Argument("semantic_output", help="Directory containing the organized documents and graph"),
    output_html: str = typer.Option("graph.html", help="Name of the output HTML file")
):
    """Generate an interactive HTML visualization of the Semantic Knowledge Graph."""
    from pyvis.network import Network
    import webbrowser
    
    gm = GraphManager(target_dir)
    
    if gm.graph.number_of_nodes() == 0:
        console.print("[bold red]No graph found! Have you run 'organize' yet?[/bold red]")
        raise typer.Exit(1)
        
    console.print(f"[cyan]Visualizing {gm.graph.number_of_nodes()} nodes and {gm.graph.number_of_edges()} edges...[/cyan]")
    
    # Initialize Pyvis Network
    net = Network(height="100vh", width="100%", bgcolor="#222222", font_color="white", select_menu=True)
    
    # Add nodes with custom colors based on type
    for node, data in gm.graph.nodes(data=True):
        node_type = data.get("type", "Unknown")
        color = "#97c2fc" # Default blue
        
        if node_type == "Document":
            color = "#ff6b6b" # Red
            label = data.get("filename", node)
        elif node_type == "Folder":
            color = "#feca57" # Yellow
            label = data.get("name", node)
        elif node_type == "Tag":
            color = "#1dd1a1" # Green
            label = f"#{data.get('name', node)}"
        elif node_type == "Entity":
            color = "#c8d6e5" # Light grey
            label = data.get("name", node)
            
        net.add_node(node, label=label, title=f"Type: {node_type}", color=color)
        
    # Add edges
    for source, target, data in gm.graph.edges(data=True):
        edge_type = data.get("type", "")
        net.add_edge(source, target, title=edge_type)
        
    # Physics options for a nice layout
    net.set_options("""
    var options = {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -100,
          "centralGravity": 0.01,
          "springLength": 100,
          "springConstant": 0.08
        },
        "maxVelocity": 50,
        "solver": "forceAtlas2Based",
        "timestep": 0.35,
        "stabilization": {"iterations": 150}
      }
    }
    """)
    
    out_path = Path(output_html).resolve()
    net.write_html(str(out_path))
    
    console.print(f"[bold green]Interactive graph generated at {out_path}[/bold green]")
    webbrowser.open(f"file://{out_path}")

@app.command()
def sweep(
    target_dir: Path = typer.Option("semantic_output", help="The output directory to sweep"),
    days: int = typer.Option(180, help="Number of days since last access to flag for deletion")
):
    """Find and clean up old, unused files using Graph OS Metadata."""
    gm = GraphManager(target_dir)
    if gm.graph.number_of_nodes() == 0:
        console.print("[red]No graph found! Run `organize` first.[/red]")
        return
        
    now = time.time()
    threshold = now - (days * 86400)
    
    candidates = []
    for node_id, data in gm.graph.nodes(data=True):
        if data.get("type") == "Document":
            last_accessed = data.get("last_accessed", now)
            if last_accessed < threshold:
                candidates.append((node_id, data))
                
    if not candidates:
        console.print(f"[green]No files found older than {days} days.[/green]")
        return
        
    console.print(f"\n[bold yellow]Found {len(candidates)} files that haven't been opened in {days} days:[/bold yellow]")
    
    # Group by their new dynamic folders (which we can find by looking at their physical path or their clustered name, 
    # but their physical path is what we actually want to delete)
    # The graph stored the source_path, but wait, if we copied them, the actual path to delete is in target_dir.
    # Actually, the user can just look at the filename.
    total_size = sum([d.get("size_bytes", 0) for _, d in candidates])
    
    for _, data in candidates:
        date_str = datetime.fromtimestamp(data.get("last_accessed")).strftime('%Y-%m-%d')
        size_mb = data.get("size_bytes", 0) / (1024*1024)
        console.print(f"  - {data.get('filename')} (Last opened: {date_str}, Size: {size_mb:.2f} MB)")
        
    console.print(f"\n[bold red]Total space to free: {total_size / (1024*1024):.2f} MB[/bold red]")
    if typer.confirm("Delete these files from the source directory?"):
        for _, data in candidates:
            src = Path(data["path"])
            if src.exists():
                src.unlink()
        console.print("[green]Files successfully deleted![/green]")

@app.command()
def chat(
    target_dir: Path = typer.Argument("semantic_output", help="Directory containing the graph to query")
):
    """Launch an interactive Vectorless GraphRAG chat."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style
    from openai import OpenAI
    from .graph.rag import IntentExtractor, EvidenceAssembler, SynthesisEngine
    from .config import settings
    
    gm = GraphManager(target_dir)
    if gm.graph.number_of_nodes() == 0:
        console.print("[bold red]No graph found! Have you run 'organize' yet?[/bold red]")
        raise typer.Exit(1)
        
    client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key or "lm-studio")
    extractor = IntentExtractor(client)
    assembler = EvidenceAssembler(gm)
    synthesizer = SynthesisEngine(client)
    
    style = Style.from_dict({
        'prompt': 'ansicyan bold',
    })
    session = PromptSession(style=style)
    
    console.print("\n[bold green]Welcome to Vectorless GraphRAG! (Type 'exit' to quit)[/bold green]")
    console.print(f"[dim]Graph loaded with {gm.graph.number_of_nodes()} nodes and {gm.graph.number_of_edges()} edges.[/dim]\n")
    
    while True:
        try:
            query = session.prompt("Ask the Graph > ")
            if query.lower().strip() in ['exit', 'quit']:
                break
            if not query.strip():
                continue
                
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                # Step 1: Extract Intent
                task_intent = progress.add_task("[cyan]Extracting intent...", total=None)
                intent = extractor.extract(query)
                progress.update(task_intent, description=f"[green]Intent identified: {intent.intent}")
                
                # Step 2: Query the Graph
                task_evidence = progress.add_task("[cyan]Traversing Knowledge Graph...", total=None)
                evidence = assembler.assemble(intent)
                progress.update(task_evidence, description=f"[green]Evidence assembled!")
                
                # Step 3: Synthesize Answer
                task_synth = progress.add_task("[cyan]Synthesizing answer...", total=None)
                answer = synthesizer.synthesize(query, evidence)
                progress.update(task_synth, description=f"[green]Done!")
                
            console.print(f"\n[bold magenta]AI:[/bold magenta] {answer}\n")
            
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/bold red]")

if __name__ == "__main__":
    app()

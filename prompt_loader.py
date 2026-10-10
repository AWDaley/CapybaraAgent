import json
import os
from typing import Any


def load_prompts_from_file(filepath: str) -> list[dict[str, str]]:
    """Loads and normalizes prompts from a JSON or text file.
    
    Supported JSON formats:
      1. Single dict: {"prompt": "...", "title": "..."} (also supports "text", "goal", "query")
      2. List of strings: ["prompt 1", "prompt 2"]
      3. List of dicts: [{"prompt": "...", "title": "..."}, ...]
      4. Container dict: {"prompts": [...]}

    Supported Text format:
      - Line-separated prompts (.txt), ignoring empty lines and comments starting with '#'

    Returns:
      List of dicts: [{"title": "...", "prompt": "..."}]
    """
    cleaned_path = filepath.strip().strip("'\"")
    if not os.path.exists(cleaned_path):
        raise FileNotFoundError(f"Prompt file not found: '{cleaned_path}'")

    results: list[dict[str, str]] = []

    # Handle JSON file
    if cleaned_path.lower().endswith(".json"):
        with open(cleaned_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        from tal.schemas import StructuredPipeline

        def _is_structured_pipeline(item: Any) -> bool:
            return isinstance(item, dict) and ("pipeline" in item or "steps" in item)

        def _extract_pipeline_item(item: dict, default_title: str) -> dict[str, Any]:
            pipeline = StructuredPipeline.from_dict(item)
            title = pipeline.title or default_title
            summary_steps = ", ".join(f"[{s.step_id}: {s.objective[:40]}...]" for s in pipeline.steps)
            prompt_str = f"Execute Structured Pipeline '{title}' ({len(pipeline.steps)} steps): {summary_steps}"
            return {
                "title": title,
                "prompt": prompt_str,
                "pipeline": pipeline,
                "is_pipeline": True
            }

        # Helper to extract prompt and title from a dict
        def extract_item(item: Any, default_title: str) -> dict[str, Any] | None:
            def _clean_str(s: str) -> str:
                s = s.strip()
                if (s.startswith('"') and s.endswith('"') and len(s) >= 2) or \
                   (s.startswith("'") and s.endswith("'") and len(s) >= 2):
                    s = s[1:-1].strip()
                return s

            if _is_structured_pipeline(item):
                return _extract_pipeline_item(item, default_title)

            if isinstance(item, str) and item.strip():
                return {"title": default_title, "prompt": _clean_str(item)}
            elif isinstance(item, dict):
                p = (
                    item.get("prompt")
                    or item.get("text")
                    or item.get("goal")
                    or item.get("query")
                    or item.get("content")
                    or ""
                )
                if isinstance(p, str) and p.strip():
                    t = (
                        item.get("title")
                        or item.get("name")
                        or item.get("id")
                        or default_title
                    )
                    return {"title": str(t), "prompt": _clean_str(p)}
            return None

        # Case 0: Direct structured pipeline at root
        if _is_structured_pipeline(data):
            results.append(_extract_pipeline_item(data, "Structured Pipeline"))

        # Case 1: Dict with a "prompts" or "pipelines" list
        elif isinstance(data, dict) and ("prompts" in data or "pipelines" in data):
            key = "prompts" if "prompts" in data else "pipelines"
            for i, elem in enumerate(data[key], 1):
                extracted = extract_item(elem, f"Prompt {i}")
                if extracted:
                    results.append(extracted)

        # Case 2: List of strings or dicts
        elif isinstance(data, list):
            for i, elem in enumerate(data, 1):
                extracted = extract_item(elem, f"Prompt {i}")
                if extracted:
                    results.append(extracted)

        # Case 3: Single dict
        elif isinstance(data, dict):
            extracted = extract_item(data, "Prompt 1")
            if extracted:
                results.append(extracted)

    # Handle Text file (.txt or generic)
    else:
        with open(cleaned_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        for i, line in enumerate(lines, 1):
            results.append({"title": f"Prompt {i}", "prompt": line})

    if not results:
        raise ValueError(f"No valid prompts could be extracted from '{cleaned_path}'.")

    return results


def check_and_extract_file_path(user_input: str) -> str | None:
    """Checks if a user input string is an instruction to load a prompt file.
    
    Matches patterns like:
      - 'load prompts.json' / 'load data/prompts.json'
      - '/load prompts.json'
      - '@prompts.json'
      - 'prompts.json' / 'C:/path/to/prompts.json' (if the file actually exists)
    """
    s = user_input.strip()
    if not s:
        return None

    # Pattern: load <filepath> or /load <filepath>
    for prefix in ("load ", "/load ", "@"):
        if s.lower().startswith(prefix):
            path_part = s[len(prefix):].strip().strip("'\"")
            if path_part:
                return path_part

    # Pattern: direct filepath entered ending in .json or .txt that exists on disk
    cleaned = s.strip("'\"")
    candidates = [
        cleaned,
        cleaned + "n",        # Handles '.jso' -> '.json'
        cleaned + ".json",    # Handles omitting extension
        cleaned + ".txt",
    ]
    for cand in candidates:
        if (cand.lower().endswith(".json") or cand.lower().endswith(".txt")) and os.path.exists(cand):
            return cand

    return None

import json
import os
import tempfile

import pytest

from prompt_loader import check_and_extract_file_path, load_prompts_from_file


def test_load_single_dict_prompt():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"prompt": "Calculate the 10th fibonacci number.", "title": "Fibonacci"}, f)
        temp_path = f.name

    try:
        items = load_prompts_from_file(temp_path)
        assert len(items) == 1
        assert items[0]["title"] == "Fibonacci"
        assert items[0]["prompt"] == "Calculate the 10th fibonacci number."
    finally:
        os.remove(temp_path)


def test_load_list_of_strings():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(["Prompt A", "Prompt B", "Prompt C"], f)
        temp_path = f.name

    try:
        items = load_prompts_from_file(temp_path)
        assert len(items) == 3
        assert items[0]["prompt"] == "Prompt A"
        assert items[1]["prompt"] == "Prompt B"
        assert items[2]["prompt"] == "Prompt C"
    finally:
        os.remove(temp_path)


def test_load_nested_prompts_dict():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({
            "suite": "Benchmark",
            "prompts": [
                {"id": "p1", "prompt": "First task"},
                {"name": "Second task title", "goal": "Second task text"}
            ]
        }, f)
        temp_path = f.name

    try:
        items = load_prompts_from_file(temp_path)
        assert len(items) == 2
        assert items[0]["title"] == "p1"
        assert items[0]["prompt"] == "First task"
        assert items[1]["title"] == "Second task title"
        assert items[1]["prompt"] == "Second task text"
    finally:
        os.remove(temp_path)


def test_load_txt_file():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("# Comment line\nTask 1\n\nTask 2\n# Another comment\nTask 3\n")
        temp_path = f.name

    try:
        items = load_prompts_from_file(temp_path)
        assert len(items) == 3
        assert items[0]["prompt"] == "Task 1"
        assert items[1]["prompt"] == "Task 2"
        assert items[2]["prompt"] == "Task 3"
    finally:
        os.remove(temp_path)


def test_load_sample_prompts_json():
    # Verify the provided sample_prompts.json loads successfully
    sample_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_prompts.json")
    if os.path.exists(sample_file):
        items = load_prompts_from_file(sample_file)
        assert len(items) >= 4
        assert any("prime" in p["title"].lower() for p in items)
        assert any("orbital" in p["title"].lower() for p in items)


def test_check_and_extract_file_path():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"prompt": "Hello"}, f)
        temp_path = f.name

    try:
        # Prefix 'load '
        assert check_and_extract_file_path(f"load {temp_path}") == temp_path
        assert check_and_extract_file_path(f"load '{temp_path}'") == temp_path
        
        # Prefix '/load '
        assert check_and_extract_file_path(f"/load {temp_path}") == temp_path

        # Prefix '@'
        assert check_and_extract_file_path(f"@{temp_path}") == temp_path

        # Direct existing file path
        assert check_and_extract_file_path(temp_path) == temp_path

        # Normal prompt string should NOT match
        assert check_and_extract_file_path("Tell me a story about a capybara") is None
    finally:
        os.remove(temp_path)


def test_load_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        load_prompts_from_file("nonexistent_path_12345.json")


def test_load_absolute_path_formats():
    abs_path = os.path.abspath("data/orbital_simulation_prompt.json")
    assert os.path.isabs(abs_path)
    
    # Standard Windows backslash path
    items1 = load_prompts_from_file(abs_path)
    assert len(items1) == 1
    assert "JWST" in items1[0]["prompt"]
    
    # Forward slash path
    fwd_path = abs_path.replace("\\", "/")
    items2 = load_prompts_from_file(fwd_path)
    assert len(items2) == 1
    assert "JWST" in items2[0]["prompt"]

    # Quoted path
    items3 = load_prompts_from_file(f'"{abs_path}"')
    assert len(items3) == 1

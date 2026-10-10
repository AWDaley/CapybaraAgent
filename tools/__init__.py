from collections.abc import Callable
from dataclasses import dataclass

from tal.effect_classes import EffectClass, get_effect_class
from tal.schemas import ToolParamSchema, get_schema_for_tool

from .basic_tools import BASIC_TOOL_DESCRIPTIONS, BASIC_TOOL_REGISTRY
from .external_tools import EXTERNAL_TOOL_DESCRIPTIONS, EXTERNAL_TOOL_REGISTRY
from .file_tools import FILE_TOOL_DESCRIPTIONS, FILE_TOOL_REGISTRY


@dataclass
class ToolDefinition:
    name: str
    func: Callable
    schema: type[ToolParamSchema] | None = None
    effect: EffectClass = EffectClass.READ
    description: str = ""


TOOL_REGISTRY = {}
TOOL_REGISTRY.update(BASIC_TOOL_REGISTRY)
TOOL_REGISTRY.update(FILE_TOOL_REGISTRY)
TOOL_REGISTRY.update(EXTERNAL_TOOL_REGISTRY)


def get_tool_descriptions() -> str:
    """Returns a string describing all available tools for the LLM."""
    descriptions = "Available Tools:\n"
    descriptions += BASIC_TOOL_DESCRIPTIONS.strip() + "\n"
    descriptions += FILE_TOOL_DESCRIPTIONS.strip() + "\n"
    descriptions += EXTERNAL_TOOL_DESCRIPTIONS.strip() + "\n"
    return descriptions


import re


def _build_tool_info():
    info = {}
    desc_str = BASIC_TOOL_DESCRIPTIONS + "\n" + FILE_TOOL_DESCRIPTIONS + "\n" + EXTERNAL_TOOL_DESCRIPTIONS
    
    lines = desc_str.split('\n')
    current_tool = None
    current_block = []
    
    for line in lines:
        if not line.strip(): continue
        
        if re.match(r'^\d+\.', line.strip()):
            if current_tool and current_block:
                info[current_tool] = "\n".join(current_block)
            current_block = [line]
            match = re.search(r'"tool":\s*"([^"]+)"', line)
            if match:
                current_tool = match.group(1)
        elif current_tool:
            current_block.append(line)
            
    if current_tool and current_block:
        info[current_tool] = "\n".join(current_block)
        
    return info

TOOL_INFO = _build_tool_info()


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {}
for tool_name, tool_func in TOOL_REGISTRY.items():
    TOOL_DEFINITIONS[tool_name] = ToolDefinition(
        name=tool_name,
        func=tool_func,
        schema=get_schema_for_tool(tool_name),
        effect=get_effect_class(tool_name),
        description=TOOL_INFO.get(tool_name, "")
    )

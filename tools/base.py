"""Base Tool class and ToolRegistry for self-describing, extensible tools."""

import inspect
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# JSON Schema type -> Python type mapping for Gemini signature generation
_SCHEMA_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


class Tool(ABC):
    """Base class for all agent tools.

    Subclasses declare metadata as class attributes and implement execute().
    Schemas for both Anthropic and Gemini are generated automatically.
    """

    name: str
    description: str
    parameters: dict  # JSON Schema "properties" dict
    required: list[str] = []

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Run the tool and return a string result for the LLM."""
        ...

    def anthropic_schema(self) -> dict:
        """Generate an Anthropic-format tool schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
        }

    def as_callable(self):
        """Return a plain function suitable for Gemini's automatic_function_calling.

        Gemini introspects __name__, __doc__, and __signature__ to build its
        own schema, so we construct a function that matches self.parameters.
        """
        params = []
        for param_name, schema in self.parameters.items():
            annotation = _SCHEMA_TYPE_MAP.get(schema.get("type"), str)
            default = schema.get("default", inspect.Parameter.empty)
            params.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=annotation,
                )
            )

        tool_ref = self

        def wrapper(**kwargs):
            return tool_ref.execute(**kwargs)

        wrapper.__name__ = self.name
        wrapper.__doc__ = self.description
        wrapper.__signature__ = inspect.Signature(
            params, return_annotation=str
        )
        return wrapper


class ToolRegistry:
    """Collects Tool instances and serves them in both Anthropic and Gemini formats."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a tool instance."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def anthropic_schemas(self) -> list[dict]:
        """All tool schemas in Anthropic API format."""
        return [t.anthropic_schema() for t in self._tools.values()]

    def gemini_callables(self) -> list:
        """All tools as plain callables for Gemini's automatic_function_calling."""
        return [t.as_callable() for t in self._tools.values()]

    def run(self, name: str, inputs: dict) -> str:
        """Dispatch a tool call by name. Returns result string."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        try:
            result = tool.execute(**inputs)
            logger.debug("[TOOL %s] => %s", name, result[:500] if result else "")
            return result
        except Exception as e:
            logger.error("[TOOL %s] error: %s", name, e)
            return f"Tool error ({name}): {e}"

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


# Module-level singleton
registry = ToolRegistry()

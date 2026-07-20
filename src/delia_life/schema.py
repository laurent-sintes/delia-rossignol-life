from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

FORMAT_CHECKER = FormatChecker()


def _path(error: JsonSchemaValidationError, root: str) -> str:
    result = root
    for part in error.absolute_path:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _message(error: JsonSchemaValidationError, path: str) -> str:
    if error.validator == "required":
        match = re.match(r"'(.+)' is a required property", error.message)
        missing = match.group(1) if match else "?"
        return f"{path}.{missing}: required property is missing"
    if error.validator == "type":
        return f"{path}: expected {error.validator_value}"
    if error.validator == "enum":
        return f"{path}: value is not in enum"
    if error.validator == "minLength":
        return f"{path}: string is too short"
    if error.validator == "minimum":
        return f"{path}: value is below minimum"
    if error.validator == "maximum":
        return f"{path}: value is above maximum"
    return f"{path}: {error.message}"


@lru_cache(maxsize=64)
def _compiled_validator(serialized_schema: str) -> Draft202012Validator:
    schema = json.loads(serialized_schema)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate with a cached JSON Schema 2020-12 validator."""
    serialized_schema = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    validator = _compiled_validator(serialized_schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: (list(error.absolute_path), error.message))
    return [_message(error, _path(error, path)) for error in errors]

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


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


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate with the declared JSON Schema 2020-12 contract."""
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: (list(error.absolute_path), error.message))
    return [_message(error, _path(error, path)) for error in errors]

"""JSON transport for a SAT-SA pipeline result.

The pipeline result is a plain Python dictionary, but the values inside it are
not all plain Python: the profiling layer returns numpy scalars, the loader
returns pandas timestamps, and the scope builders use sets. The adapter has to
make that result survive a JSON round trip without editing it.

The rule this module follows is that it converts types and nothing else. It
does not rename a key, drop a field, reorder a list, round a number, or
replace a value with a default. A value that cannot be represented is
reported as such rather than dropped, so the frontend can distinguish "the
backend said nothing" from "the transport lost it".
"""

from __future__ import annotations

import datetime
import math
from typing import Any

#: Marker used where a value exists but has no faithful JSON form. The
#: frontend treats this as "not available", never as a number or a zero.
UNREPRESENTABLE = {"__unrepresentable__": True, "python_type": None}


def to_jsonable(value: Any) -> Any:
    """Convert a pipeline result value into JSON-serialisable data."""

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        # NaN and infinity are valid IEEE results but not valid JSON. They
        # are preserved as an explicit marker rather than silently becoming
        # null, which would read as "not measured".
        if math.isnan(value):
            return {"__unrepresentable__": True, "python_type": "float", "reason": "nan"}

        if math.isinf(value):
            return {
                "__unrepresentable__": True,
                "python_type": "float",
                "reason": "infinity" if value > 0 else "-infinity",
            }

        return value

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]

    if isinstance(value, (set, frozenset)):
        return [to_jsonable(item) for item in value]

    if isinstance(value, (bytes, bytearray)):
        return {"__unrepresentable__": True, "python_type": "bytes"}

    # numpy scalars and arrays, without importing numpy: the anomaly layer
    # treats it as optional, so this module must not require it either.
    item_method = getattr(value, "item", None)
    if callable(item_method) and getattr(value, "shape", None) == ():
        try:
            return to_jsonable(item_method())
        except (ValueError, TypeError):
            pass

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return to_jsonable(tolist())
        except (ValueError, TypeError):
            pass

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (ValueError, TypeError):
            pass

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, datetime.timedelta):
        return value.total_seconds()

    return {
        "__unrepresentable__": True,
        "python_type": type(value).__name__,
    }


def serialisable_result(result: Any) -> Any:
    """Convert a whole pipeline result for transport."""

    return to_jsonable(result)

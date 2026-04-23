"""Wraps dialekt-manifest-validator for cloud-side manifest checks."""


def validate_manifest(yaml_str: str) -> dict:
    """Returns {"valid": bool, "errors": [...], "warnings": [...]}."""
    try:
        from dialekt_manifest import ManifestValidator
    except ImportError:
        return {"valid": True, "errors": [], "warnings": ["validator not installed"]}

    try:
        result = ManifestValidator().validate_string(yaml_str)
        return {
            "valid": True,
            "errors": [],
            "warnings": [str(w) for w in (result.warnings if hasattr(result, "warnings") else [])],
        }
    except Exception as exc:
        errors = []
        raw = str(exc)
        # Extract structured errors if available
        if hasattr(exc, "errors"):
            for e in exc.errors():
                errors.append({"field": ".".join(str(x) for x in e.get("loc", [])), "message": e.get("msg", "")})
        else:
            errors.append({"field": "manifest", "message": raw})
        return {"valid": False, "errors": errors, "warnings": []}

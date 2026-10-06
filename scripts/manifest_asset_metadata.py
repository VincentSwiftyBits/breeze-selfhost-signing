"""Preserve distribution metadata from an already verified official manifest.

Checksums, sizes and platform trust are recomputed/attested by the caller.
Never infer an edition from a filename or turn a signing input into a download.
"""


def distribution_metadata(official_assets, name, *, built_msi_edition=None):
    matches = [asset for asset in official_assets if asset.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"expected one verified official metadata entry for {name}")
    source = matches[0]
    result = {}
    if "edition" in source:
        if source["edition"] not in ("self-host", "hosted"):
            raise ValueError(f"invalid official edition for {name}")
        result["edition"] = source["edition"]
    if "intendedUse" in source:
        if source["intendedUse"] == "signing-input":
            raise ValueError(f"refusing to publish signing-input metadata for {name}")
        # Preserve future distributable purposes; their verifier remains the
        # authority on allowed values. Do not silently drop a restriction.
        if not isinstance(source["intendedUse"], str) or not source["intendedUse"]:
            raise ValueError(f"invalid official intendedUse for {name}")
        result["intendedUse"] = source["intendedUse"]
    if name == "breeze-agent.msi" and built_msi_edition is not None:
        if built_msi_edition == "self-host":
            result["edition"] = "self-host"
        elif built_msi_edition != "legacy":
            raise ValueError("invalid Windows MSI build edition attestation")
        elif "edition" in result:
            raise ValueError("legacy MSI build cannot attest an edition-aware release")
    return result

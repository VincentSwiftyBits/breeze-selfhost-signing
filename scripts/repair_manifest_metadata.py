"""Repair verified metadata while preserving every existing artifact identity."""
import copy
import hashlib
import json
from pathlib import Path
from manifest_asset_metadata import distribution_metadata


def repair_manifest(current, official, asset_dir, msi_evidence=None):
    for field in ("schemaVersion", "release", "sourceCommit"):
        if current.get(field) != official.get(field):
            raise ValueError(f"official/custom manifest {field} mismatch")
    if current.get("schemaVersion") != 1:
        raise ValueError("unsupported manifest schema")
    repaired = copy.deepcopy(current)
    names = set()
    for entry in repaired["assets"]:
        name = entry["name"]
        if name in names or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("duplicate or unsafe asset name")
        names.add(name)
        data = (Path(asset_dir) / name).read_bytes()
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"published asset checksum/size mismatch: {name}")
        built_edition = None
        if name == "breeze-agent.msi":
            if not msi_evidence or msi_evidence.get("sha256") != entry["sha256"]:
                raise ValueError("Windows MSI edition evidence missing or hash mismatch")
            built_edition = msi_evidence.get("edition")
            if built_edition != "self-host":
                raise ValueError("Windows MSI is not proven self-host")
        metadata = distribution_metadata(official["assets"], name, built_msi_edition=built_edition)
        # A mirrored asset has unchanged official bytes; modified signed
        # outputs keep their existing trust attestation and identity.
        source = next(a for a in official["assets"] if a["name"] == name)
        if name.startswith("breeze-helper-"):
            if entry["sha256"] != source.get("sha256") or entry["size"] != source.get("size"):
                raise ValueError(f"mirrored Helper differs from verified official bytes: {name}")
        for field in ("edition", "intendedUse"):
            if field in metadata:
                if field in entry and entry[field] != metadata[field]:
                    raise ValueError(f"cannot replace conflicting existing {field}: {name}")
                entry[field] = metadata[field]
            elif field in entry:
                raise ValueError(f"cannot remove existing {field} restriction: {name}")
    for before, after in zip(current["assets"], repaired["assets"]):
        if {k: v for k, v in before.items() if k not in ("edition", "intendedUse")} != {
            k: v for k, v in after.items() if k not in ("edition", "intendedUse")
        }:
            raise ValueError("repair changed artifact identity")
    return repaired


if __name__ == "__main__":
    import sys
    current_path, official_path, asset_dir, evidence_path, output_path = sys.argv[1:]
    repaired = repair_manifest(json.loads(Path(current_path).read_text()),
                               json.loads(Path(official_path).read_text()), asset_dir,
                               json.loads(Path(evidence_path).read_text(encoding="utf-8-sig")))
    Path(output_path).write_text(json.dumps(repaired, indent=2, sort_keys=True) + "\n")

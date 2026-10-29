# ADR-0003: Large and private data remains inside project storage

Status: Accepted  
Date: 10 October 2026

## Decision

`D:\Projects\Jarvis\storage` is the only approved root for model weights, datasets, private recordings, benchmark outputs, caches and project temporary files. Human-facing documentation remains in `deliverables`.

## Consequences

- Hugging Face, PyTorch, pip, uv and temporary paths are redirected into `storage`.
- Model manifests record source, license, size and SHA-256 before certification.
- Storage APIs reject traversal and resolved paths outside their declared area.
- `storage` contents are excluded from Git except for its ownership README.


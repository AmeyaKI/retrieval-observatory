"""Demoted subsystems: advisor, classifier, diagram, forge.

These packages are outside the supported surface. They are kept importable so the
`testsets` CLI, the SDK's `generate_testset`, and dashboard/MCP callers keep working, but
they carry no compatibility guarantee across releases.
"""

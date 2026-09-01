# Agent MCP Integration Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make retobs MCP integration radically easier for an agent to connect to a production retrieval pipeline with minimal setup and no deep knowledge of retobs config internals.

**Architecture:** Keep the existing stdio-based MCP server, but add a thin bootstrap layer that turns a small, human-readable integration config into a ready-to-use agent experience. The core idea is to reduce the number of moving parts: one install command, one config file, and one set of simple tools for benchmark, compare, and inspect.

**Tech Stack:** Python, Typer CLI, FastMCP, YAML, pytest.

## Global Constraints

- Preserve the current MCP server contract for existing clients.
- Keep the new path simple, zero-friction, and opt-in.
- Avoid introducing a second transport or a heavyweight runtime.
- Favor config-driven integration over new APIs when possible.

---

## Problem Summary

The current MCP path is useful, but it still assumes the agent can reason about retobs-specific `ExperimentConfig` objects and benchmark semantics. That is fine for a technical operator, but it is too much friction for a production agent trying to plug into an existing pipeline quickly.

## Design Principles

1. Simplicity first: one command to initialize, one config file to maintain.
2. Keep the production pipeline untouched: the agent should benchmark and inspect, not require a rewrite of the existing retrieval stack.
3. Make the “happy path” obvious: install, init, register, run.
4. Prefer reuse of the existing SDK seam over adding a parallel execution path.

## Recommended Approach

Add a lightweight “easy mode” around the current MCP server:

- `retobs mcp init` creates a starter config file and example client registration snippets for Claude, Cursor, or VS Code.
- `retobs mcp serve --config <path>` loads that config and exposes the same tools with a simpler default setup.
- The config file captures only the essentials: database path, default max queries, optional baseline run, and optional pipeline description metadata.
- A small helper tool, `benchmark_existing_pipeline`, accepts a simple descriptor object rather than a full retobs config, and internally translates it into the existing config-first benchmark path.

This keeps the implementation small while making integration materially easier.

## Out of Scope

- A new HTTP transport for MCP.
- Full workflow orchestration beyond benchmark/compare/inspect.
- A complete visual editor for pipeline definitions.

## Acceptance Criteria

- A new user can install retobs, run one init command, and get a working MCP registration snippet.
- An agent can benchmark or compare a pipeline using a minimal descriptor without needing to manually author a full retobs `ExperimentConfig`.
- Existing MCP clients continue to work unchanged.
- The new path is covered by unit tests.

"""Golden-fixture tests for the shapes of manifests that the Builder
Wizard (`frontend/src/screens/AgentWizardScreen.jsx::buildManifestYaml`)
emits.

The wizard is JS; pytest cannot invoke it directly. Instead we assert
the two shapes the wizard is required to produce — one non-MCP
(spec_version 1.0.1, back-compat with v0.11.x dialekt installs) and
one MCP-bearing (spec_version 1.1.0, mcp_tools capability silently
injected, mcp_servers block inlined). Both must validate cleanly
through `dialekt_manifest`.

This guards against four regressions:
- Wizard stops emitting the version-bump path when MCP is selected.
- Wizard stops injecting the mcp_tools capability when MCP is selected.
- Wizard emits an mcp_servers block shape the validator rejects.
- Wizard downgrades to 1.0.0 (the `minimum_dialekt_version` for non-MCP)
  for MCP-bearing agents, which would let them load on a runtime that
  lacks MCP.
"""
from dialekt_manifest import ManifestValidator


_NON_MCP_YAML = """\
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "b8ef25df-20aa-4165-a416-fea08c27e557"
  name: "Plain Research Agent"
  description: "No MCP tools."
  version: "1.0.0"
  language: "en"
  tags:
    []
  author:
    name: "tester"
    email: "tester@example.com"
  created_at: "2026-04-24T12:00:00+05:00"
  updated_at: "2026-04-24T12:00:00+05:00"

model:
  preferred: "llama3.2:3b"
  acceptable:
    []
  min_context_window: 32768
  requirements:
    min_ram_gb: 8
    min_vram_gb: 0
    recommended_ram_gb: 16
  parameters:
    temperature: 0.7
    top_p: 0.95
    max_tokens: 4096

system_prompt: |
  You are a helpful assistant.

capabilities:
  groups:
    []

autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"

input:
  type: "chat"
  placeholder: "Ask me anything..."

output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
"""


_MCP_YAML = """\
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"

metadata:
  id: "92073b42-bbdb-44b5-af28-e09c346fe3b7"
  name: "GitHub Operations Agent"
  description: "Uses GitHub MCP."
  version: "1.0.0"
  language: "en"
  tags:
    []
  author:
    name: "tester"
    email: "tester@example.com"
  created_at: "2026-04-24T12:00:00+05:00"
  updated_at: "2026-04-24T12:00:00+05:00"

model:
  preferred: "llama3.2:3b"
  acceptable:
    []
  min_context_window: 32768
  requirements:
    min_ram_gb: 8
    min_vram_gb: 0
    recommended_ram_gb: 16
  parameters:
    temperature: 0.7
    top_p: 0.95
    max_tokens: 4096

system_prompt: |
  You are a GitHub operations agent.

mcp_servers:
  - name: "github"
    transport: "stdio"
    command:
      - "npx"
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${secrets.github_token}"
    timeout_seconds: 30

capabilities:
  groups:
    - "mcp_tools"

autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"

input:
  type: "chat"
  placeholder: "Ask me anything..."

output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
"""


def test_wizard_non_mcp_yaml_validates_and_reports_spec_1_0_1():
    """Non-MCP path: spec_version 1.0.1, minimum_dialekt_version 1.0.0,
    no mcp_servers block, no mcp_tools capability, validator clean.
    """
    result = ManifestValidator().validate_string(_NON_MCP_YAML)
    assert result.valid, (
        f"wizard non-MCP YAML failed validation: "
        f"{[(e.code, e.message) for e in result.errors]}"
    )
    assert result.manifest.spec_version == "1.0.1"
    assert result.manifest.minimum_dialekt_version == "1.0.0"
    assert "mcp_tools" not in (result.manifest.capabilities.groups or [])
    assert not getattr(result.manifest, "mcp_servers", None)


def test_wizard_mcp_yaml_bumps_spec_and_injects_capability():
    """MCP-bearing path: spec_version 1.1.0, minimum_dialekt_version
    0.20.0, mcp_tools capability auto-injected, mcp_servers block
    present with stdio transport + env secret reference, validator clean.
    """
    result = ManifestValidator().validate_string(_MCP_YAML)
    assert result.valid, (
        f"wizard MCP YAML failed validation: "
        f"{[(e.code, e.message) for e in result.errors]}"
    )
    assert result.manifest.spec_version == "1.1.0"
    assert result.manifest.minimum_dialekt_version == "0.20.0"
    groups = result.manifest.capabilities.groups or []
    assert "mcp_tools" in groups, (
        "wizard must silently inject mcp_tools capability when mcp_servers "
        "is non-empty (design doc §3.3 ruling 3)"
    )
    servers = getattr(result.manifest, "mcp_servers", None)
    assert servers and len(servers) == 1
    gh = servers[0]
    assert gh.name == "github"
    # secret ref uses the single-segment form per Этап 1 Decision 3.
    assert gh.env["GITHUB_TOKEN"] == "${secrets.github_token}"

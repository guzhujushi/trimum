# awesome-mcp-servers (trimmed fixture)

> Fixture for tests/test_mcp_catalog.py — one line per feature the importer must handle.

* [What is MCP?](#what-is-mcp)
* [Server Implementations](#server-implementations)

## What is MCP?

- [Not A Server](https://example.com/not-a-server) 🐍 🏠 - a bullet outside any server section.

## Legend

* 🎖️ – official implementation

## Server Implementations

### 📁 <a name="file-systems"></a>File Systems

Servers for file access.

- [acme/filesystem-mcp](https://github.com/acme/filesystem-mcp) [![acme/filesystem-mcp MCP server](https://glama.ai/mcp/servers/acme/filesystem-mcp/badges/score.svg)](https://glama.ai/mcp/servers/acme/filesystem-mcp) 🎖️ 🐍 🏠 🍎 🪟 🐧 - Local filesystem access with a whitelist. Install: `uvx mcp-server-filesystem /work`.
- [acme/mixed-lang](https://github.com/acme/mixed-lang) [![acme/mixed-lang MCP server](https://glama.ai/mcp/servers/acme/mixed-lang/badges/score.svg)](https://glama.ai/mcp/servers/acme/mixed-lang) 📇 🐍 🏠 - Mixed language entry. `pip install mixed-lang`
- [acme/no-hint](https://github.com/acme/no-hint) [![acme/no-hint MCP server](https://glama.ai/mcp/servers/acme/no-hint/badges/score.svg)](https://glama.ai/mcp/servers/acme/no-hint) 🐍 ☁️ - Python server without an install hint.
- [acme/rust-thing](https://github.com/acme/rust-thing) [![acme/rust-thing MCP server](https://glama.ai/mcp/servers/acme/rust-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/rust-thing) 🦀 🏠 🐧 - Single binary. `cargo install rust-thing`
- [acme/go-thing](https://github.com/acme/go-thing) [![acme/go-thing MCP server](https://glama.ai/mcp/servers/acme/go-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/go-thing) 🏎️ 🏠 🐧 - Go server. `go install github.com/acme/go-thing@latest`
- [acme/pip-flags](https://github.com/acme/pip-flags) [![acme/pip-flags MCP server](https://glama.ai/mcp/servers/acme/pip-flags/badges/score.svg)](https://glama.ai/mcp/servers/acme/pip-flags) 🐍 ☁️ - Supports `pip install -U acme-pip-flags` and nothing else.
- [acme/uvx-from](https://github.com/acme/uvx-from) [![acme/uvx-from MCP server](https://glama.ai/mcp/servers/acme/uvx-from/badges/score.svg)](https://glama.ai/mcp/servers/acme/uvx-from) 🐍 🏠 - Runs from git: `uvx --from git+https://github.com/acme/uvx-from@main uvx-from`
- [acme/both-hints](https://github.com/acme/both-hints) [![acme/both-hints MCP server](https://glama.ai/mcp/servers/acme/both-hints/badges/score.svg)](https://glama.ai/mcp/servers/acme/both-hints) 🐍 🏠 - Prefer `uvx both-hints` over `npx -y both-hints`.
- [acme/py-npx](https://github.com/acme/py-npx) [![acme/py-npx MCP server](https://glama.ai/mcp/servers/acme/py-npx/badges/score.svg)](https://glama.ai/mcp/servers/acme/py-npx) 🐍 ☁️ - Python server shipped through the Node registry. `npx -y py-npx`
- [acme/no-desc](https://github.com/acme/no-desc) [![acme/no-desc MCP server](https://glama.ai/mcp/servers/acme/no-desc/badges/score.svg)](https://glama.ai/mcp/servers/acme/no-desc) 🐍 🏠
- [acme/mac-only](https://github.com/acme/mac-only) [![acme/mac-only MCP server](https://glama.ai/mcp/servers/acme/mac-only/badges/score.svg)](https://glama.ai/mcp/servers/acme/mac-only) 🐍 🏠 🍎 - macOS only. `pip install mac-only`
- [acme/unknown-lang](https://github.com/acme/unknown-lang) [![acme/unknown-lang MCP server](https://glama.ai/mcp/servers/acme/unknown-lang/badges/score.svg)](https://glama.ai/mcp/servers/acme/unknown-lang) 🏠 - No language marker. `pip install unknown-lang`
- [acme/embedded](https://github.com/acme/embedded) [![acme/embedded MCP server](https://glama.ai/mcp/servers/acme/embedded/badges/score.svg)](https://glama.ai/mcp/servers/acme/embedded) 🐍 📟 - Embedded scope. `uvx embedded-mcp`

### 🌐 <a name="browser-automation"></a>Browser Automation

- [acme/ts-server](https://github.com/acme/ts-server) [![acme/ts-server MCP server](https://glama.ai/mcp/servers/acme/ts-server/badges/score.svg)](https://glama.ai/mcp/servers/acme/ts-server) 📇 ☁️ - TypeScript server. `npx -y ts-server`
- [acme/docker-thing](https://github.com/acme/docker-thing) [![acme/docker-thing MCP server](https://glama.ai/mcp/servers/acme/docker-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/docker-thing) 🐍 🏠 🐧 - Containerised. `docker run --rm -i acme/docker-thing`
- [acme/java-thing](https://github.com/acme/java-thing) [![acme/java-thing MCP server](https://glama.ai/mcp/servers/acme/java-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/java-thing) ☕ 🏠 - Java server. `uvx java-thing`
- [acme/csharp-thing](https://github.com/acme/csharp-thing) [![acme/csharp-thing MCP server](https://glama.ai/mcp/servers/acme/csharp-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/csharp-thing) #️⃣ 🏠 - C# server. `uvx csharp-thing`
- [acme/brew-thing](https://github.com/acme/brew-thing) [![acme/brew-thing MCP server](https://glama.ai/mcp/servers/acme/brew-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/brew-thing) 🐍 🏠 - Homebrew only. `brew install brew-thing`
- [acme/mcp-server](https://github.com/acme/mcp-server) [![acme/mcp-server MCP server](https://glama.ai/mcp/servers/acme/mcp-server/badges/score.svg)](https://glama.ai/mcp/servers/acme/mcp-server) 🐍 🏠 🐧 - First server with this name. `uvx mcp-server`
- [other/mcp-server](https://github.com/other/mcp-server) [![other/mcp-server MCP server](https://glama.ai/mcp/servers/other/mcp-server/badges/score.svg)](https://glama.ai/mcp/servers/other/mcp-server) 🦀 ☁️ - Second server with the same repo name. `cargo install other-mcp-server`

### Other Tools and Integrations

- [acme/no-anchor-thing](https://github.com/acme/no-anchor-thing) 🐍 🏠 - Category without an anchor. `uvx no-anchor-thing`
- [Acme Weird](https://example.com/acme/weird) 🐍 ☁️ - Non-GitHub URL. `pip install weird`

## Frameworks

- [acme/framework](https://github.com/acme/framework) [![acme/framework MCP server](https://glama.ai/mcp/servers/acme/framework/badges/score.svg)](https://glama.ai/mcp/servers/acme/framework) 🐍 🏠 - Not a server implementation. `pip install framework`

## Star History

- [acme/star-thing](https://github.com/acme/star-thing) [![acme/star-thing MCP server](https://glama.ai/mcp/servers/acme/star-thing/badges/score.svg)](https://glama.ai/mcp/servers/acme/star-thing) 🏎️ ☁️ - Outside the server section. `go install x`

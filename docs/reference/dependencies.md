# Project Dependencies

MusicBee Tagger MCP relies on standard Python libraries as well as specialized audio tagging, MCP protocol, and documentation packages.

## Core Dependencies (`pyproject.toml`)

- **mcp>=1.0.0**: Model Context Protocol library for exposing MCP tools and resources.
- **mutagen>=1.47.0**: Audio metadata parsing and writing for FLAC, MP3, M4A, OGG, etc.
- **requests>=2.31.0**: HTTP requests for MusicBrainz and external API queries.
- **pydantic>=2.0.0**: Data validation and settings management.

## Development & Documentation Dependencies

- **mkdocs>=1.5.0**: Static site generator for markdown documentation.
- **mkdocs-material>=9.5.0**: Material theme for MkDocs with advanced navigation, code copy, and search.
- **mkdocstrings[python]>=0.24.0**: Automatic documentation from Python docstrings.
- **pymdown-extensions>=10.0**: Rich markdown formatting (admonitions, tabbed content, superfences, emoji).
- **pytest>=8.0.0**: Robust unit testing framework.
- **pyinstaller>=6.15.0**: Bundling standalone executables for Windows/macOS/Linux.

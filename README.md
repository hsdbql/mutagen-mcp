# Mutagen MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that provides audio metadata (tags) reading, writing, and management capabilities using the [Mutagen](https://mutagen.readthedocs.io/) library.

## Features

- **Metadata Read/Write**: Supports reading and modifying tags for various formats including MP3, FLAC, M4A, OGG, WAV, and more.
- **Batch Processing**: Process entire directories of audio files using the `isDir` parameter (1: current directory, 2: recursive).
- **Cover Art Management**: Extract or embed cover art images.
- **Lyrics Support**: Read and set both synced and unsynced lyrics.
- **File Organization**: Rename files based on metadata templates (e.g., `%artist% - %title%`).
- **Safe Deletion**: A file deletion tool with a double-confirmation safety mechanism.

## Installation

1. **Ensure Python 3.10+ is installed.**
2. **Create and activate a virtual environment** (recommended):
   ```bash
   python -m venv .venv
   # Windows
   .\.venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### MCP Client Configuration (e.g., Claude Desktop)

Add the following to your MCP settings file (e.g., `mcp_settings.json`):

```json
{
  "mcpServers": {
    "mutagen-mcp": {
      "command": "path/to/your/python.exe",
      "args": [
        "path/to/the/server.py"
      ]
    }
  }
}
```
*Note: Ensure the paths point to your actual local installation.*

### Development & Debugging

You can run the server directly to check for start-up errors:
```bash
python server.py
```
*Note: The server listens on `stdio` and may appear unresponsive when started manually.*

## Available Tools

- `read_audio_metadata`: Reads audio information (duration, bitrate, tags). Supports exporting to a file via `export_to`.
- `write_audio_metadata`: Updates audio tags. `metadata_updates` should be a JSON string.
- `delete_audio_metadata`: Permanently removes all metadata tags from a file.
- `rename_audio_by_template`: Renames files based on tags. Supports placeholders like `%artist%`, `%title%`, `%album%`, `%track%`, `%year%`, and `$num(%track%,2)` for padding (inspired by [Mp3tag](https://www.mp3tag.de/en/), with thanks).
- `extract_cover_art`: Extracts the first found cover art to a specified path.
- `embed_cover_art`: Embeds an image as the audio file's cover art.
- `get_lyrics` / `set_lyrics`: Manage unsynced lyrics.
- `strip_legacy_tags`: Removes legacy tags (ID3v1, APEv2) and standardizes to ID3v2.4 (primarily for MP3).
- `list_directory`: Lists files in a directory.
- `read_file` / `write_file`: General text file utilities.
- `delete_file`: Permanently deletes a file. Requires `force_delete=True` and `confirm_file_name` for safety.

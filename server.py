import os
import re
import json
import mimetypes
from typing import List
from mcp.server.fastmcp import FastMCP
import mutagen

# Create an MCP server
mcp = FastMCP("mutagen-mcp")


AUDIO_EXTS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".m4b",
    ".m4p",
    ".m4r",
    ".mp4",
    ".m4v",
    ".ogg",
    ".oga",
    ".ogv",
    ".mka",
    ".mkv",
    ".webm",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".ape",
    ".aac",
    ".alac",
    ".wma",
    ".wv",
    ".mpc",
    ".tak",
    ".dsf",
    ".dff",
    ".spx",
    ".tta",
    ".3gp",
}


def expand_tasks(raw_tasks: list) -> list:
    """Expand any directory tasks into individual file tasks."""
    final_tasks = []
    for task in raw_tasks:
        is_dir = task.get("isDir", 0)
        fp = task.get("filepath", "")

        if is_dir in (1, 2) and fp:
            if not os.path.exists(fp) or not os.path.isdir(fp):
                final_tasks.append({**task, "filepath": fp, "isDir": 0})
                continue
            if is_dir == 2:
                for root, _, filenames in os.walk(fp):
                    for filename in filenames:
                        if os.path.splitext(filename)[1].lower() in AUDIO_EXTS:
                            final_tasks.append(
                                {
                                    **task,
                                    "filepath": os.path.join(root, filename),
                                    "isDir": 0,
                                }
                            )
            elif is_dir == 1:
                for entry in os.scandir(fp):
                    if (
                        entry.is_file()
                        and os.path.splitext(entry.name)[1].lower() in AUDIO_EXTS
                    ):
                        final_tasks.append({**task, "filepath": entry.path, "isDir": 0})
        else:
            final_tasks.append(task)
    return final_tasks


def run_tasks(tasks: list, handler) -> str:
    """Expand and execute tasks, returning JSON results."""
    expanded = expand_tasks(tasks)
    results = []
    for task in expanded:
        try:
            res = handler(task)
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except json.JSONDecodeError:
                    pass
            results.append(res)
        except Exception as e:
            results.append({"error": str(e), "filepath": task.get("filepath", "")})

    if len(results) == 1:
        return json.dumps(results[0], indent=2, ensure_ascii=False)
    return json.dumps({"batch_results": results}, indent=2, ensure_ascii=False)


def get_audio_object(filepath: str, format_name: str = ""):
    if format_name:
        from mutagen import mp3, flac, mp4, oggvorbis, wave, id3

        FORMAT_MAP = {
            "mp3": mp3.MP3,
            "flac": flac.FLAC,
            "mp4": mp4.MP4,
            "oggvorbis": oggvorbis.OggVorbis,
            "wave": wave.WAVE,
            "id3": id3.ID3,
        }
        fmt = format_name.lower().strip()
        if fmt not in FORMAT_MAP:
            raise ValueError(
                f"Unsupported format: {format_name}. Supported: {list(FORMAT_MAP.keys())}"
            )
        return FORMAT_MAP[fmt](filepath)
    return mutagen.File(filepath)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def read_audio_metadata(tasks: List[dict]) -> str:
    """Reads audio file information and tags.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        format_name (str, optional): Force a mutagen format class ("mp3", "flac", "mp4", "oggvorbis", "wave", "id3").
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example (single):
        tasks=[{"filepath": "song.mp3"}]

    Example (batch):
        tasks=[{"filepath": "song1.mp3"}, {"filepath": "song2.flac"}]

    Example (directory):
        tasks=[{"filepath": "C:/Music/Album", "isDir": 2}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        format_name = task.get("format_name", "")
        try:
            audio = get_audio_object(filepath, format_name)
            if audio is None:
                return {
                    "filepath": filepath,
                    "error": "Unsupported format or file not found.",
                }

            info = {}
            if hasattr(audio, "info"):
                for attr in ["length", "bitrate", "sample_rate", "channels"]:
                    val = getattr(audio.info, attr, None)
                    if val is not None:
                        info[attr] = val
            mime = getattr(audio, "mime", [])
            if mime:
                info["mime"] = mime

            tags = {}
            target = audio.tags if hasattr(audio, "tags") else audio
            if target is not None and (
                isinstance(target, dict) or hasattr(target, "items")
            ):
                for key, val in target.items():
                    tags[str(key)] = (
                        [str(v) for v in val]
                        if isinstance(val, (list, tuple))
                        else str(val)
                    )
            return {"filepath": filepath, "info": info, "tags": tags}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def write_audio_metadata(tasks: List[dict]) -> str:
    """Updates tags for audio files.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        metadata_updates (dict, required): Tag key-value pairs to write.
            For MP3: use ID3 frame names like "TIT2" (title), "TPE1" (artist), "TALB" (album).
            For FLAC/Ogg: use Vorbis comment names like "TITLE", "ARTIST", "ALBUM".
            For MP4/M4A: use iTunes atoms like "\\xa9nam" (title), "\\xa9ART" (artist), "\\xa9alb" (album).
        format_name (str, optional): Force a mutagen format class.
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3", "metadata_updates": {"TIT2": "My Song", "TPE1": "Artist"}}]

    Example (batch):
        tasks=[
            {"filepath": "a.mp3", "metadata_updates": {"TIT2": "Song A"}},
            {"filepath": "b.mp3", "metadata_updates": {"TIT2": "Song B"}}
        ]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        metadata_updates = task.get("metadata_updates")
        format_name = task.get("format_name", "")
        if not metadata_updates or not isinstance(metadata_updates, dict):
            return {
                "filepath": filepath,
                "error": "metadata_updates must be a non-empty dict.",
            }
        try:
            audio = get_audio_object(filepath, format_name)
            if audio is None:
                return {
                    "filepath": filepath,
                    "error": "Unsupported format or file not found.",
                }
            target = audio.tags if hasattr(audio, "tags") else audio
            if getattr(audio, "tags", None) is None:
                if hasattr(audio, "add_tags"):
                    audio.add_tags()
                    target = audio.tags
                else:
                    return {
                        "filepath": filepath,
                        "error": "Cannot add tags to this format.",
                    }
            if target is not None:
                for key, value in metadata_updates.items():
                    target[key] = value if isinstance(value, list) else [value]
                audio.save()
                return {
                    "filepath": filepath,
                    "status": "success",
                    "message": "Metadata updated.",
                }
            return {"filepath": filepath, "error": "Audio format has no tags."}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def delete_audio_metadata(tasks: List[dict]) -> str:
    """Completely removes all metadata tags from audio files.

    WARNING: Destructive — permanently deletes all embedded tags.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        format_name (str, optional): Force a mutagen format class.
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        format_name = task.get("format_name", "")
        try:
            audio = get_audio_object(filepath, format_name)
            if audio is None:
                return {
                    "filepath": filepath,
                    "error": "Unsupported format or file not found.",
                }
            if hasattr(audio, "delete"):
                audio.delete()
                return {
                    "filepath": filepath,
                    "status": "success",
                    "message": "All tags deleted.",
                }
            return {
                "filepath": filepath,
                "error": "delete() not supported by this format.",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def rename_file(tasks: List[dict]) -> str:
    """Renames or moves files.

    Each task dict supports:
        old_path (str, required): Current file path.
        new_path (str, required): New file path.

    Example:
        tasks=[{"old_path": "old.mp3", "new_path": "new.mp3"}]
    """

    def handle(task):
        old_path = task.get("old_path", "")
        new_path = task.get("new_path", "")
        try:
            os.rename(old_path, new_path)
            return {"status": "success", "old_path": old_path, "new_path": new_path}
        except Exception as e:
            return {"error": str(e), "old_path": old_path}

    return run_tasks(tasks, handle)


@mcp.tool()
def list_directory(directory: str, recursive: bool = False) -> str:
    """Lists files in a directory.

    Args:
        directory: Path to the directory.
        recursive: If true, lists files in all subdirectories as well.
    """
    try:
        files = []
        if recursive:
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    files.append(os.path.join(root, filename))
        else:
            for entry in os.scandir(directory):
                if entry.is_file():
                    files.append(entry.path)
        return json.dumps({"files": files}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def rename_audio_by_template(tasks: List[dict]) -> str:
    """Renames audio files based on their metadata tags using a template string.

    WARNING: Destructive — modifies file paths on disk.

    Template syntax:
        %title%, %artist%, %album%, %year%, %track% — replaced with tag values.
        $num(%track%,2) — formats the track number zero-padded to N digits.
    Example template: "%artist% - $num(%track%,2) - %title%"
    Result: "Artist Name - 03 - Song Title.mp3"

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        template (str, required): Filename template string (without extension).
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3", "template": "%artist% - %title%"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        template = task.get("template", "")
        try:
            audio = mutagen.File(filepath)
            if audio is None or getattr(audio, "tags", None) is None:
                return {"filepath": filepath, "error": "Cannot read metadata."}

            tag_map = {}
            for k, v in audio.tags.items():
                k_lower = k.lower()
                val_str = (
                    str(v[0]) if isinstance(v, (list, tuple)) and len(v) > 0 else str(v)
                )
                if k_lower in ("tit2", "title", "\xa9nam"):
                    tag_map["title"] = val_str
                elif k_lower in ("tpe1", "artist", "\xa9art"):
                    tag_map["artist"] = val_str
                elif k_lower in ("talb", "album", "\xa9alb"):
                    tag_map["album"] = val_str
                elif k_lower in ("trck", "tracknumber", "trkn"):
                    if isinstance(v, list) and len(v) > 0 and isinstance(v[0], tuple):
                        tag_map["track"] = str(v[0][0])
                    else:
                        tag_map["track"] = val_str.split("/")[0]
                elif k_lower in ("tyer", "tdrc", "date", "\xa9day", "year"):
                    tag_map["year"] = val_str[:4]
                tag_map[k] = val_str
                tag_map[k_lower] = val_str

            def repl_num(match):
                tag = match.group(1).lower()
                pad = int(match.group(2))
                val = tag_map.get(tag, "")
                m = re.search(r"\d+", val)
                return m.group(0).zfill(pad) if m else "0".zfill(pad)

            def repl_var(match):
                return tag_map.get(match.group(1).lower(), f"%{match.group(1)}%")

            new_name = re.sub(r"\$num\(%([^%]+)%,(\d+)\)", repl_num, template)
            new_name = re.sub(r"%([^%]+)%", repl_var, new_name)
            new_name = re.sub(r'[\\/:*?"<>|]', "_", new_name)

            dir_name = os.path.dirname(filepath)
            ext = os.path.splitext(filepath)[1]
            new_filepath = os.path.join(dir_name, new_name + ext)
            os.rename(filepath, new_filepath)
            return {"status": "success", "old_path": filepath, "new_path": new_filepath}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def extract_cover_art(tasks: List[dict]) -> str:
    """Extracts cover art from audio files and saves it to disk.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        output_path (str, required): Path to save the extracted image (e.g. "cover.jpg").
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3", "output_path": "cover.jpg"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        output_path = task.get("output_path", "")
        try:
            audio = mutagen.File(filepath)
            if audio is None or getattr(audio, "tags", None) is None:
                return {"filepath": filepath, "error": "Cannot read metadata."}

            data = None
            if hasattr(audio, "pictures") and audio.pictures:
                data = audio.pictures[0].data
            elif hasattr(audio.tags, "getall") and audio.tags.getall("APIC"):
                data = audio.tags.getall("APIC")[0].data
            elif audio.tags.get("covr"):
                data = audio.tags["covr"][0]
            elif audio.tags.get("METADATA_BLOCK_PICTURE"):
                import base64
                from mutagen.flac import Picture

                data = Picture(
                    base64.b64decode(audio.tags["METADATA_BLOCK_PICTURE"][0])
                ).data

            if data:
                with open(output_path, "wb") as f:
                    f.write(data)
                return {
                    "filepath": filepath,
                    "status": "success",
                    "saved_to": output_path,
                }
            return {"filepath": filepath, "error": "No cover art found."}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def embed_cover_art(tasks: List[dict]) -> str:
    """Embeds an image file as the cover art of audio files.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        image_path (str, required): Path to the image to embed (JPEG or PNG recommended).
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3", "image_path": "cover.jpg"}]

    Example (apply same cover to whole album directory):
        tasks=[{"filepath": "C:/Music/Album", "image_path": "cover.jpg", "isDir": 1}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        image_path = task.get("image_path", "")
        try:
            if not os.path.exists(image_path):
                return {"filepath": filepath, "error": "Image file does not exist."}
            with open(image_path, "rb") as f:
                pic_data = f.read()
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            audio = mutagen.File(filepath)
            if audio is None:
                return {"filepath": filepath, "error": "Cannot read audio file."}
            if getattr(audio, "tags", None) is None:
                audio.add_tags()

            name = type(audio).__name__
            if hasattr(audio, "add_picture"):
                from mutagen.flac import Picture

                pic = Picture()
                pic.type = 3
                pic.mime = mime
                pic.desc = "Front Cover"
                pic.data = pic_data
                audio.clear_pictures()
                audio.add_picture(pic)
            elif name == "MP3" or hasattr(audio.tags, "getall"):
                from mutagen.id3 import APIC

                audio.tags.delall("APIC")
                audio.tags.add(
                    APIC(encoding=3, mime=mime, type=3, desc="Cover", data=pic_data)
                )
            elif name == "MP4":
                from mutagen.mp4 import MP4Cover

                fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
                audio.tags["covr"] = [MP4Cover(pic_data, imageformat=fmt)]
            else:
                return {
                    "filepath": filepath,
                    "error": f"Unsupported format for cover art: {name}",
                }

            audio.save()
            return {
                "filepath": filepath,
                "status": "success",
                "message": "Cover art embedded.",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def get_lyrics(tasks: List[dict]) -> str:
    """Reads unsynced lyrics from audio files.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        try:
            audio = mutagen.File(filepath)
            if audio is None or getattr(audio, "tags", None) is None:
                return {"filepath": filepath, "error": "Cannot read metadata."}

            lyrics = None
            name = type(audio).__name__
            if name == "MP3" or hasattr(audio.tags, "getall"):
                uslt = audio.tags.getall("USLT")
                if uslt:
                    lyrics = uslt[0].text
            elif name == "MP4":
                lyr = audio.tags.get("\xa9lyr")
                if lyr:
                    lyrics = lyr[0]
            else:
                lyr = audio.tags.get("LYRICS") or audio.tags.get("UNSYNCEDLYRICS")
                if lyr:
                    lyrics = lyr[0]

            if lyrics:
                return {
                    "filepath": filepath,
                    "status": "success",
                    "lyrics": str(lyrics),
                }
            return {"filepath": filepath, "error": "No lyrics found."}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def set_lyrics(tasks: List[dict]) -> str:
    """Sets the unsynced lyrics of audio files.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        lyrics_text (str, required): The full lyrics text to embed.
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3", "lyrics_text": "Line 1\\nLine 2\\nLine 3"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        lyrics_text = task.get("lyrics_text", "")
        try:
            audio = mutagen.File(filepath)
            if audio is None:
                return {"filepath": filepath, "error": "Cannot read audio file."}
            if getattr(audio, "tags", None) is None:
                audio.add_tags()

            name = type(audio).__name__
            if name == "MP3" or hasattr(audio.tags, "getall"):
                from mutagen.id3 import USLT

                audio.tags.delall("USLT")
                audio.tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics_text))
            elif name == "MP4":
                audio.tags["\xa9lyr"] = [lyrics_text]
            else:
                audio.tags["LYRICS"] = [lyrics_text]

            audio.save()
            return {
                "filepath": filepath,
                "status": "success",
                "message": "Lyrics embedded.",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def strip_legacy_tags(tasks: List[dict]) -> str:
    """Removes legacy tags (APEv2, ID3v1) from MP3s and re-saves as ID3v2.4.

    WARNING: Destructive — replaces legacy tag structures.

    Each task dict supports:
        filepath (str, required): Path to the audio file or directory.
        isDir (int, optional): 0=single file (default), 1=scan directory, 2=scan recursively.

    Example:
        tasks=[{"filepath": "song.mp3"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        try:
            audio = mutagen.File(filepath)
            if audio is None:
                return {"filepath": filepath, "error": "Cannot read audio file."}
            name = type(audio).__name__
            if name == "MP3":
                audio.save(v1=0, v2_version=4)
                try:
                    from mutagen.apev2 import APEv2

                    APEv2(filepath).delete()
                except Exception:
                    pass
                return {
                    "filepath": filepath,
                    "status": "success",
                    "message": "Saved as ID3v2.4, legacy tags stripped.",
                }
            return {
                "filepath": filepath,
                "status": "ignored",
                "message": f"Not an MP3, ignored ({name}).",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def read_file(tasks: List[dict]) -> str:
    """Reads the text content of files (UTF-8).

    Each task dict supports:
        filepath (str, required): Path to the text file to read.

    Example:
        tasks=[{"filepath": "lyrics.txt"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return {"filepath": filepath, "status": "success", "content": content}
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def write_file(tasks: List[dict]) -> str:
    """Writes text content to files, overwriting any existing content (UTF-8).

    WARNING: Completely replaces the file. Original content will be lost.

    Each task dict supports:
        filepath (str, required): Path to the file to write.
        content (str, required): The text content to write.

    Example:
        tasks=[{"filepath": "output.txt", "content": "Hello, world!"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        content = task.get("content", "")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "filepath": filepath,
                "status": "success",
                "message": f"Written to {filepath}",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


@mcp.tool()
def delete_file(tasks: List[dict]) -> str:
    """Permanently deletes files from disk.

    WARNING: HIGHLY DESTRUCTIVE. Requires double confirmation per file:
      1. Set `force_delete: true`
      2. Set `confirm_file_name` to the exact basename of the file (e.g. "song.mp3").
    If either check fails, a dry-run preview is returned instead (safe default).

    Each task dict supports:
        filepath (str, required): Path to the file to delete.
        force_delete (bool, required): Must be true to actually delete.
        confirm_file_name (str, required): Must exactly match the filename (basename).

    Example:
        tasks=[{"filepath": "song.mp3", "force_delete": true, "confirm_file_name": "song.mp3"}]
    """

    def handle(task):
        filepath = task.get("filepath", "")
        force_delete = task.get("force_delete", False)
        confirm_file_name = task.get("confirm_file_name", "")
        try:
            if not os.path.exists(filepath):
                return {"filepath": filepath, "error": "File not found."}
            if os.path.isdir(filepath):
                return {
                    "filepath": filepath,
                    "error": "Cannot delete directories with this tool.",
                }
            expected = os.path.basename(filepath)
            if not force_delete or confirm_file_name != expected:
                return {
                    "filepath": filepath,
                    "status": "needs_confirmation",
                    "message": f"DRY RUN. To confirm, call with force_delete=true and confirm_file_name='{expected}'.",
                    "would_delete": True,
                }
            os.remove(filepath)
            return {
                "filepath": filepath,
                "status": "success",
                "message": f"Deleted: {filepath}",
            }
        except Exception as e:
            return {"filepath": filepath, "error": str(e)}

    return run_tasks(tasks, handle)


if __name__ == "__main__":
    mcp.run()

import os
import re
import json
import mimetypes
import inspect
from typing import Union, List
from functools import wraps
from mcp.server.fastmcp import FastMCP
import mutagen

# Create an MCP server
mcp = FastMCP("mutagen-mcp")


def standardize_batch_args(kwargs):
    is_dir_val = kwargs.get("isDir", 0)
    is_dir = is_dir_val[0] if isinstance(is_dir_val, list) else is_dir_val

    if is_dir in (1, 2) and "filepath" in kwargs:
        fps = kwargs["filepath"]
        if not isinstance(fps, list):
            fps = [fps]

        expanded_fps = []
        exts = {
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

        for fp in fps:
            if not os.path.exists(fp):
                expanded_fps.append(fp)
                continue
            if not os.path.isdir(fp):
                expanded_fps.append(fp)
                continue

            if is_dir == 2:
                for root, _, filenames in os.walk(fp):
                    for filename in filenames:
                        if os.path.splitext(filename)[1].lower() in exts:
                            expanded_fps.append(os.path.join(root, filename))
            elif is_dir == 1:
                for entry in os.scandir(fp):
                    if (
                        entry.is_file()
                        and os.path.splitext(entry.name)[1].lower() in exts
                    ):
                        expanded_fps.append(entry.path)

        kwargs["filepath"] = expanded_fps

    batch_len = None
    for k, v in kwargs.items():
        if isinstance(v, list):
            if batch_len is None:
                batch_len = len(v)
            elif len(v) != batch_len:
                raise ValueError("All array arguments must have the same length.")

    if batch_len is None:
        return [kwargs], False

    batch_kwargs_list = []
    for i in range(batch_len):
        single_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, list):
                single_kwargs[k] = v[i]
            else:
                single_kwargs[k] = v
        batch_kwargs_list.append(single_kwargs)

    return batch_kwargs_list, True


def batchable(func):
    sig = inspect.signature(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        all_kwargs = bound.arguments

        try:
            batch_kwargs_list, is_batch = standardize_batch_args(all_kwargs)
        except Exception as e:
            return json.dumps({"error": str(e)})

        results = []
        for kw in batch_kwargs_list:
            try:
                res = func(**kw)
                if isinstance(res, str):
                    try:
                        res = json.loads(res)
                    except json.JSONDecodeError:
                        pass
                results.append(res)
            except Exception as e:
                results.append({"error": str(e)})

        if not is_batch:
            final_res = json.dumps(results[0], indent=2)
        else:
            final_res = json.dumps({"batch_results": results}, indent=2)

        export_to = all_kwargs.get("export_to", "")
        if isinstance(export_to, list) and len(export_to) > 0:
            export_to = export_to[0]

        if export_to:
            try:
                with open(export_to, "w", encoding="utf-8") as f:
                    f.write(final_res)
                return json.dumps(
                    {
                        "status": "success",
                        "message": f"Results successfully exported to {export_to}",
                    }
                )
            except Exception as e:
                return json.dumps({"error": f"Failed to export to file: {str(e)}"})

        return final_res

    # Append batch instruction to the docstring so AI models know how to use it
    batch_notice = (
        "\n\n**BATCH OPERATION SUPPORT**:\n"
        "This tool supports batch processing. You can pass a list (array) of values for arguments "
        "(e.g., a list of filepaths instead of a single string) to process multiple items at once. "
        "When using batch mode, all list arguments must be of the same length."
    )
    if wrapper.__doc__:
        wrapper.__doc__ += batch_notice
    else:
        wrapper.__doc__ = batch_notice

    return wrapper


StrOrList = Union[str, List[str]]


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
                f"Unsupported format class: {format_name}. Supported: {list(FORMAT_MAP.keys())}"
            )
        return FORMAT_MAP[fmt](filepath)
    else:
        return mutagen.File(filepath)


@mcp.tool()
@batchable
def read_audio_metadata(
    filepath: StrOrList,
    format_name: StrOrList = "",
    isDir: int = 0,
    export_to: StrOrList = "",
) -> str:
    """Reads audio file information and tags for the specified file."""
    try:
        audio = get_audio_object(filepath, format_name)
        if audio is None:
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": "Unsupported audio format or file not found.",
                }
            )

        info = {}
        if hasattr(audio, "info"):
            for attr in [
                "length",
                "bitrate",
                "sample_rate",
                "channels",
            ]:
                val = getattr(audio.info, attr, None)
                if val is not None:
                    info[attr] = val

        mime = getattr(audio, "mime", [])
        if mime:
            info["mime"] = mime

        tags = {}
        target = audio.tags if hasattr(audio, "tags") else audio
        if target is not None:
            if isinstance(target, dict) or hasattr(target, "items"):
                for key, val in target.items():
                    tags[str(key)] = (
                        [str(v) for v in val]
                        if isinstance(val, (list, tuple))
                        else str(val)
                    )

        return json.dumps({"filepath": filepath, "info": info, "tags": tags})
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def write_audio_metadata(
    filepath: StrOrList,
    metadata_updates: StrOrList,
    format_name: StrOrList = "",
    isDir: int = 0,
) -> str:
    """Updates tags for an audio file."""
    try:
        updates = json.loads(metadata_updates)
        audio = get_audio_object(filepath, format_name)

        if audio is None:
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": "Unsupported audio format or file not found.",
                }
            )

        target = audio.tags if hasattr(audio, "tags") else audio
        if getattr(audio, "tags", None) is None:
            if hasattr(audio, "add_tags"):
                audio.add_tags()
                target = audio.tags
            else:
                return json.dumps(
                    {"filepath": filepath, "error": "Cannot add tags to this format."}
                )

        if target is not None:
            for key, value in updates.items():
                target[key] = value if isinstance(value, list) else [value]
            audio.save()
            return json.dumps(
                {"filepath": filepath, "status": "Metadata updated successfully."}
            )
        else:
            return json.dumps(
                {"filepath": filepath, "error": "Audio format has no tags."}
            )
    except json.JSONDecodeError:
        return json.dumps(
            {
                "filepath": filepath,
                "error": "metadata_updates must be a valid JSON string.",
            }
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def delete_audio_metadata(
    filepath: StrOrList, format_name: StrOrList = "", isDir: int = 0
) -> str:
    """Completely removes all metadata tags from an audio file.

    WARNING: This is a destructive operation! It will permanently delete
    all embedded tags (ID3, Vorbis comments, APIC, etc.) from the file.
    Ensure you or the user actually intend to wipe metadata before calling this.
    """
    try:
        audio = get_audio_object(filepath, format_name)
        if audio is None:
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": "Unsupported audio format or file not found.",
                }
            )

        if hasattr(audio, "delete"):
            audio.delete()
            return json.dumps(
                {"filepath": filepath, "status": "Metadata tags deleted successfully."}
            )
        else:
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": "delete() not supported by this format.",
                }
            )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def rename_file(old_path: StrOrList, new_path: StrOrList) -> str:
    """Renames or moves a file."""
    try:
        os.rename(old_path, new_path)
        return json.dumps(
            {"status": "success", "old_path": old_path, "new_path": new_path}
        )
    except Exception as e:
        return json.dumps(
            {"error": f"Error renaming file: {str(e)}", "old_path": old_path}
        )


@mcp.tool()
def list_directory(directory: str, recursive: bool = False) -> str:
    """Lists files in a directory."""
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
@batchable
def rename_audio_by_template(
    filepath: StrOrList, template: StrOrList, isDir: int = 0
) -> str:
    """Renames an audio file based on its metadata tags using a template.

    WARNING: This is a destructive operation that modifies file paths on the disk.
    If multiple files resolve to the same newly generated name, it may overwrite
    existing files or cause file system errors. Proceed with caution.
    """
    try:
        audio = mutagen.File(filepath)
        if audio is None or getattr(audio, "tags", None) is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read metadata for this file."}
            )

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
            digits_match = re.search(r"\d+", val)
            if digits_match:
                return digits_match.group(0).zfill(pad)
            return "0".zfill(pad)

        def repl_var(match):
            tag = match.group(1).lower()
            return tag_map.get(tag, f"%{tag}%")

        new_name = re.sub(r"\$num\(%([^%]+)%,(\d+)\)", repl_num, template)
        new_name = re.sub(r"%([^%]+)%", repl_var, new_name)
        new_name = re.sub(r'[\\/:*?"<>|]', "_", new_name)

        dir_name = os.path.dirname(filepath)
        ext = os.path.splitext(filepath)[1]
        new_filepath = os.path.join(dir_name, new_name + ext)

        os.rename(filepath, new_filepath)
        return json.dumps(
            {"status": "success", "old_path": filepath, "new_path": new_filepath}
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def extract_cover_art(
    filepath: StrOrList, output_path: StrOrList, isDir: int = 0
) -> str:
    """Extracts the first cover art picture found in the audio file."""
    try:
        audio = mutagen.File(filepath)
        if audio is None or getattr(audio, "tags", None) is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read metadata for this file."}
            )

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

            b64_data = audio.tags["METADATA_BLOCK_PICTURE"][0]
            pic = Picture(base64.b64decode(b64_data))
            data = pic.data

        if data:
            with open(output_path, "wb") as f:
                f.write(data)
            return json.dumps(
                {"filepath": filepath, "status": "success", "saved_to": output_path}
            )
        else:
            return json.dumps(
                {"filepath": filepath, "error": "No cover art found in the file."}
            )

    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def embed_cover_art(filepath: StrOrList, image_path: StrOrList, isDir: int = 0) -> str:
    """Embeds an image as the cover art for an audio file."""
    try:
        if not os.path.exists(image_path):
            return json.dumps(
                {"filepath": filepath, "error": "Image file does not exist."}
            )

        with open(image_path, "rb") as f:
            pic_data = f.read()

        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"

        audio = mutagen.File(filepath)
        if audio is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read audio file."}
            )

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
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": f"Unsupported format for cover art embedding: {name}",
                }
            )

        audio.save()
        return json.dumps(
            {
                "filepath": filepath,
                "status": "success",
                "message": "Cover art embedded successfully.",
            }
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def get_lyrics(filepath: StrOrList, isDir: int = 0) -> str:
    """Reads synced/unsynced lyrics from the audio file."""
    try:
        audio = mutagen.File(filepath)
        if audio is None or getattr(audio, "tags", None) is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read metadata for this file."}
            )

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
            return json.dumps(
                {"filepath": filepath, "status": "success", "lyrics": str(lyrics)}
            )
        else:
            return json.dumps(
                {"filepath": filepath, "error": "No lyrics found in the file."}
            )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def set_lyrics(filepath: StrOrList, lyrics_text: StrOrList, isDir: int = 0) -> str:
    """Sets the unsynced lyrics of the audio file."""
    try:
        audio = mutagen.File(filepath)
        if audio is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read audio file."}
            )

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
        return json.dumps(
            {
                "filepath": filepath,
                "status": "success",
                "message": "Lyrics embedded successfully.",
            }
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def strip_legacy_tags(filepath: StrOrList, isDir: int = 0) -> str:
    """Removes legacy tags (like APEv2 or ID3v1 on MP3s) and forces standard ID3v2.4.

    WARNING: Destructive formatting. This deletes original legacy tags structure
    and replaces them. Use only when you need to unify ID3 versions natively.
    """
    try:
        audio = mutagen.File(filepath)
        if audio is None:
            return json.dumps(
                {"filepath": filepath, "error": "Cannot read audio file."}
            )

        name = type(audio).__name__
        if name == "MP3":
            audio.save(v1=0, v2_version=4)
            try:
                from mutagen.apev2 import APEv2

                ape = APEv2(filepath)
                ape.delete()
            except Exception:
                pass
            return json.dumps(
                {
                    "filepath": filepath,
                    "status": "success",
                    "message": "Legacy MP3 tags stripped. Saved as ID3v2.4.",
                }
            )
        else:
            return json.dumps(
                {
                    "filepath": filepath,
                    "status": "ignored",
                    "message": f"strip_legacy_tags primarily targets MP3 files, ignored {name}.",
                }
            )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def read_file(filepath: StrOrList) -> str:
    """Reads the text content of a file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return json.dumps(
            {"filepath": filepath, "status": "success", "content": content}
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def write_file(filepath: StrOrList, content: StrOrList) -> str:
    """Writes text content to a file, overwriting any existing content.

    WARNING: This completely replaces the file. Use with caution as original
    contents will be lost without recovery.
    """
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return json.dumps(
            {
                "filepath": filepath,
                "status": "success",
                "message": f"Successfully wrote to {filepath}",
            }
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


@mcp.tool()
@batchable
def delete_file(
    filepath: StrOrList, force_delete: bool = False, confirm_file_name: str = ""
) -> str:
    """Permanently deletes a file from the disk.

    WARNING: THIS IS A HIGHLY DESTRUCTIVE OPERATION!
    To prevent accidental deletions by you or the AI, this tool requires strict double confirmation:
    1. You must set `force_delete=True`
    2. You must provide `confirm_file_name` which must EXACTLY match the basename of the file.

    If either fails, the tool returns a dry-run/preview showing what would be deleted.
    """
    try:
        import os

        if not os.path.exists(filepath):
            return json.dumps({"filepath": filepath, "error": "File not found."})

        if os.path.isdir(filepath):
            return json.dumps(
                {
                    "filepath": filepath,
                    "error": "Cannot delete directories, use this tool for files only.",
                }
            )

        expected_basename = os.path.basename(filepath)

        if not force_delete or confirm_file_name != expected_basename:
            return json.dumps(
                {
                    "filepath": filepath,
                    "status": "needs_confirmation",
                    "message": f"DRY RUN (Safety restriction). To confirm deletion, you must call this tool with force_delete=True and confirm_file_name='{expected_basename}'.",
                    "would_delete": True,
                }
            )

        os.remove(filepath)
        return json.dumps(
            {
                "filepath": filepath,
                "status": "success",
                "message": f"Permanently deleted: {filepath}",
            }
        )
    except Exception as e:
        return json.dumps({"filepath": filepath, "error": str(e)})


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run()

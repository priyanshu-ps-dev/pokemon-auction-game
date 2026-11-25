"""
Local Anime Avatar Library Manager
==================================
Manages local character portrait images stored under public/assets/avatars/<franchise>/
and synchronizes public/assets/avatars/manifest.json without any external APIs.
"""

import base64
import hashlib
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

FRANCHISES: List[Tuple[str, str]] = [
    ("one-piece", "One Piece"),
    ("naruto", "Naruto"),
    ("pokemon", "Pokémon"),
    ("dragon-ball", "Dragon Ball"),
    ("bleach", "Bleach"),
    ("jujutsu-kaisen", "Jujutsu Kaisen"),
    ("demon-slayer", "Demon Slayer"),
    ("attack-on-titan", "Attack on Titan"),
    ("hunter-x-hunter", "Hunter x Hunter"),
    ("my-hero-academia", "My Hero Academia"),
    ("death-note", "Death Note"),
    ("solo-leveling", "Solo Leveling"),
    ("marvel", "Marvel"),
    ("other-anime", "Other Anime"),
    ("default", "Default"),
]

SLUG_TO_NAME: Dict[str, str] = {slug: name for slug, name in FRANCHISES}
NAME_TO_SLUG: Dict[str, str] = {name.lower(): slug for slug, name in FRANCHISES}
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB per portrait


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or f"char-{int(time.time())}"


def _title_from_filename(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    words = re.split(r"[_\-\s]+", stem)
    return " ".join(w.capitalize() for w in words if w) or "Unknown Character"


def resolve_franchise_slug(anime_value: str) -> str:
    if not anime_value:
        return "other-anime"
    low = anime_value.strip().lower()
    if low in SLUG_TO_NAME:
        return low
    if low in NAME_TO_SLUG:
        return NAME_TO_SLUG[low]
    slug = _slugify(low)
    return slug if slug in SLUG_TO_NAME else "other-anime"


class LocalAvatarLibrary:
    def __init__(self, public_dir: str):
        self.public_dir = os.path.abspath(public_dir)
        self.avatars_dir = os.path.join(self.public_dir, "assets", "avatars")
        self.manifest_path = os.path.join(self.avatars_dir, "manifest.json")
        self.ensure_structure()

    def ensure_structure(self) -> None:
        os.makedirs(self.avatars_dir, exist_ok=True)
        for slug, _ in FRANCHISES:
            os.makedirs(os.path.join(self.avatars_dir, slug), exist_ok=True)
        if not os.path.exists(self.manifest_path):
            self._write_manifest({"characters": []})

    def _read_manifest_raw(self) -> Dict[str, Any]:
        if not os.path.exists(self.manifest_path):
            return {"characters": []}
        try:
            with open(self.manifest_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("characters"), list):
                return data
        except Exception:
            pass
        return {"characters": []}

    def _write_manifest(self, data: Dict[str, Any]) -> None:
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _image_url_to_disk_path(self, image_url: str) -> str:
        rel = image_url.lstrip("/").replace("/", os.sep)
        return os.path.join(self.public_dir, rel)

    def sync_and_get_manifest(self) -> Dict[str, Any]:
        """
        Validates manifest entries against disk (never returns missing images)
        and auto-discovers any portrait images placed directly into franchise folders.
        """
        self.ensure_structure()
        raw = self._read_manifest_raw()
        valid_chars: List[Dict[str, Any]] = []
        seen_paths = set()
        seen_ids = set()

        for entry in raw.get("characters", []):
            if not isinstance(entry, dict):
                continue
            img_url = str(entry.get("image", "")).strip()
            if not img_url:
                continue
            disk_path = self._image_url_to_disk_path(img_url)
            if not os.path.isfile(disk_path):
                continue
            norm_url = "/" + img_url.lstrip("/")
            cid = str(entry.get("id") or _slugify(entry.get("name", "char"))).strip()
            while cid in seen_ids:
                cid = f"{cid}-{len(seen_ids) + 1}"
            seen_ids.add(cid)
            seen_paths.add(os.path.normcase(os.path.abspath(disk_path)))

            slug = resolve_franchise_slug(entry.get("anime", "Other Anime"))
            anime_display = SLUG_TO_NAME.get(slug, entry.get("anime", "Other Anime"))
            valid_chars.append({
                "id": cid,
                "name": str(entry.get("name") or _title_from_filename(disk_path)).strip(),
                "anime": anime_display,
                "franchise_slug": slug,
                "image": norm_url,
                "description": str(entry.get("description", "")).strip(),
                "source": str(entry.get("source", "")).strip(),
                "license": str(entry.get("license", "")).strip(),
            })

        # Auto-discover files placed manually into franchise folders
        changed = len(valid_chars) != len(raw.get("characters", []))
        for slug, anime_display in FRANCHISES:
            folder = os.path.join(self.avatars_dir, slug)
            if not os.path.isdir(folder):
                continue
            for fname in sorted(os.listdir(folder)):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ALLOWED_EXTS:
                    continue
                disk_path = os.path.join(folder, fname)
                if not os.path.isfile(disk_path):
                    continue
                norm_disk = os.path.normcase(os.path.abspath(disk_path))
                if norm_disk in seen_paths:
                    continue

                char_name = _title_from_filename(fname)
                base_id = f"{slug}-{_slugify(os.path.splitext(fname)[0])}"
                cid = base_id
                idx = 2
                while cid in seen_ids:
                    cid = f"{base_id}-{idx}"
                    idx += 1
                seen_ids.add(cid)
                seen_paths.add(norm_disk)

                valid_chars.append({
                    "id": cid,
                    "name": char_name,
                    "anime": anime_display,
                    "franchise_slug": slug,
                    "image": f"/assets/avatars/{slug}/{fname}",
                    "description": "",
                    "source": "Local Folder Import",
                    "license": "",
                })
                changed = True

        if changed:
            self._write_manifest({"characters": valid_chars})

        # Compute category counts (only populated categories)
        counts: Dict[str, int] = {}
        for ch in valid_chars:
            counts[ch["anime"]] = counts.get(ch["anime"], 0) + 1

        categories = [
            {"slug": slug, "name": display, "count": counts.get(display, 0)}
            for slug, display in FRANCHISES
            if counts.get(display, 0) > 0
        ]

        return {
            "characters": valid_chars,
            "categories": categories,
            "franchises": [{"slug": s, "name": n} for s, n in FRANCHISES],
            "total": len(valid_chars),
        }

    def _decode_and_validate_image(self, data_url_or_b64: str, filename: str) -> Tuple[bytes, str]:
        if not data_url_or_b64:
            raise ValueError("Empty image data.")
        raw_b64 = data_url_or_b64
        if "," in raw_b64 and raw_b64.startswith("data:"):
            raw_b64 = raw_b64.split(",", 1)[1]
        img_bytes = base64.b64decode(raw_b64)
        if len(img_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError("Image exceeds 8 MB size limit.")

        ext = os.path.splitext(filename or "avatar.png")[1].lower()
        if ext not in ALLOWED_EXTS:
            ext = ".png"

        # Validate real image using Pillow
        with Image.open(io.BytesIO(img_bytes)) as im:
            im.verify()
        return img_bytes, ext

    def upload_character(
        self,
        name: str,
        anime: str,
        image_data: str,
        filename: str,
        description: str = "",
        source: str = "",
        license_info: str = "",
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Character name is required.")
        slug = resolve_franchise_slug(anime)
        anime_display = SLUG_TO_NAME.get(slug, "Other Anime")

        img_bytes, ext = self._decode_and_validate_image(image_data, filename)
        img_hash = hashlib.sha256(img_bytes).hexdigest()[:12]

        manifest = self.sync_and_get_manifest()
        chars = manifest["characters"]

        # Duplicate detection: same name + anime OR identical image file hash in same folder
        for ch in chars:
            if ch["name"].strip().lower() == clean_name.lower() and ch["franchise_slug"] == slug:
                raise ValueError(f"Duplicate character: '{clean_name}' already exists in {anime_display}.")
            disk_p = self._image_url_to_disk_path(ch["image"])
            if os.path.isfile(disk_p):
                with open(disk_p, "rb") as existing_f:
                    if hashlib.sha256(existing_f.read()).hexdigest()[:12] == img_hash:
                        raise ValueError(f"Duplicate image detected (matches '{ch['name']}').")

        file_slug = _slugify(clean_name)
        target_name = f"{file_slug}{ext}"
        target_path = os.path.join(self.avatars_dir, slug, target_name)
        counter = 2
        while os.path.exists(target_path):
            target_name = f"{file_slug}-{counter}{ext}"
            target_path = os.path.join(self.avatars_dir, slug, target_name)
            counter += 1

        with open(target_path, "wb") as f:
            f.write(img_bytes)

        existing_ids = {c["id"] for c in chars}
        cid = f"{slug}-{file_slug}"
        c_idx = 2
        while cid in existing_ids:
            cid = f"{slug}-{file_slug}-{c_idx}"
            c_idx += 1

        new_entry = {
            "id": cid,
            "name": clean_name,
            "anime": anime_display,
            "franchise_slug": slug,
            "image": f"/assets/avatars/{slug}/{target_name}",
            "description": (description or "").strip(),
            "source": (source or "Local Upload").strip(),
            "license": (license_info or "").strip(),
        }
        chars.append(new_entry)
        self._write_manifest({"characters": chars})
        return new_entry

    def edit_character(self, char_id: str, new_name: str, new_anime: str) -> Dict[str, Any]:
        manifest = self.sync_and_get_manifest()
        chars = manifest["characters"]
        target = next((c for c in chars if c["id"] == char_id), None)
        if not target:
            raise ValueError("Character not found.")

        clean_name = (new_name or "").strip()
        if not clean_name:
            raise ValueError("Character name cannot be empty.")

        new_slug = resolve_franchise_slug(new_anime)
        new_display = SLUG_TO_NAME.get(new_slug, "Other Anime")

        # Move image file if franchise changed
        if new_slug != target["franchise_slug"]:
            old_disk = self._image_url_to_disk_path(target["image"])
            fname = os.path.basename(old_disk)
            new_disk = os.path.join(self.avatars_dir, new_slug, fname)
            if os.path.exists(new_disk):
                stem, ext = os.path.splitext(fname)
                fname = f"{stem}-{int(time.time())}{ext}"
                new_disk = os.path.join(self.avatars_dir, new_slug, fname)
            if os.path.isfile(old_disk):
                os.replace(old_disk, new_disk)
            target["image"] = f"/assets/avatars/{new_slug}/{fname}"
            target["franchise_slug"] = new_slug

        target["name"] = clean_name
        target["anime"] = new_display
        self._write_manifest({"characters": chars})
        return target

    def replace_portrait(self, char_id: str, image_data: str, filename: str) -> Dict[str, Any]:
        manifest = self.sync_and_get_manifest()
        chars = manifest["characters"]
        target = next((c for c in chars if c["id"] == char_id), None)
        if not target:
            raise ValueError("Character not found.")

        img_bytes, ext = self._decode_and_validate_image(image_data, filename)
        old_disk = self._image_url_to_disk_path(target["image"])
        slug = target["franchise_slug"]
        new_fname = f"{_slugify(target['name'])}-{int(time.time())}{ext}"
        new_disk = os.path.join(self.avatars_dir, slug, new_fname)

        with open(new_disk, "wb") as f:
            f.write(img_bytes)
        if os.path.isfile(old_disk) and os.path.abspath(old_disk) != os.path.abspath(new_disk):
            try:
                os.remove(old_disk)
            except OSError:
                pass

        target["image"] = f"/assets/avatars/{slug}/{new_fname}"
        self._write_manifest({"characters": chars})
        return target

    def delete_character(self, char_id: str) -> bool:
        manifest = self.sync_and_get_manifest()
        chars = manifest["characters"]
        target = next((c for c in chars if c["id"] == char_id), None)
        if not target:
            return False

        disk_path = self._image_url_to_disk_path(target["image"])
        if os.path.isfile(disk_path):
            try:
                os.remove(disk_path)
            except OSError:
                pass

        remaining = [c for c in chars if c["id"] != char_id]
        self._write_manifest({"characters": remaining})
        return True

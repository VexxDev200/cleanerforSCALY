from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class VolumeInfo:
    letter: str  # "C:"
    mountpoint: str
    fstype: str
    label: str
    total: int
    used: int
    free: int
    percent: float


def list_volumes() -> list[VolumeInfo]:
    out: list[VolumeInfo] = []
    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint:
            continue
        mp = part.mountpoint
        if part.fstype.upper() not in ("NTFS", "FAT32", "EXFAT", "REFS", ""):
            # пропускаем CD-ROM и т.п., но пустой fstype на некоторых томах оставляем
            if part.fstype and "UDF" in part.fstype.upper():
                continue
        try:
            du = psutil.disk_usage(mp)
        except (PermissionError, OSError):
            continue
        letter = mp.rstrip("\\")
        if len(letter) == 2 and letter[1] == ":":
            letter = letter + "\\"
        elif not letter.endswith("\\"):
            letter = mp
        label = _volume_label(letter) or part.device
        out.append(
            VolumeInfo(
                letter=letter if letter.endswith("\\") else letter + "\\",
                mountpoint=mp,
                fstype=part.fstype or "?",
                label=label,
                total=du.total,
                used=du.used,
                free=du.free,
                percent=du.percent,
            )
        )
    out.sort(key=lambda v: v.letter)
    return out


def _volume_label(drive: str) -> str:
    try:
        import ctypes

        vol_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        max_comp = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        root = drive if drive.endswith("\\") else drive + "\\"
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            root,
            vol_name,
            260,
            ctypes.byref(serial),
            ctypes.byref(max_comp),
            ctypes.byref(flags),
            fs_name,
            260,
        )
        if ok:
            return vol_name.value.strip()
    except Exception:
        pass
    return ""


def default_drive() -> str:
    vols = list_volumes()
    for v in vols:
        if v.letter.upper().startswith("C:"):
            return v.letter
    return vols[0].letter if vols else "C:\\"

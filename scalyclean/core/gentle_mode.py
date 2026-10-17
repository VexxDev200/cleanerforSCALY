"""Бережный режим: не убивать лаунчеры/игры и не трогать их процессы."""

# Точные имена exe (lower)
_PROTECTED_EXACT = {
    "steam.exe",
    "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "epicwebhelper.exe",
    "riotclientservices.exe",
    "riotclientux.exe",
    "valorant.exe",
    "valorant-win64-shipping.exe",
    "cs2.exe",
    "dota2.exe",
    "fortniteclient-win64-shipping.exe",
    "fortnitelauncher.exe",
    "gta5.exe",
    "fivem.exe",
    "cod.exe",
    "modernwarfare.exe",
    "battle.net.exe",
    "agent.exe",
    "origin.exe",
    "eadesktop.exe",
    "galaxyclient.exe",
    "ubisoftgamelauncher.exe",
    "overwatch.exe",
    "minecraft.exe",
    "javaw.exe",
    "runtimebroker.exe",
    "discord.exe",
    "nvcontainer.exe",
    "nvdisplay.container.exe",
    "amdow.exe",
    "radeonsoftware.exe",
}

# Подстрока в имени процесса
_PROTECTED_PARTS = (
    "steam",
    "epic",
    "riot",
    "valorant",
    "fortnite",
    "easyanticheat",
    "battleye",
    "bedaisy",
    "vgc",
    "vgtray",
    "faceit",
    "unity",
    "unreal",
    "gamebar",
    "xbox",
    "eadesktop",
    "origin",
    "battlenet",
    "blizzard",
    "minecraft",
    "roblox",
    "gta",
    "forza",
    "eldenring",
    "denuvo",
)


def is_protected_process(name: str) -> bool:
    n = (name or "").lower()
    if not n:
        return False
    if n in _PROTECTED_EXACT:
        return True
    return any(p in n for p in _PROTECTED_PARTS)


def ram_trim_skip_names() -> set[str]:
    base = {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "dwm.exe",
        "explorer.exe",
    }
    base.update(_PROTECTED_EXACT)
    return base


def should_skip_ram_trim(name: str) -> bool:
    n = (name or "").lower()
    if n in ram_trim_skip_names():
        return True
    return is_protected_process(n)

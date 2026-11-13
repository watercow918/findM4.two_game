# -*- coding: utf-8 -*-
import asyncio
import pygame
import sys
import os
import io
import base64
import random
import math
import array
import gc
try:
    import wave          # 浏览器(wasm)里 audioop 可能缺失，缺了就不写 wav，用预置 ogg
except Exception:
    wave = None

# ===================== 基础配置 =====================
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
# ---- 手机端自动减负：检测到手机浏览器就降到 30 帧、关掉帧率数字 ----
IS_MOBILE = False
if sys.platform == "emscripten":
    try:
        import platform as _pf
        _ua = str(_pf.window.navigator.userAgent).lower()
        IS_MOBILE = any(k in _ua for k in ("mobile", "android", "iphone", "ipad"))
    except Exception:
        IS_MOBILE = False

# wasm 是单线程，手机跑 60 帧太吃力；dt 已按真实时间归一，降帧不会让游戏变慢
FPS = 30 if IS_MOBILE else 60
SHOW_FPS = not IS_MOBILE        # 手机上不显示右上角帧率数字
AUDIO_ENABLED = True    # 排错开关：改成 False 则完全不启动音频（用来确认噪音是不是音频引起）
_AUDIO_READY = sys.platform != "emscripten"   # 本地直接就绪，网页端等手势
pygame.init()
if sys.platform == "emscripten":
    # 浏览器硬性要求：音频必须由用户手势启动。
    # 页面一加载就 init 会让 wasm 音频卡进坏状态，全程出静电嗡鸣。
    # 所以先彻底关掉音频设备，等玩家第一次点击/触摸再开（见 ensure_audio）。
    try:
        pygame.mixer.quit()
    except Exception:
        pass
def _make_screen():
    """手机和网页上把 1280x720 的画布撑满屏幕。"""
    mobile = sys.platform == "emscripten" or any(
        k in os.environ for k in ("ANDROID_ARGUMENT", "ANDROID_STORAGE", "PYGBAG"))
    if not mobile:
        return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    if sys.platform == "emscripten":
        return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    try:
        return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SCALED | pygame.FULLSCREEN)
    except Exception:
        try:
            return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SCALED)
        except Exception:
            return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))


screen = _make_screen()
pygame.display.set_caption("找到M4")
clock = pygame.time.Clock()

WHITE = (255, 255, 255)
WHITE_FLOWER = (242, 250, 250)
LEAF_COLORS = [(160, 120, 70), (180, 140, 85), (145, 110, 60), (196, 158, 100)]
PLAYER_COLOR = (252, 245, 210)
PLAYER_INNER = (255, 255, 235)
TRUNK = (92, 74, 56)

player_radius = 22
player_speed = 4.5
PICK_RADIUS = 13

MAP_W = 2400
MAP_H = 1600

CELL = 112
WALL_T = 26
COLS = 20
ROWS = 13
OX = (MAP_W - COLS * CELL) // 2
OY = (MAP_H - ROWS * CELL) // 2

GRID = 20
GW = MAP_W // GRID
GH = MAP_H // GRID


# ===================== 字体 =====================
def _dir_candidates():
    """网页沙箱里 __file__ / cwd 不一定同一个，两个都试。"""
    out = []
    try:
        out.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    try:
        out.append(os.getcwd())
    except Exception:
        pass
    return out


def _find_asset(*parts):
    for d in _dir_candidates():
        p = os.path.join(d, *parts)
        if os.path.exists(p):
            return p
    return None


def get_font(size):
    bundled = _find_asset("assets", "font", "game_cjk.ttf")
    if bundled is None:
        bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font", "game_cjk.ttf")
    for p in [bundled, r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
              "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
              "/usr/share/fonts/truetype/SimHei.ttf",
              "/usr/share/fonts/truetype/arphic/uming.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            try:
                return pygame.font.Font(p, size)
            except Exception:
                continue
    return pygame.font.SysFont(None, size)


font_big = get_font(58)
font_mid = get_font(30)
font_small = get_font(20)
font_tiny = get_font(16)


# ===================== BGM（程序生成，不依赖外部音频文件） =====================
BGM_DIR = None
MUSIC_OK = False
_current_track = None

MUSIC = {
    "menu": {"drone": [(98.0, 0.16, 0.0), (147.0, 0.10, 1.1), (196.0, 0.05, 2.0)],
             "mel": [(2.0, 392.0, 0.05, 3.0), (7.0, 349.5, 0.04, 3.0), (12.0, 294.0, 0.05, 3.0)]},
    "东风草原": {"drone": [(110.0, 0.18, 0.0), (165.0, 0.11, 1.2), (220.0, 0.06, 2.4)],
               "mel": [(3.0, 330.0, 0.05, 2.5), (8.0, 392.0, 0.045, 2.5), (13.0, 262.0, 0.05, 2.5)]},
    "朝见湿地": {"drone": [(92.0, 0.17, 0.4), (138.0, 0.10, 1.6), (184.0, 0.06, 2.2)],
               "mel": [(2.5, 294.0, 0.05, 2.8), (9.0, 246.0, 0.045, 2.8), (13.5, 196.0, 0.05, 2.8)]},
    "源泉": {"drone": [(82.0, 0.17, 0.2), (123.0, 0.10, 1.4), (164.0, 0.06, 2.6)],
             "mel": [(4.0, 233.0, 0.045, 3.0), (10.0, 196.0, 0.04, 3.0)]},
    "漂浮木院": {"drone": [(73.5, 0.18, 0.0), (110.0, 0.11, 1.5), (147.0, 0.06, 2.6)],
                "mel": [(2.0, 261.6, 0.06, 2.2), (6.5, 220.0, 0.05, 2.2),
                        (10.0, 174.6, 0.055, 2.6), (13.5, 233.1, 0.045, 2.2)]},
    "地窖": {"drone": [(54.0, 0.20, 0.0), (81.0, 0.12, 1.4), (108.0, 0.05, 2.6)],
             "mel": [(2.0, 311.1, 0.05, 2.6), (7.5, 233.0, 0.05, 2.4),
                     (12.0, 174.6, 0.06, 3.0), (15.0, 277.0, 0.035, 1.8)]},
    "地下深处": {"drone": [(46.0, 0.22, 0.0), (69.0, 0.12, 1.2), (92.0, 0.05, 2.4)],
               "mel": [(3.0, 233.0, 0.04, 3.0), (9.0, 155.6, 0.04, 3.4)]},
    "boss": {"drone": [(58.0, 0.26, 0.0), (87.0, 0.12, 0.8), (116.0, 0.06, 1.6)],
             "mel": [(1.5, 174.6, 0.05, 2.2), (8.0, 146.8, 0.045, 2.6)]},
}
MUSIC_VOL = {"menu": 0.5, "东风草原": 0.45, "朝见湿地": 0.4, "源泉": 0.38,
             "漂浮木院": 0.42, "地窖": 0.5, "地下深处": 0.52, "boss": 0.55}
BGM_FILES = {"menu": "bgm_menu.wav", "东风草原": "bgm_grass.wav",
             "朝见湿地": "bgm_wetland.wav", "源泉": "bgm_spring.wav",
             "漂浮木院": "bgm_house.wav", "地窖": "bgm_cellar.wav",
             "地下深处": "bgm_depths.wav", "boss": "bgm_boss.wav"}


def _snap_freq(f, dur):
    return max(1.0, round(f * dur)) / dur


def synth_bgm(profile, dur=16.0, sr=22050):
    """低音持续音 + 极稀疏旋律音，全部按 16 秒对齐整数周期，循环无接缝。"""
    n = int(dur * sr)
    buf = [0.0] * n
    for (f, amp, ph) in profile["drone"]:
        w = 2.0 * math.pi * _snap_freq(f, dur) / sr
        for i in range(n):
            buf[i] += amp * math.sin(w * i + ph)
    for i in range(n):
        buf[i] *= 1.0 + 0.16 * math.sin(2.0 * math.pi * (3.0 / dur) * (i / sr))
    for (t0, f, amp, dec) in profile["mel"]:
        st = int(min(t0, max(0.0, dur - dec - 0.3)) * sr)
        ln = min(int(dec * sr), n - st)
        w = 2.0 * math.pi * f / sr
        for j in range(ln):
            env = math.exp(-3.2 * (j / sr) / dec)
            buf[st + j] += amp * env * (math.sin(w * j) + 0.35 * math.sin(2.0 * w * j + 0.7))
    peak = max(0.0001, max(abs(v) for v in buf))
    gain = 0.88 / peak
    return [v * gain for v in buf]


def _write_bgm(path, buf, sr=22050):
    if wave is None:
        return
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(array.array("h", [int(max(-1.0, min(1.0, v)) * 30000) for v in buf]).tobytes())
    w.close()


def _web_asset_path(name):
    """浏览器里优先读预置的 ogg，避免运行时用 wave 现合成（很慢）。没有就返回 None。"""
    base = os.path.splitext(name)[0]
    for ext in (".ogg", ".wav"):
        p = os.path.join(BGM_DIR, base + ext)
        if os.path.exists(p):
            return p
    return None


def _locate_bgm_dir():
    global BGM_DIR
    for d in _dir_candidates():
        c = os.path.join(d, "bgm_cache")
        try:
            if os.path.isdir(c) and (os.path.exists(os.path.join(c, "bgm_menu.ogg"))
                                     or os.path.exists(os.path.join(c, "bgm_menu.wav"))):
                BGM_DIR = c
                return True
        except Exception:
            pass
    return False


def init_music():
    """只定位音频目录。mixer 的真正启动交给 ensure_audio（等玩家手势）。"""
    global MUSIC_OK, BGM_DIR
    if not AUDIO_ENABLED:
        MUSIC_OK = False
        return
    if sys.platform == "emscripten":
        MUSIC_OK = _locate_bgm_dir()
        return
    try:
        pygame.mixer.quit()
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
    except Exception:
        MUSIC_OK = False
        return
    MUSIC_OK = True
    if not BGM_DIR:
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            cand = os.path.join(base, "bgm_cache")
            os.makedirs(cand, exist_ok=True)
        except Exception:
            import tempfile
            cand = os.path.join(tempfile.gettempdir(), "bgm_cache")
            try:
                os.makedirs(cand, exist_ok=True)
            except Exception:
                MUSIC_OK = False
                return
        BGM_DIR = cand


def ensure_audio():
    """玩家第一次点击/触摸后才真正打开音频设备。"""
    global MUSIC_OK, _AUDIO_READY, _current_track
    if _AUDIO_READY:
        return MUSIC_OK
    _AUDIO_READY = True
    if not AUDIO_ENABLED:
        MUSIC_OK = False
        return False
    if sys.platform != "emscripten":
        return MUSIC_OK
    try:
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=4096)
        pygame.mixer.init()
        _current_track = None      # 允许把当前曲目重新播一次
        MUSIC_OK = bool(BGM_DIR)
    except Exception:
        MUSIC_OK = False
    return MUSIC_OK


def play_music(key):
    """切图时换曲；同曲不重播。音频设备不可用时静默跳过。"""
    global _current_track
    if not _AUDIO_READY:
        return
    if key not in MUSIC or not MUSIC_OK:
        return
    if _current_track == key:
        return
    _current_track = key
    try:
        name = BGM_FILES.get(key, "bgm_other.wav")
        path = _web_asset_path(name)
        if path is None:
            path = os.path.join(BGM_DIR, name)
            if not os.path.exists(path):
                _write_bgm(path, synth_bgm(MUSIC[key]))
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(MUSIC_VOL.get(key, 0.4))
        pygame.mixer.music.play(-1)
    except Exception:
        pass


# ===================== 主题 =====================
THEMES = {
    "东风草原": {
        "ground": (118, 120, 88),
        "sky_top": (150, 132, 168),
        "sky_bottom": (238, 186, 140),
        "water": (74, 98, 104),
        "water_line": (110, 134, 134),
        "wall": (72, 95, 62),
        "wall_edge": (48, 66, 44),
        "tuft": (86, 112, 74),
        "grass_tuft": (104, 112, 82),
        "shore": (108, 104, 86),
        "mist": [],
        "kind": "maze",
        "sub": "黄昏的风穿过草叶",
        "clearings": 4,
        "extra_ponds": 2,
        "portals": [{"label": "朝见湿地", "target": "朝见湿地"}],
    },
    "朝见湿地": {
        "ground": (100, 110, 86),
        "sky_top": (126, 124, 160),
        "sky_bottom": (212, 174, 148),
        "water": (70, 94, 100),
        "water_line": (106, 130, 132),
        "wall": (94, 112, 78),
        "wall_edge": (64, 80, 54),
        "tuft": (122, 138, 96),
        "grass_tuft": (96, 112, 84),
        "shore": (96, 98, 82),
        "mist": [(380, 460, 300, 110), (1080, 620, 340, 120),
                 (1820, 480, 300, 100), (700, 1180, 320, 120)],
        "kind": "maze",
        "sub": "雾贴在皮肤上",
        "clearings": 4,
        "extra_ponds": 4,
        "portals": [{"label": "源泉", "target": "源泉"},
                    {"label": "东风草原", "target": "东风草原"}],
    },
    "源泉": {
        "kind": "water",
        "sky_top": (86, 96, 120),
        "sky_bottom": (158, 168, 168),
        "deep": (26, 46, 56),
        "shallow": (40, 66, 76),
        "water": (32, 54, 64),
        "water_hi": (78, 108, 118),
        "water_line": (96, 126, 134),
        "plank": (128, 104, 74),
        "plank_light": (156, 130, 96),
        "plank_line": (92, 72, 50),
        "post": (74, 58, 42),
        "lily": (86, 116, 84),
        "reed": (104, 122, 84),
        "mist": [(420, 380, 360, 130), (1500, 300, 320, 120),
                 (900, 1180, 380, 140), (1980, 980, 300, 110)],
        "sub": "水声很轻，像有人在下面呼吸",
        "portals": [{"label": "漂浮木院", "target": "漂浮木院", "style": "door"},
                    {"label": "朝见湿地", "target": "朝见湿地"}],
    },
    "漂浮木院": {
        "kind": "house",
        "sky_top": (58, 56, 62),
        "sky_bottom": (26, 26, 30),
        "floor": (88, 74, 58),
        "floor_line": (72, 60, 46),
        "stain": (58, 48, 38),
        "wall": (104, 84, 62),
        "wall_dark": (48, 38, 28),
        "wood": (120, 96, 68),
        "rug": (112, 78, 64),
        "rug_dim": (58, 48, 44),
        "door": (74, 54, 38),
        "threshold": (70, 58, 46),
        "mist": [],
        "sub": "门在你身后关上了",
        "portals": [{"label": "源泉", "target": "源泉", "style": "door"},
                    {"label": "地窖", "target": "地窖", "style": "hatch"}],
    },
    "地窖": {
        "kind": "cellar",
        "sky_top": (34, 30, 30),
        "sky_bottom": (8, 8, 9),
        "dirt": (52, 41, 31),
        "dirt_dark": (18, 14, 11),
        "floor": (60, 48, 37),
        "floor_light": (78, 63, 47),
        "rim": (14, 10, 8),
        "damp": (32, 38, 36),
        "metal": (94, 90, 82),
        "rust": (104, 62, 38),
        "mist": [],
        "sub": "泥土的味道盖住了别的",
        "portals": [{"label": "漂浮木院", "target": "漂浮木院", "style": "ladder"},
                    {"label": "地下深处", "target": "地下深处", "style": "stairs"}],
    },
    "地下深处": {
        "kind": "depths",
        "sky_top": (24, 21, 21),
        "sky_bottom": (4, 4, 5),
        "dirt": (44, 37, 31),
        "dirt_dark": (14, 12, 10),
        "floor": (58, 48, 39),
        "floor_light": (74, 61, 47),
        "rim": (11, 9, 7),
        "damp": (30, 35, 34),
        "metal": (88, 84, 76),
        "rust": (100, 58, 34),
        "mist": [],
        "sub": "越往下，回声越像有人在跟着",
        "portals": [{"label": "地窖", "target": "地窖", "style": "ladder"}],
    },
}


# ===================== 迷宫生成 =====================
def gen_maze(rng):
    E = [[False] * COLS for _ in range(ROWS)]
    S = [[False] * COLS for _ in range(ROWS)]
    vis = [[False] * COLS for _ in range(ROWS)]
    stack = [(0, 0)]
    vis[0][0] = True
    while stack:
        c, r = stack[-1]
        nbrs = []
        if c + 1 < COLS and not vis[r][c + 1]:
            nbrs.append(("E", c + 1, r))
        if c - 1 >= 0 and not vis[r][c - 1]:
            nbrs.append(("W", c - 1, r))
        if r + 1 < ROWS and not vis[r + 1][c]:
            nbrs.append(("S", c, r + 1))
        if r - 1 >= 0 and not vis[r - 1][c]:
            nbrs.append(("N", c, r - 1))
        if not nbrs:
            stack.pop()
            continue
        d, nc, nr = rng.choice(nbrs)
        if d == "E":
            E[r][c] = True
        elif d == "W":
            E[nr][nc] = True
        elif d == "S":
            S[r][c] = True
        else:
            S[nr][nc] = True
        vis[nr][nc] = True
        stack.append((nc, nr))

    for r in range(ROWS):
        for c in range(COLS):
            if c + 1 < COLS and not E[r][c] and rng.random() < 0.18:
                E[r][c] = True
            if r + 1 < ROWS and not S[r][c] and rng.random() < 0.18:
                S[r][c] = True
    return E, S


def cell_center(c, r):
    return OX + c * CELL + CELL // 2, OY + r * CELL + CELL // 2


def clearing_center(bc, br):
    return OX + (bc + 1) * CELL, OY + (br + 1) * CELL


def pick_clearings(rng, n, avoid_cell):
    """按象限铺开空地，保证至少有一块在出生点的对角区域（出口才够远）。"""
    hc = COLS // 2
    hr = ROWS // 2
    scx, scy = cell_center(*avoid_cell)
    quads = [(0, 0), (hc, 0), (0, hr), (hc, hr)]
    quads.sort(key=lambda q: -math.hypot(
        OX + (q[0] + hc // 2) * CELL - scx,
        OY + (q[1] + hr // 2) * CELL - scy))

    clears = []

    def far_enough(bc, br):
        for (x, y) in clears:
            if abs(x - bc) <= 2 and abs(y - br) <= 2:
                return False
        if abs(bc - avoid_cell[0]) < 3 and abs(br - avoid_cell[1]) < 3:
            return False
        return True

    for (qx, qy) in quads:
        if len(clears) >= n:
            break
        for _t in range(150):
            bc = rng.randint(qx, min(qx + hc - 2, COLS - 2))
            br = rng.randint(qy, min(qy + hr - 2, ROWS - 2))
            if far_enough(bc, br):
                clears.append((bc, br))
                break

    tries = 0
    while len(clears) < n and tries < 800:
        tries += 1
        bc = rng.randint(0, COLS - 2)
        br = rng.randint(0, ROWS - 2)
        if far_enough(bc, br):
            clears.append((bc, br))
    return clears


def build_walls(E, S):
    obs = []
    obs.append(pygame.Rect(OX - WALL_T, OY - WALL_T, COLS * CELL + 2 * WALL_T, WALL_T))
    obs.append(pygame.Rect(OX - WALL_T, OY + ROWS * CELL, COLS * CELL + 2 * WALL_T, WALL_T))
    obs.append(pygame.Rect(OX - WALL_T, OY - WALL_T, WALL_T, ROWS * CELL + 2 * WALL_T))
    obs.append(pygame.Rect(OX + COLS * CELL, OY - WALL_T, WALL_T, ROWS * CELL + 2 * WALL_T))
    for r in range(ROWS):
        for c in range(COLS - 1):
            if not E[r][c]:
                obs.append(pygame.Rect(OX + (c + 1) * CELL - WALL_T // 2,
                                       OY + r * CELL - WALL_T // 2,
                                       WALL_T, CELL + WALL_T))
    for r in range(ROWS - 1):
        for c in range(COLS):
            if not S[r][c]:
                obs.append(pygame.Rect(OX + c * CELL - WALL_T // 2,
                                       OY + (r + 1) * CELL - WALL_T // 2,
                                       CELL + WALL_T, WALL_T))
    return obs


def degree(E, S, c, r):
    d = 0
    if c + 1 < COLS and E[r][c]:
        d += 1
    if c - 1 >= 0 and E[r][c - 1]:
        d += 1
    if r + 1 < ROWS and S[r][c]:
        d += 1
    if r - 1 >= 0 and S[r - 1][c]:
        d += 1
    return d


# ===================== 通行格网（20px，精确判定） =====================
def build_free_grid(blockers):
    BS = 100
    buckets = {}
    for b in blockers:
        for bx in range(b.left // BS, b.right // BS + 1):
            for by in range(b.top // BS, b.bottom // BS + 1):
                buckets.setdefault((bx, by), []).append(b)

    free = [[True] * GH for _ in range(GW)]
    for gx in range(GW):
        cx = gx * GRID + GRID // 2
        L = cx - player_radius
        R = cx + player_radius
        for gy in range(GH):
            cy = gy * GRID + GRID // 2
            T = cy - player_radius
            B = cy + player_radius
            hit = False
            for bx in range(L // BS, R // BS + 1):
                for by in range(T // BS, B // BS + 1):
                    for b in buckets.get((bx, by), ()):
                        if L < b.right and b.left < R and T < b.bottom and b.top < B:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
            if hit:
                free[gx][gy] = False
    return free


def bfs_dist(free, start_xy):
    sx = min(GW - 1, max(0, int(start_xy[0]) // GRID))
    sy = min(GH - 1, max(0, int(start_xy[1]) // GRID))
    if not free[sx][sy]:
        hit = False
        for rad in range(1, 3):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < GW and 0 <= ny < GH and free[nx][ny]:
                        sx, sy = nx, ny
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
    dist = {}
    if not free[sx][sy]:
        return dist
    dist[(sx, sy)] = 0
    queue = [(sx, sy)]
    head = 0
    while head < len(queue):
        cx, cy = queue[head]
        head += 1
        d = dist[(cx, cy)]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < GW and 0 <= ny < GH and free[nx][ny]:
                if (nx, ny) not in dist:
                    dist[(nx, ny)] = d + 1
                    queue.append((nx, ny))
    return dist


def free_cell_center_near(x, y, free, blockers, max_r=120):
    """把坐标吸附到最近一个真正站得住的格心，保证寻路起点可信。"""
    gx0 = min(GW - 1, max(0, int(x) // GRID))
    gy0 = min(GH - 1, max(0, int(y) // GRID))
    rad_max = int(max_r // GRID) + 1
    for rad in range(0, rad_max + 1):
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                gx, gy = gx0 + dx, gy0 + dy
                if not (0 <= gx < GW and 0 <= gy < GH):
                    continue
                if not free[gx][gy]:
                    continue
                cx = gx * GRID + GRID // 2
                cy = gy * GRID + GRID // 2
                if is_free_spot(cx, cy, player_radius + 2, blockers):
                    return (cx, cy)
    return None


def cell_of(x, y):
    return (min(GW - 1, max(0, int(x) // GRID)),
            min(GH - 1, max(0, int(y) // GRID)))


def reach_ok(x, y, dist):
    gx = min(GW - 1, max(0, int(x) // GRID))
    gy = min(GH - 1, max(0, int(y) // GRID))
    if (gx, gy) not in dist:
        return False
    cnt = 1
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
        if (gx + dx, gy + dy) in dist:
            cnt += 1
    return cnt >= 5


def is_free_spot(x, y, r, blockers):
    rect = pygame.Rect(int(x - r), int(y - r), int(r * 2), int(r * 2))
    if rect.left < 0 or rect.top < 0 or rect.right > MAP_W or rect.bottom > MAP_H:
        return False
    for b in blockers:
        if rect.colliderect(b):
            return False
    return True


def find_free_spot(x, y, r, blockers, avoid=()):
    x, y = int(x), int(y)

    def ok(nx, ny):
        if not is_free_spot(nx, ny, r, blockers):
            return False
        probe = pygame.Rect(nx - r, ny - r, r * 2, r * 2)
        for a in avoid:
            if probe.colliderect(a):
                return False
        return True

    if ok(x, y):
        return (x, y)
    for radius in range(12, 700, 8):
        for deg in range(0, 360, 8):
            nx = int(x + radius * math.cos(math.radians(deg)))
            ny = int(y + radius * math.sin(math.radians(deg)))
            if ok(nx, ny):
                return (nx, ny)
    return None


# ===================== 落叶 =====================
class Leaf:
    def __init__(self, key):
        self.key = key
        self.reset(random.randint(-100, MAP_H))

    def reset(self, y=None):
        self.x = random.randint(0, MAP_W)
        self.y = y if y is not None else -20
        self.vx = random.uniform(-0.7, 0.5)
        self.vy = random.uniform(0.4, 1.0)
        self.color = random.choice(LEAF_COLORS)
        self.size = random.randint(4, 9)
        self.phase = random.uniform(0, 6.28)
        self.sway = random.uniform(0.3, 1.0)

    def update(self):
        self.phase += 0.02
        self.x += self.vx + math.sin(self.phase) * self.sway
        self.y += self.vy
        if self.y > MAP_H + 30 or self.x < -60 or self.x > MAP_W + 60:
            self.reset()

    def draw(self, surf, ox, oy):
        sx, sy = int(self.x - ox), int(self.y - oy)
        if -20 <= sx <= SCREEN_WIDTH + 20 and -20 <= sy <= SCREEN_HEIGHT + 20:
            pygame.draw.circle(surf, self.color, (sx, sy), self.size, 1)


# ===================== 源泉：水上木桥关卡 =====================
W_COLS = 10
W_ROWS = 7
W_SPACE = 236
W_DECK = 96
W_BRIDGE = 84
W_ISLAND_W = 268
W_ISLAND_H = 208
W_ISLAND_DOOR_W = 360
W_ISLAND_DOOR_H = 280
W_TILE = 12
WX0 = (MAP_W - (W_COLS - 1) * W_SPACE) // 2
WY0 = (MAP_H - (W_ROWS - 1) * W_SPACE) // 2


def w_node(c, r):
    return WX0 + c * W_SPACE, WY0 + r * W_SPACE


def w_degree(E, S, c, r):
    d = 0
    if c + 1 < W_COLS and E[r][c]:
        d += 1
    if c - 1 >= 0 and E[r][c - 1]:
        d += 1
    if r + 1 < W_ROWS and S[r][c]:
        d += 1
    if r - 1 >= 0 and S[r - 1][c]:
        d += 1
    return d


def gen_net(rng, cols, rows, loop_chance):
    """在节点上长出一棵树，节点之间用木桥连接，再打通少量环。"""
    E = [[False] * cols for _ in range(rows)]
    S = [[False] * cols for _ in range(rows)]
    vis = [[False] * cols for _ in range(rows)]
    stack = [(0, 0)]
    vis[0][0] = True
    while stack:
        c, r = stack[-1]
        nbrs = []
        if c + 1 < cols and not vis[r][c + 1]:
            nbrs.append(("E", c + 1, r))
        if c - 1 >= 0 and not vis[r][c - 1]:
            nbrs.append(("W", c - 1, r))
        if r + 1 < rows and not vis[r + 1][c]:
            nbrs.append(("S", c, r + 1))
        if r - 1 >= 0 and not vis[r - 1][c]:
            nbrs.append(("N", c, r - 1))
        if not nbrs:
            stack.pop()
            continue
        d, nc, nr = rng.choice(nbrs)
        if d == "E":
            E[r][c] = True
        elif d == "W":
            E[nr][nc] = True
        elif d == "S":
            S[r][c] = True
        else:
            S[nr][nc] = True
        vis[nr][nc] = True
        stack.append((nc, nr))

    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols and not E[r][c] and rng.random() < loop_chance:
                E[r][c] = True
            if r + 1 < rows and not S[r][c] and rng.random() < loop_chance:
                S[r][c] = True
    return E, S


def merge_blocked_runs(mask, cols, rows, tile):
    """把非通行格按行合并成尽量少的矩形，碰撞检测才不会卡。"""
    rects = []
    for r in range(rows):
        c = 0
        while c < cols:
            if mask[r][c]:
                s = c
                while c < cols and mask[r][c]:
                    c += 1
                rects.append(pygame.Rect(s * tile, r * tile, (c - s) * tile, tile))
            else:
                c += 1
    return rects


def create_level_water(theme_key, arrive_from=None):
    th = THEMES[theme_key]
    rng = random.Random()

    E, S = gen_net(rng, W_COLS, W_ROWS, 0.10)
    spawn_node = (0, W_ROWS - 1)
    sx, sy = w_node(*spawn_node)

    all_nodes = [(c, r) for r in range(W_ROWS) for c in range(W_COLS)]
    all_nodes.sort(key=lambda nr: -math.hypot(w_node(*nr)[0] - sx,
                                              w_node(*nr)[1] - sy))

    portal_nodes = []
    for nr in all_nodes:
        if len(portal_nodes) >= len(th["portals"]):
            break
        cx0, cy0 = w_node(*nr)
        if math.hypot(cx0 - sx, cy0 - sy) < 700:
            continue
        pstyle = th["portals"][len(portal_nodes)].get("style")
        if pstyle == "door" and not (200 <= cx0 <= MAP_W - 200 and 170 <= cy0 <= MAP_H - 170):
            continue
        if any(abs(nr[0] - p[0]) + abs(nr[1] - p[1]) < 3 for p in portal_nodes):
            continue
        portal_nodes.append(nr)

    # ---------- 木台与木桥 ----------
    decks = []
    half = {}
    for (c, r) in all_nodes:
        cx, cy = w_node(c, r)
        if (c, r) in portal_nodes:
            idx = portal_nodes.index((c, r))
            style = th["portals"][idx].get("style") if idx < len(th["portals"]) else None
            if style == "door":
                w, h = W_ISLAND_DOOR_W, W_ISLAND_DOOR_H
            else:
                w, h = W_ISLAND_W, W_ISLAND_H
        else:
            w, h = W_DECK, W_DECK
        half[(c, r)] = (w // 2, h // 2)
        decks.append(pygame.Rect(cx - w // 2, cy - h // 2, w, h))

    bridges = []
    for r in range(W_ROWS):
        for c in range(W_COLS):
            if c + 1 < W_COLS and E[r][c]:
                x1 = w_node(c, r)[0] + half[(c, r)][0] - 12
                x2 = w_node(c + 1, r)[0] - half[(c + 1, r)][0] + 12
                cy = w_node(c, r)[1]
                if x2 > x1:
                    bridges.append(pygame.Rect(x1, cy - W_BRIDGE // 2, x2 - x1, W_BRIDGE))
            if r + 1 < W_ROWS and S[r][c]:
                y1 = w_node(c, r)[1] + half[(c, r)][1] - 12
                y2 = w_node(c, r + 1)[1] - half[(c, r + 1)][1] + 12
                cx = w_node(c, r)[0]
                if y2 > y1:
                    bridges.append(pygame.Rect(cx - W_BRIDGE // 2, y1, W_BRIDGE, y2 - y1))

    # ---------- 水 = 除木台木桥之外的一切 ----------
    MC = MAP_W // W_TILE
    MR = MAP_H // W_TILE
    blocked = [[True] * MC for _ in range(MR)]

    def clear_walk(rc):
        for gx in range(max(0, rc.left // W_TILE - 1), min(MC, rc.right // W_TILE + 2)):
            px = gx * W_TILE + W_TILE // 2
            if not (rc.left <= px < rc.right):
                continue
            for gy in range(max(0, rc.top // W_TILE - 1), min(MR, rc.bottom // W_TILE + 2)):
                py = gy * W_TILE + W_TILE // 2
                if rc.top <= py < rc.bottom:
                    blocked[gy][gx] = False

    for rc in decks + bridges:
        clear_walk(rc)

    blockers = merge_blocked_runs(blocked, MC, MR, W_TILE)
    free = build_free_grid(blockers)

    spawn_xy = (sx, sy)
    snap = free_cell_center_near(sx, sy, free, blockers, 60)
    if snap:
        spawn_xy = snap
    dist = bfs_dist(free, spawn_xy)

    # ---------- 传送门放在最远的水上平台 ----------
    portals = []
    for idx, pdef in enumerate(th["portals"]):
        if idx < len(portal_nodes):
            cx, cy = w_node(*portal_nodes[idx])
        else:
            cx, cy = w_node(*portal_nodes[0]) if portal_nodes else (sx, sy)
        if pdef.get("style") == "door":
            pad = pygame.Rect(0, 0, 240, 160)
        else:
            pad = pygame.Rect(0, 0, 120, 98)
        pad.center = (int(cx), int(cy))
        portals.append({"rect": pad, "label": pdef["label"], "target": pdef["target"],
                        "style": pdef.get("style"), "next": pdef.get("next")})

    # 门离出生点太近就换更远的平台
    for p in portals:
        r = p["rect"]
        if math.hypot(r.centerx - spawn_xy[0], r.centery - spawn_xy[1]) >= 650:
            continue
        for nr in all_nodes:
            cx, cy = w_node(*nr)
            if math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) < 650:
                continue
            if any(q["rect"].inflate(90, 90).collidepoint(cx, cy)
                   for q in portals if q is not p):
                continue
            r.center = (cx, cy)
            break

    # ---------- 白花：最远且可达的死胡同木台 ----------
    pad_zone = [p["rect"].inflate(80, 80) for p in portals]
    best = None
    best_d = -1
    for nr in all_nodes:
        c, r = nr
        if nr == spawn_node or nr in portal_nodes:
            continue
        if w_degree(E, S, c, r) != 1:
            continue
        cx, cy = w_node(c, r)
        if any(z.collidepoint(cx, cy) for z in pad_zone):
            continue
        d = dist.get(cell_of(cx, cy), -1)
        if d < 0:
            continue
        if d > best_d:
            best_d = d
            best = nr
    if best is None:
        for nr in all_nodes:
            if nr in portal_nodes:
                continue
            cx, cy = w_node(*nr)
            d = dist.get(cell_of(cx, cy), -1)
            if d > best_d:
                best_d = d
                best = nr
    if best is None:
        best = spawn_node
    flower_anchor = w_node(*best)

    flower_xy = None
    jitter = (flower_anchor[0] + rng.randint(-10, 10),
              flower_anchor[1] + rng.randint(-10, 10))
    for cand in (jitter, flower_anchor):
        if cell_of(cand[0], cand[1]) in dist and \
           is_free_spot(cand[0], cand[1], PICK_RADIUS + 3, blockers):
            flower_xy = (int(cand[0]), int(cand[1]))
            break
    if flower_xy is None:
        snap = free_cell_center_near(flower_anchor[0], flower_anchor[1], free, blockers, 120)
        flower_xy = snap if snap else (int(flower_anchor[0]), int(flower_anchor[1]))

    flower_pos = [flower_xy]

    # ---------- 到达点：站在返回门所在的大平台上，避开门的触发区 ----------
    if arrive_from:
        pad = None
        for p in portals:
            if p["target"] == arrive_from:
                pad = p["rect"]
                break
        if pad is None and portals:
            pad = portals[0]["rect"]
        arrive = None
        zones = [q["rect"].inflate(34, 34) for q in portals]
        if pad is not None:
            for gaps in (104, 118, 132, 146, 90):
                for dx, dy in ((gaps, 0), (-gaps, 0), (0, gaps), (0, -gaps),
                               (gaps, gaps), (-gaps, -gaps), (gaps, -gaps), (-gaps, gaps)):
                    snap = free_cell_center_near(pad.centerx + dx, pad.centery + dy,
                                                 free, blockers, 40)
                    if snap is None:
                        continue
                    ax, ay = snap
                    box = pygame.Rect(ax - 26, ay - 26, 52, 52)
                    if any(box.colliderect(z) for z in zones):
                        continue
                    d2 = bfs_dist(free, (ax, ay))
                    if cell_of(flower_xy[0], flower_xy[1]) not in d2:
                        continue
                    arrive = (ax, ay)
                    break
                if arrive:
                    break
        if arrive is None:
            arrive = spawn_xy
        spawn_xy = arrive

    # 白花不能落在起点边上
    if math.hypot(flower_xy[0] - spawn_xy[0], flower_xy[1] - spawn_xy[1]) < 700:
        d3 = bfs_dist(free, spawn_xy)
        for (gx, gy), _d in sorted(d3.items(), key=lambda kv: -kv[1]):
            cx, cy = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) < 700:
                continue
            if any(z.collidepoint(cx, cy) for z in pad_zone):
                continue
            if not is_free_spot(cx, cy, PICK_RADIUS + 3, blockers):
                continue
            flower_xy = (cx, cy)
            flower_pos[0] = flower_xy
            break

    # ---------- 水面装饰 ----------
    lilies = []
    for _ in range(120):
        lx = rng.randint(60, MAP_W - 60)
        ly = rng.randint(60, MAP_H - 60)
        if not is_free_spot(lx, ly, 34, blockers):
            lilies.append((lx, ly, rng.randint(10, 20)))
    reeds = []
    for _ in range(90):
        rx = rng.randint(40, MAP_W - 40)
        ry = rng.randint(40, MAP_H - 40)
        if not is_free_spot(rx, ry, 18, blockers):
            reeds.append((rx, ry))

    return {
        "kind": "water",
        "theme": theme_key,
        "E": E, "S": S,
        "walls": blockers, "ponds": [], "blockers": blockers,
        "decks": decks, "bridges": bridges,
        "lilies": lilies, "reeds": reeds,
        "free": free, "dist": dist,
        "portals": portals,
        "flowers": flower_pos,
        "collected": [False] * len(flower_pos),
        "pick_fx": [],
        "trees": [], "benches": [],
        "px": spawn_xy[0], "py": spawn_xy[1],
        "armed": [False if (arrive_from and p["target"] == arrive_from) else True
                  for p in portals],
        "leaves": [Leaf(theme_key) for _ in range(70)],
        "surface": None,
        "sky": None,
    }


# ===================== 漂浮木院：木屋内部 =====================
HOUSE_T = 28
HOUSE_DOOR_W = 150
ROOM_DOOR_W = 120
HOUSE_RECT = pygame.Rect(180, 150, 2040, 1300)
LIGHT_R = 260
_light_mask = None


def get_light_mask():
    """中心全亮、边缘全暗的圆形遮罩，用减法从黑幕上挖出视野。"""
    global _light_mask
    if _light_mask is None:
        m = pygame.Surface((LIGHT_R * 2, LIGHT_R * 2), pygame.SRCALPHA)
        for rr in range(LIGHT_R, 0, -3):
            a = int(255 * (1.0 - rr / LIGHT_R) ** 0.85)
            pygame.draw.circle(m, (0, 0, 0, a), (LIGHT_R, LIGHT_R), rr)
        _light_mask = m
    return _light_mask


def _segments(lo, hi, forbids, margin):
    """在 [lo, hi] 里挖掉已有门洞的位置，返回还能落墙的区间。"""
    segs = [(lo, hi)]
    for (f0, f1) in forbids:
        a, b = f0 - margin, f1 + margin
        out = []
        for (s0, s1) in segs:
            if b <= s0 or a >= s1:
                out.append((s0, s1))
            else:
                if a > s0:
                    out.append((s0, a))
                if b < s1:
                    out.append((b, s1))
        segs = out
    return [(s0, s1) for (s0, s1) in segs if s1 - s0 >= 60]


def _room_split(rect, depth, rng, rooms, walls, doors, forbid_x=(), forbid_y=()):
    """递归切房间。forbid_x / forbid_y 记录这一侧已有门洞的位置，
    新墙不能压上去，否则门洞被夹细，整排房间会封死。"""
    min_w = 300
    min_h = 250
    can_v = rect.w >= min_w * 2 + HOUSE_T
    can_h = rect.h >= min_h * 2 + HOUSE_T
    if depth <= 0 or (not can_v and not can_h):
        rooms.append(rect.copy())
        return

    if not can_v:
        order = ["h"]
    elif not can_h:
        order = ["v"]
    else:
        order = ["v", "h"] if rng.random() < 0.6 else ["h", "v"]

    for d in order:
        if d == "v":
            xs = _segments(rect.left + min_w, rect.right - min_w, forbid_x, 95)
            gs = _segments(rect.top + 110, rect.bottom - 110, forbid_y, 95)
            if not xs or not gs:
                continue
            x = rng.randint(*rng.choice(xs))
            g = rng.randint(*rng.choice(gs))
            top_end = g - ROOM_DOOR_W // 2
            bot_start = g + ROOM_DOOR_W // 2
            if top_end > rect.top:
                walls.append(pygame.Rect(x - HOUSE_T // 2, rect.top, HOUSE_T, top_end - rect.top))
            if rect.bottom > bot_start:
                walls.append(pygame.Rect(x - HOUSE_T // 2, bot_start,
                                         HOUSE_T, rect.bottom - bot_start))
            doors.append(pygame.Rect(x - HOUSE_T // 2 - 4, top_end, HOUSE_T + 8, ROOM_DOOR_W))
            _room_split(pygame.Rect(rect.left, rect.top, x - HOUSE_T // 2 - rect.left, rect.h),
                        depth - 1, rng, rooms, walls, doors, forbid_x, forbid_y + ((g, g),))
            _room_split(pygame.Rect(x + HOUSE_T // 2, rect.top,
                                    rect.right - (x + HOUSE_T // 2), rect.h),
                        depth - 1, rng, rooms, walls, doors, forbid_x, forbid_y + ((g, g),))
            return
        else:
            ys = _segments(rect.top + min_h, rect.bottom - min_h, forbid_y, 95)
            gs = _segments(rect.left + 110, rect.right - 110, forbid_x, 95)
            if not ys or not gs:
                continue
            y = rng.randint(*rng.choice(ys))
            g = rng.randint(*rng.choice(gs))
            left_end = g - ROOM_DOOR_W // 2
            right_start = g + ROOM_DOOR_W // 2
            if left_end > rect.left:
                walls.append(pygame.Rect(rect.left, y - HOUSE_T // 2,
                                         left_end - rect.left, HOUSE_T))
            if rect.right > right_start:
                walls.append(pygame.Rect(right_start, y - HOUSE_T // 2,
                                         rect.right - right_start, HOUSE_T))
            doors.append(pygame.Rect(left_end, y - HOUSE_T // 2 - 4, ROOM_DOOR_W, HOUSE_T + 8))
            _room_split(pygame.Rect(rect.left, rect.top, rect.w, y - HOUSE_T // 2 - rect.top),
                        depth - 1, rng, rooms, walls, doors, forbid_x + ((g, g),), forbid_y)
            _room_split(pygame.Rect(rect.left, y + HOUSE_T // 2, rect.w,
                                    rect.bottom - (y + HOUSE_T // 2)),
                        depth - 1, rng, rooms, walls, doors, forbid_x + ((g, g),), forbid_y)
            return

    rooms.append(rect.copy())


def create_level_house(theme_key, arrive_from=None):
    th = THEMES[theme_key]
    rng = random.Random()

    h = HOUSE_RECT
    rooms_raw, walls, doors = [], [], []
    _room_split(pygame.Rect(h.left, h.top, h.w, h.h), 4, rng, rooms_raw, walls, doors)

    outer = [
        pygame.Rect(h.left - HOUSE_T, h.top - HOUSE_T, h.w + 2 * HOUSE_T, HOUSE_T),
        pygame.Rect(h.left - HOUSE_T, h.top - HOUSE_T, HOUSE_T, h.h + 2 * HOUSE_T),
        pygame.Rect(h.right, h.top - HOUSE_T, HOUSE_T, h.h + 2 * HOUSE_T),
    ]
    dl = h.centerx - HOUSE_DOOR_W // 2
    dr = h.centerx + HOUSE_DOOR_W // 2
    outer.append(pygame.Rect(h.left - HOUSE_T, h.bottom, dl - (h.left - HOUSE_T), HOUSE_T))
    outer.append(pygame.Rect(dr, h.bottom, (h.right + HOUSE_T) - dr, HOUSE_T))
    outer.append(pygame.Rect(dl, h.bottom, HOUSE_DOOR_W, HOUSE_T))   # 大门是关着的
    walls.extend(outer)

    entry_room = None
    for room in rooms_raw:
        if room.collidepoint(h.centerx, h.bottom - 90):
            entry_room = room
            break
    if entry_room is None:
        entry_room = min(rooms_raw,
                         key=lambda r: abs(r.centerx - h.centerx) + abs(r.bottom - h.bottom))

    rinfo = []
    for room in rooms_raw:
        rinfo.append({"rect": room, "lit": rng.random() > 0.42, "props": [], "lamps": []})
    for ri in rinfo:
        if ri["rect"] is entry_room:
            ri["lit"] = True

    dim_list = [ri for ri in rinfo if not ri["lit"]]
    guard = 0
    while len(dim_list) < 3 and guard < 20:
        guard += 1
        pool = [ri for ri in rinfo if ri["lit"] and ri["rect"] is not entry_room]
        if not pool:
            break
        rng.choice(pool)["lit"] = False
        dim_list = [ri for ri in rinfo if not ri["lit"]]

    door_zone = [pygame.Rect(dl - 30, h.bottom - 210, HOUSE_DOOR_W + 60, 210)]

    props_block = []
    for ri in rinfo:
        r = ri["rect"]
        for _k in range(rng.randint(1, 2)):
            if r.w < 260 or r.h < 240:
                break
            pw = rng.randint(96, 132)
            ph = rng.randint(56, 72)
            px0 = rng.randint(r.left + 100, max(r.left + 100, r.right - 100 - pw))
            py0 = rng.randint(r.top + 100, max(r.top + 100, r.bottom - 110 - ph))
            rc = pygame.Rect(px0, py0, pw, ph)
            if any(z.inflate(40, 40).colliderect(rc) for z in door_zone):
                continue
            ri["props"].append(("table", rc))
            props_block.append(rc)
        if rng.random() < 0.45 and r.w > 300 and r.h > 280:
            cs = rng.randint(54, 74)
            cx0 = rng.randint(r.left + 90, max(r.left + 90, r.right - 90 - cs))
            cy0 = rng.randint(r.top + 90, max(r.top + 90, r.bottom - 100 - cs))
            rc = pygame.Rect(cx0, cy0, cs, cs)
            if not any(z.inflate(40, 40).colliderect(rc) for z in door_zone) and \
               not any(q.colliderect(rc.inflate(20, 20)) for q in props_block):
                ri["props"].append(("crate", rc))
                props_block.append(rc)
        if rng.random() < 0.6 and r.w > 240:
            ri["props"].append(("chair", (rng.randint(r.left + 80, max(r.left + 80, r.right - 110)),
                                          rng.randint(r.top + 80, max(r.top + 80, r.bottom - 110)))))
        if ri["lit"]:
            ri["lamps"].append((r.centerx + rng.randint(-40, 40), r.top + rng.randint(50, 90)))
        else:
            if rng.random() < 0.5:
                ri["props"].append(("cobweb", (r.left, r.top)))

    blockers = walls + props_block
    free = build_free_grid(blockers)

    spawn_xy = free_cell_center_near(h.centerx, h.bottom - 170, free, blockers, 200)
    if spawn_xy is None:
        spawn_xy = (h.centerx, h.bottom - 170)
    dist = bfs_dist(free, spawn_xy)

    # 家具把房间之间堵死就整体撤掉家具重算
    if any(cell_of(ri["rect"].centerx, ri["rect"].centery) not in dist for ri in rinfo):
        for ri in rinfo:
            ri["props"] = [p for p in ri["props"] if p[0] not in ("table", "crate")]
            ri["lamps"] = []
        for ri in rinfo:
            if ri["lit"]:
                ri["lamps"].append((ri["rect"].centerx, ri["rect"].top + 70))
        blockers = walls
        free = build_free_grid(blockers)
        spawn_xy = free_cell_center_near(h.centerx, h.bottom - 170, free, blockers, 200)
        if spawn_xy is None:
            spawn_xy = (h.centerx, h.bottom - 170)
        dist = bfs_dist(free, spawn_xy)

    # 大门（回源泉）
    door_pad = pygame.Rect(0, 0, 116, 96)
    door_pad.center = (h.centerx, h.bottom - 78)
    if not is_free_spot(door_pad.centerx, door_pad.centery, 56, blockers):
        pos = find_free_spot(door_pad.centerx, door_pad.centery, 56, blockers)
        if pos:
            door_pad.center = pos

    # 地窖：离入口最远的那间暗室，取它最远的角落
    cellar_room = None
    best_score = -1e9
    for ri in rinfo:
        if ri["lit"] or ri["rect"] is entry_room:
            continue
        r = ri["rect"]
        if r.w < 240 or r.h < 220:
            continue
        score = math.hypot(r.centerx - spawn_xy[0], r.centery - spawn_xy[1])
        if score > best_score:
            best_score = score
            cellar_room = ri

    hatch_pad = None
    if cellar_room is not None:
        r = cellar_room["rect"]
        corners = [(r.left + 96, r.top + 96), (r.right - 96, r.top + 96),
                   (r.left + 96, r.bottom - 96), (r.right - 96, r.bottom - 96)]
        corners.sort(key=lambda p: -math.hypot(p[0] - spawn_xy[0], p[1] - spawn_xy[1]))
        for cx0, cy0 in corners:
            pad = pygame.Rect(0, 0, 116, 96)
            pad.center = (int(cx0), int(cy0))
            if not is_free_spot(pad.centerx, pad.centery, 58, blockers):
                continue
            if pad.inflate(80, 80).colliderect(door_pad):
                continue
            if math.hypot(cx0 - spawn_xy[0], cy0 - spawn_xy[1]) < 340:
                continue
            if reach_ok(pad.centerx, pad.centery, dist):
                hatch_pad = pad
                break
    if hatch_pad is None:
        for (gx, gy), _dd in sorted(dist.items(), key=lambda kv: -kv[1]):
            cx0, cy0 = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            pad = pygame.Rect(0, 0, 116, 96)
            pad.center = (cx0, cy0)
            if pad.inflate(90, 90).colliderect(door_pad):
                continue
            if math.hypot(cx0 - spawn_xy[0], cy0 - spawn_xy[1]) < 340:
                continue
            if is_free_spot(cx0, cy0, 58, blockers) and reach_ok(cx0, cy0, dist):
                hatch_pad = pad
                break
    if hatch_pad is None:
        hatch_pad = pygame.Rect(0, 0, 116, 96)
        hatch_pad.center = spawn_xy

    # 白花：暗室角落，离出生点 700px 以上
    flower_xy = None
    flower_rooms = [ri for ri in rinfo if not ri["lit"] and ri["rect"] is not entry_room]
    if not flower_rooms:
        flower_rooms = [ri for ri in rinfo if ri["rect"] is not entry_room] or rinfo
    cands = []
    for ri in flower_rooms:
        r = ri["rect"]
        for (bx, by) in ((r.left + 88, r.top + 88), (r.right - 88, r.top + 88),
                         (r.left + 88, r.bottom - 88), (r.right - 88, r.bottom - 88)):
            cands.append((bx, by))
    cands = [c for c in cands
             if math.hypot(c[0] - spawn_xy[0], c[1] - spawn_xy[1]) >= 700
             and is_free_spot(c[0], c[1], PICK_RADIUS + 3, blockers)
             and cell_of(c[0], c[1]) in dist
             and not hatch_pad.inflate(60, 60).collidepoint(c)
             and not door_pad.inflate(60, 60).collidepoint(c)]
    if cands:
        flower_xy = max(cands, key=lambda c: dist.get(cell_of(c[0], c[1]), 0))
    if flower_xy is None:
        for (gx, gy), _dd in sorted(dist.items(), key=lambda kv: -kv[1]):
            cx0, cy0 = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if math.hypot(cx0 - spawn_xy[0], cy0 - spawn_xy[1]) < 700:
                continue
            if not is_free_spot(cx0, cy0, PICK_RADIUS + 3, blockers):
                continue
            flower_xy = (cx0, cy0)
            break
    if flower_xy is None:
        flower_xy = (int(spawn_xy[0]), int(spawn_xy[1]))
    flower_pos = [(int(flower_xy[0]), int(flower_xy[1]))]

    portals = []
    for pdef in th["portals"]:
        pad = door_pad if pdef.get("style") == "door" else hatch_pad
        portals.append({"rect": pad, "label": pdef["label"], "target": pdef["target"],
                        "style": pdef.get("style"), "next": pdef.get("next")})

    if arrive_from:
        pad = door_pad
        for p in portals:
            if p["target"] == arrive_from:
                pad = p["rect"]
        zones = [q["rect"].inflate(36, 36) for q in portals]
        arrive = None
        for gaps in (150, 185, 220):
            for dx, dy in ((0, -gaps), (-gaps, -40), (gaps, -40), (-gaps, 40), (gaps, 40)):
                snap = free_cell_center_near(pad.centerx + dx, pad.centery + dy,
                                             free, blockers, 60)
                if snap is None:
                    continue
                ax, ay = snap
                box = pygame.Rect(ax - 26, ay - 26, 52, 52)
                if any(box.colliderect(z) for z in zones):
                    continue
                d2 = bfs_dist(free, (ax, ay))
                if cell_of(flower_pos[0][0], flower_pos[0][1]) not in d2:
                    continue
                arrive = (ax, ay)
                break
            if arrive:
                break
        if arrive:
            spawn_xy = arrive

    # 落点定下来再确认一次白花距离（出生点可能被回程门拉近了）
    if math.hypot(flower_pos[0][0] - spawn_xy[0],
                  flower_pos[0][1] - spawn_xy[1]) < 700:
        d3 = bfs_dist(free, spawn_xy)
        for only_dim in (True, False):
            cands2 = []
            for ri in rinfo:
                if ri["rect"] is entry_room or (only_dim and ri["lit"]):
                    continue
                r = ri["rect"]
                for (bx, by) in ((r.left + 88, r.top + 88), (r.right - 88, r.top + 88),
                                 (r.left + 88, r.bottom - 88), (r.right - 88, r.bottom - 88)):
                    cands2.append((bx, by))
            cands2 = [c for c in cands2
                      if math.hypot(c[0] - spawn_xy[0], c[1] - spawn_xy[1]) >= 700
                      and is_free_spot(c[0], c[1], PICK_RADIUS + 3, blockers)
                      and cell_of(c[0], c[1]) in d3
                      and not hatch_pad.inflate(60, 60).collidepoint(c)
                      and not door_pad.inflate(60, 60).collidepoint(c)]
            if cands2:
                f2 = max(cands2, key=lambda c: d3.get(cell_of(c[0], c[1]), 0))
                flower_pos[0] = (int(f2[0]), int(f2[1]))
                break

    return {
        "kind": "house",
        "theme": theme_key,
        "rooms": rinfo, "walls": walls, "blockers": blockers, "doors": doors,
        "free": free, "dist": dist,
        "portals": portals,
        "flowers": flower_pos,
        "collected": [False] * len(flower_pos),
        "px": spawn_xy[0], "py": spawn_xy[1],
        "armed": [False if (arrive_from and p["target"] == arrive_from) else True
                  for p in portals],
        "pick_fx": [],
        "leaves": [],
        "surface": None,
        "sky": None,
        "veil": 0.0,
    }


def build_surface_house(state):
    th = THEMES[state["theme"]]
    surf = pygame.Surface((MAP_W, MAP_H))
    surf.fill((9, 8, 10))
    rnd = random.Random(5150)
    h = HOUSE_RECT

    # 房子外面那圈悬空木台
    ring = h.inflate(180, 180)
    pygame.draw.rect(surf, (26, 23, 21), ring)
    for y in range(ring.top, ring.bottom, 30):
        pygame.draw.line(surf, (18, 16, 14), (ring.left, y), (ring.right, y), 1)
    pygame.draw.rect(surf, (12, 11, 12), ring, 10)

    # 地板
    pygame.draw.rect(surf, th["floor"], h)
    for y in range(h.top, h.bottom, 17):
        pygame.draw.line(surf, th["floor_line"], (h.left, y), (h.right, y), 1)
    for x in range(h.left + 40, h.right, 260):
        pygame.draw.line(surf, th["floor_line"], (x, h.top), (x, h.bottom), 1)
    for _ in range(90):
        sx = rnd.randint(h.left, h.right - 60)
        sy = rnd.randint(h.top, h.bottom - 40)
        rw = rnd.randint(20, 70)
        pygame.draw.ellipse(surf, th["stain"], (sx, sy, rw, rw // 2))

    # 房间：地毯、家具、吊灯、蛛网
    for ri in state["rooms"]:
        r = ri["rect"].inflate(-18, -18)
        if r.w > 120 and r.h > 100:
            rug = r.inflate(-int(r.w * 0.36), -int(r.h * 0.38))
            if rug.w > 40 and rug.h > 40:
                rc = th["rug"] if ri["lit"] else th["rug_dim"]
                layer = pygame.Surface((rug.w, rug.h), pygame.SRCALPHA)
                layer.fill(rc + (104,))
                surf.blit(layer, (rug.left, rug.top))
                pygame.draw.rect(surf, th["wall_dark"], rug, 1)
        for kind, val in ri["props"]:
            if kind == "table":
                rc = val
                pygame.draw.rect(surf, th["wood"], rc)
                pygame.draw.rect(surf, th["wall_dark"], rc, 2)
                pygame.draw.line(surf, th["wall_dark"],
                                 (rc.left + 6, rc.centery), (rc.right - 6, rc.centery), 1)
            elif kind == "crate":
                rc = val
                pygame.draw.rect(surf, th["wood"], rc)
                pygame.draw.rect(surf, th["wall_dark"], rc, 3)
                pygame.draw.line(surf, th["wall_dark"],
                                 (rc.left + 4, rc.top + 4), (rc.right - 4, rc.bottom - 4), 2)
                pygame.draw.line(surf, th["wall_dark"],
                                 (rc.right - 4, rc.top + 4), (rc.left + 4, rc.bottom - 4), 2)
            elif kind == "chair":
                cx0, cy0 = val
                pygame.draw.rect(surf, th["wood"], (cx0, cy0, 40, 40))
                pygame.draw.rect(surf, th["wood"], (cx0, cy0 - 34, 40, 12))
                pygame.draw.rect(surf, th["wall_dark"], (cx0, cy0 - 34, 40, 12), 1)
            elif kind == "cobweb":
                ox0, oy0 = val
                for k in range(3):
                    pygame.draw.line(surf, (146, 146, 140),
                                     (ox0 + 6, oy0 + 6 + k * 12),
                                     (ox0 + 54 - k * 10, oy0 + 6), 1)
        for (lx, ly) in ri["lamps"]:
            pygame.draw.line(surf, (60, 48, 36), (lx, h.top + 12), (lx, ly - 14), 2)
            glow = pygame.Surface((320, 320), pygame.SRCALPHA)
            for rr in range(150, 8, -8):
                a = max(0, int(92 * (1 - rr / 158) ** 1.5))
                pygame.draw.circle(glow, (255, 224, 156, a), (160, 160), rr)
            surf.blit(glow, (lx - 160, ly - 160))
            pygame.draw.circle(surf, (252, 232, 186), (lx, ly), 7)

    # 暗室里极淡的人影
    for ri in state["rooms"]:
        if ri["lit"] or rnd.random() > 0.32:
            continue
        sh = pygame.Surface((130, 240), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0, 0, 0, 30), (48, 0, 34, 40))
        pygame.draw.rect(sh, (0, 0, 0, 30), (42, 34, 46, 160))
        surf.blit(sh, (ri["rect"].centerx - 65, ri["rect"].centery - 160))

    for d in state["doors"]:
        pygame.draw.rect(surf, th["threshold"], d)
        pygame.draw.rect(surf, th["wall_dark"], d, 2)

    for w in state["walls"]:
        pygame.draw.rect(surf, th["wall"], w)
        if w.w >= w.h:
            for x in range(w.left + 6, w.right, 22):
                pygame.draw.line(surf, th["wall_dark"], (x, w.top + 3), (x, w.bottom - 3), 1)
        else:
            for y in range(w.top + 6, w.bottom, 22):
                pygame.draw.line(surf, th["wall_dark"], (w.left + 3, y), (w.right - 3, y), 1)
        pygame.draw.rect(surf, th["wall_dark"], w, 2)

    # 墙脚投影，给纵深
    shade = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
    for w in state["walls"]:
        if w.w >= w.h:
            shade.fill((0, 0, 0, 40), pygame.Rect(w.left, w.bottom, w.w, 16))
            shade.fill((0, 0, 0, 18), pygame.Rect(w.left, w.bottom + 16, w.w, 16))
        else:
            shade.fill((0, 0, 0, 40), pygame.Rect(w.right, w.top, 16, w.h))
            shade.fill((0, 0, 0, 18), pygame.Rect(w.right + 16, w.top, 16, w.h))
    surf.blit(shade, (0, 0))

    # 关着的大门
    door_l = h.centerx - HOUSE_DOOR_W // 2
    pygame.draw.rect(surf, th["wall_dark"],
                     (door_l - 12, h.bottom - 18, HOUSE_DOOR_W + 24, HOUSE_T + 18))
    pygame.draw.rect(surf, th["door"], (door_l, h.bottom - 8, HOUSE_DOOR_W, HOUSE_T + 8))
    pygame.draw.line(surf, (26, 20, 16), (h.centerx, h.bottom - 6),
                     (h.centerx, h.bottom + HOUSE_T), 3)
    for half_x in (door_l + 16, h.centerx + 12):
        for xx in range(half_x, half_x + HOUSE_DOOR_W // 2 - 22, 20):
            for yy in (h.bottom + 2, h.bottom + 16):
                pygame.draw.circle(surf, (86, 74, 56), (xx, yy), 2)

    # 踏板：门槛 / 地窖方口
    for p in state["portals"]:
        r = p["rect"]
        if p.get("style") == "hatch":
            pygame.draw.rect(surf, (34, 28, 24), r)
            pygame.draw.rect(surf, (10, 9, 8), r.inflate(-12, -12))
            for i in range(r.left + 10, r.right - 10, 16):
                pygame.draw.line(surf, (48, 40, 32), (i, r.top + 6), (i, r.bottom - 6), 1)
            pygame.draw.rect(surf, (70, 58, 44), r, 3)
            pygame.draw.circle(surf, (96, 84, 62), (r.centerx, r.centery), 5)
        else:
            pygame.draw.rect(surf, (92, 76, 56), r)
            pygame.draw.rect(surf, (64, 52, 40), r.inflate(-12, -10))
            for yy in range(r.top + 14, r.bottom - 6, 15):
                pygame.draw.line(surf, (52, 42, 32), (r.left + 6, yy), (r.right - 6, yy), 1)
            pygame.draw.rect(surf, (46, 38, 28), r, 2)
            leak = pygame.Surface((r.w, 18), pygame.SRCALPHA)
            for i in range(18):
                pygame.draw.line(leak, (255, 200, 138, max(0, 46 - i * 2)),
                                 (0, i), (r.w, i))
            surf.blit(leak, (r.left, r.bottom))

    return surf


# ===================== 地窖：全泥土的封闭空间 =====================
CELLAR_ROOMS = [
    pygame.Rect(860, 1200, 560, 300),     # 入口厅
    pygame.Rect(940, 720, 500, 340),      # 中央塌陷厅
    pygame.Rect(260, 900, 440, 340),      # 西侧低厅
    pygame.Rect(1740, 860, 460, 360),     # 东侧厅
    pygame.Rect(900, 340, 520, 320),      # 北侧裂厅
    pygame.Rect(240, 320, 460, 340),      # 西北机房
    pygame.Rect(1700, 300, 380, 300),     # 东北厅
    pygame.Rect(2160, 320, 160, 300),     # 大门厅
]
CELLAR_TUNNELS = [
    pygame.Rect(1090, 1050, 96, 160),
    pygame.Rect(690, 830, 260, 96),
    pygame.Rect(1430, 930, 320, 96),
    pygame.Rect(1160, 640, 96, 90),
    pygame.Rect(690, 450, 220, 96),
    pygame.Rect(1410, 430, 300, 96),
    pygame.Rect(690, 1150, 180, 96),
    pygame.Rect(2070, 400, 106, 120),
]
CELLAR_GATE = pygame.Rect(2085, 400, 70, 120)
CELLAR_GEN = pygame.Rect(395, 415, 150, 106)


def _mark_rects(rects):
    """把矩形集合铺到 12px 掩膜上，True 表示这里是可以站的土面。"""
    MC = MAP_W // W_TILE
    MR = MAP_H // W_TILE
    open_mask = [[False] * MC for _ in range(MR)]
    for rc in rects:
        for gx in range(max(0, rc.left // W_TILE), min(MC, (rc.right - 1) // W_TILE + 1)):
            px = gx * W_TILE + W_TILE // 2
            if not (rc.left <= px < rc.right):
                continue
            for gy in range(max(0, rc.top // W_TILE), min(MR, (rc.bottom - 1) // W_TILE + 1)):
                py = gy * W_TILE + W_TILE // 2
                if rc.top <= py < rc.bottom:
                    open_mask[gy][gx] = True
    return open_mask


def build_gate_open_surf(theme_key, gate_rect, bg, bg_pos):
    """门开之后贴回去的一块：走廊底面复原 + 两扇推开的门扇 + 门框横梁。"""
    surf = pygame.Surface(bg.get_size(), pygame.SRCALPHA)
    surf.blit(bg, (0, 0))
    lx = gate_rect.left - bg_pos[0]
    rx = gate_rect.right - bg_pos[0]
    ty = gate_rect.top - bg_pos[1]
    by = gate_rect.bottom - bg_pos[1]
    # 两侧石柱
    pygame.draw.rect(surf, (44, 40, 34), (lx - 9, ty - 12, 11, by - ty + 24))
    pygame.draw.rect(surf, (44, 40, 34), (rx - 1, ty - 12, 11, by - ty + 24))
    # 推开的门扇：薄薄贴在柱边，带一圈铆钉
    for xx in (lx - 15, rx + 3):
        leaf = pygame.Surface((12, by - ty), pygame.SRCALPHA)
        leaf.fill((70, 66, 60, 238))
        pygame.draw.rect(leaf, (36, 32, 28, 238), leaf.get_rect(), 2)
        for yy in range(12, by - ty - 8, 26):
            pygame.draw.circle(leaf, (108, 104, 96, 238), (6, yy), 3)
        surf.blit(leaf, (xx, ty))
    # 门顶横梁
    pygame.draw.rect(surf, (50, 45, 38), (lx - 11, ty - 16, rx - lx + 22, 10))
    pygame.draw.rect(surf, (26, 23, 20), (lx - 11, ty - 6, rx - lx + 22, 3))
    # 门后渗过来一点冷光，暗示再往里就是往下的路
    glow = pygame.Surface((rx - lx, 66), pygame.SRCALPHA)
    for y in range(66):
        a = max(0, int(30 * (1.0 - y / 66.0)))
        pygame.draw.line(glow, (112, 134, 142, a), (0, y), (rx - lx, y))
    surf.blit(glow, (lx, by - 66))
    return surf


def _draw_generator(surf, rc):
    body = rc.inflate(-10, -14)
    pygame.draw.rect(surf, (66, 62, 56), body)
    pygame.draw.rect(surf, (34, 31, 28), body, 3)
    for i in range(5):
        pygame.draw.line(surf, (44, 40, 36), (body.left + 8, body.top + 16 + i * 12),
                         (body.right - 36, body.top + 16 + i * 12), 2)
    tank = pygame.Rect(body.right - 30, body.top + 12, 22, body.h - 26)
    pygame.draw.rect(surf, (58, 52, 46), tank)
    pygame.draw.rect(surf, (30, 27, 24), tank, 2)
    pygame.draw.circle(surf, (78, 72, 64), (body.left + 26, body.bottom - 20), 13, 3)
    pygame.draw.circle(surf, (92, 40, 30), (body.right - 54, body.top + 20), 6)
    pygame.draw.line(surf, (54, 48, 40), (body.left + 6, body.bottom - 4),
                     (body.left + 46, body.bottom + 10), 2)


def _draw_gate_closed(surf, rect, th):
    pygame.draw.rect(surf, (30, 26, 22), rect.inflate(30, 22))
    pygame.draw.rect(surf, (58, 52, 44), rect.inflate(10, 10), 4)
    half = rect.w // 2
    for panel in (pygame.Rect(rect.left, rect.top, half - 2, rect.h),
                  pygame.Rect(rect.left + half + 2, rect.top, rect.w - half - 2, rect.h)):
        pygame.draw.rect(surf, (86, 82, 76), panel)
        pygame.draw.rect(surf, (40, 36, 32), panel, 4)
        for yy in range(panel.top + 14, panel.bottom - 8, 26):
            for xx in range(panel.left + 8, panel.right - 6, 22):
                pygame.draw.circle(surf, (120, 116, 108), (xx, yy), 3)
    pygame.draw.line(surf, (16, 14, 12), (rect.centerx, rect.top),
                     (rect.centerx, rect.bottom), 4)
    rnd = random.Random(77)
    for _ in range(26):
        rx = rnd.randint(rect.left + 4, rect.right - 4)
        ry = rnd.randint(rect.top + 4, rect.bottom - 4)
        pygame.draw.circle(surf, th["rust"], (rx, ry), rnd.randint(2, 5))
    for k in range(9):
        px = rect.left + 4 + k * (rect.w - 8) // 8
        pygame.draw.circle(surf, (52, 48, 42), (px, rect.top + 34), 5, 2)
        pygame.draw.circle(surf, (52, 48, 42), (px, rect.bottom - 34), 5, 2)


def create_level_cellar(theme_key, arrive_from=None):
    th = THEMES[theme_key]
    rooms = [r.copy() for r in CELLAR_ROOMS]
    tunnels = [r.copy() for r in CELLAR_TUNNELS]
    floors = rooms + tunnels

    open_mask = _mark_rects(floors)
    MC = MAP_W // W_TILE
    MR = MAP_H // W_TILE
    solid = [[not open_mask[r][c] for c in range(MC)] for r in range(MR)]
    blockers = merge_blocked_runs(solid, MC, MR, W_TILE)
    free = build_free_grid(blockers)

    spawn_xy = free_cell_center_near(1140, 1380, free, blockers, 260)
    if spawn_xy is None:
        spawn_xy = (1140, 1380)
    dist = bfs_dist(free, spawn_xy)

    torch_pos = free_cell_center_near(1052, 1346, free, blockers, 90)
    if torch_pos is None:
        torch_pos = (int(spawn_xy[0]) - 88, int(spawn_xy[1]) - 34)

    ladder_pad = pygame.Rect(0, 0, 116, 96)
    ladder_pad.center = (980, 1452)
    stairs_pad = pygame.Rect(0, 0, 116, 96)
    stairs_pad.center = (2238, 468)

    gen_rect = CELLAR_GEN.copy()
    gate_rect = CELLAR_GATE.copy()

    portals = []
    for pdef in th["portals"]:
        pad = ladder_pad if pdef.get("style") == "ladder" else stairs_pad
        portals.append({"rect": pad, "label": pdef["label"], "target": pdef["target"],
                        "style": pdef.get("style"), "next": pdef.get("next")})

    # 白花：藏进最远、最黑的一处角落
    pad_zone = [q["rect"].inflate(70, 70) for q in portals]
    gate_room = rooms[-1].inflate(40, 40)
    flower_xy = None
    best_d = -1
    for (gx, gy), d in dist.items():
        cx = gx * GRID + GRID // 2
        cy = gy * GRID + GRID // 2
        if math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) < 700:
            continue
        if any(z.collidepoint(cx, cy) for z in pad_zone):
            continue
        if gate_room.collidepoint(cx, cy):
            continue
        if gen_rect.inflate(90, 90).collidepoint(cx, cy):
            continue
        if gate_rect.inflate(120, 120).collidepoint(cx, cy):
            continue
        if not is_free_spot(cx, cy, PICK_RADIUS + 3, blockers):
            continue
        if d > best_d:
            best_d = d
            flower_xy = (cx, cy)
    if flower_xy is None:
        flower_xy = (int(spawn_xy[0]), int(spawn_xy[1]))

    # 发电机和机关门只挡人不挡路：寻路先按“已经打开”算，背后的阶梯才不会误判
    blockers = blockers + [gen_rect, gate_rect]

    glow = pygame.Surface((170, 170), pygame.SRCALPHA)
    for rr in range(80, 6, -5):
        a = max(0, int(72 * (1.0 - rr / 88.0)))
        pygame.draw.circle(glow, (255, 208, 120, a), (85, 85), rr)

    return {
        "kind": "cellar",
        "theme": theme_key,
        "floors": floors, "rooms": rooms, "tunnels": tunnels,
        "walls": [], "blockers": blockers, "free": free, "dist": dist,
        "portals": portals,
        "flowers": [flower_xy],
        "collected": [False],
        "pick_fx": [],
        "px": spawn_xy[0], "py": spawn_xy[1],
        "armed": [False if (arrive_from and p["target"] == arrive_from) else True
                  for p in portals],
        "leaves": [],
        "surface": None,
        "sky": None,
        "torch": False,
        "torch_pos": (int(torch_pos[0]), int(torch_pos[1])),
        "power": False,
        "veil_a": 246.0,
        "gen_rect": gen_rect,
        "gen_glow": glow,
        "gate_rect": gate_rect,
        "gate_open": False,
        "gate_open_pos": None,
        "gate_open_surf": None,
        "facing": [0, -1],
        "quest": "找到发电机 · 入口处有支手电筒",
    }


def build_surface_cellar(state):
    th = THEMES[state["theme"]]
    surf = pygame.Surface((MAP_W, MAP_H))
    rnd = random.Random(31337)

    # 土体先铺成连续的一整块，再压大块明暗和细颗粒——不要黑底上浮一层亮石子
    wall = (30, 23, 17)
    surf.fill(wall)
    for _ in range(1100):
        gx = rnd.randint(-90, MAP_W + 90)
        gy = rnd.randint(-90, MAP_H + 90)
        rx = rnd.randint(48, 140)
        ry = rnd.randint(32, 96)
        sh = rnd.choice([-9, -6, -3, 3, 6])
        col = (max(0, wall[0] + sh), max(0, wall[1] + sh), max(0, wall[2] + sh))
        layer = pygame.Surface((rx * 2, ry * 2), pygame.SRCALPHA)
        pygame.draw.ellipse(layer, col + (rnd.randint(28, 50),), layer.get_rect())
        surf.blit(layer, (gx - rx, gy - ry))
    for _ in range(9000):
        gx = rnd.randint(0, MAP_W - 1)
        gy = rnd.randint(0, MAP_H - 1)
        sh = rnd.choice([-6, -4, -2, 3, 5, 7])
        col = (max(0, wall[0] + sh), max(0, wall[1] + sh), max(0, wall[2] + sh))
        pygame.draw.circle(surf, col, (gx, gy), rnd.randint(2, 5))
    # 嵌在土里的碎石子：底面压暗、顶面一点微光
    for _ in range(240):
        gx = rnd.randint(0, MAP_W - 1)
        gy = rnd.randint(0, MAP_H - 1)
        rr = rnd.randint(4, 10)
        pygame.draw.circle(surf, (14, 11, 8), (gx + 2, gy + 3), rr)
        pygame.draw.circle(surf, (42, 34, 27), (gx, gy), rr - 1)

    for rc in state["floors"]:
        pygame.draw.rect(surf, th["floor"], rc)

    for rc in state["floors"]:
        area = rc.w * rc.h
        for _ in range(max(26, area // 900)):
            gx = rnd.randint(rc.left, rc.right - 1)
            gy = rnd.randint(rc.top, rc.bottom - 1)
            sh = rnd.choice([-14, -10, -6, 4, 8, 12])
            col = (max(0, th["floor"][0] + sh), max(0, th["floor"][1] + sh),
                   max(0, th["floor"][2] + sh))
            pygame.draw.circle(surf, col, (gx, gy), rnd.randint(2, 6))
        for _ in range(max(3, area // 6000)):
            gx = rnd.randint(rc.left + 10, rc.right - 12)
            gy = rnd.randint(rc.top + 10, rc.bottom - 12)
            ln = rnd.randint(14, 46)
            ang = rnd.uniform(0, 6.28)
            pygame.draw.line(surf, (26, 20, 16), (gx, gy),
                             (gx + int(ln * math.cos(ang)),
                              gy + int(ln * math.sin(ang))), 2)
        for _ in range(max(1, area // 12000)):
            gx = rnd.randint(rc.left + 20, max(rc.left + 20, rc.right - 60))
            gy = rnd.randint(rc.top + 20, max(rc.top + 20, rc.bottom - 60))
            pw = rnd.randint(40, 110)
            layer = pygame.Surface((pw, max(10, pw // 2)), pygame.SRCALPHA)
            pygame.draw.ellipse(layer, th["damp"] + (52,), layer.get_rect())
            surf.blit(layer, (gx, gy))

    # 墙脚：可走区域贴着泥土的那一圈暗边
    T = W_TILE
    MC = MAP_W // T
    MR = MAP_H // T
    open_mask = _mark_rects(state["floors"])
    for gy in range(MR):
        for gx in range(MC):
            if not open_mask[gy][gx]:
                continue
            x0, y0 = gx * T, gy * T
            if gy > 0 and not open_mask[gy - 1][gx]:
                pygame.draw.rect(surf, th["rim"], (x0, y0, T, 6))
            if gy < MR - 1 and not open_mask[gy + 1][gx]:
                pygame.draw.rect(surf, th["rim"], (x0, y0 + T - 6, T, 6))
            if gx > 0 and not open_mask[gy][gx - 1]:
                pygame.draw.rect(surf, th["rim"], (x0, y0, 6, T))
            if gx < MC - 1 and not open_mask[gy][gx + 1]:
                pygame.draw.rect(surf, th["rim"], (x0 + T - 6, y0, 6, T))

    # 垂下来的根须、地上的抓痕
    for rc in state["rooms"]:
        for _ in range(rnd.randint(2, 5)):
            rx = rnd.randint(rc.left + 30, max(rc.left + 30, rc.right - 30))
            ry = rc.top + 8
            ln = rnd.randint(26, 92)
            pts = [(rx, ry)]
            for k in range(1, 5):
                pts.append((rx + rnd.randint(-10, 10), ry + ln * k // 4))
            pygame.draw.lines(surf, (58, 46, 34), False, pts, 2)
        for _ in range(rnd.randint(1, 3)):
            sx = rnd.randint(rc.left + 40, max(rc.left + 40, rc.right - 60))
            sy = rnd.randint(rc.top + 40, max(rc.top + 40, rc.bottom - 40))
            for k in range(3):
                pygame.draw.line(surf, (24, 18, 14), (sx + k * 9, sy + k * 4),
                                 (sx + k * 9 + 22, sy + k * 4 + 16), 2)

    for p in state["portals"]:
        r = p["rect"]
        if p.get("style") == "ladder":
            pygame.draw.rect(surf, (18, 14, 11), r.inflate(24, 18))
            pygame.draw.rect(surf, (58, 44, 32), r)
            for i in range(4):
                pygame.draw.rect(surf, (96, 74, 52),
                                 (r.left + 8, r.top + 8 + i * 22, r.w - 16, 6))
            beam = pygame.Surface((r.w, 150), pygame.SRCALPHA)
            for y in range(150):
                a = max(0, int(46 * (1.0 - y / 150.0)))
                pygame.draw.line(beam, (255, 226, 178, a), (0, y), (r.w, y))
            surf.blit(beam, (r.left, r.top - 150))
        else:
            # 往下的石阶：口子一圈石材，里面越踩越黑
            pygame.draw.rect(surf, (12, 10, 9), r.inflate(22, 18))
            pygame.draw.rect(surf, (56, 50, 42), r.inflate(14, 10), 5)
            mouth = r.inflate(-14, -12)
            pygame.draw.rect(surf, (7, 7, 9), mouth)
            for i in range(5):
                inset = i * 8
                yy = mouth.top + i * (mouth.h // 5)
                shade = 46 - i * 7
                pygame.draw.rect(surf, (shade, shade - 3, shade - 7),
                                 (mouth.left + inset, yy, mouth.w - inset * 2,
                                  mouth.h // 5 - 2))
            beam = pygame.Surface((mouth.w, 46), pygame.SRCALPHA)
            for y in range(46):
                a = int(34 * (y / 46.0))
                pygame.draw.line(beam, (104, 124, 134, a), (0, y), (mouth.w, y))
            surf.blit(beam, (mouth.left, mouth.top))

    _draw_generator(surf, state["gen_rect"])
    # 先把还没被门盖住的那一块存下来：门开时贴回去，避免出现一块颜色不对的补丁
    gate_pad = state["gate_rect"].inflate(34, 26)
    gate_bg = surf.subsurface(gate_pad).copy()
    state["gate_open_pos"] = gate_pad.topleft
    state["gate_open_surf"] = build_gate_open_surf(state["theme"], state["gate_rect"],
                                                   gate_bg, gate_pad.topleft)
    _draw_gate_closed(surf, state["gate_rect"], th)
    return surf


# ===================== 跳脸与光照遮罩 =====================
JS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "jumpscare")
# 跳脸用哪张：None = 三张随机；1 / 2 / 3 = 固定用 js_1 / js_2 / js_3
JS_FIXED = None
JS_SPEC = [("js_1.jpg", 0.62), ("js_2.jpg", 0.45), ("js_3.jpg", 0.50)]

# 三张跳脸图（预裁切为 1280x720 的灰度 JPEG）直接内嵌在代码里，
# 这样单文件拷贝也能正常跳脸，不依赖 assets 目录。
_JS_EMBED_B64 = {
    "js_1.jpg": (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJC"
        "IeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCALQ"
        "BQADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhBy"
        "JxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
        "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAA"
        "AAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
        "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExc"
        "bHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwC4pxVXUAzGIjorgn8xVjdTJF3xSep6fh/9fFADCMDnhgetO+8A"
        "SP8AgVDqSqyAZJHK0Eh8DOD6dqAHnPA++Kh8RTtY6XL5LhHcbI88gseMUl7cpbxYIVpf4UGOTVAwpJqtvc3Eoka2jaUJhSoOMYx3PNAGH4X0e8"
        "uWmlvliZoMQ+QWO3qWzj1OazviZpNi+jX7xWtvZC3jzIyDhiRkD69/xrtIYp7KJtVihLPJueZG6NnGMfQCuH8aTf2v4SurCzyJmkFzdl/4VJ+V"
        "fxGKAPJZLq8s9DtLaJwsE4LurLz6YB+hIpmq2891qb3SxqizlnRd2QoUDP8AOuh8cCOXw7pSWkLLDbQr5nHOdv8Aj1rnzK1tsDq6BEIZh1yw6f"
        "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"
        "96AEbpilHSkZgZCopaAP/9k="
    ),
    "js_2.jpg": (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJC"
        "IeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCALQ"
        "BQADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhBy"
        "JxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
        "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAA"
        "AAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
        "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExc"
        "bHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDzKiiigAooooAKKKKACiiigApQcUlFADt3tRu9qbRQA7d7Ubva"
        "m0UAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFA60AFBp"
        "56Uw0AANFIKWgBSO4oyfWnL0ppOTQAoxikIx0oUZpW9KAFByKXpTF+8Ke44oAa9Np2MDnpSAE0AJS5PrSlcCk2mgBQxpSM03aacOlACFTSqMHJ"
        "pc0HmgBSajbrTzQRxQAxeuaQmijGTQADmlb0pyDFKFy3SgBqCkKkHpUrcUHkUAR844pOfepFA70pAoAiBpcinlRTSvpQAmVptLtNGDigBM0UUu"
        "DQAlFKtDDBoASiiigAooooAKegpo608UAOXrUuPlqJTzU4+6aAK7j5qbjmpH+9SAZFAB2pAvelPFG6gBrcUwDJpz80KCDQApTNNKVMRxSAGgBi"
        "rSsnFPxik5oAhxg808GldaaBigBTTD1p9NK0AIDilC5ptSp05oARVqQDFAIoNAAcUzbRRmgBcUjKKM80N0oAbtFOVQKQdaM80APIpMUjNSbveg"
        "AIHpQRSbhRu96AFxSUm6lHNACjmjFAFL1oATNOApuKepoACKjk61K1Qv1oAbRQOtKTmgBynilzTF606gBc0ZpKKAFzSUUUAFNYYp1FADKBxSkY"
        "NJQAUUUox3oASgUppKAHDnk0hGKVaGOaAG0oFJSg+tACkYFNpzdKbQAUoGRSU5elABtFIwxTqRu1ADaKKKACiiigAooooAKKKKACiiigAooooA"
        "KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAXI9KMj0pKKAFyPSjI9KSigANFFFABRRRQAUUUUAFFFFABRRSjk0AJRTtvvRt96"
        "AG0U7b70bfegBtFKeDSUAFFFFABRRRQA7d7U2iigApetJSr1oAcvA5pGHPFLRQAi5pWGaKKAEVcHNPoHSigBCM0IMUtFACPk9KbuI4pxpCMigB"
        "mTT1BxSKvPNSCgBq04jmk708OB1oAaRSsPloY0ZAHNAEQU+lOQYPNPDrTdwzxQA7FKOKTcBRuoAbJTQT6U8kGkGKADBNG008GmsaAGmm7qUmmG"
        "gB26jdmmCnL1oAE60880jdKFPFAChcUjcjFKTimluaAEwfSkqQciggGgCOinFfekPBoASnD5uKQkmlQ80ASKOatLH+4L5qstXlx9iNAGe55PtS"
        "I/alcr81MT1oAeTmkpKUDNAC4pMgcUpqNutAEoalzTKM0AOzS5pmaM+1ADiaSgMB1prnPSgB/FITUfPvTgwxQAEZpQMCmE+lOBwO9ABuxTlNM3"
        "CnqQaAHGmU49KaaAEJwaUnIprdKbQA7dg04cjNR0uTQAr8kUm004dOaKAGkYpDTm7U00AFPXpTBRQBJ1pM4puT60E5oAeGBpc1FS89KAJd1Nbm"
        "mYPpRg+lABg0bTRg+lGD6UALnHFG72pADQQRQAu72oyKbRQA/IoyPWmUv40AOyPWjI9ab+NH40AK3NIOvNH40lAC/jSUv4UfhQAlKMZo/Cj8KA"
        "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"
        "AUUUUAFFFKMd6AFUd6Q9adkUw9aACiiigApxGFoBA70EjFADaKKKACiiigAooooAKKKKACiiigAooooAKKUCgjFACUUUUAFFFFABRRRQAUUUUA"
        "FFFFABRRRQAUUUUAFFFFABRSjHrRgetACUUuB60YHrQAlFLx60lABRRRQAUUUUAFFFFABRRRQAUUUuD6UAJRTlGKWgBlFOyKMigBAM04cUZFGR"
        "QAuaRuabuNOBoATbSgUuRQSKAAUtM3e1G72oAfmkJFR044P1oAerCn5GKhUGn7qABiKQYpGGaVVoAQqKaetSkCmFKAEGKeBTQn1p44oAaR3ppX"
        "JqTNITQAwKRTsUtLmgBlFKetJQAUUuKMUAJSikoBFAD1rqNEffpkg9q5YGuo8PKPsEuPQ0Ac3cLid/rUY6mpL1v9LcDpuqOgAooNJmgB1L2pma"
        "cGoAQnFIDSOaavUUATLQ1IDxSGgAAzRtpASKXJoAKTJpQc0uBQAzeR2p+eKTatBwOlAAaB0ptIWINADhnPNOY8cUztSjGOaAAZ70rYpAM0GgBV"
        "60GlQetK3tQBG4plPcEik2+9ADaKXBpKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKV"
        "etJSr1oAc3SmU9ulMoAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAHKTmhu"
        "nNNooAKUnNJRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABTx0plPHSgB1I1KKRqAI6K"
        "KKACiiigAooooAKKKKACiiigAoHWilAzQA7NNPWnbeMU0jHcUAOU8U/NRqKfQAuaM0lFAC5pKKKAA02nGkxQAClpBS4zQA0n5qU00qc040ABOB"
        "Sg5FIRkUoXigBr9KEHFL2pVFAEbDmuv8NKW02T6GuTIz2rtvCMYbTJOOxoA4zUAVvH/wB40xelW9XjAvX4/iNVQOKACm06kPWgBh60lOYd6bQA"
        "UUUUASLS0gpaAENJSmkoAUUtIKWgApDS0hoASiiigANKKSlHWgB2cCkXk0Hk0uMUALRSCloAQ0hNKaaaAEowKKKADHFNwcVJQelAEQpR0NGCaX"
        "GAaAEFKq+tCVKB8tAEQXmlwKX+KloAjPWg0rA5pWWgBlFKRikoAKKKKACkXvmlooARs9qWlxwDSUAKDikpT1pKACiiigAooooAKKKKACiiigBV"
        "xnmpFAqIc09QaAHyY21DUsoO2ohQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUo5NACU5R604Cg8"
        "GgBMD0owPSiigAwPSjA9KKKAEam0p60AE0AN5paUgikoAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAK"
        "KKKACiiigAp46UynjpQA4UjUopGoAjooooAKKKKACiiigAooooAKKKKAFAJpyLTQM09BQA/bTGTnrUmD60xhQAgXFLSdKM0ALRSZozQAtKKbml"
        "BoAU0lGaTNADhS0zNKDQA40hWkzzSlhQA7pRximk5FKDxQAbeKFo3cU0HmgB7DpXZ+CGJtZF+tcY2OK7DwGcpKPegDnvES7dVnA6bqz61PFY26"
        "xMP9qsodaAA0hp1NoAb0pCvpTqSgBNppcD0oooAeBmjFJnimsxoAc1NpoJzTqAFFLSCloAKQ0tIaAEooooAKUUlFADxQeabmjNAC5AqQDIqFji"
        "p4uUoAYaaac3DGmk0ANpCcGlowKAAc0pPFJRQA6L5jSzrilg+9S3XWgCJKl/hqIHHWpR92gCPHNLRnmigBpIzSsRTG+9SsDigBGOaSiigAoooo"
        "AKKKKAHfw02lBxSHigBzetNqRRlaY3WgBKKKKACiiigAooooAKKKKACpl6VDUy9KAHS9KgPWp5egqFh3oAbRRRQAUUUUAFFFFABRRRQAUUUUAF"
        "FFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABSqcGkpR1oAmTkUkg5pY6STrQBFuNKSabSnt9KADcaCSaSigAqSLk4qOpIfvUAOmGKhqa4qGgA"
        "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAUjFJTmpB1oASpEXIph61LHwKAInGDikp0h+ahVyM0ANooooAKXJpKKAH7"
        "qQtmm0UAKOtDdaBwaDyaAFUZNIeDT4R1pHHzUANPBpKVutJQAUGiigAooooADToutNPSnR0ATKDioWJ3Gp0+7Vd/vGgABOKNxoHQ0YPpQAbjRu"
        "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"
    ),
    "js_3.jpg": (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJC"
        "IeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCALQ"
        "BQADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhBy"
        "JxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
        "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAA"
        "AAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
        "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExc"
        "bHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDyekp2KMCgBtFOxSHigBrc01FwxNO/GlH1FABS0fjR+NABSUv4"
        "0fjQAlFL+NSJGGGaAIqKn8kepo8oe9AEflMecCl8p/QfnU4AAxS4oAr+U/oPzo8p/QfnVjFGKAK5jIHNRkY61bIz2qMxAmgCKNCVOKXyn9KmRd"
        "owKd+FAECxsKdsY1KKKAIvLamOCpwascU1ogxzuIoAkspgrAZxWvDdr5eM1g+UAfvGlaRoiApJFAHQh0ZevWs/UrcOoxziqS3ZUjJq5HdqyepN"
        "AHPX1ttY8Gs+T5TiuouIkmyTgCuZ1EeXc+WvT3oAfajLA1fwx4qnYIcg+9bKopQcc0AU/LOasJGdvSpPKHvUqIuOtAFfy27Cjyn9BVsRrjg0eW"
        "PWgCp5T+lTQRvjoKl8setPQbRQBH5b+g/Ojy39B+dTZozQBD5b+g/Ojy39B+dTZNGTQBD5b+g/Ojy39B+dTBuafigCt5b+g/OrKo+0cUhWnhsC"
        "gBNjUbGp276UbvpQA3Y1Jtb0p+76UbvpQAihgelPpm6pIxvoASipNg9aNg9aAI6Kk2D1o2D1oAjoqTYPWjYPWgCOkIyDUuwetIUwOtAEGxqNjV"
        "JRQBXnVvLNV8H0rQPI6ZpuF9KAM4yAEjB/Kopn3AAZrTa3Qkn1qvd2yhMg9KAKEvzR4rT8Nf6wfWqKxjbzWj4eQLIuO7YoA6telKW2jPpTPMVT"
        "g1FdTKIWPtQBzWvXe25bB61no+R707Vf9IuPl6A0kMWcZoAli61LSrEFPGalWIGgBIDzU5piRgU/igBr/dqMDNSMARinRryKAADAxRUmwUjJgc"
        "UAMopdpo2mgCe1+6frU1Vo2ZBgLmnea/8Ac/WgCenBuOpqt5r/ANz9aPPx1GKALQbnrml3VU88UGcY6UAWSp9f1ppGKpidmPDVIsjgdM/U0AWR"
        "1pWOarec3oKPOb0FAEjSopwc5+lJ58fv+VVJXJcnFN3mgC758fv+VHnx+/5VS3mjefagC758fv8AlTXmQqQM5+lVN5pC5xQA/P0oyPWq/mU3zO"
        "c0AWS3NKDmqwkH0pRLjpzQBOWHrSM2RxUDzKFJqMXIoAnLc0jZI6iqrzqSecVXN1h8FjQBckZEJ3E5qtI646nmo2YytkGnlQTg0ARSRhiDzVu0"
        "gXbgnBpYVVl4B4q3bQl3G1ee1ADo0WNdnUmpNhIxg4q9BYk/M64q0IYwOe1AFK3tiQCBgVdwEIVfSmyXUcalVwMVm3Ooh8quB70AXriVVBBIqm"
        "9zIylP4e1UvOYnJbNHnn+6PzoAc3BNIaYZkzyeaPNjPegBHXNNp+8Hoaace9ACUUcetIxwMigBaKi3t6GlDtnoaAFkUsOKZ5bVMvNO/H9KAK/l"
        "tT41Kjmpce/6UhBoASijB9aMH1oAgk+9TanMYJyW/Sk8pf7x/KgCGnbTTzEPU/lTCx6EfpQAxwSOKgZWzUzsR0qMn3oAVTin76ix70AH1oAkds"
        "imU18gZzTd9AD91Ju5qBpVyahlmA6GgC6zLjrUDOM8niqb3XbNQPMx9aALc0q7uD+tQvKhFQeXJIdwJxTvLYDkcetAD96UwqxOQaBHnvUyoMDm"
        "gCDys/eoEC5GasiP3pPJfcMZoAjMap0puc1eNs/dakjsweSMUAUIlO6nvHnqK0lt1i+YsuPeiW4sY1+ZgTQBQhsnlOUXA960Le1SIHcVBqhdaq"
        "oGIzhfasttQlkdhlgPUmgDp2uYIV5cVWl1W1C8DNc1I8knHnEVG0W4csTQB6D9j/2TR9j/ANk13v8AZdt/dH5UjadbL/ADQBwgs+fumo5bTHQG"
        "u+Gn2xOPLFK2k2x/hFAHngs8jODQbM9ga9C/se39P0oOkW/p+lAHnv2M+h/Kj7G3ofyr0H+yLf8AytH9kW/+VoA8++xt6H8qPsbeh/KvQf7It/"
        "8AK0f2Rb9h/wCO0AeemzI605YmXgA13zaREf4R+VA0OEruAX/vmgDgzG45Kmk2t6Gu5fQ4zx8o/wCA03+wI/Vf++f/AK9AHD7W9D+VG1vQ/lXc"
        "f2DF6r/3zQNBh9R+VAHEhGJ6H8qf5ddl/YAJ+VFNKfDxH8C0AcS6HPAoVDnkGuxbw7IW4jFN/wCEcl/55igDk9g9KXy/aur/AOEcl/55injQJQ"
        "MeXQByOwelNKegrr38PTMOI6hPh+cfwGgDkyp9DUiKNnI5rqP7An/uGk/sGcf8szQByZU7vumkMPmc9K63+wp/+eZo/sKf/nmaAOLubQnpmltL"
        "dkzluo7muyfQpQhzGfwFVm0CWUYCMPwoA51gQpAbj61n31h5xWQfe711jeHpV4KN+VJ/YU/v/wB80Achb2Mkb45xWpBDhMljmtv+xJx/CT/wGn"
        "jRZ/7h/KgDG2HsBRggdK2G0iYfwH/vk0n9mTD+A/lQBkqDjpS7T6VqHTJ+ykfhTf7LuPQ/lQBm7T6UYNaf9l3PofyoGl3OejflQBmYNG01of2d"
        "cbjwf++aP7PufQ/kaAKQHFLgVd/s6467T+VN+wTD+8P+AmgCpgUtWvsUn95vypPsc3qfyoAq05RzVj7DOegJ/CgWU6nlSKAIsUcVYNtJ6H8qQW"
        "0nofyoArnA64pylfapns5XGFUk0z7LOn/LMmgBDt9qWPAFOEEvdTR5Mo/hNABkUZFHky/3TR5Uv900AG4UZFI0Uo52mmeXLn7poAkyKTcPWkCu"
        "Oqml2t/doANwo3Cja392ja392gAytGVo2t/do2t/doAPl9KjbrwKk2Mf4aTYfQ0AR4PpQwypyuakKP6GjY+CCDQBmyrtY8cVd0fCkdvmzTJoWO"
        "Rg0+0iZec0AbIkAJJ5qrqN0i2rjAHFROWz16VQvd8iFPWgCjagTuXJwM1pJCoXgVTtIWQbSO9aafdoAiKDb0oAxUxGaNlADfl9KPl9Kd5fvSeV"
        "70AJhT0FKq4pVjwc5qSgBlI2ccU7BoUEGgCP5vQU7PtT/wA6bQAmfammQA4NEmex59KZFHvyzHBoAeHz0FMaMsc1Iq4p69O9AFfyj60eSfU/nU"
        "5ooAiWJR9akCkdz+NAp6nIoAZzRzTyeM0m40AQyISelM8sn1qweaSgCDyT6/pR5Te9WKKAK4jI6jNLt/2anooAr7B/c/So3jOeFq5TW9KAKYTn"
        "G2opYznjP4Ve204IpHNAGU8R2k81AIz2rYdVPG2oJoRjIOMUAY0isGOM1SkVzLk9M9a07n5SfeoYYvOfb6HNADrKNsYHNakcBJ+7T7G1CAAitO"
        "OJVIJoAgtrHeQegrTt7VIMHg03zYo125FVrm6OQAeKALl5cBFwG5NZdzfPs2ryaY7M5yTUTJk0AVp5ZpFxtIquVYdRzWjs96PLXvQBnDfjnNL8"
        "3vWh5aelHlp6UAZ34GjHoDWj5aelL5aelAGb8w9QKRnHZjWkY0I6VF9lT2oAzvMP+1QZG/2qvtboDTXt1K4B5oAo+YfQ0eYferH2Q/8APTH4Un"
        "2Rv+eg/KgCAzketJ57epqdrYKMuwP4Unkx0AQ+c3qaelwR1p3k/wC1+lIYT/f/AEoAPtFH2ik8k/3x+VHkn++PyoADc4PWj7T7/rUMkXzfe/Sm"
        "mI56/pQBY+0+9Refz1pvl89aTy/egB5mqJ5yP4af5Z9f0prx/KeaAI/tPt+lI10B9ajZcHpVa4G0ZoAnN382CRUUl3g9az55CDxTI2LnmgDQa4"
        "B6VGzsTUSR/NUvl47igBuzceacI8CnKG6AVIIZD2NAEYYjgE1JESWw2SKtQ2o2AsRmn4hh+ZsEfWgCv5YbocVMkHGR0pftNr/d/WsrVvEC20yw"
        "xMAKANVlVAKek0Kru3Djmuel1WWdec/WoPNmI+/jNAHRSarHtOMZqs+qyFPlrIVSf46eFwOuaALMl7LKpVt351XbcaAOaWgCPae9BQt3qSnIu6"
        "gBiRD1p2w08IwYYFT+Wf8AIoA97yKil5xTN59aTd70APj+9U26qwbml3e5oAs9aSollAHOaXzl9DQBJS96j81fQ0ocGgB/ehetNDA0uaAJdwpQ"
        "wx1FQ0fjQBMSPWjj1qD8aejKOpoAkozTd4pVO7pQA5Sdw5qY/MOpqDvT0bHWgCQDFLTS6k96TevvQA+kpu8UoYGgBaQqDS0UAJsX0/SgIuelLR"
        "QA9UjP8IpfLj9BTVOD1p24etAC+XHjpR5af3RSbh6ijcPUUAHlRZztH5UeTF/dH5Ubh6il3D1FACGGL+6Pyo8uP+6Pypdw9RQDk0ANMMR6oKTy"
        "Ij/ABUtKOgoAh+xwnq36Uv2KD+8fyqZGCnnAp3mD1oAr/YoP7x/Kj7FBn736VY8wUBxQBVOnWxzz+lJ/Zdv/AHv0q5vFG9aAKn9l2x/jP5Uf2T"
        "bH+LP4Vb8wUeYKAKZ0i1PcflSf2Naj0q75gp2T6CgDPbRoD0ANMbRI+wX860+aUfhQBlf2Gp7LS/2F7LWuGANO836UAY39hE9lpDoAPUCtnzm7"
        "Uee/rQBht4ejHO0VEdBTsldD5pPWnKwagDnP7BX+7+lH9gr/AHf0rpePQ0cehoA5ltAB/h/Som8PqDnbzXV8elAHPQ0Acn/wj6HkpTX8OqRwpH"
        "4GuuOaQcds0AcZ/wAI4/8Ae/Sl/wCEcf1rtN5HSNfxpN5/55pQBxn/AAjj+v6VG/h5w2N1dvvP/PKOlBQ8tEuaAOEk0CQDhqjbQpsj5gK78+X/"
        "AM8lpjpEx/1YFAHn50WcHG6nJokx6tXfeVD/AM8x+VAgib/lmtAHnz6FLnO4U1dGmAwFNei/ZIv+eaU1raHugH0oA85k0i4U8Jmo30icj/VjNe"
        "lLZ2zLyGzSHT7cngGgDzRNJkU/MnPsKG0yTJ+Vvyr0sadB6GmtpcB7UAea/wBmv2DflR/Zsno35V6P/ZMPpSHSoQM4oA85/s9x1yKT7C2M5r0N"
        "9Mtm6r+lR/2Tajov6UAcAbRh71HJbMCOK9E/si0PVf0psmjWrfw/pQB52bebsmRTXgnUZEJ/OvQH0q3HAFNXRomyVAoA4JIpCvKYNI8MhHKYH1"
        "ruJtNt4lwyZPtVc6ZbOOUNAHFLbt5uSaJkVXGGJPpiuybSLRRnGB7VSuLCHfiOL8aAOc2+tNbodvNaeqtYWNuZLieJcdRnmuL1jxto1pJ5MCCd"
        "8dVNAG6PM6mMqPWlOVXJrh5viN8hSKGOIep5qonjeJ5C91IZPYHAoA7s3Ck4FOFxtBya821D4gwsCttpqp/tFua5y98XanMxKSGL0CmgD21rmA"
        "KCZADTY7u17yj868Il8SatIu1rpiPSqrarfN1uZfwagD386jZ7iolUkds0+O6jkbaCBXgUGrXMWGWSQsDnO6thvGeoiFVjxkdzQB7NNOqLwRUD"
        "alZxrmS5jXHWvE7zxVq1wu0zFPoazZNRupf9bPI3/AqAPcx4i0gy7ftsfHXmp4NZ0+WUhbuIjPHNeBRSnO7r9TzT1vHjk3KWHOeGxQB9EBg43q"
        "y7PrS+apHCkmvDLTxTf2xVRI5UHoWNay/ELUhgQxqv1oA9YMvOKfG+7jvXmmleI9YvruOUuGTdhgor0qMxKI3ZlVyoJ5oAcEGSaiuM7SFxUt1c"
        "W0MZaSVVGMk7q5i88WaVDcGMT7sdSORQBavQxOMHNWNMt2RtxByRWHJ4u0bfk3ByP9mm/wDCb6SDlJ3z7pigDtFJQdDTJLhzxyK5KHxpp0jYFy"
        "R9RV2HxNpj/eu0x9aANx3ZuppcE4JrPt9Ts51LRzKR9RWjazRzcB1H1NABRz6Vb+zkfdIYeopRbyHtQBTx7Uc+lXDazf3M/hSGCUdUP5UAVOfS"
        "jn0q15Ev9w0eRL/coAq8+lHPpVkxS/8APOk8uQfeTFAFfn0oxUzZB5WmPjHQ0ARMoNARfSnYzzShR/eFAEbIOwpmDVjaP7wppIHcUAQMuRyKb5"
        "a+lTvgjqKZtHqKAI/LX0o8tfT9adx2waUA+goAZ5a+lHlr6VJtPt+dGw+goAqSRDcTtpmxP7tWpDjI2kn2qDD/ANw0AN8tT/DSCNP7tTxthcMp"
        "pmCTwpoAY0a4+7UDqM/dqy4ZTyKa2WUjFAFGSNT2qndxjZWp5Te1Vry2faSMUAc/cgK1JaplhU17byEgDHWpba2eMAtigCzbWiscs1PnthHjHO"
        "aieby+mc0i3Dtn+tAD1Ow528U9r1EByKrSPIwIqvLG+zNAEWpamwHynmsz7XdSMOeKfeRM8mAKntrdVUBgM0AWLXJiZpDzisPUkL3u48gdK3Ll"
        "RHbcDOayc7nKcZoAsW5LxgEcDpxVlFGMYpLaMqmDVmGB3cBVJoAiA7AUpB6YrXh0qZiGCcVei0dwwLRcUAc5HEzNjBp5jCnB611sWkBW3GPAx1"
        "xXE+KNSFjctHGASKALChd2G4FSSfZo13GXGK4m51yd2++Vqsb+4fJMrHNAHZTataxDhzxVWXxBEBwBXHyzSOOtMLtigD638xvSjzGqPevpSFlP"
        "agCZZGJwak/KqoYZ4p+TQBPxRxjtUGTRk0ATjGafVUE/5FShxgZJoAsKxA7Uu8+1V949TTgQe5oAmLt7UiyEnmoj9TSfiaALY+tH41UBP94/nS"
        "hj/eb86ALWKcpI6VCsi4GWpfMX+9QBNvaje1QiRf7xp4OaAH7zSF2ptL3oAcGanoxqLvRzQBY3mjear5PqaMn1NAFjeaN5qvk+pp6sMc0AS7zR"
        "vNR71o3rQBLvNG9qi3ijeKAJQ5JqTn1qvvGadmgCb8aASO9Q5pMmgCxvNG81XyaMn2oAsbzRuNQq2OtO3igCTcaN7VHvFG8UASb2o3tUe4UbhQ"
        "BJvaje3rUe8etG8etAEgds9anErY6VUDj1p+frQBY81/SjzX9Kr5+tGfrQBY81/QUeY3oPzqvk+9GT70AWPMb0o8xvSq+T70ZPqaALHmN6VJFI"
        "2DVPJ9TTkbA5JoAveY1HmN7VT3j+8aN4/vGgC55r+1Hmv7VVB4+9S5/2qALPmv7UvmP7VVz/ALVJk+poAt+Y/tR5j+1VMn1NGT6mgC35j+1HmP"
        "7VVyfU0ZPqaALXmP7Unmt7VXViDyTT96+v6UAS+a3tUkUjE9qrb19f0oDj1NAF3zDSMxNVN4/vGjzB/eNAFtWIp3mMKphs9GNLk+p/OgC35rUe"
        "Y1VMn1NNLDPJoAu+Y1JvaqW9fWlDrkc0AWaKhedOx/So/tOODQBOr5bFSVQE/wA2cimXN+yofKG5vagC5Iyhjmqc9wRwhxWbPqTqm65kEf1rkf"
        "FfxE0PQoSDdC4uu0UXJ/PoKAO6DKPnlf8AOs7U9f0yyjZpJUUAZyTXz/r/AMWfEV9K32QR2kZ6bclsfWuM1DWNR1AmS8vJZmJ7scUAe6a58XdI"
        "tC8cEbTFTj0rg/EfxY1a/Z47CFLVCMZGS1ebvJuPIoAPXtQBp6l4g1TUBi8upX+prMM8nmBgx44oPPWomGGPWgBXYucn+VN49P0o/A0fgaAFJG"
        "OlRsc9sUrHHHNStAUVSSDuHY0AQUVIU46UygAyaXcaQ0YoADk0lLilYAAetADaXPFJRQAUqnBzSUUAa1hrMlnGUhTAqzN4n1KV9zSt6dawKKAN"
        "K81nUbjKvcybT23VRMznPPXvUdFAClmPc/nQGI6GkooAlSUgYJqVJAORmqtFAGlb3UwYMJGAH+1it3TNeuY2C+bKgHGQcgVyOT609JZE+6xH40"
        "AewaJ40uLdQsjw3kQ67WwwrstH8Z6DcbBLMImP8L8frXzvaXTK+M4zWiJRtBZuaAPqOxutOuyHiliKn3zV9rG3kO9WXFfNPhzxJqGmMRBKXjzy"
        "rnP4ivSPDnxAhe5SJ/NBPXeflzQB6Z/Z0PqppP7Oh/uCotN1O2vE3oxX2zWgp3DIbIoAqHS4T0HNMfTI15ZQa0VYD60O2ehoAym0yI/8sxUUul"
        "IV/wBSK2M0ZNAGCdIj7xCk/sWE/wDLOt49aQdqAMBtGRekQqM6MhOTGK6Fx1qPigDAbR0A/wBWKZ/ZC/8APMV0WBRgUAcy+jxjkIajbSR2DV0j"
        "LjNNoA5ltL7DdSf2Q/o3510/GaXH0oA5J9Jl3cE/jSHSZe5rrvl7gU2SJGFAHHvpkoOARQdKuD/EK6wwR+9NeBCOCaAOQfS5QcFs/jTf7Mfv/O"
        "uqaCNDySSartGNxxnFAHMyaaR2NQTae5GMGuqeFTTPITHSgDiZ9LkLDaOfpSmymRPmC5+ldm0K+i/lUEttEzYagDiF0tpizOT17CoTpzxvjnFd"
        "19jhHQ0x9Pgc8n9KAOCuYGiG45wKzZrsA7a73X9OjW2JTGcHFeb6jbslyFPrQBOhEjZAqURZcYptohXAAq/bpmUAigCOaBjDgisW5gFu5kbiuz"
        "e1BhyOeK5/V9NublTsjPFAGNbXjSSiP3r0TwjpTTQ+Yy5LdK5zw54bOVeQZcEcEV6d4dtvs0S4yDjpmgB8VjDEdrKAR6ipTDD/ALJ/CrE53Nk1"
        "VcYbjIzQBBesq20nHAHpXgHjacvq83PAavdNblEOnTuegU189665kvJnPTceaAM4KpY5NSIB0qGI5cntU1AAwFNY4pTTSKAPrDAzQP60d6P8aA"
        "FBwadvpn+NHegB++jfTO9H+NAEinNPqHJpMn1oAnzinCTHaoUz3p5oAk832oEmT0qLI9R+dKM9aALAwaDgVBuPrQWPrQBYwPWjB9KgVuetSgj1"
        "oAdTlcioyRnrTqAJhJmlMnoKiFFAEnmn0pfNPpUVFAE6MT2p34VFEcZyak3L6igBaSjcvqKTcvqKAFopNy+opdy+ooAWko3L6ik3L6igBwODT/"
        "M9v1qPIPejFAEnmH0P50eZ7frUeKMUASeZ7frR5nt+tMooAf5nt+tHme360yigB/me3609TkZ/rUNKCR0NAEvH+TRx/k1Fub1o3N60ATfhR+FQ"
        "bm9TRuPqaAJ/wp/mVWDHPU1ICPWgCXzPYUeZ7Cosj1oyPWgCTzD7UeYfambl/wAmk3L/AJNAEokNHmGo8g9P50c0ASeYaN59Kj5pR7mgB+/2o3"
        "+1M49aOPWgCdZDjoaXzD71Bk9jRuP94/nQBP5h96PMPpUG4+pqQEY60AP3n0o8w+lMyPWjI9aAH+Z7UeZ7UzcvrRuX1oAf5ntRv9qYCCetO49a"
        "AF3+1ORs0zj1ozjoaAJMjmg/hUWTRk0ATo+0Yp3mCoVIxzS5HrQBL5lMbk5puR60uV9aAFFBxTdy+tNZx60AOPFQu5J6UTSYTIbpWPea3Z2UUk"
        "l3KqKB3OKAL87rEC00iBfrXHeMPHumaNaP5TqZhwAjAk15v4/+IlzfSyWmnvsjGQWVsZrza5upZpjJKzMx65OaAOm8VePNZ1mRlE7Rxk9j2rkT"
        "80jO5Lseck04gnmm0AKfYU0DBPJ5paKAEwPrS54oNJQAUhGRS0UARlD2x+VHl4HJFSZxz1pAd/BGKAECqOwNIWCnAWhiBwKYeo4NACs5Iximqp"
        "PSpET1p/A6CgCMR464pGUAdqczjFQkk0AKW9hTTRRQAUUpBHUUlABRSgE0lABRRRQAUUUUAFFFFABRRRQAUUUUAKDg5FWUlZlz1x2qspAYEjIH"
        "ata2S2vEzbqsVwvWInhx7e9ADbS4VTw+zPADVor5sRSaQMAejg8fjWS6KzZVjGB/CRU8N1dwR7HGY25weQaAPSvCHijYixS3IV+i5PBr0LQPFM"
        "b3K2k58uc8hGP3voa+fbZYblsQF1l/uk4z9K3NE1640+5S11JDPEh+Uk4aP3BoA+mIJllXcy7D6Z6VL8nY1wPhDxFHdwqrT+bFwEmHGPYjtXZ2"
        "xYkEcgjg0AWzUXmH0pysCCM1EetAD/MPpQH5qOlFAD2bNMpe9JQAGjNBIHWq8jnNADmlJNMzTaKAHBsc0u80ztR3oAfuyKYz7e1L2qKRqAFMmT"
        "0prSsBkYplNZhtoAHfecnFQtjmlOTTCaAE4prHtTqY3WgBpX5s5pjnnNOkOBxUWcmgAOc0oyetNPHNOQg5xQBn64cQrXC6nCr3JfFdr4gbEQz7"
        "1yVyrGQkLmgCraoN2CuKurGu4D3pIUBTdwDVuyTdOuRkUAakESmBQR1FSCzix0GasbP3a7RjinrjAGOaAGWsKowGelblj8o/SsqLG4Vq2v3cUA"
        "SscmoJj83tUxqKT5jxQBg+K51j0W4dumMV4FqEgLOx6MTXtfxFk8rw/KmfvHNeGXzZHtQBBAOTUwqOAfLmn0AKaSiigD6u70f40FGHc0fhigA/"
        "xo70jdDTMt60ASd6P8aRacKAE/xo707A9KMe1AArbacZOOlNoNADlcHtThUQJH50E0AS4z3ox71GpNPI/wA4oAB+NLz6mkA/zilFAAOD3qTzPa"
        "o6Mn1oAso4Ip2aiiPy0/NADqKbmjJoAcKKFJFO3GgBtFO3GjcaAG0U7caNxoAbRTtxo3GgBFODmpBIKZuNNoAl8wUqsCeKhpQSDQBPS1DvNG80"
        "ATUlRhz3pN7UAS0tRo2etPGKAFpKWk4oAXmjmk4paADmiik/KgBeKKT8qXvQAUUUflQAqnBp28elR0vegB+8elOVge1Rd6FbFAE/HpRx6VDvNG"
        "40AS/hRUW457U5WzQA+jH1oFH4UAGPrRj60UUAGP8AOKMf5xS0UALH1qXioQSKXcaAJeKQ1HuNBZvWgCTFGKjDGnqaAHDijNJxQcUALmkY8UZF"
        "RsxzQAu4e9NY8UgOTjvXK+PPFtr4dszmQNO3Cr6UAWfF3iKz0ixcyyJ5mOma8G8Y+MbvWCbe3byo88+9UPE/iK51u7cuWCE561hOB0oAbICT15"
        "70zAHXmhmIOBSMcgetAClh2plPKgLmmUAFFFO2k0ANNJTihpNvtQAlA689KGwPal2bhnNADe/tSmneX2zQYyD6UARheadt5BpSV6Ac00sFHNAC"
        "sQvFRSP2FDMHPSmhCTigBvWggAdaccr1zTkiLc9BQBGBmlAA61KYiOhxUb/ex3oAaSTQOtKeBjFSQoR8zD6UAIRtFRmnu25sAcUkmN3FADKKUD"
        "JxTyu0ZAzQA0qQKQc09QTyc0rKFGe1AEVFFFABRRRQAUUUUAFKjMjBlJDA5BFJRQBcubhbpQ0hIl6HA4Pv9ajgupYMrwy/3W6VXpSSTk0AbWnT"
        "Wt1KsNyWjUjd5i/eQ+g9q0tSt7q2It75S6cNFcLyGB6c1y1vI0cyspwQa6ePW4pLZYZ/njH3kPC/hjvQBe8Pa1c6JeLJv3xtjK9jXsXhjxPFcQ"
        "wyJcB4T94Z5U14TcSWjoWt9xiJyFPUU/R9YvNJuhPa5eM8PH1BFAH1RFJFzIj7kb+IU6vP/AfimCa3DLKJLWUbct/yyf8Aumu6iYk9eMUAS/hS"
        "0nHtR+VACMdtJ5gps5xjFRg0APlbcKipSaKAEopaKAE7Ud6Rjhc1Fvb1oAkdu1RHk0p560UAIeBUJ61MeaiI56UAMZscUw9adIOabQA00xjhc0"
        "5+BTW5WgCJmyabS7RnOKMD0oAhduadb9DQ8a4zSKdo4oAz/ECbo1Hsa5thhGP1rf12ZhtGawbjIjIHegCi10sS7SM1q6HItw+V6CuZ1GOQ5K5F"
        "bngpJFB3HjNAHWdsUoi460jZ5xUg6UAEUeHGK07UYqhF98VoIcAUAD96gEnUGpnIqIqACe9AHCfE+XNkYs/wZrxa94OPevXPiy3lQqV43DmvIb"
        "k5IzQBJEMIKKF4AooAKKKfGM0AfYBs1AyTVS6h+bKDgda2XQYxVaRABjHWgDGKnByKTArSnjAibjtWc4wKAEyAaFIJxTTn0NEf3qAJPxo/Giig"
        "A/Gj8aKKAExR3paQ9aAFBxS7qZ3oHP50ATD/ADzRSL0paACiiigCRGUDmnh1Y8VBTovvCgCbvR2o70dqAHLS5plFAD80UylBoAdRSbqM0ALRRR"
        "QAUUUUAFFFFABRRRQAoOKSiigByGpA4HU1DS0AS+Yvr+lHmL6/pUNFAE3mL6/pR5i+v6VDRQBP5ik9f0pRUC9anFABS96Sl70AHekpe9JQAUve"
        "kpe9AB3pKXvSUAFL3pKXvQAd6VTSd6SgCQNTx0qHODUy9KAFopOKOKAFopKKAFopKKAFopKWgApVOKaaM0ASFhimk0lIxoAC4HWo5JVUcmmucn"
        "mud8V6zBpdq8kkwDAHAoAi8Z+L7LRLCRg+6c8KB1Br598Ua3ea1evcXUpIJyqk9Ks+Ltdk1W/eaQ/KG+UGuddTKcpQAwsS3FSMRtGDzSqojXDD"
        "mkQbVJPegCMISaUoFGc80jPzxTR1yaAG5ctjtTjQeTRtagBdvvSBj2pDycGgIRQA5V3ty2MU4uFyoGT60xufYU5YmA+UEigBhXeeamRDtx6UKs"
        "a8swB9Kjmnz8qGgCXckYOTzUEzFxkH86hCszfMTT9hHQ5+tADAdp3UpzJ0qTbuG2pooVQcigCqsRzzxU4TIwOoqR1BPpQAB0NAEXlYOW5B6UrH"
        "YnFOkZV6mq0uWO8HigBxkJpoiJG7vSohbntU8XJzk7R1oAZBA2NzCmSl2bYvSpp58/LHnBqvtxySc0AW4rCTyPM2hvoQapsp3lQvI9RSb33fKx"
        "H44qwpkkXa+DQBAgy2CKlZSMADNSqiIh3ZDdh2pIQ2S/UUANVAqEnvUM7AjAqcyb5Paqs5BkOKAGUU5F3ZPpTaACilIIpKACiiigAooooAWkpy"
        "jOaNvrQA2rUChlwarkd6dHJtoAuLvi+63y9xU8bcAg8HtUIcyQDbye/0piMAcAnNAG7omsTaJdCSIlreT5Z0PKsv09feve/A/iCDVdMjiWTcyD"
        "AY/wAQr5xB+XDcg9RW34Q1y60jUIAJT5QfIFAH00rbMhhThICcVl+H9Sh1fTorhH3OVy/oKvpgvxQBJMu7FREYzVjI4qCXljQA0ikpSaSgAooo"
        "oAR/uGocH/JqZvu1FQAUUUUAFQnr1qaoj1oAjk60ynydaZQAyX7tNP3adL92mn7tAERooooAbJ92owOBUkn3ajUnHagDF11WMgx2NZuwN1ra1d"
        "dzA96z2UGgClNZxSAcCtTRrWOCNtvXNVSMcCtaxT91mgCxH0p1IBinKMsKAHQjMgxWgeFFVIk2uOlWpPuUAREk96WX/VCk5pJj+7xQB5f8YZ1P"
        "lRD72K8om5cV3/xTuPN1sx54UVwTj96KAJgvyikUZpd3GKdFQAwjBqaBeM0yUcZqa0G7igD7KxUcikngVY2CkYY4oAqyQBkNVGtwOw/KtF+lQF"
        "SetAGdLEMnCjpVQoVIJGK1ZYzuNVZYwwwTjFAFSillGxtvWk/CgAopD9KM+1ACf40d6P8AGjvQAd6B2+tHegdvrQBKP88UtIP880tABRRRQAU6"
        "L7wptOi+8KAJu9HajvR2oAZL2qPJ/wAinzdvrUdAC5P+RUsf3ahqaL7tADu1HejtR3oAVe9Opq9TTqAAUUDrRQAUUUUAFFFFABRRRQAUUUUAFF"
        "FFABRRRQAvNLuam0UAO3NTkJJ5qOnx9aAJu9JS96SgApe9JS96ADvSUvekoAKXvSUvegA70lL3pKACgE570UvegBdx9aQE7h1o70qjmgCWlpKW"
        "gAooooAKKKKAE/Cj8KWigA7VAWIY9anrP1S6W0gaTdg4/KgCj4h1aLTrSWU4JVSTzjFeCeOfENzrF9vEn7oZwAa0fiB4ourq4lthN8hJBANcG5"
        "d5Nqk4oAbKpZsnkUIpUZFOl+UYPJpqn5ck4oAGdAcnmo5HZmwPu0u0ucDFLtaP5Rg96AI2QDvSbTUw6ckZpv40ARHrSpuP3TUqRK/1pREA+0Z3"
        "e1AEOCpyakQNJ0HFWPJ2cysMVFJMqZEQxQAMqIMGoZZwoIibHrUMsrkncaaiF/u80AN+++WNShF7U8Q4HIyaADnGKAExzTooyx605ImZqmRPL7"
        "0ABiSPknmozIWOAOBSuctknIo4LAYxQAfMOcUgIAJfjFWHdVTbjPvVSQ+a4UcD1oAgOZJM4+UU9ULYCjipmRQdoqTAQFQcZHWgCMDB2r+PtTZH"
        "K/uYgNnc+tLuCKQg69TTAD2oAbGpBKgcDvUsq/JwBjpT48KORSSAscDqe1AECRZ96nKYQYqTyvJjBfgnoKillCRtkcnpQA3DNKI1PB70XrhF8q"
        "M9ODipIFEVqZH++33faqhJebPXHWgBY8qhzUB5NWZP9VmoreMvKAOgoAk2+VDhupquoyQKt3mGYKO1MCADd6UARTAAgD0puPl3UoBeTHqakdeN"
        "g7UAQgcGkqRhgYFN2mgBtA60U5VJ57UAOAx/+qjGf/1UqKWcjPA701j8xA6UAK6gLwaYATRk05T2oAms5PKk578VZaILKSOQRmqhXcoxxVhWLK"
        "ATyvT3oAdC+JfnOV9K0I40unWCMhZj/q2Bxu9vrWcdrr8vDd6dFuwVOc9sHkUAen/BzxDPaarJpF020tlQGPIPpXssbLjhs4r5m0O5druK4Rgu"
        "oxNuDFseYB2+tfQXhfU4tX0aK9h4Lr86nqrDgigDaVs96OtRw96koAMUUUUANpwpMUtABijA9KKKAIH4Y0lOf75ptABUJ61NUJ60AMl7Uynydq"
        "ZQA2ToKgcnJqeToKrv1NABRRRQA2T7tR1JJ92o6AM6/wCT+FUcVev+v4VRoAXA4rVsseR+FZSnL7a1bT5YvwoAkoHWj8aKALsak4NTMQFwaZB9"
        "z8KJRkUAR0pYbDnsKOajnOInPtQB4b8SJBJ4inx2rkDy4PpW/wCNLjzNeunHOGIrAjORn1oAfTlptFADnJ2Dmr9gox+FUG6AVpWQxGDQB9jZHN"
        "Mk5xij8aKAG4qNlqU9KbQBCyZqN4FAzirVNk+7QBk3kIzkLzVQqw6gj8K2mXNVpoSBzzQBmHrSf41PMnPAxUZQgZoAZ/jR3o/xo70AHelApO9O"
        "U4oAkFFAooAKKKKACnRfeFNp0X3hQBPSdqO9HagBkoJxio8N6Gp6WgCvhvQ1LH0p9JQAdqWk7Ud6AFXvTqaKdQAUUUUAFFFFABRRRQAUUUUAFF"
        "FFABRRRQAUUUUAFLg+lJUgHPWgBm0+lPRSDyKeBiloAO9AoFKKAEpe9JS96ADvSUvekoAKXvSUvegAoAz0oNOj60AIVPpSYPpUxooAiCn0p6jF"
        "OooAWikooAWikooAWikooAWko4psjBV5oAZO4VCQwrzX4n+JFsrUqjAswwOfeuk8W69FpVlK5ZcD1PWvnvxNrE+s6o91NwpOFUHgCgDPnna5la"
        "WRssxzSCURIcDLGmNgDKjmk2NtyTjNABjfhiaaQd2McVPbxgAsxFITjIHSgCJztGFojBUc8k8059o+Y0qKXcbck+lADCFHsacsbN90E/QVb8mN"
        "BuuTs9AKjmvo418uHbj+dADY4sZ847QPzpjzBSREOB3NRGUtyR160ABjhRQBFJI7nLE1E0nbmpZhtJU8N3HpTPIZgpI7UAIkQP3Tkmp4Fw22NQ"
        "D3oiiIxipgu1flHzd6AGF9pwB9aVFEvKjFLKmQvOAeppWKxKACM4oAfuES7e/rVdpsMQXBqGednbao5p8FqZeD1oAdChlfjpU85WMAY5p4Vbf5"
        "Qao3MjuxC8+hoASWYs4UAmnxjjA4JohjAiBPL1Zhj2gMRkn9KAEhh2fM5yTUUxGSKnu3CoAvJ/lVFmJbk5NAEkC7yVwfWpREBU0cflxgnhz1Hf"
        "FRsGd8Rg47mgBrrxgDNSiHykEh5PX6VLbKpk2n+Hq1RXEhllKD7i/rQBXYu7BpMkZ4pI4A8nmSH5V6CpQ3y4YYUdBSTEJGD2oAgvZW3YAxnoKV"
        "IwiDI5PWmQ5ln3v0HSp5pFJLdABxQBUmbLeWPWrkcX2a18wjk1Xso/OmLN9anu5TJiLOQvFAFcAyYbHNJcPt+UelTKNi5PFVgGkm555oAmto1V"
        "GcnntUanMjGpZiFAX0poXI3ZoAaig5JpswAXpUgwq5PQVCSZHPp2oASAAtz2qwqgIeKIIsLk1KB2FAFbcIwVHU1BipJW/efQYo24QUANwKMcjA"
        "/SlxnjmnqCGGaAHDgU+Jgrhj25ptJjLCgC26qk6svKtzTkJkO4DbtPX1pkYzEQeo6Ukch8zBOBQBdQqCCRhs8EdzXpfwj8QrFfyaVdELJK25VJ"
        "wGPqK8yYgpwOe1T6ZcTQXCShilxEwaNhQB9P7WVyFOR6ipUztGetc/4F11dY0KKdmBlA2uvqR1roQcjNABRRRQAUUUUAFFIfSlFAELg7iabVgj"
        "IqF1wM0ANqIg5qXvmmyfdoAgkB4plS1G33j9aAGSdBUDfeNTy9BUTd6AGUUUUANk+7UQwBUsn3agYfLmgClffe/CqOCKt3T5fFQEZoASBQZM1s"
        "2igpyAayYIyXFbNqhCZoAfsT+6KhdSG6HFWKbL9w0ATwfcH0ofpxTYv9Wv0p1AEdVNYlMNlK6/3D+dXPzrP1xC+nzgccUAfPGvSE6jOW6sx/nV"
        "CL7lXvEaGPUpVPPzEfrVOP7ooAd2paT1pRQAJzIBWvbgLAOayoB+8BrUj3GMDFAH2BRSZoyKAA9KSlJ4ptAC0yTpTqRxkUARU1lFPNJigCncRg"
        "kfLUBhHoa0JFJIwKYy8dKAMy4jCKCo71D3rSeM49apzxPvJA4oAg70Dt9aeyMq7jwKYO31oAlH+eKWkHT/AOvS0AFFFFABTovvCm06L7woAm70"
        "dqO9HagAooooAKKKKADtR3o7Ud6AFFOpAKWgAooooAKKKKACiiigAooooAKKKKACig05VLHigBtFSeWaPLNADB1qYDFM8s5qTNABSjpRxSd6AF"
        "pKXvSUAFL3pKXvQAd6Sl70CgBKXvQBmnbDQA5V4pQuKFzil5oADRmjFGKADNGaMUYoAWig8UmaAFooooAKQ5pcHGaKAGlsA5rK1rUIbazlmmk2"
        "Iik5q9eOEViTwBk+1eIfFXxO9/qDafYyBYkOJCP4qAOf8a+IZdXvGj8w+QDhfeuZdFii7kmpSgx8/bvQQrQl5CBj7ue9AERCRx+Y3J9KjjLTZk"
        "I2L2GKfDGZjvfp6etSuMkcAUAQMr7cDgDrRFEZDlc/WrARnYALle5q2scaKMMCPSgCkkCh/wB6wVfU0+aZEX90oFJeMX+UqW+lVpYVjTezgj0N"
        "AFeUzTybuSo65pFRAc4zUnmjBwmwVCzgZoAcz7jhRimFW7Dntz0pYUeQZVcClC4kGGLGgDSjd57YNqITbGMK4XEh/wARSyxhyuwYXbmmQQGfqO"
        "BWtcIiJGEhwAgGfegDNjgyOQePwpZPKjiYnjHemX95DCMAh29KzJHlnbMp+Tso6CgBbi4JJEXzA9TUQLSDbu5qVIByVYfSrlpZAgNjGaAILWxZ"
        "/mA5FXvlt0yfvCpnZLZPf2qhdSluetAFS5Z5Hwh4qSBCi/MMmnRr+Aq3ZxpIpZzgDpQAkSqVyw5ps8qxj/aPSn3knlAY4J6Vnuxck55PagAJLE"
        "46nrU9pCN29hkDnFLBD8u49qt2satGzuwVV70ARSf68N602fBYJD8oB+bHeieRp2Kwr8vdqlWNY4QE+Zu/rQAhYvH5UfANRhNi7Dx71IoAJOcE"
        "/pVW7lyxUHpQBHKTNIAvCr3pJ9zbYhz61JhUiDqeT1p9igZtzUARSIYolVRzVefJdYwevWrcjZlduy9Kgso2mnMr/dFAFlFS0gI/iYVXhXJLHv"
        "TrlzK+ew4FORD5eeBQBBdM2MU6xG1DIw4Bpjgs2B61PL8se3tigCG5+aVVHc5p+AFIHSmwqd+5qdMdoNAEM5OAPXrT4IhnOKZEhdtxq2inIzwB"
        "QAImT04FRk4f2qaQ7EOO9Vskru9KAK2NzD3NTyDAxTYVPUjvmny5LkjpQAxFxzTn6U5RkgDvTHB349KAFwcUrqQRipljBiPrSFGLBR35oAlg++"
        "CelMljHmnrjtQh2xkHqKkPROM5oAkB+VR6U5CQ+7vTUXOfanFCKAO9+EOs/Yte+yyufKm6L2zzXt69Oua+W9MkMN5FKpwyuDX0P4S1EX+mwPuy"
        "WX+VAG9RSqCxwKd5belADKkjXcpNJ5belSRgqpBoAhPBpKeyHk0ygApkoytPooArnIxTZPu1LKBmo3Hy0AQ/41G33j9akqM9TQAyXoKiP8VSy9"
        "BUR6GgBlFFFADZPu1DJkRVORkVFcYEdAGRc438etItLIMyt6ZoC4oAlthl610G1QBWXYjDkmtUkAc0AFI3IxRuHrSjk0ASqAEWijjaBSZGcUAM"
        "rP1mQLaSrjtWjg1meIiI9Nmc9QuaAPnrxMSdVmP+2apR52irGtSmTUpD23Goh0oAKWko57UAT2h+fkVr27ps5FZVmMnpWnbJ8vNAH1srZp9U0u"
        "ATjpVlWyKAHUUUUAFKBmkooAjcc00VKeaQrQBGaaw4p5GKbQBCwpGUMNuKmK0wqQcigCjPESdrcCq0sYRwBWnKCwqB0+blRQBSUmn1OVXP3R+V"
        "RygDBFADKKKKADn3p8X3hTowCtPwAeKADvR2o70dqACiiigAozRRQAdqXvQBS49qAFFFFFABRRRQAUUUUAFFFFABRRRQAUUU5VzQAiAsamC7RQ"
        "q4p1ACUveg0d6ADvSUvejFACUvekpe9AB3pKXvSUAFL3pKXvQAd6BmjvT4wMUANQHNSikxS0AFFGaM0AFFGaM0AFFGaM0ALQAKKVeTQAh4pVGa"
        "eAKMgUAIw+WmZABJPAFSbhXP+KtZSwsZSDlyCBigDmviR4o+xWkllasfOlHLDsK8PuB+9eUsS7HJJPWtzxRqsl3etudi3dq51gctuY7cdaAGMS"
        "0bFvujt61FtM5DN8sa/dWnLmZvmOI06Y71ahiVk3lgoHQGgAhG4HsB2p3kqTksAPQ96dG75/d7AO+R1pz7Tk7cUARAMn3M7T2NN29d521O1zDH"
        "EM8sOgqhcytNzIfLi/hoAZLclTstlaRj1NQECBt8pDOecZzTGuEhcrb5yeM4pI7V2bzHySfagBsjNMeDgHtQkABwxH17Vo29mzDKxN+VXbTSZZ"
        "jtKFYx1yKAMhUlk/dxcDvjvWvpmkGQAupQDksa1IE0uxHCl5SOGxkCs3UtX8kN5EhcE8j0oAfcXFpal03jj7uKyb69uJI1KsVXoPeqkrtcSFwv"
        "zGr0UaLComOSKAM5YwdzsMsTnmpY5FGA67vUCrEyrKyonyj271estNQSL5nzHsBQBUtrcvIGRSF7g1qsixRZAqZA1vkFV2D1HNUNQvlJxGuRQB"
        "TunZckjJ7VVhwxJPU1JJIztuZsZ4AqWCBnxtGRQBCUaRgsfJzzVmXbDBwTuXt61Yn+zWFruHzTP+lY1xM3Xks1ADxI1w2eD7ntSLGWm2oCfU0s"
        "cbLGOCSwrYtbdLW1LuNxIyKAI7eNIoysuDmq02+RypHlxDjHrUsaPeTFvuxg5OajvpGkfy14QcAGgBhcRr5cPJ747CnWreXucktnrUkVuIAG3D"
        "5uDTLpxCMLjpQBXvHAXdG2d3SoxEdoJ6d6jhBlfdj5e1XlG9No6CgCBVZyAORipp9sUIReHapNnlAuT24qpNIdhll+9/AKAIZiXZYo+v8AFirT"
        "j7Lb+WepHb1pNOjCEyTKdzcg064CSN+OeaAK8CZOTT55MjYtLJhen6UwYJ4oAZDHhuallw2FPanqu0bj+tRqpaTIGRQAoU7cADioLg5O0danmc"
        "jhf0qOKMsc45oAdCgVMmkkkYHAHFSuwVOetVXcswAFAEhckEHNMAwtSIozzQvOc0ANkwAoAprKcZFScMQKkRBhs9qAI0UArTJExPx9Kntx+9GR"
        "xSBQ0jZ9aAHR9Ce4ppJC7R1PNPxig4GD6UAQvIS4bHA4qwpyqnqKrSruJIqaQMIEI4oAVVeOTfn5GODVpQZYGC9V5FNtSbi2kixyvIpmnvtkKE"
        "88igCSEEkt0yeK9L+E+tE3H2SR+U+6PavMzxCWHDA9K0fCeoNp2sQz5IUnDUAfTNnL5jHHTFW6x9MmUwwyIflkQEEd611oAXvSd6XvSd6AEk+4"
        "ar1ZqORPSgCKjPFKRikoAik60xvu1Ow4qBhzQBEcioSOancYNRsOKAIZOgqI9Klk6Coj0oAZRRRQAVBd/cqXvVe8b5aAM0/fP1paYx+c4PenJz"
        "QBYtev41pv0qjZgZ6d6uydvrQA3HsKkX7wqPHsKkT71AEvpTf46d6U1vvHrQA6uf8AHMwh0Wdh1MZroM4xXH/Ey4CaHOuRkrQB4LcHddO2epqU"
        "dKiQbpmPvU7DAFADaUUlFAFuwGTWtAPlNZemjLVrQD5TQB9LRzZccY/GtCN+g9qxUf8AeDmtCGQFl5HFAGmrdqcahUg4waduOetAEvNJ3pFNAx"
        "mgBcUUUUAIUzTSuBmpB3prfdNAEWKCM0UuOKAIiuDmopF3NmrJFMK80AV3QEcdageItznFXGFRSDpigCo0RHek8s1ZK+tG2gCJRgU7vSsKTHtQ"
        "AUnal/Ck/CgBaKTr2owfSgBaUCm4PpT1oAMUUUUAFFFFABRRRQAUUUUAFFFHNABTlGTQoz6U9RQABBTlUDilH4UvegA70lL3pKACl70lL3oAO9"
        "JS96SgAo70U5Rk0AAGacEp22lxQAzyxQEqSigCPy6UDbT6TFAB2oA5oNLQAUoGaAKcB2oAAmaNlPHWg9aAGbKNlOooAbs96ULilooAXHvTWXPe"
        "lBpjtigCtqEwhhbnnFeY/EDVEis5Fcne2cc13msTZD4YYjG5jntXhfj3Uvt+pSbG+VTgCgDmrmUyOSTkk1BMS67QcUr9TzSdsjp60AIoAUAdqU"
        "B5SFAJTuM0qRvI+0ZA9asFPsy7dwoAelvtiyWBqG6mSOLAbnFRNI+GYsQo96oXTu8gCLkHoaAI5LhlfJNG+S5OQcD3Fadh4fuJtszjCHuTXZ+G"
        "fCmmOwa6kec90X5V/OgDkNK0ye7wtrCJHzy2OBXXab4TvYAH1GYLD1+QgYrrxpWl2Sboka3jUfwkVzWtazCyyQQs7hT3PFAF1bbTrCNioLqBkM"
        "/NcprWqs6k2+FjLY44JqCa/wA4ctJKgPEeeKo3XnX7eWm2L0ULyKAM/Ur95XFumUUdAvU/Wq6wM8e/n3rYi063gjZJXzKerVF5TkYhHyDjgdaA"
        "KA2qowMepqewhe6YxAMwPRsVNHp5ZszNsT2611Gj2kUNmWiURxt/y0fnd9BQBn2elC3VTIgMgq7+7XJWP5vYVPOwDqkIye5JqzeyJpmntcXCKW"
        "YcA9RQBzuuOIrcHPzt0FYGCWGCWY+1Ole5vLlp5mIUn5R6CtCygPlnaAx9TQBWhsS53TcAdqnnlW1j/d9qW6l8lCmfmPeqqoSu58k+9AFCZ3ll"
        "EjnKnoKsW1ozS+ZLgJj5eKf5YLcLnn0rTtY44133OWGPlHpQBFHAuBnii4IGd5woHFSyyKAXJ46isq6d5Jv352qfugd6AJJ7iW5lEUA2qO471L"
        "FEVkBkXIp1rGXIx+7UDg06eYRId53YoAZdOiqxJGT0HpWUfNuJNgOcGnyGWZ93X0HpViKMwRA4+c9KAHKixReWVG7IxTlRo1LOCo7VHbxvNcZY"
        "9DzzUuo3KvILcD7vegCCd3fHPA7U14/NkV2X5VHFOAyKV5CECAUAPWQkgHt0qMg5NKQR9abkngcGgCCXPrmnwJyCaegz96pcdPloAV8H5ailkE"
        "a4HU0TPtHA5pgiMq7zQAkClpOfunqankCxA7GpSyRxbO7VTeXLjrQASHjmmKDvHNObJbFOjXMmBQBMqHvTGICtjsamuAViBzUUSg5zQA2JMSCp"
        "M53+1PhXex9qekeA5PegBIl4V84zTI4/3zgnpUyg7FGOhom4fIHBFAELdM1GxzxT87gcU1hyCKAGxLvcLnGanbmDj+E4qCM4lBqcHEL/AO8KAH"
        "6fL5bls4zwaV4wlxuToearupSIHpk5q5a5li3ntxQAjLu284x196QjHOcD2pN2JdtPbBJXOM0AezfCrVpbvRFspZNxt/8AVjOTjvXpMJDRIwOc"
        "ivCfhRfC3u5Ygdjh/X7y17Zpbs0PynKgcUAXe9A60lFAAaO9FL3oAjkjySwNQDpVpvut9Kq9qAAnioCfmqY1AfvUANk6io2+6afJ1FMbpQBBKc"
        "AVGBkCny9BTR0FAEZXAzSU9/u/jTKAGuM1RvDzir7dKz7v/WUAVPL+bOe9KFwcU/v+NIfvCgC5ZjnFXGG4VBZJ36VZoAFiB9KUJhqA2KeDkZoA"
        "QnGKaSCSaVqSgB33u+AOteSfGLUn3C2jbAJ5r1osUjY47V4J8TbjzdYK56ZoA5S1XLnJ96ncZ/CorUEAmpiP85oAiopzLQo5oAvaeu3B9a17ZQ"
        "UrLsQcDitm2A2cCgD30DFT20gDgGoadHwwNAGzauBU+8VkwTv5gXI9KueY340AXAQaeg5qujnYD3p8bnNAFiiot59aXccdaAJRTW+6aZvNIXJF"
        "ACUuaTNHvQAUcUtFADWXI4qNl21LQRnrQBVdc1FV1lGKgKDPSgCGipio9KjcYPSgBppCKUUZoAF46il4/u0g96KAF4/u0H2GKSigAooooAKKKK"
        "ACipVUY6U7YPSgCCnKMnvUuwelAUDpQAzy/rR5f1qSl70AMRMU/FHejJoASl70GjvQAd6Sl70lABS96SlFAB3p2w00feqagCPYaVVIOakooATi"
        "ijFLQAcUlFKKAE4ooIpyCgBtOUZpxUZpQAKAFC8UYpc0ZoASiinAetADaKkCjFLtFAESin7KcAKcO1AERTHIBqpcuCDnIwKvlguSRkVheJb2K1"
        "s5JCedpJoA4P4k64tnbvY2z4lkO5jntXi99db525JYnk1r+L9UbUdUkl3HIJAOf0rnygOWPUUASIw+8TStN5hWNE4zVXqeDxUqsq8rkGgC6HKD"
        "bnFQsFYl3fJHY1BuPJLEk0w5Y4JoAsKUMg837npV20WJmxBarHz94nOapxzRkbNoPuau6c1lEWNzdsp/hRVzn2oA6HTYbW2XzrnEhHTL8D8Ks3"
        "Piy2jIjggRyPQVhw2xu3IhjmXdwqMOtadrpi2EBl2K79wRwPoaAGXWqahdK0ijy0I+6xqnZW1zcBnCMIycMTxWsmni5UXNyQqhhhc/M/4Ut/JJ"
        "aoPNCheiRjrj3oAz7m1EFusKxAM/C+poS1+yI3mrtlx8x9KltxKk4vJgX7qn92qk0hnnlkleQRnkuwwD7CgDIZo2kaRwVhBznPU1HJqF3cSCKI"
        "BYgcKqL1qV4Z9XvRDaqnkpycenc10GjafBD8qQbiO57mgCtpejPIpkuS2zGcd6vmV1BjY5A4RQtXpbfaShcjPJx2rS0jRxABcTYlAGVBoApabp"
        "ogQ310QAo34btXF+ItVjv7+QrhoAc4znmtHx54hlvZ/7Os9yL91gPWqOj6VFZOj3QaQkAkEcCgBmnadLchLqdfKtuwPBNWb24t0BitApQcZqzr"
        "97HdqIoX8mIenSsQgE5J2qvf1oAR40c7mbn3qvMzs+E7flVnYGiMhYBO5NWrCylnjO2Fli6iVu9AEFhBI5zjGO/apL2ZI/l+YydlFW765gsE+z"
        "oys7Dp3FYdy0iZJUvIfXtQA6ad1YKgDMf4TUtpAXbfKMDufSq9pBJM2TyB1Yfyq9JJFHFtjJx3FAE1ykH2cvDejAHPFYs8bYLeYGycYBp004D7"
        "AAEPJA6Gi2KvJveLaoP50AFrEYhucjntTpQ9y+xM5HWlupY3lAjPBOFAp6qtvHuY7GPU0AOJSGLyUxv9arxQlmJk61JBFLI5mYECi6nQABWwe4"
        "FADZwEHy9aZCCWyxxTUcM/U5NTzJtTb3oAhnkUNxzSK+faowCjZPIqWMBh2oAdg9akbAj96fEoVcdajkTDBgTQAxF3nHTFDvtTAPNFxKq/d4NQ"
        "jJBJNACHPemlcmhXO/B6Usj9l60ANGVarI2onmnq3AFOt4VZA7jtSCMS3QHO0CgCJ92zDHmnW4yxHapbnB4A6U+0jXJNAD4UCxufWhAQq571OE"
        "G0r2piKGcL6GgBJV2Y9Kil+6Pep7zJ5XoKroDKwPZaAHQQ7Y3LcE1AFxGT71qGMNGSfSqLIRuXtQBUiHNTMQqMD6iol+WYKOhqW5BDmPucUAF2"
        "pNsrZ71Y0w/udlVpSTAIz65FTacWEoSgBlz8k5z60Z+cMRgVNfw7gXHUGhlE1nuAwV9KALWjX76bepdxnIVvmHqDX0H4C1AXmnoyuCSor5rhO6"
        "EqeR0r174K37fNZs5yBhaAPWz1pKXtmigBKXvSGjNACP0P0qqKtHkUzyl96AIDUTpg5xViVQpwKjk+5mgCqVJbimOCM81N159qicZbGaAK8v3R"
        "TR0FSEZJHpTWGDigCN/u/jTKe/3fxplACN0rPu/wDWVoN0rPu/9ZQBB3/GlX7w+tJ3/GnQ/NJg0Aadv/qxUgqKM7VAAFPVjmgB3enjoKZ3p46C"
        "gBH7Ugxmn4zTgooAhuiRbvz/AA187+O23axKSejmvoLVXCWMzdwpr5z8WTeZqsxHQuaAKVqPkqY0yBcRrtqYL60AQnrQq/NxTn4bilQjI5oA0b"
        "LoBite1U7c1kWYPBrd09Q8eTzQB7p1pyAjFMXrUv8AjQA+H/WD61dUjnJqgpIbI9asxOXJzQBaVgAOTUqupOFJzVbJwBT0baelAFgHmnhh61XD"
        "5PSpAR6UASqQelL+dRK23tTt/tQA/wDOimb/AGp6nIoAWijik4oAWik4o4oAWmOBT+Ka4BoAi4prrkVKEFDKAOKAK+zjpTD1qwR7Uxk9qAIjjA"
        "xSUpBBxSUAFFFFABRRRQAUUUUATp0p3emr0p3egA70lL3pKACl70lL3oAO9JS96SgApe9JS96ADvSUvejHtQAYo70UDrQAD71TUwCn8UALRScU"
        "cUALRRRQAUAE0qLk4p4GKAGhT3p4x2oz60qgUAB4pKU9aKAEopaKAAdakAqPvUo7UAHSkyaOpp2KAEpR2pKVTQA2TAU5rzb4nXsdpptxl/mf5V"
        "Ga9Bv5RFC7HOAMmvAPixrDX2sfZ1yIoR69c0AcDdSozkg85qpvYtTpx8x+tMRcnmgBSc/KODUiKeARSRYzgjmps+WCW5oAZImw8c0zZuIycUsf"
        "76U5JA9aeUJ+VeTQA2NWZ9pHHtWzYWSInnsSijnOKqWNtID5m3JHQetdDo0N/JcoXhURgjapHAPqaANGwhka2WUs8Nsxxgj96x9vaugsoVhCNK"
        "EO4fu4h1xTdPthHdrNcEzTY4PYD2FXLuddjyo8Vvn7xZcsfp6UAZcksMM8zs+ZVBwHOET/AOvVSz055I21CU7mYny45RkZ9fpWhZ2jyXDzyGA2"
        "zHLKRkt7nNLqd0TKIbJ0ncr8zEEbcenagDntQWOOOREd5LmT/WbT8q/T0qhDp11qLLbus0dvnOA2TXS6fZiWzIkuPJlJyfLUc/iathFgiJ/coE"
        "HzSMvJoAp2OgW1vD5ceQuMsqDGT71JPd6dZR8MolUbd5PK/hVO/wDElzbrstxDCdp+Z3GWrO0+x/tmfzri7laRjyirx+dAFzR92r37rHu8uNvn"
        "fHDVt3V0un272/mDkYDZ6VPsg0TTY7O0jctIPmYjmuX1Zg4SHBaUHBNAELWsUm6ZbdGxy0pHOawtT1JpnFnbffB+aTPatTVb+SzsTaLcKXf5WV"
        "OaxI4AFWGJQXzlm70ARRwyM+FjaZ+7DoKuLbiaRE2Myj74xWzoumMuJC5HogHX61dlW3sWbbHulz93qRQBnnSIYwst3hbZeVi7mszVtWmYmC1X"
        "yohwqj0q3qVxIwaa4c4z8qd6zobQ7hOzcnlG7L9aAKMMTM5kZWZ26se1XLLTDKzF5QUHLNngj0rQhFsH2s42/wDLRv730qlrF5EHEVsDHAOAM8"
        "n60AQ3FwhkFtaRiKNTgnPWq100ceV3c00TCMHaAD396pusl5KMZFADoIWuX44UHrVq+fbGsSY6Y4pGWS3QRIcE9RTra2Zzuck96AGWVqqDzGBL"
        "ngD0qYQxu3704UeverHmRhNg/Os24k3SMpJCjrjvQA64u2GIrcEAcVTKMHO5tzHmrEeUVpGYdPlFRW6uXLP1NAD0jZWV2Ip83I3A8VLIBGnTOR"
        "VeFHY5Y8UAORC69KcEKj7pqdQFGAKTeqn5hQApG1Nx4FQTSjHy80y+nMkgRDxiocENg0AJy7fNT8c4pO9AR2cbelAAse5+AanECLIA/U9KkVRG"
        "mQMmmIWe5Vm6ZoAtyoEtjjiq0HyyE47Vb1A7owo4OcVXSMAjJoAI4ssd1TwqEbpQi7SaljGTQA9kwpNQ7DGC/ep5ThKhc7hg9KAI3YYx3NLHH5"
        "a8d6ib5nHsa0LRN3BFADoQDGue4qrdIATWiYwpx6VRvMUAZbqPMJo1BmE8agcbRk08geZ9aW/TddIo7qKAK8rN9qVP4QBVqAhLrLcKelZ93J/p"
        "DAdhV2P5vLIPHGaAL9xCHPyk4IqOyjyWgHQg1fMYGz6VTjdVnVV4dX796AM5cpcNGR3rsfBGoNp2rWs6kBHfy2yfWuX1GMR3rEdiDU9o0hz5ZO"
        "Y+R9aAPqmF1ktY3U5DDNLXNfDzVDqnh+CU44UK2fUV0lACmko/Cj8KADtRR2o/CgCGf71Qy/6vFTTffqGT7tAEI6fhUb/fqQfj0qN/v0AQ/wAT"
        "Ux/vU/8AiamP96gCN/u/jTKe/wB38aZQAjdKz7oZkJFaBqhcfeNAFfvj3qSBSJOaTHOangXL0AWl6dBTk60Mu04wKF+lAEiqTyKeB0FJF9004d"
        "aAHIvGTTqB0pG6UAY/ilmj0m4cf3D/ACr5x1h/Mv39dxr6B8e3HlaDMc9VP8jXz1M2+9J9TQBYt+Bg+lSucDgUzbg5ApWBIoAiJzRFlpABTZOD"
        "UloMyjNAGxaKQnat3SkYx9BWJajK10ukRgxdaAPYx1qRaaBzTx/WgA/xqaz5Zs+1Q/41PZfeb6CgCcdqcCc00dqcKAJM/N17VMKi/i/CpRQAGk"
        "pTSUAFLk9M0lKMUALuOetPU1GaATQBNmjNMD+1L5ntQA7NHPpTQ+TjFPoATmjr1FLSMcDNACNgVE2KVmyaRRmgCOQZ6U0IanddtIKAIdg9aCQO"
        "MZqVhmmMmaAIj1opWXFJQBIgFSACkXpS0ABxS96Q0vegA70lL3pKACl70lL3oAO9JS96SgApaSnquRQAiYJqTAx0pAuDTugoAQAelLgelAo/Gg"
        "A/ClpKMUALRSYpVHNADlHNPwPSkApaAEAwadSUUAFOUU2np0oAcBQQKUUelAABxRgUetFABgUvpSd6B2oAPWlpD3ooAKM4opGZVxuOB3PpQBg+"
        "OdRXTtCnkyAzoeR1FfNHiO+a5upJSSzMcgk1678adUb7EIIW+XO0nNeIXj+ZIfTGKAKpJkbk0RnnHpTXBONvFSouF96AHL94dqmERlfa7fIvO4"
        "VFEm+UIeAe9TyN0gi4HegCGUq77I12oOPrVu0hQYMhOBUUIjjYg5z0qXIkkBmyEXsDjNAGtpNvLLMDGykjnI6V0D6gLaFYI/3143yiJR8v1Jrn"
        "47pJYREiiCJf7g5P41teH4tPVmnl+XHOS33vagDd0i6nEXnXEbAjjaoyCfrViyDTXwmugFx9xV5496r3F4m0XJKxwAYKN0+oqjDqV7PCy6bCYL"
        "Rj8zkfO/0oA6C68i4jkSLMfb5wVB9+KqI1uE8uZtqRDB8kElvxqC0hdSvm3chc/wATc1ZtZFuLs2tvulZT87bcDFAESzOzoLW0Kw9z3x9KyvEE"
        "xtyXSUK+MDceK3L7UbSweWJpZIpFXgqmea40xHW78wxgzyFsnJ6fWgCnpWnz6jdeekW8A4xnjP8AhXY6dp/2CP7ZNIA6/Lj0rS0zShYW4t49iH"
        "ABIFGoyRNMkWRuT8jQBnarem3BklcvIRmNWOQPeuOuNU/fuVG6RhhmPr9Km8TXry38kEJMkp4QLzireleE7trRZJGCTSLuYt2oAzLfTLedxlib"
        "o8tjnBrodP0ZbWAPHbxtM33nkxnHtVzTLC202HykCiQDlxyW+ppNWmNpajy5Ip2bkgnlfpQBFfGa1t1gR03SHG70rI1ENasJl+eVeM5ySaZe38"
        "i2jRxb2nl+V5G+9t9BUuh2kQhUyiTdn5IiMsR60ALFok16PteoypEMZ3f3R/jU97a2FvYeXjbFjk/3veruqssEAaZhuHICnj6GuQ1e7kuyrOxX"
        "YflGaAILu4hUBYQ2OiAVSMTKxZ8EkfPntRPkDziNzHrin2kE11hVOcfMc0AVBB502FztHSrluqRRs+MqvcetSsg37Ievc+9SyeTsUAdPvD3oAq"
        "RwPO5nmyvpz2qZ7gRLsC5Tue9V7y5Kt975egxVMSEtkZ98mgCxNMoJWMA5/MVWdS3C/rUYkALAHe3bAp8CMz5n+UDpigCUIu0AkH2qTnI+Tgd6"
        "WCHe2U6Zq5JCEUZbNAFBgWk9qlVFA4NSSRoBuB59KYrB+T8tAEYLDOelQPJweKsMdxKjp61Eibm2gZoAgjHzEkYpZFPUc1KU+bDcVKFjIAGM0A"
        "V4YS3XjNTqpicIvNSfdGPSnRDLe9AEjx4gI9R1qKJAiqxAJzVmU7IwPWlWEmIOw4PagCvITJNuI+Wmx8lu+DU8ihYxjvTljCIc9xQAkY+bfj5c"
        "VNBgAswpsaH7Nt/iz0pXXgAHgDmgBspLTBMYzTJsRS+WMMX/AEpxlAYuc5Ap1nA0khlf6igBkNu0Z+ZS3vWpbIoTO0CowMrgnBHarcaHYM0ARy"
        "gbTxzVC5RfLJKitKVccZ61n3x2rtoAxVH+kjP3au6lEEkV1/hQHNVxCd5Poau+IFEVsrZxuRaAOYc77ksOcmtLTxvBGeBWXHlZfcVqaU+BMMfw"
        "0AbQkDRxjPII59qoat+5mhnx0fn6VLCQY1PooNLrartWMjJ2ZFADdSQOPtA/5aYIqTw3IqXgWQBhJxzVeJy1hEG6BStVrSQrKSDgp0NAHtPwev"
        "WhurzSZTt8k7lz3zXqkSjHIrwL4b6gR4wt55T/AK+Lafc179CdyA4xQApVcdBTdq+gp56U30oAhcAHtSflTn+9TaAEYA9cVXYDcR2qyelV2++a"
        "AIJQB0AFQP8AeqxN1qBl5zmgCJ+Khb7xqeToKiYfMaAIyBtqOpGPFR0AMk++g9aoS/fNX5f9Yn41SlGWoAZ/D1qa0++PrUR6YqW24cfWgC5N9/"
        "p2ohA39KdIMtmiJcPQBKMDpTwBimd6eOlAC0HpRQBk4oA4L4qzGLR2VWPPGPwNeIQ/PcZIr1v4z3DJbpGo4PP868ns/mlzQBbNAFEgKmhWHegC"
        "GcYqayUErUU3zGrNiuMGgDYswOARXV6Mq+X0rk7X7wrrdGB8oUAesAc04Ud6P8aAD/Gp7MEFsjHSo4f9YPrVtcAmgBRSikHWjPegCXjNSgiqwP"
        "FSxdaAJTSU4KT0pdhoAZR3p/ltSbDQACm04qfWkFABmjPtSUUAOzg0bzTe9FADt5oLE8U2l70AA61IgFR96AaAJTg1GwwaVDSMeaAG0Ud6KAGl"
        "Qf8A9VKEHtS0vegBKKXvSUALijvSUvegA70lL3pKACl70lL3oAMEml2n0p0fWn8UARbT6U9OBzTuKWgBMijrS0UAJj3ox70tFACADPWpAoNMpy"
        "9aAHbBQFGacvSigBKKWkoAKKKKAFp8Y4pqdakoAKB2ooHagBQMk0GkJwaMHvQAUoB44pVXNSgYFAEODzxRg+lT0h+6aAIR3qlqLMIiASF71fTo"
        "30rB8SXTwWLhKAPGPibPI7yBmJUOcV5hIzFWPvXd/EGW4ebdIPkPSuDbkmgCOMktirQHFRBcDcOtPQsSMigB8mdq7R81S7lhQAcSYpknTcOW7Y"
        "qMffCn7xoAsKdoG/DM3SlKENukPI5xUcTKjZPzOOgpVlaacIq7jnkUAbGj/aLg7zCohBrqLGKEQNLdCMWiDIAHJPpmsewuBbwmExqvy8ZqS3u5"
        "TGF2BkznaTwTQBplLrWlRGt0trZG6Fhlh2rYluNJ0aEGeVgSAApPIrlzbTALJdsyqTnAPIHbFT2GkW9zOZ7mZ3jH9/kfrQBuJMuouW0+JnhIy8"
        "r8KgqW4v4tPtlNvA52nazA/fPqPaia+FtCIFjMdjGMLHgZf3+lY6uNQm3KjzEnESDKhPf3oAp373N/qIgtx5tzIclieEFdZoWhjS7HagLSt80k"
        "uMc+1Q6bYxaShuruBWmJ9efarwv7u4x5zrCD0XPCj60AOSUyLJArFmAJ3e1clrGoS3TvpdmjeaxwXA6fjWpqWoM1/wDY7K4IhPDFIzlj/dz71P"
        "pelPZzCW4LNK3McYXH50AUvC+g29ipub0A3GOcnNbihGDzSq4jUfLk9avJa+XvmlZFAXcVYVz+sa/aQwSSW7o45G09BQBU1/VrO2gHIKuPuj72"
        "a5Zbp76ZViQhFbLN3AqNWl1W+UpGzktwAOldno3hhIE853xu6igChY2UcMoSKD7RcuBt3E4Hqa0JJbbSY5C0wNyy4eUj7o9Fp1zdQ2CMoK5HG4"
        "j5jXMXkst6370EQFs7yeSfQUAUNV1I3TB8MiIfl/2/eqEcb3BLsOK0rmAz3oEab+wQDhakFnIW8tswRj75HagDJ+xy3LiOMbVX7xqSdo7dRbwS"
        "7gT84HWr13IkaGCGXYn97u1ZqRB0JUcjnJoAe0q+UYioT0HeqM8ropHOKnkeOHEj5djxzVCe6b5shSrdBQBCJl3Fdu5j0pHiZRl269BVmzt1J8"
        "xkIyMg54qSSBm+ZcEHpzQBTXzEAIQbOmasQ281wAkZITqSau2OnMXLznaAMhfWrc0scaBtqoh4IHWgCqsawgKpJI6mo7u4+7Eg/eHvTZJ98m2M"
        "7iaWZI4QJWwXPagBwCJF++c7/SqwBlJweKk2mdw5GB6UrAK21RmgBsCkuYwMmrBVIl7E0RIYhuT7wqCQh5GIPU0ARyvknNS21uT8wOO9Qup3Ae"
        "tX7cHaT7YoAaUzyy5FSWlvly7fdq9FGv2cI3GeTUTqGPl9qAIBtlkMYHQ1an+4oHTGKaYkhhZjnfj5aSVpI4wcAkDNAFQgmUIeStXby3MNujuP"
        "v4NR6PDulNzPnYec+hq5ey+cm0nIHQ0AUUbLZzyOKRELOTnihwEGQKLPfd3IjjH7tfvkUAM8nzldgMBTitawgAt95PGKjSH94tugOGcVd1OM2s"
        "flx4G7gUAVraPzLzFaksCrEOMmo9ChQwszqd4rUWCN8YyKAMOZRlc1m6mqj862763ZZDgjbnisXUu4HJBoApohNuzjvIFFVvEcxkCRHoAK3EtF"
        "xBGvUfvOfWsDVB5s7ynoDigDCJKyZPetXREyk3Gcisu5I8zA7VsaE4jR1HVhQBetlXAUj2/Cl15QXUj/AJ5YpbQ/vCx7UmpcxcdxQBnQORaxAn"
        "jmoD8lyWH3TSjiGIfWloA6TwndCPV9OOceXNya+mdPlWeyhmU53LXybZ7kuYXU4O4Yr6X+HN4t74TtJg2TyD9RQB0J6U30px6U30oAif71Npz/"
        "AHqbQAHpVZvvGrJ6VC6ED2oArzdaiboalm7VE3Q0AQydqjbqakc0w0ARU1lGaewxSUAQTf61Pxqi/wB41em/1qfjVF/vGgBpI9altwd4qOrlv9"
        "ygCdu30pY/vU2nR/eoAkxTx0pE6GloAKVfvCkoPSgDx/42SN5kSg8c15vp4+cGvQfjSw+2Knp/hXA2HCZx2oAszHLHFQ0/oTTH70AI/SrdmDgV"
        "UUZArUso+F4oAv2S/OBiuw0lSIQcdq5W0XEgruNEh3Wqg+lAHo3ej0471J5Mn92pYEwCGWgAjiXAbvUoAyaKAKAFA5oxRxSc0AO6U5Dg1Gc4p6"
        "kZ5oAsxOealBNVYyB3qZCaAJRml701akUigBjKKbsWpGINNxQBCRzRg1NtFG0UAQ4pKmKj0pmw0AMpe9O2GjYaAG96Sn7DRsNADKXvQykdaO9A"
        "B3pKDQKACl70lL3oAO9JS96SgApe9JS96ADvSUvekoAKXvSUvegB8fWpKjj61JQAUUUUAFFFFABRShSaNpoAQU8CmhTmpBQAUUU7tQA2inBaNp"
        "oAbRTttG05oAE61JTFXFPoAKB2ooHagBSAaWMFuDQqknNSgYoAXAHAopRSUAFI33T9KWg9DQBXLbVOOprnvEiNNEIgeX6V0EnKNisC8ime5yGy"
        "BQB438Wo1htrWELiRia8zCFSQa9R+KSifWViPIiBrzO7+S4decA0AQqSCBUhOOelRgHNONAEgO0ZXrUeSHJ6uaXOKFUsdy9aAHRoZJfetSNIra"
        "HecK56tVCBSjbv4qdI7TTCLf3oAvxiS4YAlti9/WrEJUyBmXCr0GeSaZbM8ICCQZ78VLaOjXoe64jQ5+tAG7CkIhSa6lkBz0HYdq1JbrT0hC3V"
        "0zpgEJIuMVzs2sK05mwqKo2qvrTIbS4v51dpyIuuZcGgDU1LUbG5ZVhjEm0YUljgflWrprPBYpKqiQ5yFQ1Q0CLT4IrqGGJbqRjwzKQfwBq9Ne"
        "mySHzCseD80ScMfagB5ea4Zp72Yxg/8swRkCm3Vpd6jGsNmWggT77MOT9KjtLSXWZzMk3kqrZyAC2PQnpVy71Fkuvslt5qxxjEj9h+NAFrRLCO"
        "zIkRWkYjgFu/rirN/runWfEl4ouAeWJ+6PSuVuvEczyS2enwDIyGuu/1x61kQaTcX94s2xUTOXLnJc+tAGjrHiqXWLjyLdiI/ul/UUzSdNe5nN"
        "r9l8yE/MZKvQWFjZN+8gEjEdEqKW7uYYWW1LQoTg444oA0IYrbTpcWyomwYfHXFVrvVrm7m8vT1Yxg/OWOPyrnL7UXLmESlk/jOeW9qu6dbT6g"
        "Egg3QR45kB7emaAGXa+ffMqzGZgRv9FqdrIzzNEDL5KgMpVeAfWtKC3hhtpLO1tyrZGXbq1JrEyWmmgyXrw2yjlI/wDWO3oPagBZGtrS3AthG4"
        "I+ebOGU1j6jcrcJlCSg4ckYLVSsBcXYaONXeJjnPcD3q/aWr3NwIFQkR/eB+7igDObT1MAkcMH7JVSdxbhmlOcjAA7Vqatei2Vk4LdAR2rk7q8"
        "aQFOTmgCKefziQTtAPBNSWVp9olCgnHUntUUNq0q+Yy/LnjmtGR5NMt/9HwHYdTQBI8lkjLCqmUr6DinMF3hlRF/2QMYqlFLLIvmELFN1Poamt"
        "0nuCCFZlPVhQBd3LJA0xdh5XJBPX2rKdri+kLlQiN0yK1o7ZA2y4JSNO3rUN5c+cWjgQLHH6CgCskccEexBufHUVBDAzFmkbOegPap495XJX2F"
        "OaPy1+XlyelACPKsSrEi5JoiCwtub5s9qRBsJkcYJ4prxYjDMcHNADZy/m70PHpUe9QfQ96e7kJkjgVTYljuU8UAW7b97cDGSBWvCijacfKDzV"
        "DSYdqGRhwelaMLKI9pIyelAEs5DHK9+wptrGZmKqMhepqPeRKuOQKub0gQIOr9cdqAIlhaSYO33VOBinapCsMEZCkyPwa0dLgVrgM5xGg35qvf"
        "77qQygYB6UAVrdPLtNmRg84qncS4IHAVeKkuXdQVIxg4qn5f2ucQe/Y0ALF5lzMFThTW/b2QtLMiJcMeSaXR9MaOZE2dBmtXUoxLGkMH3j94ig"
        "CjpFuzztcFeEBxn1oEP9qapGsfKqfm5rTv8adpC42iVxgL3NO8IaXIrNcyqV380Aatvp0aDCriori3ZWwBxWzJCBgpz9KhZFJ+agDldaheMKVH"
        "X1rnJY3NwhIBy2K7TXlBjwMZrFtbRpZlJTgUAZ9wXh8x+2No9q53UI8YXt1NdvrtskGmAkfOz5/CuQ1QZc4HYUAcvcJ/pG31NaFmxjnQDHpUVx"
        "GBKH7iizYteoM5+YUAb1oB58gPrTdXGxSo6bM023Je+YjpvxUviIhXYekYoAxohm3B9DQoHlM2eQabGf8AR1XOCW4qDnYw96ANrRohcTQ5PG8D"
        "mvePgzI6+GprR1wbaZ1/WvBtGR5bW5dDtaBVYfga9o+B109zp9+xXl5Nx59h/hQB6UelN9KcR8tN9KAIn+9Tae6knOKZ+VABTZfuGnflUbuCCB"
        "1oAgdQ3WoHGM1OzBSM1C3OTQBWfqabUklR0AI/SomOKkds8CoG4PNAFaeRvNHtUD4zkU+45biovm70AFXbf/V1TCselXIOEwaAJKfH96kVSRxT"
        "kUg5NAEqUtIlLQAUjfdNOAJ6VHOwRGz6UAeH/F6Tfqzc9BiuOs/uD3FdH8TphJrUgznBrnLMEJk9KAJyAeaiflsVMBnIqFgQ1ABDywHvWzbjYF"
        "AHasu2xvXjvW2i7iuBQBe0xPNlAb1rvNHTbCAK43R4j5o47132iR/uckUAd+elJ6Up6UnpQAdqVe9IOlKvegA70elHej0oADQtBoWgCXHGaerY"
        "xUTHjFKnVaALaHOadxUIbBNSK2RQA+jNApDQAUUUtACUufY0DrUmBQBHn2oz7VJgUjAYoAjzRmlwfSjB9KAGsN1N2D1qQ+9JQAzYPWmsMGpaQg"
        "GgCGiptq+lG1fSgCGiptq+lG1fSgCIcmpNlLgelOzQAzy6RkwM1JmkOKAIfwo/CpcCjAoAbH1p9AAHSloASilooASilooAlTpRQvSg9KACigHi"
        "igApR1pKcvWgBwp9JiigA7mgdqKB2oAD3ooPeigAoHaigdqAJk+7Tqan3adQAUUUUAFAGTj1oooAgnHl5Ws+ULHuZhwOa1JFDdeaz9XjYW+0Kf"
        "m7+lAHjHjzT57zUbi8gGQvJX2rzbXYVjYnGGP5175NaSPqV0Z1VYxGAn+1XhvjRkbXptmMBiOPrQBgiloPWgUAI3SiFi3yjrTJDxwas2Eak72I"
        "GOxoAkjSRDk4/GpIE+cso5Pc9qtrc6cHAu7Z5AB1R8GiRre4bYkz2sJ6goCaAI5XbChWU9t2ald2SIIWye9JHa2SnaJ5G7g7Ku29nasQW85j6k"
        "GgCGzsXuCu2HcWPGTXUWFhKqjei4Xqc9KgiMdvbqUSRSvIOP0p8c99NA3lRvHG/JZlwB9TQBcm1KOB2it3g87GGdU5H0qnBpg1GXzGMh2/M0kh"
        "4Puafbx6XAokmm+0SD/WCPofxqlq+vXjoYLOCKKJvlQE/MBQBZ1XVdqtpVncIpjALSQ8Af41mWltfXdyILa4dozyxLcH61HpelXEhXevzk5Zuh"
        "b8a6u3kSzcQyxKsMYHyx8lj7ntQBWl0+4sY0SKFVVsZ2jOT607UHMNokeW8xsc45rQXU3cPiJ1faSiYyasQCVIfOvFVnA3DjoPegDJn+0QW8TX"
        "LCJMZBH3qyLu4N6vlLMkcSn5m7tUmtSXWqXJSBD5ecEjpTtN0MxSkl/3p6ADNAGbZ2kDTNCIC5Y4QDk/WultdOOk2ADSMJW5Kk5U+wHrU0VvHp"
        "+0rEFuXP3wcn8RVaa78qeTG6ac8OzNgL9BQBZu5zCwunIYlcbelc49quq6gxuslVGI8HoKvSyS6hdFSVSPHzEdqcIQZ1g0xjI+OWNABa2rR27Q"
        "WxMcI4dwPm+lZ93cNYQzJYucMPnY9TWleXL2lubQcSv98np+NcpqNwZi0VqWZR/rWHSgDNv55JWySTUCxHIcj5R1qWMAvtHOKtW8Jkkwxwg5Pv"
        "QAQERReft47L61VkaWSUySqCT91fSrVx98Mh+XOAPSnx28jzLJIRx0oAjsNMuLqZTLhVJ6V0V3eW2kxra2sYJUfMcd6jhS4lXZAoHHzMei01bZ"
        "fMKnDA9WPUmgDMvJp7j97IOWpuxLaL5WzI3UYq9ftFBFjgsOgqhbLJcStKwGAOaAEglAJMgAI+7TJ+f3r8EdcVIUSYHGOOhqt5ku5V2liTgZHU"
        "0AT2EBafzpz+6xzVe7cmVm/wCWefl+lW7yZbWz+xx8mT5nPofSs50kdACeAOlAFSd2d/lPy1LaW7NIF7NT0g+YDFbmiacZZlY/dQ5zQBXjRkmW"
        "0xhI/mNV9QaTz9yHaBwBXRXFqN0jbf3rdTjqKzZrQsuApLZ7UAVbWRkXMncVo20Tyqsr9uAvrTFshgSfwDg+masglTkHGOlAGpcskFkI1O1nxk"
        "+ntWdcN5MOzOQvOaTM0mWkLOinr2qlezmaUpG2UPB55oAryztezkRRlVAxurS8OWKtI0jJllOM1FaQYj2I2M9hXR6bZ/ZLPzYsliNxB60AXIFS"
        "KB70fd+6AepNQrGLaAO7ESSc/hmrVjbmUq8uBEvLA9qztRlnvdRwuBGOFx1oAiZJda1OEHd5cXAOOwru7O2EUSoe3FUvD9gtnbLuXJbnJrXOe9"
        "AEcigKazpjgk1oyuqKSxrEu7jZvL8DsTQBnXyGaU89+lTxwi3VXI9KzZ75PPAV/c1Zj1GKexeWZwgUcc9cd6AKXiSaOUNzwh4rjL1t7VPqepls"
        "qhJVzkEmse4mk525oAr36+Wcnoaj0ld+ooR2INF65dF3dak0Pi5kbHRaANiwP76Zx/C5I/Ok8U8vKR1Ma0zTSfLY/wB5xUnihlaZIQMMQMn1Ao"
        "Ax5Rs8hfRcmoVwWI96sX5H2ldvQKBUCjLEgUAbPh9lMs8RO0uoUD15r2X4FRNBb6lEwwVfbj6V4npKu17CY/vhgfyr234LzSTXGsKwwWIIIoA9"
        "KPSm+lOIwMdcU30oAT1qH8am9ai7UAIenWqx+9Vk9KrH71AEVx1FRnpUk/3hUR6GgCGTrTO1PkpnagCL+I/Wo371J3b61HJ1NAFJvvmmNT2++a"
        "AKAFi7VP8AgahXgirUQBY5FAEkH3Ke3ShQAMChulADo6U0kfSlNAD4+hqlrD+Xbs2e1XYyc1keKJCtiwx2oA8C8ZyedrUxz1aqUI2oBT9fbdq8"
        "n1pyY2UANyR3qFzlvxqV6ibrQBPZpkg+lbVqeRmsqwHyHita2xxxQB0GiIGkzXd6SgW0zXD6CMnIFd9pQ/0XkdKAOxNJ6UpoH9KAE7Uq96TtSr"
        "3oAO9HpR3oPSgBcZoApRRQAHmlBxikooAercnmpkNVqnQ/IKAJ1anVFGRUhIxQAUfjRxRxQAq9alxUPFO3H1oAkxRio9x9aNx9aAJPwoqPcfWj"
        "cfWgB7Lmm+XSoc06gBnl0nl1JRQBH5Zo8s1JRQBH5Zo8s1JRQBH5ZpMVLSbRQBFSgVJtFIVGOKAGYpMUGkFAC0tJxRQAtKqk02pE6UAJspRGae"
        "etAoAQccUdqU9aSgAxigGijFACgZNPVeaRR3p44oAD3ooPeigAoHaigdqAA96WkPeigApcUAA09FNADk+7TqKKACiiigAooooAKr3qmSPYvWrF"
        "Kowd1AHKeIf3dnLlV8wIcHHNfMuub/7Tn8z7+85/OvqTxNEksjPjCYORXzV4pgDavdyqMAyHFAHPHrRQQc0RgtJtoAjQEt7VaQqqj1NNAVQe9R"
        "O+Zc0AaMFpJOu9AxHsMmpoNLllYYju3bpv2cCs6G5nhOY5GQ+xqzJqOoTjY9zNJntuoA2Le1sLFgL0K8g5IRt2PrVk3dvK6rbRmJegLViW7iNd"
        "0yIcdB1qxbXl3LMBZxpBGP8Alo6jA+lAHWW2+NB80T9+TVPVpL68Iimmilt1+7EhwPzHWs7zznzNRv3dF67VGDU8N8ZCEsLWNF/vP1H4UAWVtZ"
        "1tQmxLeADlgeTSWNhZ7jLliy8+ZKpHFRXOoLAUVgbi5PAj7Z9adbLe3MgF47SknKRxc7R7+1AGxLqlsliBbTeZI/ytIV5H0FNgNpG/nxzSIxHO"
        "8feqheT2Nm2yJVa8bht3RKgjW6kceZKkif3h/IUAdC2qIq+VaqrzY+Zyv3RS3E0kpEDtiZl6dyKhtEtYbdbmRGBYbYlPVj60lrILpy6QyIVONx"
        "oArPvM4toFPo23jNbIjW2ULtIyMZPWpYLIBfMddhXlT3aqM8kpuMTkhifkXHQUAPJ2IxWRgc8HvVAWzTbnJCuTyW7itPytyYPFVbi4iiO1wNoH"
        "PNAFO6iWJRDCuVP3sdSaqpd/YI5JGjKP0+XkinSTzySn7NGDH/EW/hFULxgGZYpwWB5GOGoAozSTahITJKVtx95+9VrmaGGMx2pGz1I61cubcs"
        "mIyUZv4gPkpkdgyxD7SoHof71AFGytGmIkjHf5jWhdQqI/Ig+eTuR2qUrFD8m7yx13dvpRawTXbNKrfZ4AeT3b6UAZgtZVciUZk/ujkY9TV+3t"
        "45RvMnyKOT6VdWGIMACQg6nuanKw3cUiwxiOED5iO9AFVkWNR87JF65+9T8otu07NwPUVJaxxxbpHJOPuRnnNV5Wmv5m/dYTPYUAYv7y6vd2CY"
        "weaukwLmO3Jxjn3rTuIYoIhDFHsLjDHFQ2drbw5YNhunPNAGXFaSopOPlJ4qSO2MYe6lGAv3R2q/M0hk24CD+8fSszUZp7y6Fnbk+UtAFUL9ou"
        "GlZcJTNzNIQF4zWsIoorM2r8ueg9TVnSdHd2XzI9vrQBX0bSpLuYMqHYOpNdrpmlRQxbdu3I5q1pVkkEICKFFXJZVEZUAcUAYl9axhsKAx9RWH"
        "dRPApOMc8n2roZZC85SIhtvLGs7UUiuJRsBwv8OepoAppHE0BA5QjNZ9zLAgI3c/StXdFGrITtl2/d9qzJoi8PnPgHdhEx96gDPaeedhFbZCnq"
        "PWtCK0hSIWyODM3LEjpVRreRZB/fX76jtWtBYmUb0fMj8uMfdoAl07TklvgVkGyEjPua35G3XCpEowPvCoTFHp2k/aCP9Zwg96s+GLaXyzPdcF"
        "zuA9aAJb3EFk7soBHQDvVLw1p813qUkroFRcEHsasanefb5xb28eY4z8/sK3tItfJtN4PAOQBQBpQRRltmPlVf1qG5Uqc59quRAJECON3JqjqM"
        "gQYHWgDJ1WZkU8E+1cTr1/cOdgJUY6V1WoyO2SBWNcaWLo75VyfyoA5DddOSFPzFgAfXNX9bZ00uW3XKuMAY/WuisdFQ/dXHkkkVT1rTZ5GkaN"
        "dzEZIoA83u5HVwgJ2rTY5ZMcZrcvtHuFlKmHnqaoz2bxcAUAZNwSeWPerej5H2h+yrUd5HhOnIqWxyljI2OXcCgDV0pS3lIOS75o1oLNrEK5xg"
        "EsfQVPokZ+1xlR90Eis6/DpeXE0xyNu0fjQBmO5a6OWyCxx9KuWqKYpH64NUFX96PQDAq3ayBbd1Pc0Abvgu2F3r8MBOP4q9O+CXmQeIdXt2Yk"
        "Bh+hNee/DZkTxBHKwyQCP0r0r4S28sPiW8lmORcp5g+mTQB6i3NM9KfIME+lM9KAD1qEdKm9fpUI6UABHFV3QjmrFMl+7QBTm+8KiPQ/41LN1F"
        "RHoetAEMlM7U+SmdqAIh1NMlHzY9qkUdaZcDAzQBRYfMaAKDyaKAJViJwc1Onykn1pqfcFLQBKHFObkVCAfSpwKAHAbVzRRyRijB9KAHxfexXO"
        "eM7jyrZiemDXRLlTnFcB8RrspA4zQB45qjebqsjKeM1LgrgH0qnv33TsPWraknrQAN0qFzg1OQcdKgHMoHvQBo6fETFnPWta3iOV571Rs+IcVq"
        "2y5C/WgDodAiIXPXJrutOGLf2rjtATMS/Wu0sgPswoA6k0D+lBooATtSikHpS9KADvQelJRQA8UUCigAooooAKcpP4U2l3HGKAJVNSKx71DEec"
        "VLnNAEgcYpd4qE0vegCUMCcU78KgBwc07eaAJfwo/Cot5pyMSaAH/hR+FFFAD46dUakil3mgB9FM3mjeaAH0UzeaN5oAfRQDxRmgAozRmigAzR"
        "RRQA1hTdtSYFAoAixiipWGabtFADKenSjaKCdvAoAdRTQTTgaAFxxSUUUAFFBpRQBIgpT1FJH0pTywoAD3ooPeigAoHaigdqAA96UUh71JGoPN"
        "AAq1IBigUUAFFFFABRRRQAUUUo5OKAEqZfmt2HFJ5YpyjapUd6AOY8YhjZMqEgkY4rwzx5ok1sklyvzBjmvoXWrTzkya88+IWlubBwFyoFAHz4"
        "4IPPWmM2xGcdauajCEkJ755qjIu7C8gUAKgOz60jZ2596fnjjFLCrkbccGgCzDF5hjVgcGr0dntdmRSSBV77MtrZQSSgbm7VraVLbxwSzSR7gF"
        "PH4UAcZM4VznNBv5UwkZ2oOvvSXh82d32bQWOKbaRrLOEYZFAE1s9xcvuJCJ/ePQVpJqiWURtoovNd/vSH734HtUUsRK+XGQqDqPWtK2tLO3gF"
        "1clXIHC9zQBXsreZis2GVGPzuRlvwrUmvGSBo7dhZQdHZ/8AWy/Q9hVJ9ZWCFsAYPKAdvrWYJ9T1ZiHcbVGctxtFAF0tDcusewhP4Tu5rV0rS5"
        "LpldhJFEnPlk5Bqnomn21tG0lzdibHPHWtWTWITAlnpkUg804kkbknFAFyRlmkCOpDLwg7KK0rCM7S5AjReg9T61W0mzkt4fLuGVnJyuOuK2Et"
        "43VfO3RHOAuOtAEL3oDApy7cD2qfTImd2kuY9+Txk1oWWkwmQPgEdhitJbIhcKoFAHN6hFsLuQdp6ACsiTRriceY0JKdR64runswF+YAms/Uis"
        "WBGjM3QAGgDmntTJbG2hg2kfe47Vm3At7aCSGOFJZCedvOK6Yx6lKpHEaHqAOTVODQyJS0EW055PrQBgWttLJCUUJDEeXLd6ry2IRgwJ2DoWPX"
        "6V1r2ARzHIgxjkVVnso0TbCHZh0JOcfSgDnPsUagPLjaOcHrT4ojK5kK+XCvQeorfaxjSEPPksR0aqZgDIwlJSFeQBQBli2lvJAbdCFB6j0o1Z"
        "47LFvGRyPmNTvcXByunQyLGRjd71Npfh2V5xNeSGUn+EnNAFLTbYSuDJKwX0xW15cVuA0cIWMDODwXrXt9JhgI+Tr2NSSWsay7mGQOgPQUAczJ"
        "ZtekTTAxru4T2pl1ZQIjTMQEQcZrfudsK+awymef9kVx+v341K7+z2oKxKeSOj0AY8121w7LnC5wpq/bQR6fbG6f/WY4B71ZtbGG1Rbi8iUIRw"
        "nvVeRnvbsRrGzp0UelAEFlbyXt6t1tO3Oceldnp1uQnmOOB+tLoGmm3tgGjOT1yKv3JjhBwwGeooAeZjgKqAIByaou/mGTyuMcHdxzSx3Ekr/u"
        "YiFHGG7/AEqvfyeUGQkKxHzYoAzZZySLZAIMtzKDwadDazO5jiw6j+KnRpEU2yEGM8/N296ifVYom+y2iMJDwG7UAVdQC2j7mI87oO9WrHTjKI"
        "5hulmJyCeFWtLR9Ljc/a9VI2D+9Vm/1G28h4bCHac7UPY0AY93bW8CSLEAZX5kY9c1e0PS5A8bySFj1wP61PpOkMi+bdHzpX5I9Km1a8XS4RaQ"
        "hmuLj5cL1jB60AVJre41vXfLVwbO2Ycj7hPtWtqMwdDZWK5YDaXH8NLp1qtjaRWkMpzJ8xA6596uPa+V8sKgyt98igDM8O6Q8asS2VLfMT3NdR"
        "bRsgyyhR6CpNPhWC2EY69adKcZFAETtuqleIW4xVocGoJ8+ZQBTW2VuGWmvbIDgLWixCx5xg1Wfk5zQBXSBVBGKga3j3Ma0NmRwaasB3ZIoAwr"
        "mwjlBwOfpXL6xpXzH5RXoUkGWyABWHrluEyxWgDynX7b7MpyMDGapWKkxxqPugFjXReMkDeUijkmsS3j2kxg9TQBq2DeRYzTKDnZgGs3VSZY41"
        "GfmG410f2bOmW9un32cF/pVK4spFa8uPJzBGqpuz0Of8M0AcqoJc+wqW3Qm2L9t2KULiabaO+F+laC2jwaYDIPvnK0AWPC8jw6xH5bYZvlGPcV"
        "7/4Ps1t7y1JbdILMbvqa8W8GWsT3dpKiZlSbdKD0C17l4b/5DDL2SFVH0oA6mRgVPHNQ+lPk5JNM9KAF7VAOlT9qgFABTJfu0+mS/dNAFObqKi"
        "PQ/wCFSzfeAqI/z96AIZKZ2p8lM7UARp1NMufuU9eppk3IxQBRoFKwwxFIKALUf+rX6UtJH/q1+lPRdxoAkj+7Tx1pg4BpVORQBKpFKGyaRF4y"
        "acFHWgBHYAH6V5F8VrnbOqZ6163cDCE968M+LFyW1MJ/dFAHD24y7t6tV5cZqla/dq8vFAEv8P4VUhGbn8aneQhDjFQWhzKGoA2rQfJWtajJUe"
        "9ZtmAUrY0+NWkX60AdLoqbUUV2NkP9FWuY0uNdyjmustowIQO1AHRUUUUAFL3pO1FAB3pVFHelAoAUUUuOKSgAooooAKKKKAHxnBqUGoDwARUs"
        "Z4oAdS96Sl70AHekpe9JQAU+PrTadH1oAlopKKAFopKKAFopKKAFopKKAFopKMUAKDzUm4VFS5oAk3CjcKjzRQBJkUZWo+KOKAJQR2opsfXinU"
        "AFBGaKUGgBMUUpNABoASilNFACU4dqaacO1AD4+hpe4+lJH0NL3H0oAD3ooPeigAoHaigdqAA96li6Goj3qWLoaAH0Gig0AFFFFABRRRQAUq/e"
        "FJSr94UAT0oxnrRRQA2VQ7AHp3rnfFNmt1bSRKMk57e1dJVeaEGN8ruJFAHyZ400ybT9VuIHjKgNuGfTNc41e4fEvw+99cSziMbwCBxXjOr2ct"
        "nNskGOM0AU8itjSbdprqOMocscVkW+0yR8Z+YZr0jRdNMc8UskO3c4dPcEUAZuq25kv0gB+VcDpSXjfZrZxGMhhjOK24bM3GqXGeCDxxTtc04R"
        "2saAZIB3ce1AHm16rgKWPXpVrRrcuGcckc0/XLZoV+bgDj86fpkbyW+6NskdulAFiLaZ1BGSTipJbeWSfJcFR1HpWta2CrpbSzKscmcg5qXTtO"
        "C2Mt/cEFV6DPWgDl7o20TGMKXz69qdbFXGQxRM4Ynv7VCzCW+lOz5c8VatYUSUmRCw9KAJJpmciG0jK249ua6Xw9bpHAGWMM44HHSs+yiaU7fL"
        "WNT2rpdMtykYVRigDY02CMOHkTLjnPqa3YLUXDrKy5xVLS7Qy4Jrp7KAIoXFAFUhkYBE6D0okknxhsD8K1pIAiltu44qoLdpX5zQBnql1K3l4J"
        "B/2ePzqO4to7Vh5uHY9AO1bpDRxBPNCew61HFaq5z5JfuWY0Ac+3mSjaBhPTHNPigMYCwqVPcmt6S2iXnYBVWby1baykgUAY9xAASCm5z1OOKz"
        "JfKtGaRFEjdcZrcuxcNkQw4Xuc9BWTLYG43Q7SxPJZeD+dAGY8kd8rSSLkjoBWR/ZV7qF1syywqc4x1rsrDRoocq3ykda0V8iBD9wY6cc0AYVh"
        "pIhiCum0AdDVv7LDF8yj5u2BRf6nErgYGPUGsrUtdWFMRKSTQBpyCRyCT+lUtQ8tGUPKFYn1rm5NZ1W6kZInCRj+InpWFqeo3EqvunZjGcHnvQ"
        "Bqa9qDGdrYTqkf8AHn+IelZ8eq6Lpce9IxdSn7qY+6fWsKQPcRGR3O4e9Z0j7HyeaANi/wBZa7uBPctv/wCmYGABWloXiDRbW6BltbhpTzha5B"
        "z8+/8AvHgVseGNNa51lCybugxQB3r+J45YC9vaS+UOpPaqg1Szb97cRMN3fNaMOlRR6bOHQeaPuxj+tU50tZ7dVMKZAwfk4oAs2t3HPHm0IwBz"
        "Ix/lWbebBIxmkAzySazNSmjsx5dm7KT1CnA/KotMik1KURzTHcfWgB9zLPeH7NaIxjH8Q71taD4cmkZZ5R5bDqGFbWjafDplvsaPcx/ixV6aYo"
        "g8sliR908UAZerW4CYdi8Ef3j2JHtSaNYJcyJfFSqJ91MYq3Zwtf3WJcmBeoxwTUmt6jb6da4kIVT8ibRyTQBDqOpQadDLM7LLK3CIvUVl6LBc"
        "Xmoy3bqzu3LOR8v4VVsdIutTvlvbsmK1Xnj7zCuxgjcwC0sIikK8OSOooAW2tIV/fRfNMeCauwW2wklslupp9pEBEIkBG3rU/wBmPUmgAifC7T"
        "jimS85xSunl+9RPJweKAImYDk5pjPHn1NRyyfL0qs8nzUATSzhn2jpUbNiodwVtxBP0qdGU8sMD6igCSI9KlmYbQFNQgxn7hBx708bCv8AEDQA"
        "05NZ2poFiYsM/WtZY1PO8/lWTrUqqp3HtQB5z4r2PdALjMfJrN0G13StLIvHXJp2sSPea/5MOTubBxXU6hp0dhZW1mF/fSkD65oAk0iwN1ZS6k"
        "eEiOB7+tY/iGSYaPeZCxLPKm1fUAda9BvbWGx8Ox2kIEbOFVh6nvXnXjdHbyyrfug2zj1oA5CCJpZMDu4Fa2q7sJASQEGOaXR9KuJplQKRl8g1"
        "a1xP7QuxBbLgQfKxHf3oA6v4T2SyzXFyUBDwkrkelej+DLoXOpyMP4I1VjjvXF/DMyRKuyPbH5JG7PXJ6V3vhC1jgNzKgxubk/jQB0sgwTTPSn"
        "tzz1pnpQArfcP0qCpn+4ahoAKZL9w0+mS/cNAFOb7/AOFRfnUs33/wqL8KAIJP60h6GnS/1pp6GgCJetMk64p6jOagnl2yYxnigCs/3z9aSlY5"
        "JPrSUAW4smNcelSxqQajg+4n0qegBD0NLBycU085qS3XHNAE2OMUCj8KPwoAr6gwS2c98cV88/EO6FzrMuD904zXv2vNt06RumAa8FudOi1DWp"
        "t0nVzQBgW0YEYPY1bKH+Hn8a3dU0NNOhD7sjFYyyqGxQBBIpwQRT7SHkGi4dT0q1Zj5VoAv2seFH0rd0eP96vFY8A5FdBpAw60AdRpaZYcV0KM"
        "BEBnmsTSOW/CtmNct0oA6WiiigA7Ud6O1HegBR1qRQMZqMdalU/KKAEJ4ptL2pKACiiigApaSigBTzShiKbRQBIjEmpO9RR9al70AKOWqQKPSo"
        "0+/UwoATaPSlAxS0AZNABRTttG2gBtFO2n1o2H1FADaMGnbD6inqCBQBFg+lGD6VNg0YNAEOD6UYPpU3PrRz60AQ4PpRg+lTc+tH/AqAIcH0ow"
        "fSpv+BUn/AqAIsH0owfSpce4ox7igCP5uwoy1SflRQA0bvSnDPelzikzmgAooooAKKKKACnCm04dfwoAdH0P1p/pTE6fjT+woAQ96KD3ooAKB2"
        "ooHagAPepYuhqI96li6GgB9BooNABRRRQAUUUUAFKv3hSUq/eFAE9LRRQAUdsUUUAYOuaalzDMpQbipANfMfj+wuLHVLiC5xvDZGPSvq+8yUbH"
        "pXz/APGewYam10V42DPHWgDyqzYI4duQpzivddI8vUtNsruKPCpCq4A74rwkKc4B6mvePhGrT+FdpIO04FAE9hpi/apZQuCetN1iy8/IHHHNdR"
        "aWXlSMWI+aq+s26RW7uByBQB494/tEhRV2DJx0rI0lFZEWMY6V0fj5knu4k5wACaz9JtRCpcLkdqAGalJJcSrGu4IFwQO5rUuR5nhUwZIYY70W"
        "dhNK7EoeuQal1ayeHS5JGLDPQUAYGj6T5qu4AIQ/MfWrRX96Y41Q46Gul0GxSDQGcrmSVeR3qjbaZiJpGUgg0AVrKJYpA0gEjdiOMV1uk2xkQN"
        "xg1nWVss0qq0agDvXY6VaIsaqBQBd0e3CMFxXTW9ujRgKvSs/SrTc2cYFdLYWu0cjtQBU+ykpyKge2wOBit1ougA4pksUZTpzQBhraIW3uuWA4"
        "NJI/Y9q0Z0wwCiohAc5C8/SgDHlWSVsBWYdiKcmmzS4GAD69TXRw25dQrjj024zV2OCC3QYgAPp3oA5y30EDLTvgAZqOWCBRiNFGDjpWzfTSMp"
        "UHav8AdrMnTKZHFAGHq0OAu0gH2rCuo3wdwYmulvYJDgk8Vg6jBIVYK5oA5u7jiEgLhiQemKz7qOEb3dhjHStW7t8A7yxYdKoNptzc5KpkH1oA"
        "5u9mjdGiUFVz1rNeynu2xBGQoHVuN1eg22kLHkTWwmwOmOlMW1Qkk84OFVV6UAeZXttPp6E3CNt+lZaSA5kYZB7GvWbrTGuwRIV2dMMP8a5688"
        "M2InwrlR7CgDi9Nt4Lq+CBJGOe3QV6j4V0C1to/tNy5BcYAB5FYtlaQWcwa3tTOydyMCtu11i/KFRbpGc+mcUAbN3LHFC+2Py4QMFnPzNXO3T3"
        "F5Jut40gtE+87d6nkmmkbzrhPMk7c8flTbqCWWMopYK4yccUAcxfQRrdPIrK2TwQaoPO9tfRTxNg55Aro/7AaUbS7AeoqaLwrbBVkdmOD3NAHU"
        "6d+902G6dlO/oM1QvZZp50jiC+WhO+q888sFuLW1U5UYX0qGw842zQMSiEZlmJwAaAJtV1k6ZbGOMB2P8ACKpaNZz6pMNRvM7d2QrdKl0nSft1"
        "0wjYzQqeZX9fQV2Frp0CwpEDt29gOKAILeza4dRt2Qrwxx1rUBRUEUWNq+vU0TPsRY41I2jjFPtbf5cuMsT37UATRqAoKjH4VK/3OfSnBVAAFN"
        "m+7QBmXDnfioHJ2mpJRmQ0x14IzQBSkPrWPr2sWelR+ZPKpfOFTuT71f1i4Flp812Rny1JAx1PavDL2+vdV1N7u/DAZzzkAUAdT4j8cXbKI7FR"
        "Hnqa5mbVtSuyGku5QScY3cVRu7Xzpt8cg2npg9at6Np1zd30FrFGzPuGc9qAPTfBGlXd3oYuGuJMhuCWqzqsGr2Yaa2unwvVTyK6nRNPk07Q4b"
        "YIM4y2PWs7XxItnJu4LDGKAOLs/HGoWch+3WolUHqDW7qF6L7T5bxQPLWPzSPY9BWZa+F01AOrPg9eah8UI1lodv4dtWLzzsS5HXbnpQBD8NdO"
        "j1DWptSuYQYEYhcjoRz/AFroLkpqvimJ1XKQuNox1wau6fbJoHhb7MiAOw+93JKir/gvTBDbrd3KkuVwPXOaALtzbpcXiCQcbsjNcT4qsba71W"
        "Gxggk8oOXkI9a9QNiHWSUjgDKe1Y76XCbsSbPnxyaAOQjs4rCwnl8sqvlFYyepb0qPwT4c83RLvULqMKcORuGO3FdLf6IJGAZyUEgYL2rX1SOO"
        "08MTwxqEZlEYHqaAMXwpZ/2fo0MbZZvv5+tdt4fiVbKT/awaxbG3/wBDjUjBCgV0emxeVbBfxoAtAdvakxS0UANboRUIqZqhHWgBKruxyRmrPa"
        "qr9TQBBL94VAT8x+tTzffFQH7x+tADJegpp6GnS9BTT0NAEQJANUJCS5NXv4TVGT7xoAbUsCggkioqmtvumgCZOCAKnqAfeFT0ANHep4fu1XB5"
        "NTwnigCSg0U1h0+tAGP4uk26LcH/AGDXzy97LDqbvG5Dbs17943cR6JPu/uGvnOYhtQYg9z/ADoA6K51i5voNj4O3uaypB82cc0Ih2cMRTvKx0"
        "OfrQBBKCGFalmP3a+tZ8oBIA4xWpZKcIM0AaEHVcV0Gjg+Z0rBtf8AWYz3rpNJ/wBYKAOr0kAdu1bGQINw68Vj6acD8K1YgWix70AdLRSUUAHa"
        "lpO1HegBR1qZfuioR1qVQNooAT+Gm0vakoAKKKKACiiigAooooAfH1qXvUUfWpe9ACp96phioO5qSLpQBIKeo5zTKkRuMUALzRzS0lABRRS0AJ"
        "QKWkoAXBowaSlHWgBcGjBp46UtAEeDSYapaB2oAiw1KoOeakPeigBNoo2iloHagBpUUBRTj3ooAbsFAUU6gdqAE2ijaKU96KAI2BzxSYPpUtA7"
        "UARYPpS4Pp2qQ96KAGp0/Gn9hSUDtQAHvRQe9FABQO1FA7UAB71LF0NRHvS5I6UAT5oNQpnPWpqACiiigAooo7UAFKgO4UlTxj5c0ALS0UUAFF"
        "FFADHRSDmvLfjFpJudMkkVeV4zXqvf2rm/GVmL2ymTBI2ngfSgD5GnRkdu2GxXtnwHvEeyntPy/SvKvGemnT9XeIjAds10fwU1b7D4rgt5GxE5"
        "wfzFAHvLIBcJGf7xBrM8VDZbuqd66OeFHuVlT7tYPiZDjpQB5B4ui8y+GOoAq/oGnPJEAwzS63AZrx229Grf8OMiQc9QAKALmm2kIjYOgyo9Ko"
        "+J7aGXTViJ2sW9PetCaV3zt7+lJ9mN1OkZHzDtQAy2087Ydn3BwBUd7ZbEmG0da6eytWhjClaranbYRsjqaAOb023/AHwGO1ddpUQUAEdayre1"
        "KEHFdHpkBJyR0xQBuaVGm8DHAroFRdgrK0mEfePWtcKXYBewoAaYmI3DpULLuyB1rQjjbyx9acIVHQCgDNitWd8FatW+msz5AFXI42K8CrkHDL"
        "mgCEWUQjy6jcO9UbqFj0OTWu6MzHFVJIW3EEUAYMtrM8wV+hqtNZYJU8c10JtyhyB3qpd2zO3SgDlLyxjQlvMZh6ZrHntPN3bFOa7G6tQwyBUH"
        "9nMV3F9tAHBvpYLZkPIPSnrpzhfkUbO9dTfWiBseWDn+KqktpjoOKAMIWq4wq8fWmm1ijVmJWIn0FbItQMnFVnhAkJI4oA52W183KrFvOepNQX"
        "OjvhCU2k9gOa6VowDkCmSZ3jINAHL/ANiFjy7x49qYuliIkHeffFdTICRn+lU7rOV4NAGCbOMjDLxQwiTjA4rSuFJLcVmzqI/nk5HpQBDczxwx"
        "bxgYPNUZrpphvjfEfU06SRrpmihh3AnHtWto+iizXzZE8126KT8q0AY6wMyF41MUbc7m/iqW00e61GdYZCywdSQcD8q6MWTT58xFGD2FaNpAsK"
        "BVPPagCvaWKWsAt4VEaDjAGM1YhhO6rsMQbJk4NSQwruNAFFYVSXfyTVqMCpzCuad5AAytAEO0elRSDqKs+W1QzowJoAzfLUyNmq8ygSMKsyI2"
        "800RNnJANAGXf2iT2rRkdeua5qbS9PYNbyW0ZJ4zjtXY3sJIJI4rDurdfNLY5oA4i7+H9u9wJLSd0BOdp6Cuq8OaLZ6MEkkhDyf3mHJq9bSMh5"
        "6VdZzMq5HSgCa4v1VBtzx71hakZ5pPMkJ8sHOM1oyxN554z2qteqywtuBUe4oAfpTxWtnPcsOIxuP0rC8D2A1vX7vX7uN/KU5hUnoKpXV3PcSD"
        "RrMEm5kHmEdhXoVrZppeiC3TCtGgRR/fJ60AY2plr/WreBOLdD/49n/Cux020Eg8sKBGnPFZ+g6WkMyPgfuhuP1NdRbIyQbW4PWgCNowkTKBxi"
        "qRtVMm4DntWg4LDA61Eg5HNAGXdWqhxkcd6zfE4e4msrOM4zJ5jD1xW9eIWRiKxo4G+2LMB8y0AXIE/eKoHGa3AMACqdkpC5K1fY5AoAbRRRQA"
        "xqiFOc/NTaAENVnzuNWajkYFe1AFObO4VAfvH61Zl5Iqs/U0AMl7U09DSseB9ahc/P1oATsaoyfeNXT0/AVUuPvUAR1Nbng1DT4utAF2NQRmn1"
        "UGc96nhPNAB3NTwdKgYfN9aswjan1oAfSHtS0jkBST0xQBxXxVuTBorgH7wIrwaLDTs59a9X+M2oBkWAN/DXlNqvI785oA0IzwB71NKNsYNQIc"
        "HpT5GzEaAIlG5hn1rZs0XjisaMZYYrf04fKM+lAGhBCgZTjrXQ6VGokGBWJGQSBiujsXEcQwOooA3rADcR7VrWw+T8axNJYu+6todOOKAOiooo"
        "oAO1HejtR3oAUdalUfKKiHWpV+6KAG9qSl7UlABRRRQAUUUUAFFFFAD4+tS96ij61L3oAO9OVqb3ooAmBzT4/vVAp5qaKgCWikyKWgAooooAKK"
        "KKAClHWkpR1oAkXpS0i9KWgAoHaigdqAA96KD3ooAKB2ooHagAPeig96KACgdqKB2oAD3ooPeigAoHaigdqAA96KD3ooAKB2ooHagAPeig96KA"
        "CgdqKB2oAD3pQM0h70oBPQUAAOKljbOKZsOOlIFYdqAJz1pKQZxzS0AFL2pKKACrEZ+Sq/anIeQKAJ6KKKACiiigAqpfQ5hYjnNW6SUZhYUAeB"
        "fF3QTJcC6jjGFXnA9TXl+j3DadrUUoO0o2a+nvF2mJPZ7mQEHrxXgvj/AMNNp+oedADsYZ4FAH0H4P1WLVtAtrlME7Bux61HrsRaTBHBFeYfAr"
        "xII5P7HupNqN9zJ5DeleyXsKyorE8jrQBwX9hGad1x94+lS3Hhq5tIi0bg98YrttOiRLkZAP4VsTpHIGDKCD7UAeRIklvLiaNgD3PStew8lZfO"
        "zn2FdRq+hw3MWYwcg9K5u40e4tCGjDDnpQBtR7ZQGjGaivLZpB8645zVXSZLhJgJAQCelbl2mVyuTQBheURIFCjFdDp0DbAcc8VlIm+UJ3zXSa"
        "ZCyouaANDTLdsk9q0bdACeaZZj5DipoAQTmgCQDAxS0oVj0FW44w2MigCCA/KfrVhF5BzTmiVR8tPjAyMUAAOOhpMgjGOamwPQVG33/agCJ1VB"
        "yc1Vldd2AAanvFZuFGcVWMcg6jmgCuYkGeAc1WuI/lJycVeKNjJFRygbeeaAOb1CN94qs8LECtu6gy4IGfaqcifN92gDKlhZRmoGjVxhh3rTul"
        "xxVWReBtHNAFJ4kBxioLiJVYECrMobd0NRS5Ye9AFSQDHSq0qqccVclBCng1X8pm6mgDJvM84UVnGxku8qxOz0FdIbYfxAGnxW4VflwKAMu202"
        "GGBVSJVZfTvVlQq8yHAq95IHc0i2ySNtY4B7mgCm3mynEQ+X1q9ZWjgbmOT71PHGIWCKoIHerC7j0oArFGD4xxU8UWDnFWFXjnrTgjehoAYqgY"
        "yKJSNhGAKk2N6GgwnHXNAFX8ar3ON3U81oGPHaq91GTyFoAyGUFzQUA71LKuGPGKYWHTNAEMqF1x1rMu7U78e1a8andzSTpleBk0Ac8LXJ61LH"
        "EQMgdDWj9m5yTUcqeWeOhoAglliiIZx81c74u1ZLSzIPzSN0Udh71sX4bLFPmYjgntXFPA+pak1lvy5b5pW5AHcZoA2vhjpRlupdXnI5XC59M9"
        "a7C6Jur3cTiKHiP3NZOlxrC8Wl2SMquMFvSultLMSyLEvSI8mgDT022C2qFx85ILH1q7Od77wAvsKbGcjGOBxTsZoAhPy/N36U2SMLyKsFRn2q"
        "ORS2aAK4XdwelNFrH5pYVZCcDAo2nNADQAo2gU7dwKTafSggigAzS5pB1paAIn+9Tac/3qbQAhqs3U1Zqu3U0AQy8EVWfqatTdRVZupoAgNRv9"
        "4mpDUb9TQBBLIVXI+lV5G3Gpp/ufjVc9aAFQbnAqbYFPGaii/1o+tTv1oARRlh1qyqhelV0++OvWrR6UANI5B96sjoPpUMQy5BqfigAqC7fbGc"
        "9MVPVXUAfIY4zxQB4X8W7kvq5QE4XiuUsVzWz8QpfN1qXnPzkVk2nAFAEpFNkZljIFSvjtUEoNAEtiMuM10Nou1ARWVpkSuoOPxrdggBQYNAEy"
        "uQVrptKPmxgMBjFc7DasxGOldJpyCNFw2TigDotHRVO0DtWjVDSvuA+1X6AOiopaKAE7Ud6O1LQADrUq/dHNRDrUq/dHNADe1JS9qSgAooooAK"
        "KKKACiiigB8fWpe9RR9al70AA60p60neigBV61KtRU4NigCQnmnqajU5p2cUASjpRTUOadQAUUUUAFKOtJSjrQBIvSlpF6UtABQO1FA7UAB70U"
        "HvRQAUDtRQO1AAe9FB70UAFA7UUDtQAHvRQe9FABQO1FA7UAB70UHvRQAUDtRQO1AAe9FB70UAFA7UUDtQAHvUsXQ1Ee9SxdDQA+iiigAooooA"
        "KKKKAClX7wpKVfvCgCeloooAKKKKACjsRRR2oAz9UiWS3aE4+bmuE8Y6PDcWzFoskLgV6HdxbvmHasjUbVZI23jIxQB8zXX2jw7r0U0ZKYk3V7"
        "34E8W2ev2KxmUC4QYYMeteYfFLRXkja7RD+7YAYHauD0TV77RtQE0ErIVOcZ4NAH1xCo3hhwR1FaA+Zc15t8PPH9prsKW80scd2MBlPevRI5N2"
        "3kc+lAD2GAR61UmUHKlQc+tXjg9KheMFt1AGUbNFlVsYxVx0XaABU7qrHJFMkyGAWgDLSHF0zAd66GwQ7Fz6VloMTnIxW7YAMq0AXIAEG31INW"
        "ByaryDDnHapIWLMc0AXIPuD61bHSs9WYcA1oL90UADUgOOtDUmM9aAJPMFJnPNMO0daSdgIwVOKAJKhl+/+FPtyWVsnPFRMcsc0ARzf6o1Tmq7"
        "JjaQaoyZLGgCtKcZqlMMHPrVyUfeqpP0FAFK8XPOarFMDNXJhknPaqrjigCpP96q7LyTV1kB6jmoGU85HegCnIrN0GaZ5b/3TWiijHC04r/s0A"
        "ZyRn+NaQx88HitAqD1FN8pPSgCj5Z9aBHz96rwiT0o8tP7tAEQi+Uc0+JdoNSIBuxipdq+lADEjzg56VJUiKuOlLsH92gCKipdg/u0bB6UAQsM"
        "1HwMg4qdlx0pjKD2oAzNQhAUsOKzFjyc5rbvlJjxWS6lCQOlADaa77BnFOqOSN36GgCIS7j0x+NVLucE7cfrV0W77hmq8tpubkHrQBzt+txclk"
        "gzwcHFXNK0hIY1by8O3U961rW1VJ+F471fKlUwFxzQBn21qIb1SF57NXUWNt5NuS3335Y1kRAfaE3dBW4ju2MngUAOUYpaKKACiiigAooooAKZ"
        "JT6ZJQAyiiloAhf71JSv96kFADScZqu56mp3Gc1Wl+6RQBG53EVA/U1JnBqJz940AQmon6mps/LmoWOQTQBXn+5+NV6nm+7+NQUAOi/1g+tTv2"
        "61BF/rB9anftQAJ98detWvyqqn3x161aoAWD/WGp6gh/1hqf8AGgAqtqx26e7eik/oas/jWd4il8rSZWzj5TQB85eLXMmsylu75qtAPlFLr0hl"
        "1aT/AHqfbgbB9KAHcVHN92pPxpk33aANbRf9TW9bD5Kw9BUmMDGa6CJcLwDmgDS0+L5Nx71swIoIUdcVnaYuFAbpite3UGXNAGvpgwg+lXqq2o"
        "CxrirVAHRUUUUAHajvR2o70AKOtSg4UVEOtSfwCgBO2KSiigAooooAKKKKACiiigB8fWpe9RR9al70AHeijvRQAUd6KXvQA4MBxUg55qD+Kpl+"
        "7QBIpxTwcioaep5xQBIOaKOlFACUo60lKOtAEi9KWkXpS0AFA7UUDtQAHvRQe9FABQO1FA7UAB70UHvRQAUDtRQO1AAe9FB70UAFA7UUDtQAHv"
        "RQe9FABSqMkUlOj+8KAHeWaPLNSUUAR+WaPLNSUUAR+Waci7RTqKACiiigAooooAKKKKAHIpbpTljII5pYO9SCgBKWiigAooooAKKKKAGnJQj1"
        "qrfRDyDVyo51LJgUAcJ4s0cXFmUdclyDgV8+/EXTvsOvTRRDai19X3dv5joGXIrxT4r+FpbjUpZYwV3PyaAPHtIvrjTL5LqB2DoeDmvefhv8VL"
        "O8iSw1ibypBgByOteA3kDW11JCxyUYimwh87o2IxQB9u2NxDcRpLDIHR+QQc1ZODnBr5R8EfEjXPD7LEZPtMCnG1jzj2r2Twx8V9K1ZhbYaO5I"
        "6OuBmgD0NyA2CaSAiSQsO1Y82qmUKyqORRpV60kxVsgZoA1Z4283OMc1qae21QCKrj95GGYdOmKtQqAoI7UAXHOWJp8H3jUKnK5NSwfeNAE6HE"
        "mT0q8JVwOD0qhVodB9KAJwwYZ54pu8A8imKSBikOc0AOcg9BUcillwKfQOtACwERqQe4qJ5ArkEVM64UGqs/8ArPwoAWSQMuBmq0nFPY4FVbmV"
        "lGVoAhmkAYg96rTnOBTZJd7c9aaxJNAETjOarsuBzVsrUMykqcUAVZBg0xhlcCnkd2pgYN8o60ANQEZzTu1SLGe9MbIzjtQBEVwM0mKfyRg0oU"
        "AZoAYykDNN+lPZieKryuyMAKAJUH7ypwMnFUUlbdV6AkruNAFhI2GDmpaiWToKkFAC/jTZc7fWpVUY5p6RhmwOaAKB46im7CTmtCW2LHpUHksG"
        "INAFSSIH71Zt9CqnityVECZJrMvERh70AYpUhsVJGhHWnSoAxx1pqtgUALtPc0xxkjFPLU0c/nQA2JAHyalkHA+tIv3hRMcKD70ARxruuQB1rb"
        "iXavPWsjTEaW63HoK2aAFopKKAFpKKKAAnFN30P0qOgCTeKaxzTaB0oAU01jjrSntTJetADWPzU09KU9aSgBCwB5qrL3NTS/eqGX7hoArSHkYq"
        "F26ipX7VA33qAGScKahDfKRU8gyKqvwKAGTfc/GoDUsjZXFRUAOi/wBYKnfqKgi/1gqeTqPpQAi8MDg1ZVgarDqOtSofmxQBZhU7ialpsf3ad+"
        "NABXKfEq7a20OTB+8K6v8AGvOvi/clNOEanqaAPFpm8ycueSSTVuPoB7VRU/OPWr8fQUAOx/nNRvy2KfnrUSnMoHfNAHQ+H8JwetdFbKQwbqKw"
        "9GgIjMlb0LDywDjpQBq23OSK1LJDuFZVlnZzWxY/w0Aa0IwoB7VZqBKnyPWgDoqKKKADtR3o7UHrQAo61J/AKaBSk8AUAJRRRQAUUUUAFFFFAB"
        "RRRQA+PrUveoo+tS96ADvRR3ooAKXvSUvegBP4qmT7tRd6cr4FAElKOuaap3U4UASA5paiBIqVSSM0AFKOtHenACgBy9KWgdKKACgdqKB2oAD3"
        "ooPeigAoHaigdqAA96KD3ooAKB2ooHagAPeig96KACgdqKB2oAD3ooPeigAp0f3hTadH94UATUUUUAFFFFABRRRQAUUUUAFFFFABRRRQBLB3qQ"
        "VAj7c08SZOMUASUUUUAFFFFABRRRQAUUUUARTKevaud8U6Yl5ZPOc71G4D1rp2+ZcVWu4A9qydeMUAfJvjLRzb63KShHmHd09axZ7F7chSuAwy"
        "K968XaLbzSs5jG8V5xrWmNNqixBAgVe4oA8/ceTghR1rb8KTGPWLWcdPM5qlq9v5V60RU8Vq+G4DIi4XaVbcDigD6ItXMunRSDvGKmtXaJ1k9O"
        "v0rO8Mu0ujwqx6IBWmq4XHWgDqtJmEqdc8VpwdDXM+HptqkA5wcV0lsxOPfrQBYRuMVLCwBJNV+jYqQsq9TQBaDAjNWBImOtZv2lUO2rZOIt9A"
        "FjzU9f0oWRCcA/pVQOSKkQ4INAFugcGofO/2aDOoGSMUATyyDbzxVOaRd/XtUFxfxhguRjNQtdQtLguBxQBYJyetRS4K4wKDKu0leaqS3Tb/AL"
        "tAETQgSE+9NlAB4qdjuXd6iomTceeKAIR1pD904qXysc7qZigChN8o2nrUaIoO6r7xKxyahlQKpx2oAjB7k1GVJJxUicrQMDrQBCw29aiY5bg8"
        "VJcOudoNVXlKPtoAS5mEY461Sln3nJNF7LlumKhiG7A55NAF61BKHitK3BC8im2tuVVQBnitSC2ZhgJmgCl+FSLmtZdKLKDg/lVG6tpopdm3NA"
        "DI1ZzxnFaFrBtXd3ptlF5afOOav5QRkAUAVyCByKpyxsWJxVqSUbvTFV5plGSMGgCjcggVnSKxPTIq5POWYjAqDtQBl3cbbycVTIIzn1rTvCc4"
        "9qzG+91oAQ05FpDxz709DxQAFcVHKf3ZGaklfb0FVpCzyIoxyeaANTRVIiLEdavHrUNmvlwoMdqloAKKKKACiiigBr9KZ2p8nSmUAFIaWkxmgA"
        "pkvWn96ZL1FADD2pKU9qRztGaAIpfvVDL9w1KTuyelV3fORQBA/aoG+8ank4IqBvvGgBr9KqynIqy/3aqyYCmgCBgc000FiTiigB0X+sFTydR9"
        "Kgi/1oqeTqODigBF6jg1KP8AWfjUS/eHB61KP9Z+NAFyP7tOpsf3adQAV5f8Y2XylGeQea9Pc7VzXjvxiuc3Hl56nNAHmar+9P1q6g46VRiP7z"
        "HXvVwHigB3rxUUf+vB96eTxTYsGT6dKAOr0d/9HUZrRRyXAFYtgxjgQDnNbFoCzLnvQB0Nmv7sfStey/hxWZYKDHj2rVtF2j1oA1U/pS5NMiJK"
        "5xThzQB1NFLRQAnag9aO1B60ASD7tBoH3aDQAlFFFABRRRQAUUUUAFFFFAD4+tS96ij61L3oAO9FHeigApe9JS96ADvSUvekoAkjNP4qEHFPVq"
        "AJMVJHwtRA09TQA+nA00UGgCYdKKRelLQAUDtRQO1AAe9FB70UAFA7UUDtQAHvRQe9FABQO1FA7UAB70UHvRQAUDtRQO1AAe9FB70UAFOj+8Kb"
        "To/vCgCaiiigAooooAKKKKACiiigAooooAKKKKAClX7wpKVfvCgCeloooAKKKKACiiigAooooAKZJ9w0+jsaAOb1rTFkjeUAE46Yrgb3S4rjUH"
        "M6LnHy4FesTRZyG6GubudJU35cLwKAPEPGWhGDUYzHGvlsvYd6XQ9JdVOMj8K9U1jRY57td0WQB6VWTSkjcbISAKALvhgFdPiUjBC81sEY61R0"
        "xQjbQOBWkV3AEUASaW/kXW0dGNddbSKdh6cVxaZWTI7V0+lyGSFCaANRsb8jpUqIspHPFQZyp96ltjtYCgAe1G/NW3+5il7ilABIFAESjI49ak"
        "qXyQOhpGjIBORQBGSBUb4bjtT2XNMIwcUAYWoW04nymdufwqHZcrLg4PArflUMADUDwKWzigCO0KlQG6025i3cp1qXywORTgBjOcUAUT5irtYk"
        "URkg8mp5xu71CIz6igB5Zdp5zVeQnHFOYYzzUMjcUAG4+tMlOUNAOfWiT/VmgCJDxTJs59qGfYucZqm16CT2oAjumKtntVWefjHf1qW6lWRQB2"
        "NU5OSKAIXYs3JNWtKj8y5GTwO1Vip6gVo6NGQxc/TFAHTWUClc5zituwhAGeDWJpzYUita3n2jGcYoA2kZAMcVnXojMmSBVeS7xk7qz7i+Uk4Y"
        "Z9CaALMjKCemKri7VTyRWXc6jGvymVP++qpSXSOcoyH6GgDWuLkHJGKqPJkZJ5qmJiRwaWWTK5x0FACyvjndio2k4+/WXNNKZW9O1NEr+lAFmd"
        "iVOTzVAk7uc1K0hIquzc9KAJQRTgfSoNwJ6VIGxQA2YsRT9PjMk65HA70x+hq/pERKl80AaIXaMelFLjA55pKAClpKKAFpKKKAGydKjqSTpUdA"
        "BQelFBoAKZL2p/emS9RQAw0yX7ppxpkv3aAIqrt94/WrHbNV26mgCKXqKgbqanl6ioG4JoAY/SqM5IzV1jmqd3QBVcnqKZuent0ptACoW3A5NX"
        "BnapOelV4Yy5znpVwjKgelADB1HBqVeX/Gouh71ND96gC2nC806m/wilHBJ9qAGy/6smvBvitceZrJTOQM17lqcwg01277a+cfGV0bnXZ2JztY"
        "j9aAMiLBfIFWsj1FV4VwtSUAKzZqayUGTnnNQVa0/wC/QBuWQHAPOK3bRfmT6VhWPWt+zHzL9KAN+xHA+latsMCsuw7fStaLhRxQBchYBQN1SF"
        "go61THBBqSSTcuAKAOyooooAD0o70HpR3oAePuilpB90UUAFFFFABRRRQAUUU4DNACxgHrUm0YpFGKkHSgBmBTu9Bo70AJ3ope9JQAUvekpe9A"
        "CHrSoMkUh605PvCgCTYD2oCgdqWloASlHWikoAlUinYqIHFSA5oAepNSAg1CacjYoAkxikHalBzSDtQAHvRQe9FABQO1FA7UAB70UHvRQAUDtR"
        "QO1AAe9FB70UAFA7UUDtQAHvRQe9FABTo/vCm06P7woAmooooAKKKKACiiigAooooAlRVIp2xfSiP7tOoAbsX0o2Ke1OpKAG7F9KUIOoFOozxQ"
        "AlFLRQAY4ooNFABRRRQAUUUUAFJS0UANKg9ahMQaTBXirFA4PSgDNuYEEnypxWdeRhFJ2gfhW/N64rP1BUaMjvQBz1rgSMKtliOKqxDbctnpVl"
        "/vUAG45zW7oz4hGTzWEgywrT09gGxkigDpYGDAmpEOHFUrKQY5qzvBIoA0QRtznnFQ+a4Oc96QE4HJpCCcAUAXFlcqDuoLsRgtTEUqoBp1ACVE"
        "5O+pqhf79ADSRnmopGweDTps449ahPXvQAvao5ZEUjdzULyyAkVULFmJYnOaALjSpg8VGZCw+WmqAcZqVFjU8HNAEL1BIvrVh/ve1RyYC9aAIh"
        "x60xmPTNPPTqajPWgCOVcr04rLu7bb8w4FbBPyFfWqdyhdcdh1oAyG+UUAbvrVuSFCOAafZ26mToaAG2lorDLrxV2KJYR8i45q/DbgR5qTyUxQ"
        "BViuzEwOan/tJNpOQDWffQSBsqBxWLem5jB+UnNAHRT6ogUndx9a4XxLrF/NdNBZfKCfvGnyXcvKuMZqpy0rHafyoAzHtbybmW7ct32mp9OW4s"
        "5g6XLtjseavrE5HANO8lhzigDU06+lKfvH5PqKtNeE5G4YrnSzK2BSPcTLQBvNOD2zUbzjB4rA+3Sk4FSxNNIRz1oA0/O3dDSAknsabFCQ2WOR"
        "UyoF4HSgAAAGaXP0/Ojt1o/GgAfkAL1rbs4RFbrxjIyaytPjaW4BI4BrdY5A7Y4oAbRRRQAUUUUAFFFFADZOlR1JJ0qOgBaKKKAEpkvan0yXtQ"
        "BGetMl+7Tz1pkv3aAI/wCH8KqyHGatdvwqrJ0NAEJJPWoX6kVKP61E/wB40AQycdKpXLHfirktUrj75oAhTlsGpNq+lRx/eqWgCxGiqAQKcTik"
        "VhtFB56UAIeSOO9WY1HUVXAOe9WoBlaAJgcigffHpSDp+NL/ABUAY/i6XybCQ9tpr5w1dvMvppB1dyf1r3r4l3fkaTKTxwa8Albe5PuaAFjPap"
        "M8VCDg0/cOlACBjuxWhYDkGs3+L8a1NPHSgDXsjjmuh0nLrlu1c7anFdFo/CmgDpLFBtH0FaMX3aoWJ4H0FXkYDigCWjPFN3CjcKAO4ooooAD0"
        "o70HpR3oAePuiigfcFFABRRRQAUUUUAFTRjgVDTgxxgUATGgGmIT3p+KACl70lL3oAO9JS96SgApe9JS96AEPWnJ94UnegUATcUcU2M5FPoATi"
        "jilooATilBxR+FFAEo6ZoHNIrcAU4dTQA4HFPHakQAjmlHagAPeig96KACgdqKB2oAD3ooPeigAoHaigdqAA96KD3ooAKB2ooHagAPeig96KAC"
        "nR/eFNp0f3hQBNRRRQAUUUUAFFFFABRRRQBPH92nU2LpTu9ABQBRRQAGiiigAAoo5ooAKKKKACiiigAooooAKKKKACiiigCOboKoXv3TWkcYya"
        "xtc1G0tmVJJ40ZjwC3JoAxl5uG+tWH65qvGd8xYcjNXlxk0ARRffq1CSJOKjx6CnxHDZNAG3ZuQoFW45DuFZVvJxnP0q/auWYBqANNJGIFTR4M"
        "gqshBxirMRAfNAFk80lIpDZIpeKACon+/RLKFOBimq27k96AEYZNRSLhqm/iprlQaAICo9KrzWwZspVrI3UyQHOQaAKjxOqEjqOlQKHP3j+Vae"
        "MrtPeq8sW0DbQBXIwKjc9qmIwcEUmB6UAVz06mo261ZdSe1M8sntQBB1IpvlqTzVholXqcU0xpjINAEXkp6UsCKJcYoJI6DNWbTH3iozQBL0XH"
        "apI0B5NPbAXJAxUTNzxxQA2RVLHIqtLbIx4RT9as0hIFAGNeaTDIRmNR9KqNpGxztXt3roGOTTVGTQBy09mU6jmqjoQcEcV181urEnaPyrGvrN"
        "kJbHFAHOSIDJStb5Q8ClmGLnmrODtzjg0AZAi2vyBWhZqpqvMMSGn25PYkUAaAoqOM89akH+eKACimyHC5pLYkyiPrzQBr6RFtiL461dIpsY2o"
        "FHAp1ACUUtJQAUUUtACUUtJQA2TpUfFSSdKjoAOKOKWigBKZL2p9Ml7UARnrTJfu089aZL92gCPt+FVZOhq3/D+FU5OhoAhqJ/vGpWOKik70AQ"
        "S9apT/AHz9atueuaz5TmQ80ANQ4qVTmoW6dalt/vgGgCyOnenJ3pD1705KAFq1bdKrLywq5CPkBoAX/GjjPNK1MlbbGx9qAPOPjDc400x56nFe"
        "MjrXqPxiuRuSPOecmvLIucmgB9FKetA6igB0Yy1aljxVFB8w4rUtFHH0oAvW3T8a6LSOh+orn7UdfrXTaYg2LQB0FhjA/Crn8RrPsQdwq+gPeg"
        "Bfzo/Olo70Ad5RS0UAIelHeg9KXvQA4fdFFA+6KKACiiigAoopQCelACU5VzRtPpUiDjmgAUYp60hpVoADR3pDS96ADvSUvekoAKXvSUvegA70"
        "lL3pKAJIulSVHF0p9AC0UlFAC0UlFADk61KD1qDpT0YZOTQBMjcYp47VCMcYNTZHHNAAe9FGR60UAFA7UUDtQAHvRQe9FABQO1FA7UAB70UHvR"
        "QAUDtRQO1AAe9FB70UAFOj+8KbTo/vCgCaiiigAooooAKKKKACiiigCeLoKcetNj+7TqAEpaSloAKKKKACiiigAooooAKKKKACiiigAooooAKb"
        "IwjUs7KABmlPHWvG/jR8QV0zzdM00k3B+VmzwBQBe+J/xSs9Ljk0/TGZ7jGCwPQ15h4K1fU/EPilJr65eYg5CsSQPwrz26mee4aWVmLsckk5r0"
        "X4GWxfVpbkr8qDGfegD2+x5TNXounSqsCgIAKtRggYIoAeBk0/Z701Qc5qSgCSKTbhQOlXIZSHBJ4qtGq7Qcc1KOhoA2LScbgO1XldCcCuctJS"
        "JNp5NbFvIGAwOaANOLhTSs+O1Qo+FGTTvvGgBjruOc4qVEAQe1NLBeooEnHHegAPWmmPcetOHNRyEq2BQAjIAKZTixIxSHpQBGXprNuocHPSm0"
        "ARyLyTmo6dIxDHrUcjYGc4oAUg+tMV2J5Apu8noc035hyM0ATOm7HP6U3yx65/CiIkg5qSgCJlVe1Pj5APSlYA0LgCgB8khK4xUJlxSuwx1qu7"
        "UAT+aD060123VWJ9KliznmgBTnsTT4g5YjFSxpkgepq3b2x3nkUAQxrlcsOao6rGDC4UcgZraaEocEc1RvlXkUAecXYYT525yauRRuYxkcCrd/"
        "bKt2wHPPFXLSOHyfnVcigDn7+EgBguKqwMUOSK1tVaNVYKV9hWPcIT8ytj6UAXIZcvUoftVG2L4zzVqLODnrQA9zuUg1c0u3Mkwl7Ac1SIzxmt"
        "zTFEdqB3NAFoc0UcUcUAFFFFABRRRQAUUUZFADZOlR1JJjFR0ALRSUUAFMl7U7I9abIQcYoAjPWmSfdp560yT7tADP4apy9DVwfdqnL3oArP1p"
        "jVJJ1qCQkdKAIZ+AcGs7+JvrV6VuDmqHdvrQAHkVLBw4+tRZFSw/f/ABoAtHr1NOSmkHPenKDQA5eGFXYvuCqyLViP7tADmqK4/wBW1SnNQ3Wf"
        "KbHpQB4T8U7h5NadSchTXFxjlh6V0/xFZm12fnox/nXMR/ebPpQA6hfvCkpcHrigCdeXXFbFr0/Csm35INa1tQBoWS56+tdXpiYiWuXswAPxrq"
        "dNz5S59KANezOGq1uqpaevvVnGaAHg04VFS5oA9AooooAO1OXvTe1OXvQAv8NL2pP4aXtQAlFFFACgEjNOTOaEHFSBaAFHNL0NA4o70AHekpe9"
        "JQAUvekpe9AB3pKXvSUAFL3pKXvQAd6Sl70lAEkXSpKji6VJQAUUUUAFFFFAB2pO9KKKAJYxTiaYhxTqAEUfNUwHy1EODUoPGKACgdqKB2oAD3"
        "ooPeigAoHaigdqAA96KD3ooAKB2ooHagAPeig96KACnR/eFNp0f3hQBNRRRQAUUUUAFFFFABRRRQBPH92nU2P7tOoAKDRRQAUUUUAFFFFAAoya"
        "f5Z9RSR5LVNg0AReWfUU1lK1YwaimBoAjooooAKAM9KKhvLmO0t2nkOFXqaAOZ+JviaLw74ekl80LM+VQAc5xXybr2oXF/ezXlxIzySHJz2r0T"
        "4v+KP+Eh1uQQufssBKoOxPc15beOc465oAh37jk17j8C7IRaEbl05lbP614faQPcXMcCDLOwAr6b8C6Y2m6DDbEY2oM/WgDqYP4atv1H0qtbDO"
        "36VYJyaAJB0paB93iigCzH9wU6mx/cFSRgEnNAFeYukgdDj1q/ZXROPmqJ4UcYINUwDbSAMeM0AdNDKGwCatwsrfhWLaPuwQavwna2QaALc/ao"
        "0+8KGk3dSKQHoc0ATntikKFm601Tmn9+tAEB60GpJFXGQajoAjlcbSo61UR2DEHmrrJuHHWofsxBzQBVu5kRMnrVPzmcYxkVPfWcjscHiltbfy"
        "0AYHNABEhA6dad5Z9atJ05AqI9aAI8lOtIZ1BwaWQiqc4+bigC4JFboRSGVFyM1Q3YP3qjmnCk5oAtvKrAgVHuqh9rGakjulI5PNAFztV2BVOC"
        "1Y73iIpY9BTDrcSJyKAOoQRcHjjmq91qUcB4bGDXLTeJdqkIlYmo608+AEJ5oA7TUPE0aJhXXd+tc5eeIZN5LM2DXPec0s2Tx7Gp5G8wYYL+VA"
        "Gi2rp5iyYz9aSXVBtZkB59DWexHldFyOnFUyW9aAFu7uSaRic49KfBJuABqo3Bye9SQkgjFAGnE+xeamjYOMgYqKFQyc81IuFBAoAtWcXnTgdh"
        "1raGAAB0FUNGhxC0nrV8YGc0AODjHSl8welR5HaigCTzR6Ubx6GmUmf85oAk3j0NG8ehqPP+c0Z/zmgCTePQ00nPOKbyegqMuwJ9qAJTRWZfat"
        "DbRsXIBXmsCDxnDJcMhIwPagDsqSqVpfLcwq8Z61dH3RQBC3U0gpW6mkFAATUbtxipG6VAfvGgBkj7BnNVZGz9DU1yQRg1Vc4FADXPzCoJOv41"
        "ITyKgkbr9aAKs/8QqkrdR71clbO4VQPD/U0ASD71TQ/fH1qEcflVmzUNIM+tAFqloYYJFJQBND0qZWqCE8VIKAJS1QXLYhc+1PzxWZ4gv0stNl"
        "lbPC5NAHhPxCf/ifXHs1c6hzzWh4lv11HVp5uzNms8DHFAC1KOlRCnqxyKAJ7YZ7d62bZSMVlQuBjIrUtZVJHBoA0LEfNyK6rTvmRfpXOaf8zY"
        "I4rpbFQir9KANW0+7U4zxmqduxANTbiKAJ6KRDlcmloA9BooooAO1OXvTe1OXvQAv8NL2pP4aXtQAlFFFAEsQ4qSmR9KdQAUvekpe9AB3pKXvS"
        "UAFL3pKXvQAd6Sl70lABSqCTSU+PrQAbDRsNSUUANQEU+kooAWikooAWikooAWiijigBVBzUgpgPNPFAAc05TTaKAJdwo3VFRQBMDk0pqNOlPo"
        "AKB2ozQKAA96KD3ooAKB2ooHagAPeig96KACnR/eFNp0f3hQBNRRRQAUUUUAFFFFABRRRQBKjgCnBgTjvUIp0X+s/CgCbFFL6UgoAKKKKACiii"
        "gBUIByal8xahooAm8xaZIwbpTKKACk/WgnAyeAKw9V1+CCTy4XGR1Y9AaANppERS0jBAoyc8V4x8YvHpWR9I02Uc53svYVF8TfiUwt/7M06ZWm"
        "YFXdc4WvGbqeWWQySOWkY/MxOSaAC7Yt8xI57Vi3pzLWuclOayb0fvQKAOq+FWmC88QxzOMiPkV9E2ACRqOcYrx/4L2eEe428ngV7BaAnCt2oA"
        "0omVepqVWDcg1WqaH7v40AWo+EIPU0negdKQdaALMf3BU0PU1DH9wVNF1NAElV7mEyRMtWgM0rqNvWgDMt5JIMK5xitixut643VlXsJMZAHHrV"
        "ezuXgbY3FAHVDJGQeKlRhjBrKs74PgZ4qybgbtoNAF4EY60uQR96qO9uxPNAkfpmgDQKn1zTagQtgc5p/mHpxQBKpwRT2cdqr+Yfak80jHSgAl"
        "OHNR71bikkkJY8CogSDmgCVmCnFV3cUTSkNVYyHNAEjPt5OarXDqT160s8+1eaybu5wflNAEl1KVPBrPvr4JHkmkmkd8kVj6nvEDEk5HQUASTa"
        "qig5lUfjVGbxBCr4E6DHvXE6zp2o3N2zPI0ajjaDiq6+HX2IzysWb/AGqAO6bxFC42NcIM+9RnVrZzgXUf4GuLm8PlWA3s3tmp4dLihQkqQy8f"
        "jQBv3GuWEZJa7jJHvVD/AISfTfOwrkn2rIudCBKsyMARk1XXSOuxAfegDsNO1O2uTuEgX2JrVM8Tr8j5+leZPps5nxiQf7p4rTtdPvo8bZZdvp"
        "vNAHbGRRxkYqtNqNpbHLSqxH8IPNc0bO8P8b/99Gkh0x/PBnyMnqTQA2+8XM995cVqyIDwK2tL1J7kKSuAao3OjQO6bdu71Fa+l6Y0KAsOKAN3"
        "TyzJk9KspF5kykdjUNkoWOrVu6rIBQBrx/u4VRfxoyarG5UY5FH2pfUUAWcml37etVftS+opkl1GB8xFAF3zV6ZobHXdWcbuHBIPSqx1Jf4sUA"
        "bGR60FgOSax/7Sh9aQ6irfKM/WgDVkukjXJPFc54g8TLaqwjGce1Pup5JBtUmsq6sEnbEiA0AcDrvim5ubply6r9Kxv7TYv8sxB9xXok/hqxct"
        "lFyRWFf+DWYnyAtAF3wR4omjdIp2zzivWrC7W6gVxgEjoK+fJ9Ku9NfeN2VPQV6V4C1nzIIxIxz0IJoA7xhyaQUz7QjLkdDSeelAEj5warO2OT"
        "UjTptNVXkVxgUAR3DZfg8VA7A8VJIMk1XY4oARzgiq7nGTUp+Y1VuX2/LQBVllG481WJBcYouDh6Yp70AWP8KtWZCsCTVENk4qzv2rmgDQIzkg"
        "ikYYrO+1N0BqdZmC5NAF2A5NS4qtbSDHNTBweAaAHMSvFcd8SbrybBo2OFZcV1+Ay5z+tea/F642wBAaAPIrwATEg9TSAYFMkbzJalFAAKVeop"
        "KUdRQBctxnGK1bYYIzWbZAZFacP38CgDW09cMGrprbon0rnNN5X6V0Vt0SgC+hxUoO7oahFORtpoAso4VcHNO3ioVJNLQB6TRUUcu99u3GalAo"
        "ATtTl702nL3oAX+Gl7Un8NL2oASiiigCaPpTqjR8cYqQHjNABS96Q0vegA70lL3pKACl70lL3oAO9JS96SgAp8fWmU+PrQBLRRRQAUUUUAFFFF"
        "ABRRRQAZopMUtAAOtSjpUQ61KOlABRRRQAUUUUAGT2pwb1ptFAEoIpQQcYqGnq2KAHnvRTd49aN/vQA6gdqAcigdqAA96KD3ooAKdH94U2lU4I"
        "oAnopm+jfQA+imeYKcDkZoAWiiigAooooAUU6P8A1n4UwGnK2GzQBY9KbTPN9qBJx0oAkopqtup1ABRRRQAUUUsY3tjOKAEo7E9hyalaA44OTX"
        "LfETXBoWiykMBPJhFGeTmgCe5v31K/Om2ByR95x0ryP4xeIf7Ju/7G05szbcTtnpXt3w50c2/huW/ePM0yByx6gkV8u/FR5G8dakJfvBxj6UAc"
        "pO7M7MxJJ6n1qMZxTpetM6CgBxJxis+7B82ruf8AOKrXS5bOeooA9a+D7D+zFAPO6vWLX/Vg9/WvIPg/Mq22wDJzz7V6/ZfNGoFAFip7ZST0yK"
        "b5XvU1sNgzQBKUYDOKaPvVaI3pjpmmeRz979KAHR/cFTRdTUartUDPSpIvvGgCwn3aH+7Qv3aDkigCN+UxjOaz7u1JHA5rSPHSmTAuuBwaAMeG"
        "Z7VsEZFacF2HwQBVG6jBcg81XR2jfA6UAdHHPxkgVJ9oU9hWTbzjbyan3jAwM0AaQYn+I0+NsdTVKKXnB4FTeYM8c0AWt6+tBkX1qsH9qQyD0o"
        "AklcFjg1XdyCOaa0vzdDUckvy0ALI/PWoDIM/epk0uG6Zquz98UAPu23JgGs1gM4I6Vbdg1QtHls5oAh4PSq9zZrcDHStFFRf4aimIMnyjAoA5"
        "nUNNy/JzVZtLBCgdjXVtal+qVVuLR0OQDQBjR6REHM0rKrt8qjHAqa60S2knt7NDmQtuc+tWpoJcICOAc0sTNHcmVjl8YFAEWr6NEuIomDvjBA"
        "7Vhy6W8Kn5SD9K66xZGDyzOCxPHFQXzQOTjFAHHC2dOiUsSlV5HNal1sMrbMYqi2CTzQAyorpWOOtTYpZgZMADpQA6why4yvNaxU42qSQKh06H"
        "aodh+FaUUQYjBxzQBAr+VCS2RWS2rjzDgZINd1ZaZbSwskwDZHXFY2q+EyoZ7TbzzgigDnhrDHjH60v9qv6frUN7oN/bgl1x6YrLntbyJsFXI9"
        "cGgDXfWGH/AOuoJtXlI4yfxrKLlOJFOadHIGODx+NAFmTWLnJC8fWqkmo3r9Hx9KJIwz5Bpnkc5zQAsV9cI+92Zj6Vr2epo7KrHBNYUqbWxSR7"
        "t4wcH1oA7JJA/Rql57mubgu5IsAtx61r219FIg+cFqALhVc5xQAAelIhLc9qd3oApXmnwXQO4YP0rOttI+x3O6MkL6Ct7vTHXdQBZs52MYXJ4q"
        "YzMO1Ud2CAox61IHoAuCYkjNSFx7CqsfIBqZxxQAjv71CzY5NS+XuGc1DMpUUARyOufSqt4y4FEkmXORVa7kGBxQBVndS/Wo9+OBUMz5fpTC+G"
        "z2oAtxsd2c1JI7FeKgjbcucVajwFORQBn+c6Sc1ehvFZQDioJ0R2PGKjSHByOaANZJgy8GrEBOckmsWMyKatwznbgmgDU83bxXk/xalkadVwSM"
        "mvTEkDDrmsfXtBh1ZTuwW7cUAfPyg7z7CpgeK7PxD4Jnti8luvQ9D3rk7qyubVts0TA+uOKAIRSjqKaODinDrQBftB8wrXtl6E1lWgwQa1rc5Q"
        "UAa+mRko3FdBbhgFBFY2lHEQbHWteObd2xigC6GpQQOtQo3GaczZFAEwkHY0bjVcVJ5ntQB6Vbf60fSrQqtbf60fSrIoAQ05e9NNOXvQAv8ADS"
        "9qO1HagBKKKKAFHUVMPu1COoqYfdoAU0vekNL3oAO9JS96SgApe9JS96ADvSUvekoAKfH1plPj60ASUUtFACUUtFACUUtFACUUtFACUvakpaAA"
        "feqUdKiHWpR0oAWkoooAKWkooAWkoooAKWkooAWgdaSlHWgCRelKO1IvSlHagAPejj2oPekLCgBePagY4pu8UoYZoAd+VH5UnrRQAH8KUMQOtI"
        "BmjOPSgB6vk9akyPWoMmlBIIoAnooHSgUAFFB60UAFOTHrTaKAJxgd6UEetVmYDrSg96ALNFNRs0/uKAEwaFODVhhlKgCsGxjk0AW4JlEZZgMg"
        "Zya+efi34lbVfG8doj7re3mX88j/AAr3nVvMi0i4dPvrGzD8q+RdUuZZdYuLlziQylmz65oA+1PA5abwdEoHHljt7V8mfHKxNp8QLw4/1uG6V9"
        "SfBe7a+8HW43A/IP5V4R+1HphtvFMF3jAkXb+NAHicgOcimNU0rANioWoAbTLtSVUj86fTnG+ILQB2nwdn2XpibnIJNe76cAUUgYGM184/DW5+"
        "z+JEjJwGBFfRelSo0Srn+EUAaNOj+7TadH92gC6v3RS0i/dFLQAVJGCDmmqpPaplHGKAHrnAofIFORSVppBOaAGHmmvnacU4jBpGGQQKAKzIrd"
        "QM1XuYV7LzV3ym9aYRgkGgDHm3xP8AeOB2qazvSTg9BVm5gBBOM1nyRFQWUGgDYWdWOAQKmik2ggmufimccEEVbjuc/L3oA2VfLDninSMB3qhF"
        "MrDGak3r60ATMw65qJz9KYZBmknI2cUARTkFuD2qNvu0tIRkUAR9qRjgHmlYYpGGQR60AQ729abu+bJ5pzptqNhmgC6LtfSkeQSDoMVnElTxSe"
        "Y1AFl8McEDioJ4FfBUYPemeefSo5brb14oAr3C7TtBwDWTeXXkuUzuNX7iYNzzVPyYp2yQd1AFL7SGyQhpnmqxIC4Jq7JAiNtFTpZRDB5NAGYF"
        "JHAq3ZW5LhiCR3q9HBGikbaeh+YKiEdqAJUjyAqjAHStHTbbHMgyKZaRZK7lrSVCEKigC3a8AYrQyWUYVSMd6zIOwrQX7o+lAFW8RdpBRce4rN"
        "nsrWUfOigfStS7G8fSqsqHyzQBz+oeHbS6Rtnyn6VyuqeHbqy+dMuhPFehQ/ITnmrcaLIhDAEH1GaAPGyJVbDIVI9qkyNuT0+telat4btbyIlc"
        "pJ3I4FcLqvh68tGJ2s6+gFAGcUD87SaQRqD93H41E0jwMUyRjrxTvPBGTnmgBZ84AAPNQoHQ/LuFWImD5xT/AMTQBZtNTeBQrh2NaVvqMU5AJZ"
        "T9KxM+5/KonmkRsKeKAOsRt3Qk1J1rnLHUHDBWzW1DdRFR60AWNoz3oyAaRXD9M02UHHGaAJ1c8YNTLIM8mqaZCc5pQ3PU0AaKSLt6USqHXpVF"
        "ZMd6kWcHjNAFDUl8rkHrWRJMxPzNnFaepzAqRWDPkKxBoAbLMN/SozJk8GqRlYyHJoExDDuKANqyJPBPFaaAbKydOYEjA7VrgHZQBBgZPFPjA3"
        "4xTdpyakgB8wZoAnECkHioJbcgHbV7tRjHGKAMhfMhJc5xVizvkZ8HANJrswt9OkcLyK8mk8VzRagVDnANAHsUkcE8bBkRsnoeawtX8N2V5Ewa"
        "MDPoKytC8VW86KDLhveuntr2OZQRIGz6UAeX+IfA89vultct7VyklpNbuUmjZCPUV9B+VG4+bawNZeq6DY3qMrQpkjr3oA8YtiM8mtS05wBW/q"
        "fgyeBi9uCwHasZLKe3kIaNhg+lAGvp3ESitO36GsqwPTKkVq23Q/WgC2jDaOaUEHpUAP1p8Z5oAloptI7he1AHpyMVO4HnFWYGLg5qp/D+FWbX"
        "7p+tAEtKDR6UUAPH3KO1A+5R2oASiiigBR1FPD9qYOopR940ASK26n96iiqXvQAd6Sl70lABS96Sl70AHekpe9JQAU+PrTKfH1oAlooooAKKKK"
        "ACiiigAooooASlpKWgAHWpR0qIfeqUdKACiiigAooooAKKKKACnoAaZUkfagBdoo2ilPeigAHFA7UUDtQAHvSbRSnvRQAm0UBRS0DtQAHvRQe9"
        "FACikHaigdqAF9aTvmg96WgB3mMB2pYnLE5xUdTwQlyfegBjuQcAUqOSeRV1NMuHUMpODTl0e6Y4JIoAp80BXwScVoros46s1XotIKwndycUAc"
        "ld3DRtg1PYu03HtS63ZbGOARzVXT5TEcHgCgDctbZiOaux2QYZIOaZpk28Vt2tuThj0NAGJNC6nA6UkKEP83Nbd3bqG61mThYyeaAI7+18zTLk"
        "9f3Tfyr4w8QjydXvlPRZW/nX22Hjl054t2SykV8Y/EmAWXjLUbfGF84sPxoA+kf2YtV8/wALxqSPk4rJ/a10gTaXDqESnMUg59un9awv2VdRwJ"
        "rYn7r8D2xXqHx6svtvga43KCyxkkehoA+LHX5ju681E1STnbKVznBxUXU0AIevWnDpn0pG60gODzQBPpFx9h1eG5Xghua+jPDNwtxZwzqeGUGv"
        "mx8N7HHFexfB/WhcaeLOZvnjOPwoA9XgO4HNWNoGAO9VbYgID2PSrTMCBQBZX7o5p1Voz8681YoAnQ/KOKenWo4+RgVLGCDzQA8EhcCkAIqVAK"
        "GFAELAGmYFSHr3ppFADMe9MZAQTT+9DfdNAFf1FVpgMkYGKs1Xm++T7CgCjOiqeKquzK5xWmSD6VUuEPzEAYNAFdLl1bOeO9XIJvM71kSRuSak"
        "hm8vC5OaAN2PJUGnsxYYNULa54+Y8VcWQMMg0ALtyM4oxUykKMNxTSjE5HSgCF1zimhRVqNSBzipBGTjgYNAGdIqntUfkkgkZxWr9mWlMCBSM0"
        "AYZgJJqN4CGxk1sG3Gc1HJabiODQBiSxurYB4rPvEldwD2rpLi0ZXHFZ88AWQ5FAGTHbucA9Kf9kMZyvNX9oHGKXHrQBltbM7ZOatJEVwTVkge"
        "lRjOTQAwoDU1pAWYfXio246+ta+l25VQ5HXmgCa1twqZYc1OUGc1MVJQGmlDjNAEeNhBFWg7YH+FV2BOMVct+VwMZoAhPIOahnX5MCrrrlSOM1"
        "XnXC80AZxGDU9u7btvaoXGXIqW3Q+ZQBpWyBhg1Dd2yksCoYHsat2gwOfSpJACDuoA47UfDVrdqzBAre1cNrOh3FjI2EJjHf0r12RAG46VSvbF"
        "LpWEigg9qAPFo5ipAUd+ameUhsA5rb8WaC2mPJPEhaI5Ix2rkmuzn1oA0DM3rTGYscmqazhutI1zt6UAXgxByKlF5IuPm6VjtdMc4oWV29aAOr"
        "s9UUJljyBV+DU4pCB3riUDAgk8fWrEdy0TArk0AdwZkZTjFQbyaxNO1KOQ7GkAbuDWqjKcEMKAJdx9aUMQetNNRlWzQAtxF5iE55rEvlkRSB0r"
        "djBAwaZNAj9qAOEuJ3SQ4pUnyq55NdDqWkGQkrHuB9K5+7sZbWQ/KcZoA6DSBkKSecVrMxXAFYmhhsDJrakHANAAc9jToSfNFM/hqS3XL5oAuA"
        "84HTNOcY5HWm4IYfWpJDxn3oAwvFkgXSZc9xXgV+R9ukIGea9t+Isxj0lscAivCp2Jmc56mgCaC6lgYFCQfrXTaD4suLYqr8iuQBIp+eOuKAPa"
        "tF8UQXYUFwpPrXRwX0bgjcGA7ivnyzu57eQNHKeDXX6F4omhOZWzmgD1w4ljyrHBqndaTDcoQIxu/nWJpWtwzpuWQZ9M1v2d6HAw3WgDAu/D0s"
        "ILxNuIP3az5Elgba6lTXeACRTgiqk1jFcZDYx60AckjZUGngkdq0L3RFR2aPkA1nzLJEdrIcfSgBd596RyW6imBge1OJx2oA9SHT8KsWv3T9ar"
        "KQcc0u5lHB70AXvSimpkxg07n0oAePufjR2phPNPyCMYoASiiigBR1FKPvGko70APjqXvUake1OBGaAHd6SloFACUvekNL3oAO9JS96SgAp8fW"
        "mUoODQBNxRTUyafmgBKKKWgBKKWigBKKWigBKXtRRQAD71SjpUXNGTQBLRUWTRk0AS0VFk0ZNAEtFNTJ607FABUidqjxSgkUASnvRUe40BvWgC"
        "SgdqQHijNACnvRSZpaACgdqKB2oAD3ooPeigAo9KKPSgA9aVUZ2wKTIJwKtWcTFs9qAGNbFV3HpVnTZk8zaelT3KN5OO2Ky4lKTcZFAHa2rYhU"
        "IeKsoWHO79K53T7p1UKXNbcE/mADPNAF1dx7/pUzRqYyMc4pIBlaQkgnk0Ac1rVnv3EiuWe2Kykehr0S7iWaMgYLVyWsWzW8hIGSTyKALOgIow"
        "WrrIzGExXEafchSFPymuhsbwsQCTQBcnXeTisi9gY5raA/i7UPDG60AcwzNAu0mvlj47wCLxzcOBjzOf0r6z1q0wjMo6CvmL9oS3Eetx3GM71x"
        "n34oAk/Zs1A2/iowZxu5FfT/jS1Go+EbmErkmM/wAjXx18H7w2njSzIOCxIr7ORxdaMQT9+McfhQB8Fa9bm11q7gII2SkfrVKuu+KlkLHxpqMW"
        "zbmQtXKsMLQBEx5opT1pKAFHPet7wLqJ03X4SXISQ4YZrABwetPdisiSIcFeQQaAPqPRrpZ7RGU5rYiO44PpXk/wq8S/arZLadsSJwR616lbyA"
        "uCG60AWox+8FWagixvBzU9AEsHWrSDLVVg61bi6n8KAHrxSkZoPQ0tAEMgwe9MPpmrBAPWoJByaAI2FNP3TTjTGYYNAENV5/vH8KlmJ2cHvVWZ"
        "iR15oAjfAJqJ3yCMU0saYxAOCcUARPGMk8d6rMgBPvUzN8x54pjkGgCASOhODmr9jdLuAY8+lZkv+sIFM3MrFlPIPegDrI5FkI3ccdqsfSuUt9"
        "UljOJVDL6jrWzaajG68MD9aANKpo+QtVIJlkzzVqNgQMGgCXaPWl2DP/1qah7mngqf4jQA0hcUh47UrgbeGqPIA5NAFa96g1lXChpDmr9443ct"
        "VC6YZUrQBWdQGplSkjJqLvQAh6//AFqTHP8A9anMOM0qwvKVVc8nsaAJbK38+YZ6CugjRVQLgcVDZWhghBK8+tWRzQAqKGBBpTGuKcgx1p+B/k"
        "UAU8Y7VPbffqTavp+lKoAPHFACetQXX3KtKnOaqXPegDO/5aVZt/v1EQM9KlgHz0Aatt/QUsv3T9aLUHrjjAp5ANAFN1B5qMgVbkT5uBxTAoOR"
        "tFAGbqVhHf2kkLKpyO9eLeLNGl0fUGR1IRjlSa978s5zgVzHxC8PJqmllwB5icggcigDxJWxQTmiaJ4LqS3kBDRnBzSUAGacrkCm0UALvOetP8"
        "w1HRk+tAD92WyBg1ettQlt2BOXXpis6l3N60AdXY6tDKoDfL9a1I5EkXKEEVwAZgcgmtjR9SaMBWJ+lAHVEYPXNIelVLTUIZDtf9KuZRs7TkUA"
        "NDEg4qhqNoZuWz9avODgFaVVyvJP0oAzLODyRgLVotkdKslB2FROh7CgCFzhatWXQGq+xj1FWbUFQe1AFp/vD60SDIqMk9zTtxIJ7CgDg/itP5"
        "en7M140TlyfevR/izftJMIweK84XrQAd6eBSce1CmgCSNec1ahOKrrU6dBQBpafPKkg2OwA7ZrrdH11olCSA/WuQs9o5rVtiTgAcUAejadqqyq"
        "CHx+NbNrdRsMZFeZWkjxchiD9a17LU3SVVDE0Ad9lWOMAg1WvbGKZOFwapWt8vlglwDgcVfhuBKoCtn1oAwLvSpImJTJH0qjIGj4dGrtlAZecH"
        "61VlsIZzwoDUAdAvFSIciouvenxkAHNAFuKXotTGqKtzkVYhcnqaAJuvWgYpNygdRSBgRxQBIKKQUtACqR3FKQOoptOXrzQAbjRuOc0h60daAJ"
        "UbNPPFVwdpqVGzQA6l70lLQAd6Sl70lABSjrSUo60AODY4pwOaiNPRu1AEg5pabkAUuaAFopM0ZoAWikzRmgBaKSigBaKSigBaKSjigBaKTiji"
        "gBytil8z2pnFHFAD/M9qcrZqLilU0AS0HpQhpSR60AJRxRkUUAAODT94pmaKAH+YKPMFMooAk8wUeYKjooAk8wUbxSwRPI+1ELE+1atno5OGnB"
        "GewoAz7O0lnkxGpOfauis9LkSL96QCa1rO1jitwkcYT3xzUghP8AeoAxLiAghMjA4rNuoNjErzXSS2ZZiapTWLF+ARQBgxOyHnIrUsrraQd1RX"
        "1kUJABzWeN8JyTxQB19re8gZq7vUr161x9neZP3q1obzOPmoA1UIEhNV9Zskng85SN3fimwXIZiD3HWp7aYMhRyDmgDibxfKuMAYxVzTbnLBd1"
        "Xdf04jMqjisC2YpLzkHNAHbwTgxYJq1EoZcg1zVndkr1rYsrvgCgA1WMmGRR6GvnP9obTi9jFcgHCNzX0pdBZB14PJryH40aYLjw5eKVyVBK/h"
        "zQB8z+E7r7Hr1tc5wUevt/wTdJd6DbSnkMq5/KvhEZhuSRxtavsP4G6uupeELdedygA/hQB4n+0jpRtfGDXYGFlJH5V5Qw+XFfRv7UOmNPp8V8"
        "o5Rjk185t0oAgI5oYYpxBzRIDtFAEZ5GM08EEfSmU+MZODQBr+EtTbTtSRweCeea+hPDepw3trHIrgkj1r5lKlfmGeK9F+F/iJoLlLadyVbgA8"
        "UAe828isAwqwjBjisbT5w4G3nI4rQgdt/WgDRtx8+KuKuO9U7XJOauKeaAHHoaWkPQ0vFABVeTgnrUjsQeKrMx3HNACE5qFvvHmnk4qM0AMlHy"
        "fjVJzl6nmcg4zVdyMnmgCu33vxqvORvGanbrmq85ywxQBDv5Io5qNyQSR1pm9/X9KAGTf65hUcnTOe9PkyeT1qEnJxQAnenpLIhG1sCmd6O9AF"
        "2PUHRcc5q5b6oygEnr71iscHrULSEE84oA7i0v0dRnmrInQjOa8g1rxs2i7gqmTaeasaR8WNDuEX7QZbduh3DIoA9UecY6kVXlnIP3hXNWHjDR"
        "L9QYdRtyT/ATir/2iCUhoZ43B/utmgC3PJuNQOeOlNLDHJ/WjcCDg5x1oAaynJNMqlqmt6XYDF3qVtEfQvyPwqnpHiLTtVuGispxKV6kUAbSDc"
        "2M1t6Hbpv3OM+lZcEYBGTnNbWk5EoGOKANN1DAjtVcRlT1q1ULH5jzQAhHpQOPX8qegzSOMetADfxNA4OaQHnrS4PvQBY6L+FZ1z3rRP3fwqjK"
        "Mhs0AUtv8WamgTJHNMI+UirFmOeaANK3X9yopWTaM5p8IAQUp2kUAQkVGEYNnNTSAAjHpTcUAFK8cckDK65zSYqVFzGBQB4f8T9Gay1RriGL92"
        "3UgVxanIzjFfQ/izRk1W0eGRdxI9PavCPEGmTaVftBICFBwB7UAUKKKKACiiigAooooAKkUkHI61HT8fWgCxbzyKc54rXs9QIAyxwOorADEcLT"
        "kd8/exQB2dvfQyKB0/GrSkEZByK4yG4KOAGrXs9U2AKxzQBuk4HSjOe1RQTpMu5WGPTNSDHY0AL+FKpx2pB160uDQAu76024crA5BxxTwPao7y"
        "NntnVeCRQB4j8RZfN1IkOCOlckOort/HOg3guGlSNiuc8iuMaMxsQwwR1oATn3oQEmg49qtafAJ3ABxQAzBFTQjdx0rTvdPWCNDx8wqiqhW4NA"
        "FuFQAMnmtez6ACs22CnrWhbuQwAoAvngCr2jIHuQDWXvJxW1oKj7QDQBsX1kxg3xkqcVTsbq7tn2vkj1roVBdAh6VR1iBYoMgAGgCxZ6mG+81a"
        "kN0MbwwNcAZXjkJVuhrQsdSZfvtQB6VGcE81KpyKgU/NT1brQBOrYAFPzzUK807NAEnepLf79V80+GQoSR1oAvE9DTtw4qOJyyckU705FAD8g9"
        "KOKQGigBaKSlFABSjrSUUATg8U6oA3+c04OPWgCXFJmmeYPWgNk9aAH0vemind6ADvSUvekoAWikpe9ABRR3pKAClHWkpe9AEw6UZqMMaN7UAS"
        "Z9qM+1R729KN7UASZ9qM+1R72o3tQBJ+FH4VH5je1HmN7UAS0VFvb2o3t7UAS0hOKj3t7UhYk80ASg0uM1EGpd9AEykAU7eKgDsfpTgfpQBLvW"
        "jzBUefcUfjQBL5gpDIMVC7YoiV5fu9KAJ1JbG0E1oWFmZcNIBin6baqoBYZzW1CiJgcYoAZaQRxEYU5+lbEDAIKp4U46VPE3y0AXywK8VGPvZz"
        "UYmBGBik3mgC2h4pTF5lVBcBTzircM6EdetAFK/s8jOBWFd2J54rrWfcMYGKq3VurocDmgDh3jMRIwakhnKLgmtXULP5jgVjOnJU5HPpQBtadM"
        "XG0kc0/UPNgcGPnnJrLsXETjJNa6P5iHIGCKANSzkiv7H5z82OlclrFqbe9yFwua2NMlFtdhA3ytxVnXtPM8IljyW70Ac9byjYcCtPTHyTn1rE"
        "PmQStGwxWnpkqqDn1oA2xIrfKQcGuT+I1rHdaHcKo+YoQPyrpoXG0tWJ4neOSExHo3FAHxZrEBg1OeIj7shFfQn7LupiXTXsnb5kbgflXjXxO0"
        "ttL8TXIIOHYuM+ldP+zxqjWPioQ78LIwIH5UAe7fHXS/t3gi5kUAuFJH4V8fyIUcoeoNfcnie1/tHw7PB1DxnH1r4q8S2bWGuXVq/WOQigDO/K"
        "kboaKD6UAQn6U3o1SsnHFM2igCZGDJgetW7WSS0njnTqpzVODoPrV0xlwAOlAHr3gDxKbu3CSNyvrXo1jKH2knkgE182+HL+TTLvdvwuRXtnhT"
        "WEvoY8HJCjNAHoFm61bBBasexuQAoOM1fE+eVoAslwKazA0xWLdetLyKAGbwCQc1WldeT71Zcbjk1WkUHcKAIfNX3pDKtNlXbjBqI/WgCOVgX4"
        "qCb79Omba/FQu5LZoAZICV61A67SM1OTx1qKcgkfSgCt/H+NNl7fU1KUXrnvUU/AH1oAhb7p+lQDrVgjj8KYI1oAi70d6c6hWxTHOFyKAGT1ka"
        "rdi2Rix7cYrSmlAiLN1FcV4rvcwMVPPNAHDeM71p5iAerZrlzJt4WtDUnaSZnY85rNkXAyBQBLDcTI4ZZCMehrZtdc1OBR5V3MmPRjWCg4z3qz"
        "ExAoA6fT/Futfa4UbUJypcA5fI619EaMIpNIhlzvaWIfN+FfJ/mssgb0Ir6g+G1wLzwtYOTkBQKAPB/isJY/FUybiFIyB+NafwYvymuSJI2CRt"
        "Aqb482X2fxHFMBxIv9a5TwNO9v4mtnRiNzgGgD6jsF3qjDp1roNKXBZvWue0Fg8CYPG3+ldTpsY8s9aAJ6iCfMTU7jB4ptABTWGeMU6igCBkwc"
        "1JCcp+NK3PFKgwMUAJJ9w1Um6ircn3DVSbqKAK+OalgXc49qZ/jVq2QLhhnmgC7EMJTqF5XHtR3oAKKKKAGS9qfH9wU2XtTo/uCgBwAIINcD8S"
        "PDQvrYzxR/MOjCu97UlyivblW5B7UAfLs8bwXDQSKQy9aaDjtXd/E3w81tctfwowRutcCWPfoelAClxmmM3NJ1PQ0YFAEifdFOpqdKcQT90c0A"
        "A61PwVqAJJnpV9YG2j6UAVGBHQcUmD6VoQwtzlanW3B6rQBlwqc9Knjjc4YZrRS3j7CpUiRRgCgCK3aVQK29NbcmXPzdKzR8qgbalWd1YEY4oA"
        "3441PNWIokIPFZFpqWwATIQfWtS1uopeEOTQBL5C5pTADUtANAFK60yC4QrLGGPuK4rxL4DtLws0QETjptXivQjzTWRWHI59aAPnvWvBepWJdg"
        "pkQdwK50Ce0mw6bSPwNfT8+nwTqVkQMD61ymueCrG9LOI1zz0FAHi0l7JKmGPHbmo4/myTW/r/AIOvbCaQ28TmME9RWJHA8YxICDQBZtTitK3O"
        "T+FZ1tGwfnpWlCu0AigCyv3hW9oC5uF+orBXqM11Hh2Jd4bvkUAdRbR7nGO1Z3ifptHUCtiyAD5PSue8VXH79lX0xQBzjsAxzTKRuWOaRjigD1"
        "9TzxT1688UwZBp4Y0ATp0oqMOR2o8ygCSnKcGofMpyNuoAmEh7cVJE535J4qvzTgxoAvGaPPWnryMis/ec9KnS4KqOKALOOKcDVcXH94YqVG3A"
        "MDxQBITRmm5oBoAdS9OtJuPvSbvagB4GehoGQeaaG56CjrQBMpGKUsB1qJRSMBQBNvX1FAIqCnIQKAJqXvUfmegzR5h/u0ASd6SmeYf7tHmH+7"
        "QA+l71H5h/u0eYf7tAElFR+Yf7tHmH+7QA8mjcKjMhx901HQBY3CgMCcZFV6VTtOaALGKKi8w+lHmH0oAkYgdSKTevqKikfIpm4UAWN6+opC65"
        "6ioNwpRgigCfeueoo3J6iq+4Zpc0ATl1HegSD1qvupQc0AWNw9aN/vVerlraTXTKqjj1oAdaxGd8DkV0Gm6cqxnI5qbStJWBQeCT1rZWBY0yOt"
        "AFNLcRp0ppPz8GrUpAX61Uk4JoAlD5PDVLG4C8nvVB2PrUkDnbzzQBf+lIWwME0xGyRTZvvUAI7ENnNWra6HHSqZ6VFkg5FAHRxSq6ggipAN3F"
        "YNrO4bHpW1azrIuW+VuwoAjvbYSRkYGa5fULYxufl5zXYElvvVUvbNZlYqBvoA4ohlcEg4FadnPmPb7VFqNuyyEYIIqpaO4lwe3agDSlyMMOSO"
        "a3dJvRcxGJj82BwawWbIxUdpM1vdjaetAGhr+nKsnmovJrBt5WjmK4713S7Ly04XdgVyurWLJIzRjBFAF6zYtF+Fc94kZjIFIwQa0dLuPL+WRu"
        "e4zSeJYFmtBMg5HU0AfP/wAfdKBW31NQefkYjtXnXgDUjpniezud2MOAfpxXvPxCtF1DwzeW7oGIUEeufWvm1g9vf4GQyvnj60AfdWj3f9oaRH"
        "IOjoDxXy58fNH/ALM8YvMqkLOMg+te7fA7WY9T8LQHfuZFCEZ71xv7T+jmTTodSCYMRAJx70AfOtFKwAxg9hSUAHamspJ4qRF3U9Yxkc0ARwxs"
        "Mcd60YhgZqFEwalDEcUALNGCNwPNdD4O117C8jjZyozg5NYUfJpskfzb04IoA+jtEvxd2iOGUsCDXQwlWQNnn0rwXwB4r+yyC0umIAIAJNeu6Z"
        "qiTRKyMCGFAHRKcNjNSq6+tZSXAaTbuqxEwDfezQBd3jPJqvI6jJzUNxIQ4xxUTSHaaAFmdTjBqu55JzTZpSMcVE0pINADJD85OeKY3NDNxUbv"
        "tNAA+QKiYkjvTi5NMbj0oAjZiGpk/IX6048vTZ+Av1oAiJAHNN8xPWnEZGKiZcc0AEhBbINQSSLtIzzUhqheSbQRQBS1y6WO3wG5rzbxHdGTKg"
        "8k11eu3OUK56VxeopvOaAOcuUbd+NVZQMbcVpXa85rNm5c0AJGBtxTxxTEODTiaAGEZY19EfBG6MvhOJWP+rbFfO1e8fAOYPoEkIbJVyTQBnft"
        "EWXmQ214o6cV5Fo0vkarbyg4KuP517x8dLfzvCZcdY2Br59jJSaNx2YUAfWfg2QSadA4Odyg13VjhYzXnPwvlFzoVq4OfkAr0e0Hy0ATNz2qIq"
        "c9Km5o5oAgKN2FJ7HrVioH++aAEoopDnBoAa7AqR3qtKpJ45qQ9e/WkP40AQeW5wMd6vWiELgjmoV++KtwffP0oAsIDs6CoyDmpo/uVFQA3BoP"
        "AyadTZfuGgBkhBxinx/cFQE8U9JCBjFAEuOKU8ijtRQBleIdNh1DT5Y5lBBWvn/xHpMunapJbKrFQSR7V9JTrviZfWuG8X6GssrXXlfMR6UAeK"
        "NDKhG9CKcELdq7O80kcnZz6VlzWRTPyYxQBkw24KgmrcFsmenarMcYCgFcGnKm3mgCIW6Z6VMsagDHNFOHByaAHKoHanDHQ00HNLQApVR0NIPv"
        "A0UUAWJNrrhOtReU/p+tOtv9ZVojJ5FAFQxyHqDj606NngYNkj0wasYGelQXXUUAaVrqvADsRWrBcRyIGBrklO1gcZwauwXTb+u0elAHTBge9L"
        "WTbXy9CelX4rqNxQBPkjvSY9KaJFPQ08cjNAFe7sLe5iIkAbPWuR13wRZXW5o0VD2IrtHJGMUx+RzQB4rqnhm705yVVpUHcCszzGj+RlII9a90"
        "ktY3jKlASeuRWJqnhWyulJWEBj6CgDyuNgzqQw69K7Tw8p2A+9UNS8JXdrL5kSBkBrT0ZJ4MI0eDQB0VsdqscciuN8Sz774jPQ811vmlI2yO1c"
        "DqriS9kfOeaAK7n5sg0hJNJRQB7EG96eDnvVQHPSpEfHWgCwKX8KYpB5GaduHpQAv4U6PPambh6UBvwoAnBPelBHrUI+bvSEc0AWAfQ0uTUMZA"
        "HJp28etAEqnPWpPMYDAYgexqurA0u7tQBOJHP8bfnQZJB/G351EDRu9jQBMZZMcMamgk/vtVUPShx6UAXjIn94UeYv8AfFUwQaTP+cUAXhIP74"
        "pc++apKcGpRKAOlAFjNGagE49DS/aF/umgCYHPejPvUH2hf7tL9oH92gCbPvRn3qH7QP7tH2hf7tAE2fejPvUP2hf7tH2gf3aAJs+9GfeoftC/"
        "3aT7QvpQBOT703zE/vj86iNwpBG2q+RmgC75if3x+dHmJ/fH51Szz0pCeKAL3mL/AM9B+dHmL/fH51Q3n0o3n0oAv+Yv99fzpN6f31/OqO/Pak"
        "3ewoAv70/vr+dLvT++PzrP3ewp64PagC8HT++PzqGd/wC64/Oq7EDpSBiegoAeJXA+/wDrTkmYNjdnPvTMGtPSdOaeVWYDFAFzRNNe5OXY7fUi"
        "uq0yw8rEYX8QKdplkIYVUDiteNViGcdfSgCS1gWOLGBmkmjYgkVOhyue1SiIkAnoaAMopnqpNQyxgE5Wt023+zUU1nvHC0Ac80QbtinpGFFar2"
        "mMHFMNtz900AQ26Bh2FTG2Vu9XLe1UDGBVmOBVHQUAY32Ub+Txmq9zbNu+XpW3JGgJ4qNlQrjFAGJGpjWrFtIVYMSc1bltgY+MCqPlneOaANi3"
        "m3MEbn3q9FFvYDHHrWNbPtwT2NdBY8quO4oAzda01ZLfci/MOhAriL62ltJdzEgk16zDEkmUcZBrlvGGmfOdicA8UAcks2+Mc80hPz571EitEz"
        "K4wc1IvPNAHRaJdmErET8p61r3tgLiIvEAa5VJfnUqDmuw0G7WVFikYAHrQBxeqafJbyllBxmpCvm6cyE84ziu51bS45OUAYH9a5i4sik5AHy4"
        "5GKAPNNVtdwkhcgh8jFfOHjvTP7N8QzKFwpbI4r6o8RWbfaHZFwAeK8P+NujNG8F5jAI54oA3v2Y9X8u9n015MZIZAT1zXsXxU0Ea94RvLNxnC"
        "kqcenIr5b+EernSvGNnIzFY2cKxHavs2BY9Q0UHdvWSPOaAPga4haCd4XBDxsUP4GlVRjpXXfFXRm0jxjeQ7NsZYsvGOtcuqZAJoASOMelSCHn"
        "NPiAHapQCcGgBFjz1GKGiANSg0HmgBqjFKKkMWBuzUdADCrpJ5qHDDpXceCvFbKi210SpHvXF5HpUU25MyRZDDpigD6D0/UY3CsrZyMjnNbUFw"
        "siZDAH0rwrwd4lnjlWGeRj25Neo6TqEdxGHVvwzQB0sjMTkkmmlwOrVVExIHNG8HrmgCWZgcc1AzfMRSOd2MUwsaAFdjiozkmnFvWkJ9KAEH+e"
        "aa/PNOo7UARYGelMlGcfWpip7UjL0oAqdDSNjHNTPGSSc1DIPkNAEE5XHBxWLqrny2wcVozNhSDWRqRLRMvrQByGrFi5yTisK5BxXTX0Ocg1jX"
        "cSKjMwwFOKAOb1BkjhPyjJNYxzyTV3UJS9y2DlQaqEZoAb60jdaft60w9aAADJr2b9ne4H+kQep6fnXjIB6ivS/gDeeV4le3J++uRQB618ULFb"
        "nwpdx7Qf3ZI/I18sKGWQhudpIxX2R4jtRdaRcxHnMZH6V8i6xam11e7t+hSUigD6E+Bd2JvDcUYPzKRxnpXr1qCI+Qea+e/2drwlpbVn5U5r6G"
        "t2zbpQBJRRRQACmuvU+1OBFI3Qn2oAgFB6UUe1AFc9e/WkP0NKR83Q0nX1oAfarmTn1q8FGeBiqtp1zV2Icn6UAMJYdDxRTn+9im0AFNl+4adS"
        "NyCKAIACe1KA2RxUiLt6kGn/AIigAFFFMZ8HGKAH1Vv4lmjaNgDxU3me1IQZDnpQB55rFm1vcOpBwTxWRPbqw5UGvQPEdh50bMgywFcPN8jFWH"
        "IPIoA5rUbWRZWKBgOwFUz5mcNkV1rxpIvTBrNvdPLAshGaAMIsc9alByOtJPDLFIVkUqajDYNAEy9etPBHrUaNkGlHBzQBJRTdwo3igB4JHQ4q"
        "xA/B3NzVUEGloAuq6kdaguT0qONgrZPSpXxNyvGKAIKM1P8AZz/eFJ9nbP3hQBECQc5NT29y8bfeOKhcFG25pBwaANGDUCG5BrbtLpHQHIziuU"
        "3ewqSC5kibOeKAOu4PpSlRxWHZ6ou7bKcela0NzFIoKuKAJcClpAynoaWgBkkCTLtYD8azbnSk3ExqFPqK1aXjFAHM6haSC3YZO7FebalDNFdy"
        "cN1r2mWBZD83Sse/8OW9xuZVXJ9RQB5Juf1o3N/eP5V1Ot+FrmJi0UZI9ulc9PY3ULbWgb8qAPU0c561MhJ61RU4qeJxt5oAuo1SAj1qsGGBil"
        "yaAHu7bjg0sbMW5NR0UAWt1LmqlPUgetAE5bBxT1GQaquwJ4zTlkA9cUAWA2OlKG7k1CHBpeKAJt/pS7mqEEZpcigCwDxS55quCKUH0wPrQBY3"
        "Y70gaocnPUUu73oAm3H1pdxqLNKGA60AP3H0o3H0pvmJRuFADtx9KNx9KbuFG4UAO3H0o3Gm7hSg5oAXcaNxoooANxo3NS4oxQAmWozS4oxQAZ"
        "I6UZPeiigBKTvTsUYoAaKWlNJQAU9OlMooAkOM80qxM33aZGrM4VepNdh4d0NpijMoyfegDD0zTpJXBdT1rtdK0+JYwNo3eua2I9G8gfdHSozB"
        "5TjAoAkGYwE4qfG4DNNjVHwO9SBDnFAFqFOFFXraAs306VXgXDLn0rTt04+tACi2b2pHtztPTgVajUg5NMljY7jzzQBk+URy3NRyKAeBV142Zc"
        "CqswKnntQAyP71S4qKPrmrCoSMigCtIvJzTNq1YuAQtV6AI3AyR2waoyIoXI61fZCc+9U7lGAxQAyI4U/Wt7SXLQqxPOa5otg8mtDR7ra2xjxm"
        "gDr48KoYdai1O3a7ts4GVplq26IYORV5QPsp96APM/EGnGKUuBjmsiMYGCc816BrliZIm4BU9a4W5iMM7IR0PH0oAkjcqQV9K1NPnaKVXydves"
        "eA/vAK2dPIzigDtNHuopYvm7ioNRsTl5OMHpiq2loyr1rdRFkgCnrigDzPX7RgznH6V5f8WNJ/tHwu77MtCCeK978QWGQxA4xXneuWAe1ntpFP"
        "lyAg0AfG6+Zaaku1iNrZFfY/wT8RJrHg23JY+dCPLdfQgV8qeO9NXT9duIlUqFc7fpXqv7Mut+Rd3OnyvgPh19zQBqftSaAgMWrRJjdgEj0rwE"
        "YxxX2b8V9Gj1vwdcwgKxKk5xk8CvjW6iktrqS3lXDoxVuO4NADMkdKlRm2iowMjNSJ90UASilFJSigCw3+rP0qtVkglMD0qLym9qAI6Pl79ak8"
        "pqR0K8mgCnNDJFKZYWPmeldl4N8RlSkTviVeGB71y3vTHQhhNGxEi9MUAe66dqazoGQjpzWlFLvTIryTwd4gLOIJ5BG/Q5716Ppl2nk7i2QeOK"
        "ANbc1JyetNjdXGR/KnYxQAUUUUAFFP2tRsagBg60jCnlWpuM0ARt0NVZRhCatH7xFRzL+7IAGTQBjXHIP1qhcopBzWvNEQCpAyazbpSpOf0oAw"
        "b+FTlscDrXIeKZgsRWIYyDXW6tdxwRu5PtXA6vcGRiR0oA52UYPvUfapZzlzUfagCMt2popzdaRetACr/Wup+Ft39k8ZWb5xuO2uX7/jV/w5M8"
        "GtWkydVkX+dAH2HgSWWeoZP6V8q/E20+x+Mr5ACFZt35ivqjRpBJo8DdSUFfPXx8tBD4r3oOHXNADPgLdpB4p8ljjzBivqeBQLdK+PPhfI8HjO"
        "wKZ+d9p/KvsWH/j2SgBaKKKACmOeCKfUDn5jQAlJjmg9KXigCuc7z1p8a5zkUiH5zxUyrkcUASWiLuPFW0UDoKr2w2k5qwWwKAIpPvmm05jlqb"
        "QAUUUUAFFFFABUMn3zU1Qy/fNADakh6GozipYeh+tADSNxKlRz7Vw3irTTbXDyIuFY5rvW4GR1zVDWLJby0IYZIBoA82jztGaUgHg5qe/gNrcG"
        "MggZ4qAsB3oAjkt4pBtdc/WsLU9P8glogWXPX0roPMWmMhZvY0Acjkr7UquSQM10F3pUcmWXGe9ZU9oYnxgn0oAhpKUgjg0dDzQAqDnpT6TcBR"
        "1oAWp7c4VhkVBRQBd3DsRSjdmqanDAkmrKurEYoAhuAfNPfioqunHI6mqzxsoLdqAI6KKKAHLggggVLE8sWCjcDtUFFAGzaaqM7ZFwa1be4SXl"
        "T+tcjU9vcSwfMnNAHXE5orJs9QEyfOSDV6GVW6NQBYpD70bhUcx4GKAJGCsuMD86oXGn27tlo1qfJ9TRn15oA5tZGPUVPG5AINP+ygd6lit1xz"
        "QA2OYlguKtA5qNYUBBFS8UAOVQaCtAYDtSgluAKAG7T6UuPan7Xo2vQAiIG6ineUtOjDDrT+aAGqoFO4o5ooATijApaKAHKg60/A9KRfuiloAT"
        "A9KXAoooAKDg9qKKAEwPSloooAcoBpCOaTvTgvNAC7RUiIMUKOnFPPSgBhUAU2g9aDx1oAUUtIOlLQAUuBmkwad3oATAzRgUvej/ABoATAowM0"
        "v+NHegBrDFNpz02gAooqa2gaeRUUdTigC/4csXuroPjhDmvUdEgWNIhge/Fc/oGnLY2oBA3mun03jFAHQmFJYxx2qtNp6qC2OSKuaZhuCeB1rR"
        "nt1eHIORQBxFzGIJCRmnQSh8HPNaeo2ybjmufud9vN8oO0HrQB0Vsu4rn0rUi421j6PIZot45ArYjOSKAJz3qRI8rUR71Yi+5QBBPAqxnFY15G"
        "Pm5rfnUtGQKxbxG549aAM4SAHB6VehYPH8tZd4DG3I5p2n3eHKk4zQBdu+KqMcVclIZST6VSlB2jigAEhwOOtVr7OcipQQdvtTZ8FvagDMnGPm"
        "qS2fYVPY0t6pxxVZSQQaAOy0GUSLtzW1D80ZQ9BXG6FdlZMAkGuugkDAYPOOaAGXkAa3YDnNcN4gstpLqPmBr0FwcVz2tWjNuJGM0AefocOCOt"
        "a+myhZlBrOvLc28zIemeKjhmZJQMmgD0KxOEBBHIrbtzmIGuS8P3Rlt9jt8w6Cums5AI+TxQBJdwLcJtbg1xfiTRy0bALXbGVccMPzqndwrcxs"
        "DzjmgD41+PWgS214L0R4Eg+auE8BaxJo3iO1uVYhEYBsHqDX1D8b/Di6hoU+xMtGuQQK+SrqM2N66nqrYP1oA+5tBuodV0hXQq8U8fGexxXyj8"
        "cdBfR/GErFNsdydyntkV7d+zt4gTVPCsVq0oMkOc881D+0Z4ZXU/Dh1KOPdJFzwORQB8vK2OBShz0okXacccU00AThjT0JquuSetTp0oAso+cC"
        "n1WQ4YE9KsKQ2cGgBajuPuj61JRgEc0AVKdgelWNo9BULKwGSOKAILiMACZPlkU8EV1fg/xYiMtndnacjDHpXM8EYPSoHgGSV4PUUAe96fcpJE"
        "rKwIIzV/Oea8i8D+LWs5lstQORkBWPpXqFndQ3EKyRuCDzwaALv+etFRI4LYDVLn3oAcrE1IaiWpSOBQAnakCil9KOlAELgbutQyjirJUk5qKY"
        "cbRyx6CgChPgZb0rD1edIo2YkAgVr64s9rb75Y2iT+8wwK838SayZWMKvhF7+tAGdr9800jA4Cg8YrlL6bcxI/Cr1/dKykhuaxmYsxJ70ARSDJ"
        "zTMVMRmo3GDQBC3WgDBpW659qO/wCNAB3/ABqfTW2X0L5+66n9ag7/AI1LbKBKrHsRQB9i+EmE3h+3cf8APNf5V4h+0MB/bsDgclTXsvw+Z38L"
        "2j4PKA/pXiPx4u/P8TRwDny05oAyvg3Ym98b2ZAJEeXPPpX1rEc2yGvnr9nLRnk1W51B0I2LtX8a+gz8gCnp6UAOopAwNLQAVA/DmpxnvUD/AH"
        "j9aAE7YpD9aU9KT0oAaqKDnNTw96jqSHvQBKv3qdJ0BplLnNACd80UUUAFFFFABRRQKAFFU5ZG3niruOCaz5vv96AJu1OVyvTFNHSigBxkPtR5"
        "h6cU2igDmvF1j5sfmxr8y+lcYAQWDdRXqsqLIpRgCCMciuB8S2JtLw7V+Q9DQBkgc1OvaoCcGnbxigB8pPQGmPCkgw2M0gIPU0IcN14oAzLywb"
        "OVzVB4ZF+8K6jKsMcVVurVZMkdaAOdPFKpxVi6s3jfODVZlK9QRQBYVAQDTXXFR7iB1NKpz3NADlGWAq1HGEqsnDCrPmp/eoAkxzSOgZcHOKRZ"
        "FPekdgRgGgBn2dPU1GYwD1qQH3phdcnmgBPLFIU4psrg9DTM/wC1QAZ+tLu4phIHU0m9fU0AKZGjGQSBVux1Fg2CaouysuM5qLgHigDq4NQViA"
        "xxVzh1DBgc1x0dywABFaNpqPlMPm4oA3jwaM5qGC+iuFADLn2qQEE8GgCkaVelKQKOlAC0Gg0UAID71Nbff/CoqVWK8igC5RVXzH/vVZUkqCfS"
        "gBaKKKACiiigAooooAkX7opeKUYxRQAnFHFLRQAnFHFLRQAnFHFLRQAKATUijkU1OlOHFAErHAppbIyKaWJ600mgBScmmydRRk0HmgB6/dFOWo"
        "wTRuNAEv8AjR3qLc3qaNzepoAl70f41Fub1NG5vU0AS/40d6i3N6mjc3qaAHvTaTJJ5paAFRSzBVGSTXaeFNI8oGWdA2eVyOlYvg/Smv7ve2Sq"
        "HPtXpS24WJUQABRigCKC3YsDjitzTbcnGEqG2j/dABc1qWYddu0EfhQBZiikTkLtA61qWbh1wRxUS8x/MOe9S2oAJGOMUAVdSsgwLAcGuU1W2w"
        "xTFd6w3DB6YrI1fTw6MyjBxQBynh+ZracwueG6V09qN9cnfI0b5HyujZFbegaj9oUK/wAr+9AGzViP7lRRj94AasEANgDjFACHhTWXMm/v3rVP"
        "0qjdLiTCjHSgDn9ZTYCfSsSKUiYsOxrpdXi3xNkc1yc4MTtzgZoA6G2uRLGMjBxSsNwxWJZ3RBGDmthH3RZ3c0AROuxiKZJ0p4V2GWBJpsqkDJ"
        "BoAq3P3aoFsHpWhdY8vNZjE5NAF3TZdtwCDiu10iVZMHPavP4WxIDnFdZ4anJIVgTQB0tRX0Alt+eoqTcvrQWLfLnigDgfElifnlUfdrl2ba4a"
        "vUdWslkifjtXmmsQNb3OwDjP5UAbHh25Ec4cng12ts+5BjpjNeaafJhuD36V3WiXBkiUE8gUAa1PjbaemRSrt4yRTZioXII/OgDJ8TWEF7YSAx"
        "ggrgj1r4s+MugPoniiYGLEcjbhxwOa+4ziVXj9uteEftJ+EXvNIfUY1+aLJJAoA8i/Z/8AEP8AZPidbOWQrHNwvOBnNfVGr2cOr6BNA6hxInf6"
        "V8LaTcyWOoxXCk7onVhj619n/CzXYtb8KW02cgoFfnPagD5G8Z6XLo3iG6splKlZCV4xxmsavfv2mfB53L4htACEXEgA7eteAryc5zk0AKDipY"
        "2yKY4wKaDigCz2NTW3RvwqoGPAqWN2XoaALdFV1kYsPm4qxkHoaACkddwx0paD1NAEYg/2qiI5K5qzTdi5zigCnNCrLx8retbnhfxTdaJKttde"
        "ZJZt1PcVnlEPaq88QYkEcUAe2aTqdnf2yXNtIpV+gzzWmjZGeteDaLql/otz5ts7GLPzxk8Yr2nwVqNp4ktFFrMEugPmjLCgDUBwP/rVNnIHNO"
        "u7C+s22T252n+IVFGcdeKAJguaCnpU2mWtxfXS21uhd2OBgZxXpuh/Du3ht45NQkd5SM7R0oA8403TLq+bbFG31ArprzS9C8H6ONT16VJZ2XfH"
        "GBjn0r0/TtEstPVfssCQqOpPJql4i0XRdUG28tIbrbyPM6CgD49+I/jq68S3gWIGG2jOUjIwK891KZ2bLAc/pX1b4u+Fnhq9kd4bRYpD3RiBXl"
        "Hij4QXEJb+zp9w/uyZP60AeJ3Jziq5U11OueD9b0yVhcWMpUfxBSRXOzRtGxR12n3FAFeo5qn8umSx5FAFYDPFIeKeBhsUu3NADcd6s2i7pFGP"
        "vECoNueADWz4Vsjfa3Z2qg/PKoNAH1b8P7aRPC1rkcLGP5V88fElhd+NL1x82x9gAHU19aCxh0DwNDLKjb3h2qqjnJGAa8q8KeA7R9YudY1KIS"
        "SPLvRTQBc+B2kvp/hpJZE2tMd54wcdq9ClG85pttGkMQSNAidAPQVJQA1VxTu1FFAAM96gf7x+tT1A/wB4/WgBD0pB2paQ5oAWpIe9NQEsMjip"
        "lXA4FABQBRRQAYooooAKKKKACnqneiIA9akHFACP/q8Vlzff71pv9ysyb79AEw6UVFGxLYOalFABRRRQAVg+LrMz2BkQZZTnH51vVDdxiS3dSO"
        "CDQB5T8wJDdaUmrGpxNFcyLjGGNU1Y55NAEqnFOpmc0oPPNAEitin+ZyAOaZ8nrRuUHgUASPGknUDNUruyVhwKt7yvORTGuR3IoAw5LSSMnI4q"
        "HKqcHitu5cSCsq6tSxBAoAh3r60bl9arSLsfBpooAvJJjgDNSqcjkVnKzAjBqyHfA5oAsn6VWb7x5FG5qbu5oAXPuKQnjqKXkjimkHBoAid80w"
        "VIiZPNSbF9KAK9FWNg9KNg9KAK9IwJ6HFPYcmkHWgB8U8sQwr1qWGqhI8SAE+uawpGIbGeKZuUDG6gDsjR60GigBDS0hpaACiiigAq2vCj6VUq"
        "aKRi6qelAE9FB64ooAKKKKACiiigCYUUCigAooooAKKKKACiiigB8YzQWwcUsVMf79ACs2aRenNJSjpQAv5UflRRQAflR+VFFAB+VH5UUUAH5U"
        "flRRQAflR+VFFABnB6U+AGWVEUcu2BUbetanhSAXOsQR4zhgaAPTPCGkLZ6YMqA7da3Y7dQD61MiiONEAAGKkjRSMn1oAW0ix361qQwsApyOKr"
        "QIoxir8Byv0oAlHJqeNNpJqFPvD61a/h/GgAzTJVDRsDU6LlKYqg5BoA43XrTbIW6j2rCWZ7a5SRM8dRXa63AGQlelcdfR7X46igDsdNu4p44n"
        "BySME1pyf6w9xXnnh7UPs94LZmJBPFd7A5kiVj3FAD/pUM3MnTtU1Qzf6z8KAM6/UEEGuP1qIDdtrsr/ofpXI610agDHsZwpwcgjitmxlDEZau"
        "c71o2TEAc0AdQpBUEdKZOMxECoLKR2QDqKtYByD6UAZU4xGQfWs1+DWxdIuGFY1wSHx6UAGMNk1veHrlo3B7VzyMS2DWrp7tGw20Adv5nyg46j"
        "NSRyDAOKzrOfzoRnqBVhWI6UAWb7mMMBkVxHimw/dySovJ5rvF+aLkZxWZrVoj2jfLwaAPKLR/Lm2twwNdVoN4WkVc4rm9atvs9+3YHpU2m3Lw"
        "SRuDjmgD0yJt0QY+lRyvvXAFUtPvPMgUZByKtcUAOhYoxOKzvFOnW+saTcWsuCJIypBq3I5BwKYMt369aAPhX4gaDN4e8RXNq8LKFfAHt2r0X9"
        "nPxabDVDo9zMPJlI2AngGuw/aj8O20lgmthVWUnbwOWAr500e4ex1KK5ico0T5BoA+5PEulQa3os1lMgkSVMcc9q+K/GWiy6D4lutNlVgEfKkj"
        "GQef619efDbV5tX8NW1zLuVtgB568V5p+0t4Ygks016FSJk4cKPvCgD55k+7UZp7njFMagBVPzCpfzqH+IU7eaAJwwqaD7xqshyAas2/3j9KAJ"
        "qD1NFB6mgAooooAKaykmnUUAQtF8p3YxUVjd3em3q3VjNJFIpz8pIBq0RkYPSoHhbPy9KAPafhz8ZYAkel+J7WOWPdjzSBx9e9eyWeh+EvFVub"
        "nRb2HewyEVq+MIofn+VtrnvivT/hRpOqpeRXNvrU1sFYcIWGaAPpjwV4UttBvWmuCWYniunvNTjiHLdDR4YRpdIhN3KZpFAVpG6tx1qzqOk29w"
        "g2uBigDFuda3INrHaaoXV8cZXkmm6vp0lrnDZQdKyfMbOM0AS3E7P97qaxtRgaR87sCr8ztuqpOxYHNAGBqFqjqY3iRwfUZzXG694E0fUx++tF"
        "iYnqnFeitGrdahljVjgrQB4Zqvwliy/2OeRT2zXL3vw38QwFgkAmUfxLX0x5UfQpmk8iM8bePSgD5IvvCGu2zEvpsxA7hc1nHSr9TtaznUjqCh"
        "r7DlsYiuTGp+oqodJsmbLW8OfdBQB8lwaNqcrAJZznPYIa9T+Dfgu6i15NSvrWWFIF3rvHU17PFpFqgyttF/3yK0LO2EfyqgBJGMUAWmv7m9RY"
        "rgiSIAADHApwjVRhECj2qbyFgXGMN3plAAOBRRRQAUUUUAKKrv8AfNWBUbr1NAEQ6UUU+NAQSetAEi9Aalj70xFG4CpVXHQ0AMcck0yppOlQ96"
        "AFzSUuKSgAooooAkh6mn9qZD3p/agBsn3KzJvv1qSfcrLm+/3oARDhs81Mp3ZIqv8Agalh+6frQBJRRRQAUY3MBkUjcCo0c+aBQBwvjS38i83A"
        "j5zXOnrXXePoyVEi9Qa4xWJNAEytinB8nGKjFKDjmgCQ8daQuAPvCopmfbkVUZ3waALcs5C8EVD5m7k1TikZpME8VYHSgCdWwKV8umF60wVJFQ"
        "BTuLLeMjG6qMlvIh6ZxW79KimjJHA60AYIzn6VOjAnpUt5EIyfWqqsQc0ASs4Hal4Iz0qFiTS+ZxigCdQPSggelMibNPPPrQAgHtS49qT8TQen"
        "GaAF49KPwqJWy+Kl/OgCu/3jTGYL1p7/AHjUU3QUARyfMeKgaNhU461PGgPWgD//2Q=="
    )
}

def _js_embed_image(fn):
    """从内嵌的 base64 里取出跳脸图；没有就返回 None。"""
    data = _JS_EMBED_B64.get(fn)
    if not data:
        return None
    try:
        return pygame.image.load(io.BytesIO(base64.b64decode(data)))
    except Exception:
        return None
JS_DUR = 2.0
_js_frames = None
_js_names = []
_js_state = {"active": False, "start": 0.0, "img": None, "tail": False}
_circle_cache = {}
_cone_base = None
_cone_cache = {}
CONE_LEN = 430


def _cover_fit(img, focus_y):
    """等比铺满 1280x720，横向居中，竖向按 focus_y 取一条。"""
    iw, ih = img.get_size()
    sc = max(SCREEN_WIDTH / float(iw), SCREEN_HEIGHT / float(ih))
    nw, nh = int(iw * sc), int(ih * sc)
    s = pygame.transform.smoothscale(img, (nw, nh))
    y = int((nh - SCREEN_HEIGHT) * focus_y)
    y = max(0, min(nh - SCREEN_HEIGHT, y))
    x = max(0, (nw - SCREEN_WIDTH) // 2)
    return s.subsurface(pygame.Rect(x, y, SCREEN_WIDTH, SCREEN_HEIGHT)).copy()


def _js_search_dirs():
    """跳脸图可能放的位置：脚本同级的 assets/jumpscare、上一级、当前工作目录。"""
    base = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(base, "assets", "jumpscare"),
        os.path.join(base, "jumpscare"),
        os.path.join(os.path.dirname(base), "assets", "jumpscare"),
        os.path.join(os.getcwd(), "assets", "jumpscare"),
        os.path.join(os.getcwd(), "jumpscare"),
    ]


def _fallback_scare_face():
    """一张图都没有时临时顶上的“鬼影”：宁可糊也别黑屏，正式素材还是要放进去。"""
    base = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    base.fill((16, 12, 12))
    cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 10
    # 头：暗灰一坨，边缘糊开
    pygame.draw.ellipse(base, (118, 112, 106), (cx - 210, cy - 250, 420, 500))
    pygame.draw.ellipse(base, (96, 90, 86), (cx - 210, cy - 250, 420, 500), 14)
    # 眼窝：两个黑洞 + 一点反光
    for sx in (-96, 96):
        pygame.draw.ellipse(base, (12, 10, 10), (cx + sx - 70, cy - 120, 140, 96))
        pygame.draw.circle(base, (226, 220, 210), (cx + sx - 6, cy - 78), 10)
    # 张嘴：一条横向的黑洞，里面几颗牙
    pygame.draw.ellipse(base, (10, 8, 8), (cx - 92, cy + 26, 184, 122))
    for k in range(7):
        tx = cx - 78 + k * 24
        pygame.draw.polygon(base, (176, 168, 158),
                            [(tx, cy + 40), (tx + 16, cy + 40), (tx + 8, cy + 74)])
    # 颗粒 +  vignette，让它像糊掉的旧照片而不是卡通头像
    rnd = random.Random(9091)
    for _ in range(7000):
        gx = rnd.randint(0, SCREEN_WIDTH - 1)
        gy = rnd.randint(0, SCREEN_HEIGHT - 1)
        sh = rnd.choice([-26, -12, 10, 22])
        px = base.get_at((gx, gy))
        base.set_at((gx, gy), (max(0, min(255, px[0] + sh)),
                               max(0, min(255, px[1] + sh)),
                               max(0, min(255, px[2] + sh))))
    vign = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    for r in range(420, 40, -14):
        a = int(10 + 150 * (r / 420.0) ** 2)
        pygame.draw.ellipse(vign, (0, 0, 0, min(255, a)),
                            (cx - r * 1.5, cy - r, r * 3, r * 2))
    base.blit(vign, (0, 0))
    return base


def load_jumpscare_frames():
    global _js_frames
    if _js_frames is not None:
        return _js_frames
    global _js_names
    _js_names = []
    frames = []
    for fn, focus in JS_SPEC:
        img = _js_embed_image(fn)
        if img is not None:
            try:
                img = img.convert()
            except Exception:
                pass
            if img.get_size() == (SCREEN_WIDTH, SCREEN_HEIGHT):
                frames.append(img)
            else:
                frames.append(_cover_fit(img, focus))
            _js_names.append(fn + "(内置)")
            continue
        for d in _js_search_dirs():
            path = os.path.join(d, fn)
            if not os.path.exists(path):
                continue
            try:
                img = pygame.image.load(path)
                try:
                    img = img.convert()
                except Exception:
                    pass
                frames.append(_cover_fit(img, focus))
                _js_names.append(fn)
            except Exception:
                pass
            break
    if not frames:
        print("[找到M4] 没找到跳脸图，先用兜底鬼脸。把 js_1.jpg / js_2.jpg / js_3.jpg 放到：")
        for d in _js_search_dirs()[:2]:
            print("   " + d)
        frames.append(_fallback_scare_face())
        _js_names = []
    else:
        print("[找到M4] 跳脸图已加载：" + "、".join(_js_names) + "（内置，无需 assets 目录）")
    _js_frames = frames
    return frames


def synth_scream(dur=0.95, sr=22050):
    """短促的金属啸叫 + 噪声，够突然就够吓人，别拖长成音乐。"""
    n = int(dur * sr)
    rnd = random.Random(4242)
    buf = [0.0] * n
    for i in range(n):
        t = i / float(sr)
        env = min(1.0, t / 0.02) * math.exp(-2.1 * t)
        f = 1560.0 * math.exp(-4.8 * t) + 440.0
        tone = math.sin(2.0 * math.pi * (f * t + 70.0 * t * t))
        noise = rnd.uniform(-1.0, 1.0) * 0.55
        growl = 0.25 * math.sin(2.0 * math.pi * 96.0 * t)
        buf[i] = (0.62 * tone + noise + growl) * env
    peak = max(0.0001, max(abs(v) for v in buf))
    gain = 0.92 / peak
    return [v * gain for v in buf]


_scream_sound = None


_scream_sound = None
_tinnitus_sound = None


def synth_tinnitus(dur=1.2, sr=22050):
    """尖叫落下去之后的低频耳鸣：两只挨得很近的闷音 + 一点点高压后的细响。"""
    n = int(dur * sr)
    buf = [0.0] * n
    for i in range(n):
        t = i / float(sr)
        env = min(1.0, t / 0.22) * min(1.0, max(0.0, (dur - t) / 0.34))
        hum = 0.62 * math.sin(2.0 * math.pi * 68.0 * t) \
            + 0.32 * math.sin(2.0 * math.pi * 61.0 * t + 0.7)
        ring = 0.10 * math.sin(2.0 * math.pi * 392.0 * t)
        trem = 1.0 + 0.09 * math.sin(2.0 * math.pi * 1.6 * t)
        buf[i] = (hum + ring) * env * trem
    peak = max(0.0001, max(abs(v) for v in buf))
    return [v * (0.40 / peak) for v in buf]


def get_tinnitus_sound():
    global _tinnitus_sound
    if _tinnitus_sound is not None:
        return _tinnitus_sound
    if not MUSIC_OK or not _AUDIO_READY:
        return None
    try:
        path = _web_asset_path("tinnitus.wav") or os.path.join(BGM_DIR, "tinnitus.wav")
        if not os.path.exists(path):
            _write_bgm(path, synth_tinnitus())
        _tinnitus_sound = pygame.mixer.Sound(path)
        _tinnitus_sound.set_volume(0.6)
    except Exception:
        _tinnitus_sound = None
    return _tinnitus_sound


def play_tinnitus():
    snd = get_tinnitus_sound()
    if snd is None:
        return
    try:
        snd.stop()
        snd.play()
    except Exception:
        pass


def get_scream_sound():
    global _scream_sound
    if _scream_sound is not None:
        return _scream_sound
    if not MUSIC_OK or not _AUDIO_READY:
        return None
    try:
        path = _web_asset_path("scream.wav") or os.path.join(BGM_DIR, "scream.wav")
        if not os.path.exists(path):
            _write_bgm(path, synth_scream())
        _scream_sound = pygame.mixer.Sound(path)
        _scream_sound.set_volume(0.9)
    except Exception:
        _scream_sound = None
    return _scream_sound


def play_scream():
    snd = get_scream_sound()
    if snd is None:
        return
    try:
        snd.stop()
        snd.play()
    except Exception:
        pass


def start_jumpscare(now):
    frames = load_jumpscare_frames()
    _js_state["active"] = True
    _js_state["start"] = now
    if not frames:
        _js_state["img"] = None
    elif isinstance(JS_FIXED, int) and 1 <= JS_FIXED <= len(frames):
        _js_state["img"] = frames[JS_FIXED - 1]
    else:
        _js_state["img"] = random.choice(frames)
    _js_state["tail"] = False
    play_scream()
    return True


def draw_jumpscare(now):
    """抖动一次 + 红白闪，然后图静止停住两秒，最后硬切回来。"""
    if not _js_state["active"]:
        return False
    t = now - _js_state["start"]
    if t >= JS_DUR:
        _js_state["active"] = False
        return False
    # 尖叫落下去之后接一段很轻的低频耳鸣，别让这两秒变成纯静音
    if (not _js_state["tail"]) and t >= 0.85:
        _js_state["tail"] = True
        play_tinnitus()

    img = _js_state["img"]
    if img is None:
        screen.fill((16, 2, 2))
    elif t < 0.26:
        amp = int(11 * (1.0 - t / 0.26))
        screen.fill((0, 0, 0))
        screen.blit(img, (random.randint(-amp, amp), random.randint(-amp, amp)))
    else:
        screen.blit(img, (0, 0))
    if t < 0.05:
        flash = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        flash.fill((255, 255, 255, 238))
        screen.blit(flash, (0, 0))
    elif t < 0.2:
        a = int(128 * (1.0 - (t - 0.05) / 0.15))
        if a > 0:
            flash = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            flash.fill((176, 18, 18, a))
            screen.blit(flash, (0, 0))
    return True


_veil_half = None
_veil_full = None
_half_mask_cache = {}


def _half_mask(m):
    """把遮罩缩到一半分辨率后缓存，供半分辨率暗层使用。"""
    key = (id(m), m.get_width(), m.get_height())
    c = _half_mask_cache.get(key)
    if c is None:
        w = max(1, m.get_width() // 2)
        h = max(1, m.get_height() // 2)
        c = pygame.transform.smoothscale(m, (w, h))
        _half_mask_cache[key] = c
    return c


def _veil_render(color, alpha, holes):
    """黑暗层：整屏铺一层暗色，再用遮罩把角色附近减掉，露出下面的画面。

    surfaces 全部复用，绝不在这里新建 Surface——手机 wasm 里每帧分配
    一张全屏 SRCALPHA 是掉帧的主因之一。
    """
    global _veil_half
    if _veil_half is None:
        _veil_half = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    hv = _veil_half
    hv.fill((color[0], color[1], color[2], alpha))
    for m, x, y in holes:
        hv.blit(m, (int(x), int(y)), special_flags=pygame.BLEND_RGBA_SUB)
    screen.blit(hv, (0, 0))


PLAYER_SPR_W = 40
PLAYER_SPR_H = 52
_player_spr = {}


def _build_player_sprite(front, step):
    """俯视游戏里的玩家：一个苍白的、没有脸的小人。

    front=True 面朝下（看正面），False 面朝上（只看得到后脑）。
    step=True 走路帧，手脚前后错开，形成最简的踏步动作。
    """
    w, h, cx = PLAYER_SPR_W, PLAYER_SPR_H, PLAYER_SPR_W // 2
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    skin = (250, 245, 232)
    cloth = (206, 199, 180)
    limb = (230, 222, 202)
    edge = (52, 48, 42)
    hair = (74, 68, 58)
    sw = 3 if step else 0
    # 腿
    pygame.draw.rect(s, edge, (cx - 7 - sw, 36, 7, 14), border_radius=3)
    pygame.draw.rect(s, limb, (cx - 6 - sw, 37, 5, 12), border_radius=3)
    pygame.draw.rect(s, edge, (cx + 1 + sw, 36, 7, 14), border_radius=3)
    pygame.draw.rect(s, limb, (cx + 1 + sw, 37, 5, 12), border_radius=3)
    # 躯干
    pygame.draw.ellipse(s, edge, (cx - 11, 20, 22, 20))
    pygame.draw.ellipse(s, cloth, (cx - 9, 21, 18, 18))
    # 双臂
    pygame.draw.ellipse(s, edge, (cx - 13, 23 - sw, 6, 13))
    pygame.draw.ellipse(s, limb, (cx - 12, 24 - sw, 4, 11))
    pygame.draw.ellipse(s, edge, (cx + 7, 23 + sw, 6, 13))
    pygame.draw.ellipse(s, limb, (cx + 8, 24 + sw, 4, 11))
    # 头
    pygame.draw.circle(s, edge, (cx, 13), 9)
    pygame.draw.circle(s, skin, (cx, 13), 7)
    if not front:
        pygame.draw.ellipse(s, hair, (cx - 6, 6, 12, 10))
    return s


def get_player_sprite(front, step):
    key = (bool(front), bool(step))
    spr = _player_spr.get(key)
    if spr is None:
        spr = _build_player_sprite(key[0], key[1])
        _player_spr[key] = spr
    return spr


def get_circle_mask(r):
    if r in _circle_cache:
        return _circle_cache[r]
    m = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    for rr in range(r, 0, -2):
        a = int(255 * (1.0 - float(rr) / r) ** 0.75) + 1
        pygame.draw.circle(m, (0, 0, 0, min(255, a)), (r, r), rr)
    _circle_cache[r] = m
    return m


def get_cone_mask(direction):
    """手电筒光锥：默认朝右的扇形，按 8 个方向预生成后缓存。"""
    global _cone_base
    if direction in _cone_cache:
        return _cone_cache[direction]
    if _cone_base is None:
        half_res = CONE_LEN // 2
        base = pygame.Surface((half_res * 2, half_res * 2), pygame.SRCALPHA)
        for i in range(30):
            frac = i / 29.0
            rad = half_res * (1.0 - frac * 0.88)
            half_ang = 27.0 - 7.0 * frac
            a = int(255 * (1.0 - 0.60 * frac)) + 2
            pts = [(half_res, half_res)]
            steps = 22
            for k in range(steps + 1):
                ang = math.radians(-half_ang + 2.0 * half_ang * k / steps)
                pts.append((half_res + rad * math.cos(ang),
                            half_res + rad * math.sin(ang)))
            pygame.draw.polygon(base, (0, 0, 0, min(255, a)), pts)
        _cone_base = base
    big = pygame.transform.smoothscale(_cone_base, (CONE_LEN * 2, CONE_LEN * 2))
    # 再压一次分辨率再放大：光锥边缘糊一点，别像刀切
    big = pygame.transform.smoothscale(
        pygame.transform.smoothscale(big, (CONE_LEN // 2, CONE_LEN // 2)),
        (CONE_LEN * 2, CONE_LEN * 2))
    rot = pygame.transform.rotate(big, direction * 45)
    _cone_cache[direction] = rot
    return rot


# ===================== 草地迷宫关卡生成 =====================
def create_level_maze(theme_key, arrive_from=None):
    th = THEMES[theme_key]
    rng = random.Random()

    spawn_cell = (1, ROWS - 2)
    scx, scy = cell_center(*spawn_cell)
    clears = pick_clearings(rng, th["clearings"], spawn_cell)

    E, S = gen_maze(rng)
    for (bc, br) in clears:
        E[br][bc] = True
        E[br + 1][bc] = True
        S[br][bc] = True
        S[br][bc + 1] = True

    walls = build_walls(E, S)
    ponds = []

    near_clear = min(clears, key=lambda cb: math.hypot(
        clearing_center(*cb)[0] - scx, clearing_center(*cb)[1] - scy)) if clears else None
    if near_clear:
        bc, br = near_clear
        ponds.append(pygame.Rect(OX + bc * CELL + 10, OY + br * CELL + 10,
                                 CELL - 20, CELL - 20))

    deadends = []
    for r in range(ROWS):
        for c in range(COLS):
            if degree(E, S, c, r) == 1 and (c, r) != spawn_cell:
                if all(abs(c - bc) > 1 or abs(r - br) > 1 for bc, br in clears):
                    deadends.append((c, r))
    rng.shuffle(deadends)
    for (c, r) in deadends[:th["extra_ponds"]]:
        cx, cy = cell_center(c, r)
        ponds.append(pygame.Rect(cx - CELL // 2 + 12, cy - CELL // 2 + 12,
                                 CELL - 24, CELL - 24))

    blockers = walls + ponds
    free = build_free_grid(blockers)

    spawn_xy = (scx, scy)
    snap = free_cell_center_near(scx, scy, free, blockers, 320)
    if snap:
        spawn_xy = snap
    dist = bfs_dist(free, spawn_xy)
    if not dist:
        for gy in range(GH):
            for gx in range(GW):
                if free[gx][gy]:
                    spawn_xy = (gx * GRID + GRID // 2, gy * GRID + GRID // 2)
                    dist = bfs_dist(free, spawn_xy)
                    break
            if dist:
                break

    # ---------- 传送门：通往远处的空地 ----------
    n_portals = len(th["portals"])
    cands = []
    for (bc, br) in clears:
        cx, cy = clearing_center(bc, br)
        d = math.hypot(cx - spawn_xy[0], cy - spawn_xy[1])
        cands.append((d, cx, cy))
    cands.sort(reverse=True)

    spots = []
    for min_gap, min_d in ((420, 700), (240, 400), (120, 0)):
        for d, cx, cy in cands:
            if len(spots) >= n_portals:
                break
            if d < min_d:
                continue
            if any(math.hypot(cx - x, cy - y) < min_gap for (x, y) in spots):
                continue
            pos = find_free_spot(cx, cy, 62, blockers)
            if pos is None:
                continue
            px, py = pos
            if not is_free_spot(px, py, 62, blockers):
                continue
            if not reach_ok(px, py, dist):
                continue
            spots.append((px, py))
        if len(spots) >= n_portals:
            break

    if len(spots) < n_portals:
        far_cells = sorted(dist.items(), key=lambda kv: -kv[1])
        for (gx, gy), _d in far_cells[:400]:
            if len(spots) >= n_portals:
                break
            cx, cy = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if any(math.hypot(cx - x, cy - y) < 120 for (x, y) in spots):
                continue
            pos = find_free_spot(cx, cy, 50, blockers, avoid=[])
            if pos is None:
                continue
            px, py = pos
            if reach_ok(px, py, dist) and is_free_spot(px, py, 50, blockers):
                spots.append((px, py))

    portals = []
    for idx, pdef in enumerate(th["portals"]):
        if idx < len(spots):
            px, py = spots[idx]
        elif spots:
            px, py = spots[0]
        else:
            px, py = spawn_xy
            px += 200
        pad = pygame.Rect(0, 0, 116, 96)
        pad.center = (int(px), int(py))
        portals.append({"rect": pad, "label": pdef["label"], "target": pdef["target"],
                        "style": pdef.get("style"), "next": pdef.get("next")})

    for p in portals:
        r = p["rect"]
        if is_free_spot(r.centerx, r.centery, 52, blockers) and \
           reach_ok(r.centerx, r.centery, dist):
            continue
        pos = find_free_spot(r.centerx, r.centery, 54, blockers,
                             avoid=[q["rect"].inflate(34, 34) for q in portals if q is not p])
        if not (pos and is_free_spot(pos[0], pos[1], 52, blockers)
                and reach_ok(pos[0], pos[1], dist)):
            pos = find_free_spot(r.centerx, r.centery, 54, blockers)
        if not (pos and is_free_spot(pos[0], pos[1], 52, blockers)):
            pos = free_cell_center_near(r.centerx, r.centery, free, blockers, 400)
        if pos and is_free_spot(pos[0], pos[1], 52, blockers):
            r.center = pos

    # 出口必须离出生点够远
    for p in portals:
        r = p["rect"]
        if math.hypot(r.centerx - spawn_xy[0], r.centery - spawn_xy[1]) >= 650:
            continue
        for (gx, gy), _d in sorted(dist.items(), key=lambda kv: -kv[1]):
            cx, cy = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) < 650:
                continue
            if any(q["rect"].inflate(80, 80).collidepoint(cx, cy)
                   for q in portals if q is not p):
                continue
            pos = find_free_spot(cx, cy, 56, blockers)
            if pos and is_free_spot(pos[0], pos[1], 54, blockers) \
               and reach_ok(pos[0], pos[1], dist):
                r.center = pos
                break

    # ---------- 白花：最远且可达的死胡同 ----------
    pad_zone = [p["rect"].inflate(70, 70) for p in portals]
    best_cell = None
    best_d = -1
    for r in range(ROWS):
        for c in range(COLS):
            if degree(E, S, c, r) != 1:
                continue
            cx, cy = cell_center(c, r)
            if any(p.colliderect(pygame.Rect(cx - 20, cy - 20, 40, 40)) for p in ponds):
                continue
            if any(z.collidepoint(cx, cy) for z in pad_zone):
                continue
            if not reach_ok(cx, cy, dist):
                continue
            if best_cell is None or dist.get((cx // GRID, cy // GRID), -1) > best_d:
                best_d = dist.get((cx // GRID, cy // GRID), -1)
                best_cell = (c, r)
    if best_cell is not None:
        flower_anchor = cell_center(*best_cell)
    else:
        flower_anchor = None
        for (gx, gy), _d in sorted(dist.items(), key=lambda kv: -kv[1]):
            cx, cy = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if any(z.collidepoint(cx, cy) for z in pad_zone):
                continue
            flower_anchor = (cx, cy)
            break
        if flower_anchor is None:
            flower_anchor = spawn_xy

    flower_xy = None
    jitter = (flower_anchor[0] + rng.randint(-18, 18),
              flower_anchor[1] + rng.randint(-18, 18))
    for cand in (jitter, flower_anchor):
        if cell_of(cand[0], cand[1]) in dist and \
           is_free_spot(cand[0], cand[1], PICK_RADIUS + 3, blockers):
            flower_xy = (int(cand[0]), int(cand[1]))
            break
    if flower_xy is None:
        snap = free_cell_center_near(flower_anchor[0], flower_anchor[1], free, blockers, 160)
        flower_xy = snap if snap else (int(flower_anchor[0]), int(flower_anchor[1]))

    flower_pos = [flower_xy]

    # ---------- 到达点：贴在来源门旁，绝不压门 ----------
    if arrive_from:
        pad = None
        for p in portals:
            if p["target"] == arrive_from:
                pad = p["rect"]
                break
        if pad is None and portals:
            pad = portals[0]["rect"]
        arrive = None
        if pad is not None:
            zones = [q["rect"].inflate(34, 34) for q in portals]
            probes = 0
            for gaps in (118, 150, 182, 214):
                for dx, dy in ((gaps, 0), (-gaps, 0), (0, gaps), (0, -gaps),
                               (gaps, gaps), (-gaps, -gaps), (gaps, -gaps), (-gaps, gaps)):
                    snap = free_cell_center_near(pad.centerx + dx, pad.centery + dy,
                                                 free, blockers, 60)
                    if snap is None:
                        continue
                    ax, ay = snap
                    box = pygame.Rect(ax - 26, ay - 26, 52, 52)
                    if any(box.colliderect(z) for z in zones):
                        continue
                    if probes >= 6:
                        break
                    probes += 1
                    d2 = bfs_dist(free, (ax, ay))
                    if cell_of(flower_xy[0], flower_xy[1]) not in d2:
                        continue
                    arrive = (ax, ay)
                    break
                if arrive:
                    break
        if arrive is None and pad is not None:
            snap = free_cell_center_near(pad.centerx + 140, pad.centery, free, blockers, 240)
            if snap:
                arrive = snap
        if arrive is None:
            arrive = spawn_xy
        spawn_xy = arrive

    # 白花离玩家起点太近就显得白送
    if math.hypot(flower_xy[0] - spawn_xy[0], flower_xy[1] - spawn_xy[1]) < 700:
        d3 = bfs_dist(free, spawn_xy)
        for (gx, gy), _d in sorted(d3.items(), key=lambda kv: -kv[1]):
            cx, cy = gx * GRID + GRID // 2, gy * GRID + GRID // 2
            if math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) < 700:
                continue
            if any(z.collidepoint(cx, cy) for z in pad_zone):
                continue
            if not is_free_spot(cx, cy, PICK_RADIUS + 3, blockers):
                continue
            flower_xy = (cx, cy)
            flower_pos[0] = flower_xy
            break

    # ---------- 静态装饰 ----------
    trees = []
    for _ in range(14):
        tx = rng.randint(120, MAP_W - 120)
        ty = rng.randint(120, MAP_H - 120)
        if any(p["rect"].inflate(160, 160).collidepoint(tx, ty) for p in portals):
            continue
        if any(p.inflate(120, 120).collidepoint(tx, ty) for p in ponds):
            continue
        trees.append((tx, ty))

    benches = []
    for _ in range(8):
        bx = rng.randint(120, MAP_W - 160)
        by = rng.randint(120, MAP_H - 120)
        if is_free_spot(bx + 35, by + 12, 40, blockers) and \
           not any(p["rect"].collidepoint(bx + 35, by + 12) for p in portals):
            benches.append((bx, by))
        if len(benches) >= 4:
            break

    return {
        "theme": theme_key,
        "E": E, "S": S,
        "walls": walls, "ponds": ponds, "blockers": blockers,
        "free": free, "dist": dist,
        "portals": portals,
        "flowers": flower_pos,
        "collected": [False] * len(flower_pos),
        "pick_fx": [],
        "trees": trees,
        "benches": benches,
        "px": spawn_xy[0], "py": spawn_xy[1],
        "armed": [False if (arrive_from and p["target"] == arrive_from) else True
                  for p in portals],
        "leaves": [Leaf(theme_key) for _ in range(70)],
        "surface": None,
        "sky": None,
    }


def create_level(theme_key, arrive_from=None):
    kind = THEMES[theme_key].get("kind")
    if kind == "water":
        return create_level_water(theme_key, arrive_from)
    if kind == "house":
        return create_level_house(theme_key, arrive_from)
    if kind == "cellar":
        return create_level_cellar(theme_key, arrive_from)
    if kind == "depths":
        return create_level_depths(theme_key, arrive_from)
    return create_level_maze(theme_key, arrive_from)


# ===================== 地图预渲染 =====================
def build_surface(state):
    if state.get("kind") == "water":
        return build_surface_water(state)
    if state.get("kind") == "house":
        return build_surface_house(state)
    if state.get("kind") == "cellar":
        return build_surface_cellar(state)
    if state.get("kind") == "depths":
        return build_surface_depths(state)
    return build_surface_maze(state)


def build_surface_maze(state):
    """草地/湿地地表：低对比颗粒 + 细草叶 + 有体积的树篱墙 + 圆角水洼 + 黄昏暖调。"""
    th = THEMES[state["theme"]]
    surf = pygame.Surface((MAP_W, MAP_H))
    surf.fill(th["ground"])
    rnd = random.Random(77123)

    def soft_circle(diameter, col, alpha):
        s = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        r = diameter // 2
        for rr in range(r, 0, -2):
            a = int(alpha * (1.0 - rr / r) ** 1.2) + 1
            pygame.draw.circle(s, col + (min(255, a),), (r, r), rr)
        return s

    blot = [soft_circle(rnd.choice([260, 340, 420]), th["ground"], rnd.choice([10, 14, 18]))
            for _ in range(5)]
    for _ in range(22):
        b = rnd.choice(blot)
        surf.blit(b, (rnd.randint(-140, MAP_W), rnd.randint(-140, MAP_H)))

    # 颗粒：多数压暗，少量提亮，避免整片发白
    for _ in range(5200):
        gx = rnd.randint(0, MAP_W - 1)
        gy = rnd.randint(0, MAP_H - 1)
        sh = rnd.choice([-16, -12, -9, -6, -3, 5, 9, 12])
        col = (max(0, th["ground"][0] + sh), max(0, th["ground"][1] + sh + 4),
               max(0, th["ground"][2] + sh))
        pygame.draw.circle(surf, col, (gx, gy), rnd.randint(2, 6))

    # 草叶：细长、贴地、深浅交错
    for _ in range(3000):
        gx = rnd.randint(6, MAP_W - 6)
        gy = rnd.randint(10, MAP_H - 6)
        base = th["grass_tuft"]
        lift = rnd.choice([-18, -12, -7, 6, 12, 18])
        col = (max(0, base[0] + lift), max(0, base[1] + lift), max(0, base[2] + lift))
        pygame.draw.circle(surf, (max(0, th["ground"][0] - 14),
                                  max(0, th["ground"][1] - 12),
                                  max(0, th["ground"][2] - 12)), (gx, gy + 2), 3)
        for k in range(rnd.randint(4, 6)):
            h = rnd.randint(9, 18)
            bx = gx + k * 2 - 4
            pygame.draw.line(surf, col, (bx, gy + 2),
                             (bx + rnd.randint(-4, 3), gy + 2 - h), 2)

    # 水洼：椭圆岸线 + 深色水面 + 高光带 + 芦苇，别做成方块托盘
    for w in state["ponds"]:
        shore = w.inflate(16, 14)
        pygame.draw.ellipse(surf, th["shore"], shore)
        pygame.draw.ellipse(surf, th["water"], w)
        edge = pygame.Surface((w.w, w.h), pygame.SRCALPHA)
        pygame.draw.ellipse(edge, th["wall_edge"] + (90,), edge.get_rect(), 4)
        surf.blit(edge, (w.left, w.top))
        inner = w.inflate(-int(w.w * 0.3), -int(w.h * 0.34))
        if inner.w > 14 and inner.h > 10:
            sheen = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
            pygame.draw.ellipse(sheen, (176, 192, 188, 18), sheen.get_rect())
            surf.blit(sheen, (inner.left, inner.top + inner.h // 6))
            for i in range(3):
                ly = inner.top + 6 + i * max(6, inner.h // 4)
                if ly >= inner.bottom - 3:
                    break
                pygame.draw.line(surf, th["water_line"],
                                 (inner.left + 6, ly), (inner.right - 6, ly + 1), 1)
        for i in range(0, w.width, 26):
            if rnd.random() < 0.5:
                bx = w.x + i
                by = rnd.choice([w.y - 6, w.bottom + 4])
                for k in range(3):
                    pygame.draw.line(surf, (118, 116, 72), (bx + k * 4, by),
                                     (bx + k * 4 + rnd.randint(-3, 3), by - rnd.randint(10, 22)), 2)

    for p in state["portals"]:
        r = p["rect"]
        if p.get("style") == "door":
            continue
        pygame.draw.rect(surf, (166, 156, 126), r, border_radius=8)
        pygame.draw.rect(surf, (104, 98, 76), r, 3, border_radius=8)
        for i in range(r.x + 22, r.right - 8, 26):
            pygame.draw.circle(surf, (128, 120, 96), (i, r.centery), 6)
            pygame.draw.circle(surf, (150, 142, 116), (i - 2, r.centery - 2), 2)

    # 树篱：本体 + 顶面受光 + 底部投影 + 溢出边界的叶簇（不要硬轮廓线）
    for o in state["walls"]:
        pygame.draw.rect(surf, th["wall"], o)
        if o.w >= o.h:
            pygame.draw.rect(surf, (104, 128, 86), (o.left, o.top, o.w, min(6, o.h)))
            pygame.draw.rect(surf, th["wall_edge"], (o.left, o.bottom - 5, o.w, 5))
        else:
            pygame.draw.rect(surf, (104, 128, 86), (o.left, o.top, min(6, o.w), o.h))
            pygame.draw.rect(surf, th["wall_edge"], (o.right - 5, o.top, 5, o.h))
        cnt = max(4, (o.w * o.h) // 800)
        for _ in range(cnt):
            tx = rnd.randint(o.left - 5, max(o.left - 5, o.right + 5))
            ty = rnd.randint(o.top - 5, max(o.top - 5, o.bottom + 5))
            pygame.draw.circle(surf, th["wall"], (tx, ty), rnd.randint(4, 9))
        for _ in range(cnt // 2):
            tx = rnd.randint(o.left, max(o.left, o.right - 1))
            ty = rnd.randint(o.top, max(o.top, o.bottom - 1))
            pygame.draw.circle(surf, th["tuft"], (tx, ty), rnd.randint(2, 6))
        for _ in range(cnt // 4):
            tx = rnd.randint(o.left, max(o.left, o.right - 1))
            ty = rnd.randint(o.top, max(o.top, o.bottom - 1))
            pygame.draw.circle(surf, (50, 66, 44), (tx, ty), rnd.randint(2, 4))

    for tx, ty in state["trees"]:
        pygame.draw.circle(surf, (48, 58, 42), (tx + 7, ty + 11), 44)
        pygame.draw.circle(surf, (80, 94, 62), (tx, ty), 44)
        pygame.draw.circle(surf, (100, 116, 78), (tx - 10, ty - 12), 26)
        pygame.draw.circle(surf, (120, 136, 92), (tx - 18, ty - 20), 13)
        pygame.draw.line(surf, TRUNK, (tx, ty + 36), (tx, ty + 76), 7)
        pygame.draw.line(surf, (58, 46, 34), (tx + 4, ty + 36), (tx + 4, ty + 70), 3)

    for bx, by in state["benches"]:
        pygame.draw.rect(surf, (56, 44, 34), (bx + 3, by + 10, 70, 12))
        pygame.draw.rect(surf, (130, 106, 80), (bx, by, 70, 12))
        pygame.draw.line(surf, (96, 78, 60), (bx + 8, by + 12), (bx + 8, by + 28), 3)
        pygame.draw.line(surf, (96, 78, 60), (bx + 62, by + 12), (bx + 62, by + 28), 3)

    # 黄昏暖调：上暖下淡，整体压一点对比
    warm = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
    for y in range(MAP_H):
        t = y / MAP_H
        a = int(44 * (1.0 - t) + 15)
        pygame.draw.line(warm, (255, 168, 108, a), (0, y), (MAP_W, y))
    surf.blit(warm, (0, 0))

    return surf


def build_surface_water(state):
    th = THEMES[state["theme"]]
    surf = pygame.Surface((MAP_W, MAP_H))
    surf.fill(th["deep"])
    rnd = random.Random(90210)

    for _ in range(150):
        wx = rnd.randint(-100, MAP_W + 100)
        wy = rnd.randint(-100, MAP_H + 100)
        rad = rnd.randint(70, 240)
        col = th["shallow"] if rnd.random() < 0.5 else th["water"]
        patch = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
        pygame.draw.circle(patch, col + (34,), (rad, rad), rad)
        surf.blit(patch, (wx - rad, wy - rad))

    for _ in range(1600):
        wx = rnd.randint(10, MAP_W - 40)
        wy = rnd.randint(10, MAP_H - 10)
        ln = rnd.randint(10, 40)
        col = th["water_line"] if rnd.random() < 0.55 else th["water_hi"]
        pygame.draw.line(surf, col, (wx, wy), (wx + ln, wy + rnd.choice([0, 1, 1, 2])), 1)

    for (lx, ly, lr) in state["lilies"]:
        pygame.draw.ellipse(surf, th["lily"], pygame.Rect(lx - lr, ly - lr // 2, lr * 2, lr))
        pygame.draw.line(surf, (58, 88, 64), (lx, ly - lr // 2 + 2), (lx, ly), 2)

    for (rx, ry) in state["reeds"]:
        for k in range(rnd.randint(4, 7)):
            h = rnd.randint(16, 40)
            bx = rx + k * 4
            pygame.draw.line(surf, th["reed"], (bx, ry), (bx + rnd.randint(-3, 3), ry - h), 2)

    for rc in state["decks"]:
        pygame.draw.rect(surf, th["plank"], rc)
        for y in range(rc.top + 10, rc.bottom, 15):
            pygame.draw.line(surf, th["plank_line"], (rc.left + 3, y), (rc.right - 4, y), 1)
        pygame.draw.rect(surf, th["plank_light"], rc, 2)
        pygame.draw.rect(surf, th["post"], rc.inflate(8, 8), 2)
        for (px2, py2) in ((rc.left - 6, rc.top - 6), (rc.right + 6, rc.top - 6),
                           (rc.left - 6, rc.bottom + 6), (rc.right + 6, rc.bottom + 6)):
            pygame.draw.circle(surf, th["post"], (px2, py2), 5)

    for rc in state["bridges"]:
        pygame.draw.rect(surf, th["plank"], rc)
        if rc.w >= rc.h:
            for x in range(rc.left + 9, rc.right, 13):
                pygame.draw.line(surf, th["plank_line"], (x, rc.top + 2), (x, rc.bottom - 3), 1)
            pygame.draw.line(surf, th["plank_light"],
                             (rc.left, rc.top + 1), (rc.right, rc.top + 1), 1)
            pygame.draw.line(surf, th["plank_light"],
                             (rc.left, rc.bottom - 2), (rc.right, rc.bottom - 2), 1)
            for x in range(rc.left + 12, rc.right, 46):
                pygame.draw.circle(surf, th["post"], (x, rc.top - 3), 4)
                pygame.draw.circle(surf, th["post"], (x, rc.bottom + 3), 4)
            pygame.draw.line(surf, th["post"], (rc.left, rc.top - 8), (rc.left, rc.bottom + 8), 3)
            pygame.draw.line(surf, th["post"], (rc.right, rc.top - 8),
                             (rc.right, rc.bottom + 8), 3)
        else:
            for y in range(rc.top + 9, rc.bottom, 13):
                pygame.draw.line(surf, th["plank_line"], (rc.left + 2, y), (rc.right - 3, y), 1)
            pygame.draw.line(surf, th["plank_light"],
                             (rc.left + 1, rc.top), (rc.left + 1, rc.bottom), 1)
            pygame.draw.line(surf, th["plank_light"],
                             (rc.right - 2, rc.top), (rc.right - 2, rc.bottom), 1)
            for y in range(rc.top + 12, rc.bottom, 46):
                pygame.draw.circle(surf, th["post"], (rc.left - 3, y), 4)
                pygame.draw.circle(surf, th["post"], (rc.right + 3, y), 4)
            pygame.draw.line(surf, th["post"], (rc.left - 8, rc.top), (rc.right + 8, rc.top), 3)
            pygame.draw.line(surf, th["post"], (rc.left - 8, rc.bottom),
                             (rc.right + 8, rc.bottom), 3)

    # 传送门踏板（木屋入口画成门廊，其余是木踏板）
    for p in state["portals"]:
        r = p["rect"]
        if p.get("style") == "door":
            # 大木台 = 木屋门前那块平台，正立面：屋顶 + 木板墙 + 双扇门 + 亮着的窗
            pygame.draw.rect(surf, (118, 92, 64), r)
            for x in range(r.left + 8, r.right, 18):
                pygame.draw.line(surf, (86, 66, 46), (x, r.top + 6), (x, r.bottom - 6), 1)
            pygame.draw.rect(surf, (62, 46, 32), r, 8)

            fac = r.inflate(-34, -52)
            fac.midbottom = (r.centerx, r.bottom - 26)
            roof = [(fac.left - 18, fac.top + 36), (fac.centerx, fac.top - 30),
                    (fac.right + 18, fac.top + 36)]
            pygame.draw.polygon(surf, (52, 40, 30), roof)
            pygame.draw.polygon(surf, (96, 74, 52), roof, 3)
            pygame.draw.rect(surf, (100, 78, 56), fac)
            for xx in range(fac.left + 9, fac.right, 17):
                pygame.draw.line(surf, (82, 63, 46), (xx, fac.top), (xx, fac.bottom), 1)
            pygame.draw.rect(surf, (64, 48, 34), fac, 3)

            win = pygame.Rect(fac.right - 82, fac.top + 34, 48, 46)
            pygame.draw.rect(surf, (74, 56, 40), win.inflate(10, 10))
            pygame.draw.rect(surf, (226, 184, 120), win)
            pygame.draw.line(surf, (74, 56, 40), (win.centerx, win.top), (win.centerx, win.bottom), 3)
            pygame.draw.line(surf, (74, 56, 40), (win.left, win.centery), (win.right, win.centery), 3)

            door = pygame.Rect(0, 0, 148, 128)
            door.midbottom = (fac.centerx, fac.bottom - 6)
            pygame.draw.rect(surf, (60, 46, 34), door.inflate(18, 16))
            pygame.draw.rect(surf, (34, 25, 19), door)
            pygame.draw.line(surf, (12, 9, 7), (door.centerx, door.top),
                             (door.centerx, door.bottom), 3)
            for base in (door.left + 12, door.centerx + 12):
                for xx in range(base, base + 52, 15):
                    for yy in (door.top + 22, door.top + 54, door.top + 86):
                        pygame.draw.circle(surf, (92, 76, 54), (xx, yy), 2)
            pygame.draw.line(surf, (255, 196, 132),
                             (door.left + 5, door.bottom - 2), (door.right - 5, door.bottom - 2), 3)
            pygame.draw.rect(surf, (150, 136, 110), (door.left - 12, door.bottom, door.width + 24, 8))
        else:
            pygame.draw.rect(surf, (176, 158, 122), r)
            pygame.draw.rect(surf, (104, 88, 62), r, 3)
            for i in range(r.x + 18, r.right, 24):
                pygame.draw.circle(surf, (140, 122, 92), (i, r.centery), 4)

    return surf


def build_sky(theme_key):
    th = THEMES[theme_key]
    sky = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    for y in range(SCREEN_HEIGHT):
        t = y / SCREEN_HEIGHT
        col = (int(th["sky_top"][0] * (1 - t) + th["sky_bottom"][0] * t),
               int(th["sky_top"][1] * (1 - t) + th["sky_bottom"][1] * t),
               int(th["sky_top"][2] * (1 - t) + th["sky_bottom"][2] * t))
        pygame.draw.line(sky, col, (0, y), (SCREEN_WIDTH, y))
    return sky


def draw_flower(surf, cx, cy, t):
    alpha = 26 + int(14 * (math.sin(t * 2.2) + 1) / 2)
    glow = pygame.Surface((PICK_RADIUS * 4, PICK_RADIUS * 4), pygame.SRCALPHA)
    pygame.draw.circle(glow, (255, 255, 250, alpha),
                       (PICK_RADIUS * 2, PICK_RADIUS * 2), PICK_RADIUS)
    surf.blit(glow, (cx - PICK_RADIUS * 2, cy - PICK_RADIUS * 2))
    for i in range(5):
        ang = math.radians(i * 72 + 18)
        px = cx + int(PICK_RADIUS * 0.75 * math.cos(ang))
        py = cy + int(PICK_RADIUS * 0.75 * math.sin(ang))
        pygame.draw.circle(surf, WHITE_FLOWER, (px, py), PICK_RADIUS // 2)
    pygame.draw.circle(surf, (255, 255, 240), (cx, cy), PICK_RADIUS // 3)


def draw_menu(elapsed):
    dark = min(elapsed / 40, 1)
    screen.fill((int(210 - dark * 120), int(200 - dark * 120), int(180 - dark * 120)))
    screen.blit(font_big.render("找到", True, WHITE), (450, 120))
    screen.blit(font_big.render("M4", True, (40, 40, 40)), (620, 120))
    screen.blit(font_mid.render("朋友在等你。", True, WHITE), (530, 200))
    screen.blit(font_small.render("别来找我。", True, (80, 80, 80)), (100, 620))
    btn_y = 300
    for item in ["开始游戏", "继续游戏", "收集回顾", "设置", "退出"]:
        pygame.draw.rect(screen, (60, 60, 60), pygame.Rect(520, btn_y, 240, 50), border_radius=8)
        screen.blit(font_mid.render(item, True, WHITE), (540, btn_y + 8))
        btn_y += 70
    pygame.display.flip()


def draw_chapter_end(name, next_name=None):
    screen.fill((12, 12, 14))
    t1 = font_big.render(f"{name} · 完", True, (235, 235, 235))
    screen.blit(t1, (SCREEN_WIDTH // 2 - t1.get_width() // 2, 230))
    txt = f"下一关：{next_name} · 待开发" if next_name else "未完待续"
    t3 = font_small.render(txt, True, (110, 110, 110))
    screen.blit(t3, (SCREEN_WIDTH // 2 - t3.get_width() // 2, 340))
    pygame.display.flip()


def draw_water_shimmer(ox, oy, elapsed):
    """水面上缓慢漂移的碎光，只在水地图调用。"""
    for i in range(18):
        wx = (i * 191 + elapsed * 14) % (MAP_W + 240) - 120
        wy = (i * 103 + math.sin(elapsed * 0.5 + i) * 46) % (MAP_H + 240) - 120
        sx, sy = int(wx - ox), int(wy - oy)
        if -90 < sx < SCREEN_WIDTH + 90 and -40 < sy < SCREEN_HEIGHT + 40:
            pygame.draw.line(screen, (128, 162, 170), (sx, sy), (sx + 24, sy + 1), 1)


# ===================== 对话：聊天气泡 / 旁白 =====================
# 朋友在左侧灰白气泡里说话（像平时发消息），旁白走底部居中的细字，
# 迷宫之渊在右侧黑底红字气泡里说，出现时轻微抖动。
_dlg = {"cur": None, "t": 0.0, "queue": []}
_dlg_lift = 0
_AVATAR = None
DLG_CPS = 0.05          # 逐字速度：每字 0.05 秒
DLG_HOLD = 1.9          # 打完字之后停留的秒数


def get_avatar():
    global _AVATAR
    if _AVATAR is not None:
        return _AVATAR
    try:
        frames = load_jumpscare_frames()
        if not frames:
            return None
        face = frames[0].subsurface(pygame.Rect(530, 150, 340, 340)).copy()
        face = pygame.transform.smoothscale(face, (64, 64)).convert_alpha()
        mask = pygame.Surface((64, 64), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (32, 32), 32)
        face.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        _AVATAR = face
    except Exception:
        _AVATAR = None
    return _AVATAR


def speak(who, text, delay=0.0):
    _dlg["queue"].append({"who": who, "text": text, "delay": delay})


def clear_dialogue():
    _dlg["cur"] = None
    _dlg["t"] = 0.0
    _dlg["queue"] = []


def dialogue_busy():
    return _dlg["cur"] is not None or bool(_dlg["queue"])


def advance_dialogue():
    cur = _dlg["cur"]
    if cur is None:
        return
    need = cur["delay"] + DLG_CPS * len(cur["text"])
    if _dlg["t"] < need:
        _dlg["t"] = need + DLG_HOLD
    else:
        _dlg["cur"] = None
        _dlg["t"] = 0.0


def update_dialogue(dt):
    if _dlg["cur"] is None:
        if _dlg["queue"]:
            _dlg["cur"] = _dlg["queue"].pop(0)
            _dlg["t"] = 0.0
        return
    _dlg["t"] += dt
    cur = _dlg["cur"]
    need = cur["delay"] + DLG_CPS * len(cur["text"])
    if _dlg["t"] >= need + DLG_HOLD:
        _dlg["cur"] = None
        _dlg["t"] = 0.0


# ===================== 触屏操作（手机） =====================
UI_STICK = (146, 616)
UI_STICK_R = 84
UI_STICK_HANDLE = 0.72
UI_BTN = {"cont": (1108, 610, 52), "skip": (1180, 470, 40)}
_touch = {"stick": None, "cont": None, "skip": None, "vec": [0.0, 0.0]}
_ui_menu_request = False


def _in_circle(pos, c, r):
    return (pos[0] - c[0]) ** 2 + (pos[1] - c[1]) ** 2 <= r * r


def ui_stick_move(pos):
    if _touch["stick"] is None:
        return
    ox, oy = UI_STICK
    vx, vy = pos[0] - ox, pos[1] - oy
    lim = UI_STICK_R * UI_STICK_HANDLE
    d = math.hypot(vx, vy)
    if d > lim:
        vx, vy = vx / d * lim, vy / d * lim
    _touch["vec"][0] = vx / lim
    _touch["vec"][1] = vy / lim


def _ui_request_menu():
    global _ui_menu_request
    _ui_menu_request = True


def skip_story():
    if _prologue["active"]:
        _prologue["active"] = False
    elif _ending["active"]:
        _ending["t"] = max(_ending["t"], 999.0)
    else:
        clear_dialogue()


def ui_action(key):
    if key == "skip":
        skip_story()
        return
    if _prologue["active"]:
        advance_prologue()
    elif _ending["active"]:
        if _ending["t"] > 8.0:
            _ui_request_menu()
    else:
        advance_dialogue()


def ui_tap():
    if _prologue["active"]:
        advance_prologue()
    elif _ending["active"]:
        if _ending["t"] > 8.0:
            _ui_request_menu()
    else:
        advance_dialogue()


def ui_press(pos, pid):
    if _in_circle(pos, UI_STICK, UI_STICK_R):
        _touch["stick"] = pid
        ui_stick_move(pos)
        return True
    for key in ("cont", "skip"):
        if _in_circle(pos, UI_BTN[key][:2], UI_BTN[key][2]):
            _touch[key] = pid
            ui_action(key)
            return True
    ui_tap()
    return False


def ui_release(pid):
    if _touch["stick"] == pid:
        _touch["stick"] = None
        _touch["vec"][0] = 0.0
        _touch["vec"][1] = 0.0
    for key in ("cont", "skip"):
        if _touch[key] == pid:
            _touch[key] = None


def draw_touch_ui(show_stick=True):
    ox, oy = UI_STICK
    rr = UI_STICK_R
    if show_stick:
        base = pygame.Surface((rr * 2 + 8, rr * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(base, (255, 255, 255, 16), (rr + 4, rr + 4), rr)
        pygame.draw.circle(base, (255, 255, 255, 42), (rr + 4, rr + 4), rr, 2)
        screen.blit(base, (ox - rr - 4, oy - rr - 4))
        lim = rr * UI_STICK_HANDLE
        kx = int(ox + _touch["vec"][0] * lim)
        ky = int(oy + _touch["vec"][1] * lim)
        knob = pygame.Surface((68, 68), pygame.SRCALPHA)
        pygame.draw.circle(knob, (236, 232, 224, 72), (34, 34), 28)
        pygame.draw.circle(knob, (255, 255, 255, 110), (34, 34), 28, 2)
        screen.blit(knob, (kx - 34, ky - 34))
    for key in ("cont", "skip"):
        cx, cy, r = UI_BTN[key]
        cir = pygame.Surface((r * 2 + 6, r * 2 + 6), pygame.SRCALPHA)
        pressed = _touch[key] is not None
        pygame.draw.circle(cir, (10, 10, 12, 130 if not pressed else 180), (r + 3, r + 3), r)
        pygame.draw.circle(cir, (240, 236, 228, 96), (r + 3, r + 3), r, 2)
        screen.blit(cir, (cx - r - 3, cy - r - 3))
        lab = font_tiny.render("继续" if key == "cont" else "跳过", True, (238, 234, 226))
        screen.blit(lab, (cx - lab.get_width() // 2, cy - lab.get_height() // 2))


def _wrap_text(text, font, maxw):
    lines = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.size(cur + ch)[0] > maxw and cur:
            if ch in "，。！？、…：；）】》":
                cur += ch
                lines.append(cur)
                cur = ""
                continue
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _draw_bubble_box(cx_right, y, w, h, tail_left, fill, border, shadow_alpha=90):
    box = pygame.Surface((w + 16, h + 16), pygame.SRCALPHA)
    pygame.draw.rect(box, (0, 0, 0, shadow_alpha), (8, 9, w, h), border_radius=12)
    pygame.draw.rect(box, fill, (6, 6, w, h), border_radius=12)
    pygame.draw.rect(box, border, (6, 6, w, h), 2, border_radius=12)
    ty = h + 6 - 16
    if tail_left:
        pygame.draw.polygon(box, fill, [(10, ty), (10, ty - 6), (2, ty + 6)])
    else:
        pygame.draw.polygon(box, fill, [(w + 8, ty), (w + 8, ty - 6), (w + 16, ty + 6)])
    return box


def _render_dialogue_surface():
    """把当前这句画成一层（气泡或旁白细字），返回 (surface, pos)。"""
    cur = _dlg["cur"]
    if cur is None:
        return None
    who, text = cur["who"], cur["text"]
    t = _dlg["t"]
    if t < cur["delay"]:
        return None
    shown = int((t - cur["delay"]) / DLG_CPS)
    shown = max(0, min(len(text), shown))
    body = text[:shown]

    if who == "旁白":
        font = font_small
        lines = _wrap_text(text, font, 980)
        lh = 28 * len(lines)
        surf = pygame.Surface((1000, lh + 6), pygame.SRCALPHA)
        remain = shown
        for i, full in enumerate(lines):
            take = min(len(full), remain)
            remain -= take
            piece = full[:take]
            sh = font.render(piece, True, (12, 11, 10))
            surf.blit(sh, (1, i * 28 + 1))
            surf.blit(font.render(piece, True, (236, 232, 224)), (0, i * 28))
        tw = max(font.size(full)[0] for full in lines)
        return surf, ((SCREEN_WIDTH - tw) // 2, 588 - lh)

    # 气泡（朋友在左，深渊在右）
    font = font_small
    maxw = 430
    lines_full = _wrap_text(text, font, maxw)
    remain = shown
    lines = []
    for full in lines_full:
        take = min(len(full), remain)
        remain -= take
        lines.append(full[:take])
    lw = 120 if who == "M4" else 140
    for full in lines_full:
        lw = max(lw, font.size(full)[0] + 34)
    lw = min(lw, maxw + 34)
    lh = 26 * max(1, len(lines))
    h = lh + 26

    if who == "M4":
        left_side = True
        fill = (238, 236, 232, 255)
        border = (198, 194, 187, 255)
        tcol = (52, 50, 48)
    else:
        left_side = False
        fill = (16, 14, 16, 240)
        border = (92, 22, 22, 255)
        tcol = (188, 54, 54)

    box = _draw_bubble_box(0, 0, lw, h, left_side, fill, border)
    for i, s in enumerate(lines):
        box.blit(font.render(s, True, tcol), (6 + 16, 6 + 14 + i * 26))
    # 名字
    tag = "M4" if who == "M4" else " "
    tag_font = font_tiny
    tag_col = (150, 146, 140) if who == "M4" else (110, 30, 30)
    box.blit(tag_font.render(tag, True, tag_col), (22, 4))
    return box, None


def _dlg_lift_local(v):
    global _dlg_lift
    _dlg_lift = v


def draw_dialogue(elapsed):
    cur = _dlg["cur"]
    if cur is None:
        return
    t = _dlg["t"]
    who = cur["who"]

    # 打字中：先冒三个点
    if t < cur["delay"]:
        dots = int((t / 0.22) % 4)
        if who == "旁白":
            return
        txt = "·" * (dots + 1)
        f = font_small
        s = f.render(txt, True, (120, 116, 110) if who == "M4" else (150, 40, 40))
        bx = 118 if who == "M4" else SCREEN_WIDTH - 120 - s.get_width()
        pygame.draw.rect(screen, (238, 236, 232) if who == "M4" else (16, 14, 16),
                         (bx - 12, 500, s.get_width() + 24, 34), border_radius=12)
        screen.blit(s, (bx, 506))
        return

    surf, pos = _render_dialogue_surface()
    if surf is None:
        return

    if who == "旁白":
        screen.blit(surf, (pos[0], pos[1] - _dlg_lift))
        return

    # 气泡贴着左下往上长
    av = get_avatar()
    bh = surf.get_height()
    by = 508 - bh - _dlg_lift
    if who == "M4":
        screen.blit(surf, (104, by))
        if av is not None:
            screen.blit(av, (32, by + bh - 74))
            pygame.draw.circle(screen, (208, 204, 197), (64, by + bh - 42), 33, 2)
    else:
        sx = SCREEN_WIDTH - 104 - surf.get_width() + 8
        shake = int(2.5 * math.sin(elapsed * 26.0))
        screen.blit(surf, (sx + shake, by))


# ===================== 开场：他发来的那条消息 =====================
_prologue = {"active": False, "i": 0, "t": 0.0}
PROLOGUE = [("旁白", "三天前，他给我发了条消息。"),
            ("M4", "后山有条路，走到尽头能把丢掉的东西找回来。"),
            ("旁白", "他说他一个人不敢进去，让我陪他。"),
            ("旁白", "我来了。")]


def start_prologue():
    _prologue.update({"active": True, "i": 0, "t": 0.0})
    clear_dialogue()


def update_prologue(dt):
    _prologue["t"] += dt


def advance_prologue():
    cur = PROLOGUE[_prologue["i"]]
    need = DLG_CPS * len(cur[1])
    if _prologue["t"] < need:
        _prologue["t"] = need
        return
    _prologue["i"] += 1
    _prologue["t"] = 0.0
    if _prologue["i"] >= len(PROLOGUE):
        _prologue["active"] = False


def draw_prologue():
    screen.fill((6, 6, 7))
    # 极淡的竖向渐层，像手机屏幕的光
    for y in range(0, SCREEN_HEIGHT, 4):
        a = int(18 * (1.0 - y / SCREEN_HEIGHT))
        pygame.draw.rect(screen, (10 + a, 10 + a, 12 + a), (0, y, SCREEN_WIDTH, 4))
    i = min(_prologue["i"], len(PROLOGUE) - 1)
    who, text = PROLOGUE[i]
    t = _prologue["t"]
    shown = max(0, min(len(text), int(t / DLG_CPS)))
    body = text[:shown]

    if who == "M4":
        font = font_mid
        lines = _wrap_text(body, font, 620)
        h = 44 * max(1, len(lines)) + 40
        w = 700
        box = _draw_bubble_box(0, 0, w, h, True, (238, 236, 232, 255),
                               (198, 194, 187, 255))
        for k, s in enumerate(lines):
            box.blit(font.render(s, True, (52, 50, 48)), (34, 22 + k * 44))
        av = get_avatar()
        bx, by = 210, 296
        screen.blit(box, (bx, by))
        if av is not None:
            big = pygame.transform.smoothscale(av, (72, 72))
            screen.blit(big, (bx - 74, by + h - 88))
        tag = font_tiny.render("M4 · 现在", True, (120, 116, 110))
        screen.blit(tag, (bx + 6, by - 22))
    else:
        font = font_mid
        lines = _wrap_text(body, font, 900)
        for k, s in enumerate(lines):
            surf = font.render(s, True, (226, 222, 214))
            screen.blit(surf, ((SCREEN_WIDTH - surf.get_width()) // 2, 300 + k * 46))

    tip = font_tiny.render("点屏幕继续 · 摇杆移动", True, (86, 84, 82))
    screen.blit(tip, (26, SCREEN_HEIGHT - 30))
    draw_touch_ui(False)
    pygame.display.flip()


# ===================== 第六关：地下深处 =====================
DEPTHS_ROOMS = [
    pygame.Rect(1010, 1270, 420, 270),   # 入口厅（地窖下来的地方）
    pygame.Rect(930, 980, 400, 250),     # 窄厅
    pygame.Rect(760, 690, 520, 260),     # 落石厅
    pygame.Rect(560, 150, 1220, 480),    # 迷宫之渊厅（BOSS 场地）
]
DEPTHS_TUNNELS = [
    pygame.Rect(1140, 1160, 160, 140),
    pygame.Rect(1030, 880, 160, 120),
    pygame.Rect(1080, 600, 180, 120),
]
DEPTHS_M4 = pygame.Rect(1100, 152, 160, 110)
DEPTHS_SPAWN = (1150, 1430)
DEPTHS_LADDER = pygame.Rect(0, 0, 116, 96)


def create_level_depths(theme_key, arrive_from=None):
    th = THEMES[theme_key]
    rooms = [r.copy() for r in DEPTHS_ROOMS]
    tunnels = [r.copy() for r in DEPTHS_TUNNELS]
    floors = rooms + tunnels

    open_mask = _mark_rects(floors)
    MC = MAP_W // W_TILE
    MR = MAP_H // W_TILE
    solid = [[not open_mask[r][c] for c in range(MC)] for r in range(MR)]
    m4_rect = DEPTHS_M4.copy()
    # 门是实心的，碰撞和可走格网一起算，玩家只能停在门前那一步
    blockers = merge_blocked_runs(solid, MC, MR, W_TILE) + [m4_rect]
    free = build_free_grid(blockers)

    spawn_xy = free_cell_center_near(DEPTHS_SPAWN[0], DEPTHS_SPAWN[1], free, blockers, 220)
    if spawn_xy is None:
        spawn_xy = DEPTHS_SPAWN

    DEPTHS_LADDER.center = (980, 1452)
    portals = [{"rect": DEPTHS_LADDER.copy(), "label": "地窖", "target": "地窖",
                "style": "ladder", "next": None}]

    return {
        "kind": "depths",
        "theme": theme_key,
        "floors": floors, "rooms": rooms, "tunnels": tunnels,
        "walls": [], "blockers": blockers, "free": free,
        "dist": bfs_dist(free, spawn_xy),
        "portals": portals,
        "flowers": [],
        "collected": [],
        "pick_fx": [],
        "px": spawn_xy[0], "py": spawn_xy[1],
        "armed": [False if (arrive_from and p["target"] == arrive_from) else True
                  for p in portals],
        "leaves": [],
        "surface": None,
        "sky": None,
        "torch": True,
        "veil_a": 176.0,
        "facing": [0, -1],
        "quest": "往深处走 · 那扇门后面有光",
        "m4_rect": m4_rect,
        "m4_touched": False,
        "boss": None,
        "dlg_t": 0.0, "dlg_fired": set(),
    }


def build_surface_depths(state):
    th = THEMES[state["theme"]]
    surf = pygame.Surface((MAP_W, MAP_H))
    rnd = random.Random(60613)

    wall = (30, 26, 24)
    surf.fill(wall)
    for _ in range(1000):
        gx = rnd.randint(-90, MAP_W + 90)
        gy = rnd.randint(-90, MAP_H + 90)
        rx = rnd.randint(46, 138)
        ry = rnd.randint(30, 92)
        sh = rnd.choice([-9, -6, -3, 3, 6])
        col = (max(0, wall[0] + sh), max(0, wall[1] + sh), max(0, wall[2] + sh))
        layer = pygame.Surface((rx * 2, ry * 2), pygame.SRCALPHA)
        pygame.draw.ellipse(layer, col + (rnd.randint(26, 46),), layer.get_rect())
        surf.blit(layer, (gx - rx, gy - ry))
    for _ in range(8000):
        gx = rnd.randint(0, MAP_W - 1)
        gy = rnd.randint(0, MAP_H - 1)
        sh = rnd.choice([-6, -4, -2, 3, 5])
        col = (max(0, wall[0] + sh), max(0, wall[1] + sh), max(0, wall[2] + sh))
        pygame.draw.circle(surf, col, (gx, gy), rnd.randint(2, 5))

    for rc in state["floors"]:
        pygame.draw.rect(surf, th["floor"], rc)
    for rc in state["floors"]:
        area = rc.w * rc.h
        for _ in range(max(20, area // 1100)):
            gx = rnd.randint(rc.left, rc.right - 1)
            gy = rnd.randint(rc.top, rc.bottom - 1)
            sh = rnd.choice([-14, -9, -5, 4, 8])
            col = (max(0, th["floor"][0] + sh), max(0, th["floor"][1] + sh),
                   max(0, th["floor"][2] + sh))
            pygame.draw.circle(surf, col, (gx, gy), rnd.randint(2, 6))
        for _ in range(max(2, area // 9000)):
            gx = rnd.randint(rc.left + 12, rc.right - 14)
            gy = rnd.randint(rc.top + 12, rc.bottom - 14)
            ln = rnd.randint(16, 52)
            ang = rnd.uniform(0, 6.28)
            pygame.draw.line(surf, (18, 15, 13), (gx, gy),
                             (gx + int(ln * math.cos(ang)), gy + int(ln * math.sin(ang))), 2)

    T = W_TILE
    MC = MAP_W // T
    MR = MAP_H // T
    open_mask = _mark_rects(state["floors"])
    for gy in range(MR):
        for gx in range(MC):
            if not open_mask[gy][gx]:
                continue
            x0, y0 = gx * T, gy * T
            if gy > 0 and not open_mask[gy - 1][gx]:
                pygame.draw.rect(surf, th["rim"], (x0, y0, T, 6))
            if gy < MR - 1 and not open_mask[gy + 1][gx]:
                pygame.draw.rect(surf, th["rim"], (x0, y0 + T - 6, T, 6))
            if gx > 0 and not open_mask[gy][gx - 1]:
                pygame.draw.rect(surf, th["rim"], (x0, y0, 6, T))
            if gx < MC - 1 and not open_mask[gy][gx + 1]:
                pygame.draw.rect(surf, th["rim"], (x0 + T - 6, y0, 6, T))

    # 落石厅：几块塌下来的大石
    rb = state["rooms"][2]
    for _ in range(7):
        rx = rnd.randint(rb.left + 40, rb.right - 60)
        ry = rnd.randint(rb.top + 40, rb.bottom - 50)
        rr = rnd.randint(16, 34)
        pygame.draw.circle(surf, (16, 14, 12), (rx + 5, ry + 7), rr)
        pygame.draw.circle(surf, (54, 47, 39), (rx, ry), rr)
        pygame.draw.circle(surf, (78, 68, 56), (rx - rr // 4, ry - rr // 3), max(3, rr // 3))

    # 回程木梯
    for p in state["portals"]:
        r = p["rect"]
        if p.get("style") == "ladder":
            pygame.draw.rect(surf, (16, 13, 11), r.inflate(24, 18))
            pygame.draw.rect(surf, (56, 42, 31), r)
            for i in range(4):
                pygame.draw.rect(surf, (92, 70, 50),
                                 (r.left + 8, r.top + 8 + i * 22, r.w - 16, 6))
            beam = pygame.Surface((r.w, 150), pygame.SRCALPHA)
            for y in range(150):
                a = max(0, int(42 * (1.0 - y / 150.0)))
                pygame.draw.line(beam, (255, 226, 178, a), (0, y), (r.w, y))
            surf.blit(beam, (r.left, r.top - 150))

    # 尽头那扇门：两扇锈铁门 + 门缝的光 + 刻痕 M4
    m4 = state["m4_rect"]
    rnd2 = random.Random(31)
    pygame.draw.rect(surf, (8, 7, 7), m4.inflate(34, 26))
    # 门框：一圈粗糙的石头
    for i in range(46):
        fx = rnd2.randint(m4.left - 16, m4.right + 14)
        fy = rnd2.randint(m4.top - 12, m4.bottom + 12)
        if m4.left - 10 < fx < m4.right + 10 and m4.top - 8 < fy < m4.bottom + 8:
            continue
        rr = rnd2.randint(3, 7)
        pygame.draw.circle(surf, (38, 32, 27), (fx, fy), rr)
        pygame.draw.circle(surf, (58, 50, 41), (fx - 1, fy - 2), max(2, rr - 2))
    pygame.draw.rect(surf, (16, 13, 11), m4.inflate(10, 10), 6)
    # 两扇门：竖板 + 铆钉
    half = m4.w // 2
    for side in (0, 1):
        leaf = pygame.Rect(m4.left + side * half, m4.top, half, m4.h)
        surf.fill((66, 54, 43), leaf)
        for k in range(1, 5):
            lx = leaf.left + k * half // 5
            pygame.draw.line(surf, (46, 37, 29), (lx, leaf.top + 4), (lx, leaf.bottom - 4), 3)
        pygame.draw.line(surf, (92, 76, 58), (leaf.left + 3, leaf.top + 4),
                         (leaf.left + 3, leaf.bottom - 6), 1)
        for k in range(5):
            ry = leaf.top + 12 + k * (leaf.h - 26) // 4
            for lx in (leaf.left + 12, leaf.right - 12):
                pygame.draw.circle(surf, (44, 35, 27), (lx, ry), 3)
                pygame.draw.circle(surf, (104, 92, 74), (lx - 1, ry - 1), 1)
    # 生锈
    for _ in range(34):
        rx = rnd2.randint(m4.left + 2, m4.right - 2)
        ry = rnd2.randint(m4.top + 2, m4.bottom - 2)
        rr = rnd2.randint(1, 3)
        col = rnd2.choice([(78, 44, 27), (92, 52, 30), (104, 62, 36)])
        pygame.draw.circle(surf, col, (rx, ry), rr)
    # 门缝：一条竖直的光，越靠腰越亮
    seam = pygame.Surface((14, m4.h), pygame.SRCALPHA)
    for y in range(m4.h):
        a = int(190 * (0.35 + 0.65 * (1.0 - abs(y - m4.h * 0.55) / (m4.h * 0.55))))
        pygame.draw.line(seam, (255, 226, 178, max(0, a)), (4, y), (10, y))
    surf.blit(seam, (m4.centerx - 7, m4.top))
    # 门缝漏出来的一道光柱
    beam = pygame.Surface((m4.w, 190), pygame.SRCALPHA)
    for y in range(190):
        a = int(26 * (1.0 - y / 190.0))
        pygame.draw.line(beam, (255, 222, 170, a), (m4.w // 2 - 6, y), (m4.w // 2 + 6, y))
    surf.blit(beam, (m4.left, m4.top + 6))
    # 门框上的刻痕：M4
    lab = font_small.render("M4", True, (26, 20, 17))
    for dx in (1, 2):
        surf.blit(lab, (m4.centerx - lab.get_width() // 2 + dx, m4.top + 10 + dx))
    surf.blit(font_small.render("M4", True, (128, 110, 88)),
              (m4.centerx - lab.get_width() // 2, m4.top + 10))
    return surf


# ===================== BOSS「迷宫之渊」 =====================
BOSS_DUR = 120.0
BOSS_P2 = 60.0
BOSS_SPAWN_A = 2.4
BOSS_SPAWN_B = 1.8
BOSS_SPEED = 95.0
BOSS_BULLET_R = 11
IFRAME_T = 1.5
BLOOD = (176, 40, 36)


def start_boss(st, shield):
    st["boss"] = {
        "t": 0.0, "shield": shield, "max": 5, "bullets": [], "spawn": 0.0,
        "iframe": 0.0, "phase": "fight", "veil": 0.0, "flash": 0.0,
        "shake": 0.0, "end_t": 0.0, "m4": 0.0, "dust": [], "said": set(),
    }
    clear_dialogue()
    speak("渊", "哈哈，这次一定能……", delay=0.2)
    play_music("boss")
    st["quest"] = "别让它碰到你 · 撑住"
    # 开战把来路封上：这一分钟你别想跑
    wall = pygame.Rect(1080, 594, 180, 132)
    st["boss_wall"] = wall
    if wall not in st["blockers"]:
        st["blockers"].append(wall)


def _spawn_bullet(b, px, py):
    bx = b["bx"]
    by = b["by"]
    ang = math.atan2(py - by, px - bx) + math.radians(random.uniform(-22, 22))
    b["bullets"].append({"x": bx, "y": by,
                         "vx": math.cos(ang) * BOSS_SPEED,
                         "vy": math.sin(ang) * BOSS_SPEED,
                         "r": BOSS_BULLET_R, "dead": False})


def update_boss(st, dt, px, py):
    b = st.get("boss")
    if b is None:
        return
    if b["phase"] == "fight":
        b["t"] += dt
        if b["iframe"] > 0:
            b["iframe"] -= dt
        b["flash"] = max(0.0, b["flash"] - dt * 4.0)
        b["shake"] = max(0.0, b["shake"] - dt * 6.0)

        # 弹幕从门后那团东西里吐出来
        arena = st["rooms"][-1]
        b["bx"] = st["m4_rect"].centerx + random.randint(-60, 60)
        b["by"] = arena.top + 40
        b["spawn"] += dt
        interval = BOSS_SPAWN_A if b["t"] < BOSS_P2 else BOSS_SPAWN_B
        if b["spawn"] >= interval:
            b["spawn"] = 0.0
            _spawn_bullet(b, px, py)
            if b["t"] >= BOSS_P2 and random.random() < 0.55:
                _spawn_bullet(b, px, py)

        for p in b["bullets"]:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
        b["bullets"] = [p for p in b["bullets"]
                        if -60 < p["x"] < MAP_W + 60 and -60 < p["y"] < MAP_H + 60]

        if b["iframe"] <= 0:
            for p in b["bullets"]:
                if (p["x"] - px) ** 2 + (p["y"] - py) ** 2 < (p["r"] + player_radius) ** 2:
                    b["shield"] -= 1
                    b["iframe"] = IFRAME_T
                    b["flash"] = 1.0
                    b["shake"] = 1.0
                    ddx, ddy = px - p["x"], py - p["y"]
                    dl = max(1.0, math.hypot(ddx, ddy))
                    p["vx"], p["vy"] = ddx / dl * 620.0, ddy / dl * 620.0
                    p["r"] = 8
                    break

        if b["shield"] <= 0:
            b["shield"] = 0
            b["phase"] = "bad"
            b["end_t"] = 0.0
            clear_dialogue()
            if st.get("boss_wall") in st["blockers"]:
                st["blockers"].remove(st["boss_wall"])
        elif b["t"] >= BOSS_DUR:
            b["phase"] = "good"
            b["end_t"] = 0.0
            b["bullets"] = []
            clear_dialogue()
            if st.get("boss_wall") in st["blockers"]:
                st["blockers"].remove(st["boss_wall"])

        want = 210.0 if b["t"] >= BOSS_P2 else 0.0
        b["veil"] += (want - b["veil"]) * min(1.0, dt * 0.9)
        if b["t"] >= BOSS_P2 and "p2" not in b["said"]:
            b["said"].add("p2")
            st["quest"] = "渊暗蔽目 · 只看得到脚边"
            play_tinnitus()

    elif b["phase"] == "good":
        b["end_t"] += dt
        b["veil"] += (255.0 if b["end_t"] > 6.0 else 40.0 - b["veil"]) * min(1.0, dt * 0.6)
        b["m4"] += dt
        if b["end_t"] > 1.0 and "l1" not in b["said"]:
            b["said"].add("l1")
            speak("M4", "别回头。", delay=0.0)
        if b["end_t"] > 3.0 and "l2" not in b["said"]:
            b["said"].add("l2")
            speak("M4", "往前走吧，朋友……这次别再回来找我了。", delay=0.1)
        if b["end_t"] > 3.6 and not b["dust"]:
            for _ in range(170):
                a = random.uniform(0, math.tau)
                sp = random.uniform(30, 240)
                b["dust"].append({
                    "x": st["m4_rect"].centerx + random.randint(-110, 110),
                    "y": st["m4_rect"].bottom + random.randint(-40, 90),
                    "vx": math.cos(a) * sp, "vy": math.sin(a) * sp - 60,
                    "r": random.randint(1, 3), "life": random.uniform(1.8, 4.6),
                })
        for d in b["dust"]:
            d["x"] += d["vx"] * dt
            d["y"] += d["vy"] * dt
            d["life"] -= dt
        b["dust"] = [d for d in b["dust"] if d["life"] > 0]
        if b["end_t"] > 9.5:
            start_ending("good")
            b["phase"] = "done"

    elif b["phase"] == "bad0":
        # 花不够：什么都不打，门慢慢关
        b["end_t"] += dt
        b["veil"] += (255.0 - b["veil"]) * min(1.0, dt * 1.2)
        if b["end_t"] > 0.9 and "b0" not in b["said"]:
            b["said"].add("b0")
            speak("旁白", "门在你身后合上了。")
        if b["end_t"] > 4.8:
            start_ending("bad")
            b["phase"] = "done"

    elif b["phase"] == "bad":
        b["end_t"] += dt
        b["veil"] += (255.0 - b["veil"]) * min(1.0, dt * 1.4)
        if b["end_t"] > 1.6 and "b1" not in b["said"]:
            b["said"].add("b1")
            speak("旁白", "门在你身后合上了。", delay=0.0)
        b["bullets"] = []
        if b["end_t"] > 5.4:
            start_ending("bad")
            b["phase"] = "done"


_M4_GHOST = None


def get_m4_ghost():
    """把那张照片裁成一张边缘化开的“影子”，不要硬邦邦的矩形图。"""
    global _M4_GHOST
    if _M4_GHOST is not None:
        return _M4_GHOST
    frames = load_jumpscare_frames()
    if not frames:
        return None
    w, h = 540, 330
    g = pygame.transform.smoothscale(frames[0], (w, h)).convert_alpha()
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    steps = 26
    for i in range(steps):
        a = int(255 * (i + 1) / steps)
        ins_x = int(i * 4)
        ins_y = int(i * 3)
        pygame.draw.ellipse(mask, (255, 255, 255, a),
                            pygame.Rect(ins_x, ins_y, w - ins_x * 2, h - ins_y * 2))
    g.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    _M4_GHOST = g
    return g


def _draw_m4_dissolve(st, b, door, ox, oy):
    """好结局：他的脸在黑白之间闪，然后整个人跟着那团东西一起变成灰。"""
    # 1) 黑白频闪（1.0 – 3.9 秒），边缘是化开的，不做成一张贴图
    if b["end_t"] < 3.9:
        ghost = get_m4_ghost()
        if ghost is not None:
            fade = max(0.0, 1.0 - max(0.0, b["end_t"] - 3.0) / 0.9)
            k = int(b["end_t"] * 10) % 4
            alpha = int(([228, 72, 188, 24][k]) * fade)
            gx = door.centerx - ox - ghost.get_width() // 2
            gy = 74
            ghost.set_alpha(alpha)
            screen.blit(ghost, (gx, gy))
            for _ in range(3):
                sy = random.randint(6, ghost.get_height() - 30)
                sh = random.randint(8, 24)
                screen.blit(ghost.subsurface((0, sy, ghost.get_width(), sh)),
                            (gx + random.randint(-9, 9), gy + sy))
            ghost.set_alpha(None)

    # 2) 门缝后的光透出来
    if b["end_t"] > 2.6:
        k = min(1.0, (b["end_t"] - 2.6) / 3.4)
        bw, bh = 360, 470
        beam = pygame.Surface((bw, bh), pygame.SRCALPHA)
        for xx in range(0, bw, 4):
            q = abs(xx - bw // 2) / (bw // 2)
            fall = max(0.0, 1.0 - q) ** 1.6
            for yy in range(0, bh, 6):
                aa = int(150 * k * fall * (1.0 - yy / bh))
                if aa <= 0:
                    continue
                pygame.draw.rect(beam, (255, 244, 212, aa), (xx, yy, 4, 6))
        screen.blit(beam, (door.centerx - ox - bw // 2, door.bottom - oy - 60))

    # 3) 灰
    for d in b["dust"]:
        a = max(0, min(255, int(200 * min(1.0, d["life"] / 1.6))))
        rr = max(1, int(d["r"] * 1.7))
        s2 = pygame.Surface((rr * 4, rr * 4), pygame.SRCALPHA)
        cx2 = cy2 = rr * 2
        pygame.draw.circle(s2, (248, 244, 232, a // 6), (cx2, cy2), rr)
        pygame.draw.circle(s2, (250, 247, 238, a // 3), (cx2, cy2), max(1, rr // 2))
        screen.blit(s2, (d["x"] - ox - cx2, d["y"] - oy - cy2))


def draw_boss_body(st, ox, oy, elapsed):
    b = st.get("boss")
    if b is None or b["phase"] == "done":
        return
    door = st["m4_rect"]
    cx = door.centerx - ox
    door_bottom = door.bottom - oy

    if b["phase"] == "good" and b["end_t"] > 1.0:
        _draw_m4_dissolve(st, b, door, ox, oy)
        return

    if b["phase"] == "good":
        grow = max(0.0, 1.0 - b["end_t"] / 1.6)
    elif b["phase"] in ("bad", "bad0"):
        grow = 1.0 + b["end_t"] * 0.35
    else:
        grow = 0.62 + min(1.0, b["t"] / BOSS_DUR) * 0.55
    if grow <= 0.02:
        return
    base = int(108 * grow)

    # 坏结局：先看见他的影子，然后被这团东西整个盖过去
    if b["phase"] in ("bad", "bad0") and b["end_t"] < 1.6:
        ghost = get_m4_ghost()
        if ghost is not None:
            ghost.set_alpha(int(150 * max(0.0, 1.0 - b["end_t"] / 1.6)))
            screen.blit(ghost, (door.centerx - ox - ghost.get_width() // 2, 74))
            ghost.set_alpha(None)

    # 先铺一层由外向内加深的暗，别在边缘留出一圈亮环
    for i in range(11):
        sc = 1.06 - i * 0.055
        sw = int(base * 4 * sc)
        shh = int(base * 2.6 * sc)
        sh = pygame.Surface((sw, shh), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (5, 4, 6, 13), sh.get_rect())
        screen.blit(sh, (cx - sw // 2, door_bottom - shh // 2 - base * 0.3))

    for i in range(16):
        ang = i * 0.39 - elapsed * 0.15
        rx = int(cx + math.cos(ang) * base * 0.95)
        ry = int(door_bottom + math.sin(ang) * base * 0.48)
        rr = int(base * (0.30 + 0.10 * math.sin(elapsed * 0.9 + i)))
        pygame.draw.circle(screen, (26, 22, 26), (rx, ry), max(6, rr))

    for i in range(15):
        ang = i * 0.42 + elapsed * 0.22
        rx = int(cx + math.cos(ang) * base * 0.72)
        ry = int(door_bottom + math.sin(ang) * base * 0.34 + base * 0.1)
        rr = max(8, int(base * (0.55 + 0.28 * math.sin(elapsed * 1.3 + i * 1.7))))
        pygame.draw.circle(screen, (11, 10, 12), (rx, ry), rr)
        if rr > 26:
            pygame.draw.circle(screen, (17, 15, 18), (rx - rr // 5, ry - rr // 4), rr // 2)

    rnd3 = random.Random(4242)
    for _ in range(38):
        a = rnd3.uniform(0, math.tau)
        rad = rnd3.uniform(0, 0.82) * base
        mx = cx + math.cos(a) * rad
        my = door_bottom + math.sin(a) * rad * 0.46
        rr = rnd3.randint(int(max(4, base * 0.10)), int(max(6, base * 0.26)))
        col = rnd3.choice([(30, 26, 32), (38, 33, 40), (22, 19, 24), (16, 14, 18)])
        pygame.draw.circle(screen, col, (int(mx), int(my)), rr)

    for k in range(5):
        bx = cx + (k - 2) * base * 0.3
        ln = base * (0.9 + 0.25 * math.sin(elapsed * 1.1 + k))
        for q in range(6):
            rr = int(base * (0.26 - q * 0.035))
            pygame.draw.circle(screen, (11, 10, 13),
                               (int(bx + math.sin(q * 0.6 + elapsed) * base * 0.06),
                                int(door_bottom + ln * q / 6.0)), max(3, rr))

    for i in range(22):
        ang = i * 0.29 + elapsed * 0.16
        ln = base * (1.9 + 0.6 * math.sin(elapsed * 0.8 + i * 1.3))
        x0 = cx + math.cos(ang) * base * 0.5
        y0 = door_bottom + math.sin(ang) * base * 0.25
        pts = [(x0, y0)]
        for k in range(1, 7):
            pts.append((x0 + math.sin(elapsed * 1.4 + i + k * 0.7) * base * 0.16 * k,
                        y0 + ln * k / 6.0))
        for k in range(len(pts) - 1):
            wd = max(1, int((9 - k * 1.2) * grow))
            pygame.draw.line(screen, (20, 17, 22), (int(pts[k][0]), int(pts[k][1])),
                             (int(pts[k + 1][0]), int(pts[k + 1][1])), wd)
        ex, ey = pts[-1]
        for f in range(4):
            fa = -0.5 + f * 0.5
            pygame.draw.line(screen, (20, 17, 22), (int(ex), int(ey)),
                             (int(ex + math.sin(fa) * base * 0.16),
                              int(ey + abs(math.cos(fa)) * base * 0.2)), 2)

    if b["phase"] not in ("bad", "bad0"):
        look = (st["px"] - door.centerx) / 420.0
        eye_y = door_bottom + int(base * 0.06)
        for side in (-1, 1):
            ex = int(cx + side * base * 0.34 + look * base * 0.10)
            gl = pygame.Surface((34, 34), pygame.SRCALPHA)
            pygame.draw.circle(gl, (230, 226, 214, 26), (17, 17), 16)
            screen.blit(gl, (ex - 17, eye_y - 17))
            pygame.draw.circle(screen, (238, 234, 226), (ex, eye_y), 6)
            pygame.draw.circle(screen, (120, 30, 30), (ex, eye_y), 6, 1)
            pygame.draw.circle(screen, (20, 8, 8), (ex, eye_y), 2)


_bullet_glow = None


def draw_boss_bullets(st, ox, oy):
    global _bullet_glow
    b = st.get("boss")
    if b is None:
        return
    if _bullet_glow is None:
        _bullet_glow = pygame.Surface((48, 48), pygame.SRCALPHA)
        pygame.draw.circle(_bullet_glow, (150, 30, 30, 60), (24, 24), 22)
    for p in b["bullets"]:
        sx, sy = int(p["x"] - ox), int(p["y"] - oy)
        if -30 < sx < SCREEN_WIDTH + 30 and -30 < sy < SCREEN_HEIGHT + 30:
            pygame.draw.line(screen, (96, 22, 20),
                             (int(sx - p["vx"] * 0.05), int(sy - p["vy"] * 0.05)), (sx, sy), 3)
            screen.blit(_bullet_glow, (sx - 24, sy - 24))
            pygame.draw.circle(screen, (52, 14, 14), (sx, sy), p["r"] + 3)
            pygame.draw.circle(screen, (198, 62, 54), (sx, sy), p["r"])
            pygame.draw.circle(screen, (246, 190, 170), (sx - 2, sy - 2), max(2, p["r"] // 3))


_boss_veil = None


def draw_boss_veil(st, px, py, ox, oy):
    global _boss_veil
    b = st.get("boss")
    if b is None:
        return
    alpha = int(b["veil"])
    if alpha <= 4:
        return
    r = 170
    _veil_render((3, 3, 5), min(255, alpha), [
        (get_circle_mask(r), int(px - ox) - r, int(py - oy) - r),
    ])


def draw_boss_hud(st):
    b = st.get("boss")
    if b is None:
        return
    x, y = 20, 122
    lab = font_tiny.render("白花", True, (236, 232, 224))
    screen.blit(lab, (x, y - 20))
    for i in range(b["max"]):
        cx = x + 16 + i * 34
        if i < b["shield"]:
            draw_flower(screen, cx, y + 12, 0.0)
        else:
            pygame.draw.circle(screen, (58, 54, 50), (cx, y + 12), 6, 1)
    if b["phase"] == "fight":
        remain = max(0.0, BOSS_DUR - b["t"])
        mm, ss = int(remain) // 60, int(remain) % 60
        txt = "%02d:%02d" % (mm, ss)
        hot = remain <= 10.0
        col = (226, 74, 58) if hot else (236, 232, 222)
        big = font_mid.render(txt, True, col)
        screen.blit(big, ((SCREEN_WIDTH - big.get_width()) // 2, 30))
        bw = 340
        bx = SCREEN_WIDTH // 2 - bw // 2
        pygame.draw.rect(screen, (18, 18, 20), (bx, 66, bw, 6), border_radius=3)
        pygame.draw.rect(screen, col, (bx, 66, int(bw * remain / BOSS_DUR), 6), border_radius=3)


# ===================== 结局 =====================
_ending = {"active": False, "kind": None, "t": 0.0, "lines": []}
ENDING_TEXT = {
    "good": ["天已经亮了。",
             "身后的洞口正在合上，",
             "像有人轻轻把门带上。",
             "回到有信号的地方，那条消息还在，时间停在三天前。",
             "我回拨过去，没有人接。",
             "后来我又去过一次后山。",
             "那条路不见了。",
             "找到M4 · 完"],
    "bad": ["我听见他在门那边，很轻地笑了一下。",
            "他说他一个人不敢进来。",
            "他没说过，走在前面的那个人要留下。",
            "现在我站在门里面。",
            "数着脚步声，等下一个愿意陪我进来的人。",
            "找到M4 · 坏结局"],
}


def start_ending(kind):
    _ending["active"] = True
    _ending["kind"] = kind
    _ending["t"] = 0.0
    _ending["lines"] = ENDING_TEXT[kind]
    clear_dialogue()
    try:
        pygame.mixer.music.fadeout(1500)
    except Exception:
        pass


def draw_ending():
    screen.fill((8, 8, 9))
    t = _ending["t"]
    lines = _ending["lines"]
    body_lines = lines[:-1]
    title = lines[-1]
    y = 150
    for i, line in enumerate(body_lines):
        delay = i * 1.9
        if t < delay:
            break
        shown = max(0, min(len(line), int((t - delay) / 0.075)))
        surf = font_mid.render(line[:shown], True, (222, 218, 210))
        screen.blit(surf, ((SCREEN_WIDTH - surf.get_width()) // 2, y))
        y += 54
    tail = (len(body_lines) - 1) * 1.9 + len(body_lines[-1]) * 0.075
    if t > tail + 2.2:
        col = (188, 40, 36) if _ending["kind"] == "bad" else (234, 230, 222)
        tt = font_mid.render(title, True, col)
        screen.blit(tt, ((SCREEN_WIDTH - tt.get_width()) // 2,
                         150 + len(body_lines) * 54 + 34))
    if t > tail + 6.0:
        tip = font_tiny.render("按任意键回到主菜单", True, (120, 118, 114))
        screen.blit(tip, ((SCREEN_WIDTH - tip.get_width()) // 2, SCREEN_HEIGHT - 60))
    draw_touch_ui(False)
    pygame.display.flip()


def update_level_dialogue(st, key, elapsed):
    """每张图在固定时机只说 2–4 句，不按房间刷。"""
    fired = st.setdefault("dlg_fired", set())
    t = st.get("dlg_t", 0.0)

    if key == "东风草原":
        if "n1" not in fired and t >= 0.8:
            fired.add("n1")
            speak("旁白", "草长得很高，风从背后吹过来。")
        if "f1" not in fired and t >= 5.0:
            fired.add("f1")
            speak("M4", "我就在前面，别停，快来啊。")
    elif key == "朝见湿地":
        if "f1" not in fired and t >= 2.0:
            fired.add("f1")
            speak("M4", "还记得我吗第一次在这里玩，你陷进泥里了。")
    elif key == "源泉":
        if "f1" not in fired and t >= 2.0:
            fired.add("f1")
            speak("M4", "水底下的东西，别看。")
        # 走到木屋门口 300px 内，他第一次失真
        if "f2" not in fired:
            for p in st["portals"]:
                if p.get("style") == "door":
                    r = p["rect"]
                    ddx = max(r.left - st["px"], 0.0, st["px"] - r.right)
                    ddy = max(r.top - st["py"], 0.0, st["py"] - r.bottom)
                    if ddx * ddx + ddy * ddy < 300 * 300:
                        fired.add("f2")
                        speak("M4", "门是开的。门是开\u25a1的。\u25a8去吧。")
                        break
    elif key == "地窖":
        hl = st.get("dlg_hl")
        if hl is not None and "f1" not in fired and elapsed >= hl:
            fired.add("f1")
            speak("M4", "你拿着它又能照什么呢？")
    elif key == "地下深处":
        if "n1" not in fired and t >= 1.5:
            fired.add("n1")
            speak("旁白", "越往下，回声越像有人在跟着。")


def start_bad_short(st):
    """花没集齐就碰了 M4：不打架，直接收场。"""
    st["boss"] = {"t": 0.0, "shield": 0, "max": 5, "bullets": [], "spawn": 0.0,
                  "iframe": 0.0, "phase": "bad0", "veil": 0.0, "flash": 0.0,
                  "shake": 0.0, "end_t": 0.0, "m4": 0.0, "dust": [], "said": set()}
    clear_dialogue()


# ===================== 主循环 =====================
async def main():
    global _ui_menu_request
    state_menu = True
    menu_start = pygame.time.get_ticks()

    init_music()
    play_music("menu")
    try:
        load_jumpscare_frames()
        get_scream_sound()
        get_tinnitus_sound()
    except Exception:
        pass

    states = {}
    current = "东风草原"
    total_collected = 0
    chapter_end = False
    chapter_next = None
    elapsed = 0.0

    mist = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    # 黑暗层统一走 _veil_render，它内部自建一张复用画布，不再重复分配

    def prepare(key, arrive_from=None):
        if key not in states:
            states[key] = create_level(key, arrive_from)
        st = states[key]
        if st.get("surface") is None:
            st["surface"] = build_surface(st)
        if st.get("sky") is None:
            st["sky"] = build_sky(key)
        if IS_MOBILE:
            # 手机内存有限：每张 2400x1600 大图约 15MB，只保留当前场景那张背景
            for _k, _other in states.items():
                if _k != key and _other.get("sky") is not None:
                    _other["sky"] = None
            gc.collect()
        return st

    prepare("东风草原")

    _prev_ticks = pygame.time.get_ticks()
    while True:
        # 用真实时间推进，不再假设每帧固定 1/60 秒。
        # 掉帧时游戏逻辑、倒计时都按现实时间走，不会被拖慢成 1/3 速。
        _now_ticks = pygame.time.get_ticks()
        dt = (_now_ticks - _prev_ticks) / 1000.0
        _prev_ticks = _now_ticks
        if dt > 0.05:
            dt = 0.05        # 封顶，避免卡顿后一帧瞬移穿墙
        if dt < 0.001:
            dt = 0.001
        elapsed += dt
        for event in pygame.event.get():
            if not _AUDIO_READY and event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                if ensure_audio():
                    play_music("menu" if state_menu else current)
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
                pos = (event.x * SCREEN_WIDTH, event.y * SCREEN_HEIGHT)
                pid = ("f", getattr(event, "finger_id", 0))
                if event.type == pygame.FINGERDOWN:
                    if not state_menu:
                        ui_press(pos, pid)
                elif event.type == pygame.FINGERMOTION:
                    ui_stick_move(pos)
                else:
                    ui_release(pid)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not state_menu:
                ui_press(event.pos, "mouse")
            elif event.type == pygame.MOUSEMOTION and _touch["stick"] == "mouse":
                ui_stick_move(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                ui_release("mouse")
            if (not state_menu) and event.type == pygame.KEYDOWN and event.key == pygame.K_F9:
                start_jumpscare(elapsed)
            if event.type == pygame.KEYDOWN and _prologue["active"]:
                if event.key == pygame.K_ESCAPE:
                    _prologue["active"] = False
                elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    advance_prologue()
            elif event.type == pygame.KEYDOWN and _ending["active"]:
                if _ending["t"] > 8.0:
                    _ending["active"] = False
                    states.clear()
                    total_collected = 0
                    chapter_end = False
                    current = "东风草原"
                    prepare("东风草原")
                    clear_dialogue()
                    menu_start = pygame.time.get_ticks()
                    play_music("menu")
                    state_menu = True
            elif (not state_menu) and event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                advance_dialogue()
            if state_menu and event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if 520 < mx < 760 and 300 < my < 350:
                    states.clear()
                    total_collected = 0
                    chapter_end = False
                    chapter_next = None
                    current = "东风草原"
                    prepare("东风草原")
                    play_music(current)
                    clear_dialogue()
                    start_prologue()
                    state_menu = False
                elif 520 < mx < 760 and 580 < my < 630:
                    pygame.quit()
                    return

        if _ui_menu_request:
            _ui_menu_request = False
            _ending["active"] = False
            states.clear()
            total_collected = 0
            chapter_end = False
            current = "东风草原"
            prepare("东风草原")
            clear_dialogue()
            menu_start = pygame.time.get_ticks()
            play_music("menu")
            state_menu = True

        if state_menu:
            draw_menu((pygame.time.get_ticks() - menu_start) / 1000.0)
            clock.tick(FPS)
            await asyncio.sleep(0)
            continue

        if _prologue["active"]:
            update_prologue(dt)
            draw_prologue()
            clock.tick(FPS)
            await asyncio.sleep(0)
            continue

        if _ending["active"]:
            _ending["t"] += dt
            draw_ending()
            clock.tick(FPS)
            await asyncio.sleep(0)
            continue

        if chapter_end:
            draw_chapter_end(current, chapter_next)
            clock.tick(FPS)
            await asyncio.sleep(0)
            continue

        if _js_state["active"]:
            draw_jumpscare(elapsed)
            pygame.display.flip()
            clock.tick(FPS)
            await asyncio.sleep(0)
            continue

        st = states[current]
        th = THEMES[current]
        blockers = st["blockers"]

        keys = pygame.key.get_pressed()
        mx = (1.0 if keys[pygame.K_d] else 0.0) - (1.0 if keys[pygame.K_a] else 0.0)
        my = (1.0 if keys[pygame.K_s] else 0.0) - (1.0 if keys[pygame.K_w] else 0.0)
        mx += _touch["vec"][0]
        my += _touch["vec"][1]
        ln = math.hypot(mx, my)
        if ln > 1.0:
            mx, my = mx / ln, my / ln
        _spd = player_speed * (dt * FPS)    # 60 帧基准；掉帧时按真实时间补足
        dx = mx * _spd
        dy = my * _spd

        px, py = st["px"], st["py"]

        nx = max(player_radius, min(MAP_W - player_radius, px + dx))
        rx = pygame.Rect(int(nx - player_radius), int(py - player_radius),
                         player_radius * 2, player_radius * 2)
        if not any(rx.colliderect(b) for b in blockers):
            px = nx

        ny = max(player_radius, min(MAP_H - player_radius, py + dy))
        ry = pygame.Rect(int(px - player_radius), int(ny - player_radius),
                         player_radius * 2, player_radius * 2)
        if not any(ry.colliderect(b) for b in blockers):
            py = ny

        if (dx or dy) and st.get("kind") in ("cellar", "depths"):
            st["facing"] = [dx, dy]

        st["px"], st["py"] = px, py

        for i, (fx, fy) in enumerate(st["flowers"]):
            if not st["collected"][i]:
                if (px - fx) ** 2 + (py - fy) ** 2 < (player_radius + PICK_RADIUS) ** 2:
                    st["collected"][i] = True
                    total_collected += 1
                    st["pick_fx"].append([fx, fy, elapsed])

        prec = pygame.Rect(int(px - player_radius), int(py - player_radius),
                           player_radius * 2, player_radius * 2)

        # 地窖：捡手电筒 → 摸发电机开机关门；两件事各配一次跳脸
        if st.get("kind") == "cellar":
            if not st["torch"]:
                tx0, ty0 = st["torch_pos"]
                if (px - tx0) ** 2 + (py - ty0) ** 2 < 40 ** 2:
                    st["torch"] = True
                    st["quest"] = "找到发电机 · 光只照得到前面一小片"
                    st["dlg_hl"] = elapsed + 2.2
                    start_jumpscare(elapsed)
            if not st["power"]:
                gr = st["gen_rect"]
                gdx = max(gr.left - px, 0.0, px - gr.right)
                gdy = max(gr.top - py, 0.0, py - gr.bottom)
                if gdx * gdx + gdy * gdy < 36 * 36:
                    st["power"] = True
                    st["gate_open"] = True
                    st["quest"] = "机关松脱口 · 大门在东北方向"
                    if st["gate_rect"] in st["blockers"]:
                        st["blockers"].remove(st["gate_rect"])
                    start_jumpscare(elapsed)

        for i, p in enumerate(st["portals"]):
            if not prec.colliderect(p["rect"]):
                st["armed"][i] = True

        target = None
        for i, p in enumerate(st["portals"]):
            if st["armed"][i] and prec.colliderect(p["rect"]):
                target = p["target"]
                break

        if target is not None:
            if target == "END":
                chapter_end = True
                chapter_next = p.get("next")
                try:
                    pygame.mixer.music.fadeout(1200)
                except Exception:
                    pass
            else:
                src = current
                if target not in states:
                    prepare(target, src)
                st_dst = states[target]
                for i, p in enumerate(st_dst["portals"]):
                    if p["target"] == src:
                        st_dst["armed"][i] = False
                current = target
                st_dst["dlg_t"] = 0.0
                clear_dialogue()
                play_music(target)

        update_dialogue(dt)
        st["dlg_t"] = st.get("dlg_t", 0.0) + dt
        update_level_dialogue(st, current, elapsed)

        if st.get("kind") == "depths":
            boss = st.get("boss")
            m4 = st["m4_rect"]
            ddx = max(m4.left - px, 0.0, px - m4.right)
            ddy = max(m4.top - py, 0.0, py - m4.bottom)
            near_door = ddx * ddx + ddy * ddy < 46 * 46
            if (not st["m4_touched"]) and near_door:
                st["m4_touched"] = True
                if total_collected >= 5:
                    start_boss(st, total_collected)
                else:
                    start_bad_short(st)
            if boss is not None and boss["phase"] in ("fight", "good", "bad", "bad0"):
                update_boss(st, dt, px, py)

        ox = max(0, min(MAP_W - SCREEN_WIDTH, int(st["px"] - SCREEN_WIDTH // 2)))
        oy = max(0, min(MAP_H - SCREEN_HEIGHT, int(st["py"] - SCREEN_HEIGHT // 2)))
        if st.get("kind") == "depths" and st.get("boss") and st["boss"]["phase"] != "done":
            arena = st["rooms"][-1]
            ox = max(0, min(MAP_W - SCREEN_WIDTH, arena.centerx - SCREEN_WIDTH // 2))
            oy = max(0, min(MAP_H - SCREEN_HEIGHT, arena.top - 80))

        # 地图大图不透明且大于屏幕，会完全盖住天际层：
        # 原来每帧先贴一遍天空是白费一次整屏拷贝，这里直接跳过。
        _surf_now = st["surface"]
        if not (_surf_now is not None
                and not (_surf_now.get_flags() & pygame.SRCALPHA)
                and _surf_now.get_width() >= SCREEN_WIDTH
                and _surf_now.get_height() >= SCREEN_HEIGHT):
            if st["sky"] is not None:
                screen.blit(st["sky"], (0, 0))
        if _surf_now is not None:
            screen.blit(_surf_now, (0, 0), pygame.Rect(ox, oy, SCREEN_WIDTH, SCREEN_HEIGHT))

        if th["mist"] and not IS_MOBILE:      # 手机端跳过全屏雾效：省一次整屏半透明拷贝
            mist.fill((0, 0, 0, 0))
            for mx, my, mrx, mry in th["mist"]:
                sx, sy = int(mx - ox * 0.85), int(my - oy * 0.85)
                pygame.draw.ellipse(mist, (214, 222, 220, 26),
                                    pygame.Rect(sx - mrx, sy - mry, mrx * 2, mry * 2))
            screen.blit(mist, (0, 0))

        if st.get("kind") == "water" and not IS_MOBILE:   # 手机端关掉水面闪光
            draw_water_shimmer(ox, oy, elapsed)

        for i, (fx, fy) in enumerate(st["flowers"]):
            if not st["collected"][i]:
                sx, sy = fx - ox, fy - oy
                if -40 < sx < SCREEN_WIDTH + 40 and -40 < sy < SCREEN_HEIGHT + 40:
                    draw_flower(screen, sx, sy, elapsed)

        # 拾取后的一点极轻涟漪：只做手感反馈，不解释发生了什么
        for item in st["pick_fx"]:
            age = elapsed - item[2]
            if age < 0.6:
                rad = int(10 + age * 70)
                alpha = max(0, int(120 * (1 - age / 0.6)))
                fx_s = int(item[0] - ox)
                fy_s = int(item[1] - oy)
                if alpha > 0:
                    ring = pygame.Surface((rad * 2 + 4, rad * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.circle(ring, (255, 255, 248, alpha),
                                       (rad + 2, rad + 2), rad, 2)
                    screen.blit(ring, (fx_s - rad - 2, fy_s - rad - 2))
        st["pick_fx"] = [it for it in st["pick_fx"] if elapsed - it[2] < 0.6]

        for leaf in st["leaves"]:
            leaf.update()
            leaf.draw(screen, ox, oy)

        # 地窖：门开之后的台阶、发电机灯光、地上的手电筒
        if st.get("kind") == "cellar":
            if st["gate_open"] and st["gate_open_surf"] is not None:
                gpos = st["gate_open_pos"]
                screen.blit(st["gate_open_surf"], (gpos[0] - ox, gpos[1] - oy))
            if st["power"]:
                gx0 = int(st["gen_rect"].centerx - ox)
                gy0 = int(st["gen_rect"].centery - oy)
                screen.blit(st["gen_glow"], (gx0 - 85, gy0 - 85))
            if not st["torch"]:
                tx0 = st["torch_pos"][0] - ox
                ty0 = st["torch_pos"][1] - oy
                if -40 < tx0 < SCREEN_WIDTH + 40 and -40 < ty0 < SCREEN_HEIGHT + 40:
                    pygame.draw.rect(screen, (122, 118, 104),
                                     (int(tx0) - 14, int(ty0) - 5, 28, 11), border_radius=4)
                    pygame.draw.rect(screen, (58, 54, 46),
                                     (int(tx0) - 14, int(ty0) - 5, 28, 11), 2, border_radius=4)
                    pygame.draw.circle(screen, (206, 212, 198),
                                       (int(tx0) + 9, int(ty0) - 3), 2)

        # 木院：站在昏暗房间时只留玩家周围一圈照明
        if st.get("kind") == "house":
            room_now = None
            for ri in st["rooms"]:
                if ri["rect"].collidepoint(px, py):
                    room_now = ri
                    break
            want = 0.0 if (room_now is None or room_now["lit"]) else 1.0
            st["veil"] = st["veil"] + (want - st["veil"]) * 0.12
            alpha = int(224 * st["veil"])
            if alpha > 6:
                _veil_render((5, 6, 11), alpha, [
                    (get_light_mask(), int(px - ox) - LIGHT_R, int(py - oy) - LIGHT_R),
                ])
        elif st.get("kind") == "cellar":
            # 一开始近乎全黑：只有玩家脚下一小圈；拿到手电筒后多出一片扇形；
            # 发电机一响，整片泥土才浮出来
            target_a = 62.0 if st["power"] else (206.0 if st["torch"] else 246.0)
            st["veil_a"] += (target_a - st["veil_a"]) * 0.06
            alpha = int(st["veil_a"])
            if alpha > 4:
                r_c = 150 if st["torch"] else 126
                holes = [(get_circle_mask(r_c), int(px - ox) - r_c, int(py - oy) - r_c)]
                if st["torch"]:
                    fx, fy = st["facing"]
                    ang = math.degrees(math.atan2(-fy, fx))
                    key_c = int(round(ang / 45.0)) % 8
                    cone = get_cone_mask(key_c)
                    cone_rect = cone.get_rect(center=(int(px - ox), int(py - oy)))
                    holes.append((cone, cone_rect.topleft[0], cone_rect.topleft[1]))
                if st["power"]:
                    gx0 = int(st["gen_rect"].centerx - ox)
                    gy0 = int(st["gen_rect"].centery - oy)
                    holes.append((get_circle_mask(190), gx0 - 190, gy0 - 190))
                _veil_render((4, 5, 7), alpha, holes)
        elif st.get("kind") == "depths":
            boss_now = st.get("boss")
            if boss_now is None or boss_now["phase"] == "done":
                st["veil_a"] += (176.0 - st["veil_a"]) * 0.06
                alpha = int(st["veil_a"])
                if alpha > 4:
                    r_c = 152
                    holes = [(get_circle_mask(r_c), int(px - ox) - r_c, int(py - oy) - r_c)]
                    fx, fy = st["facing"]
                    ang = math.degrees(math.atan2(-fy, fx))
                    k2 = int(round(ang / 45.0)) % 8
                    cone = get_cone_mask(k2)
                    cr = cone.get_rect(center=(int(px - ox), int(py - oy)))
                    holes.append((cone, cr.topleft[0], cr.topleft[1]))
                    _veil_render((4, 4, 6), alpha, holes)

        # 玩家：无脸小人；上下移动时切换正面/后脑，走路时手脚交替
        _moving = bool(dx or dy)
        if _moving:
            if my > 0.3:
                st["pf"] = True
            elif my < -0.3:
                st["pf"] = False
        _pfront = st.get("pf", True)
        _pstep = (int(elapsed * 7) % 2) if _moving else 0
        _pspr = get_player_sprite(_pfront, _pstep)
        screen.blit(_pspr, (int(px - ox) - PLAYER_SPR_W // 2,
                            int(py - oy) - PLAYER_SPR_H // 2))

        if st.get("kind") == "depths":
            draw_boss_body(st, ox, oy, elapsed)
            # 弹幕必须画在黑暗层之前：二阶段视野受限时，
            # 远处弹幕只留一点点暗红微光，出圈就看不见。
            draw_boss_bullets(st, ox, oy)
            draw_boss_veil(st, px, py, ox, oy)

        for p in st["portals"]:
            ex, ey = p["rect"].x - ox, p["rect"].y - oy
            if -220 < ex < SCREEN_WIDTH + 220 and -220 < ey < SCREEN_HEIGHT + 220:
                ly = ey - 30 if p.get("style") in ("door", "hatch", "stairs") else ey + 4
                lab = font_small.render(p["label"], True, (250, 248, 238))
                shadow = font_small.render(p["label"], True, (18, 16, 14))
                screen.blit(shadow, (ex + 11, ly + 1))
                screen.blit(lab, (ex + 10, ly))

        # 只报地图名，不报白花、不报收集数
        line1 = font_mid.render(current, True, (255, 255, 245))
        pw = line1.get_width() + 34
        panel = pygame.Surface((pw, 52), pygame.SRCALPHA)
        pygame.draw.rect(panel, (10, 10, 12, 150), panel.get_rect(), border_radius=10)
        screen.blit(panel, (14, 12))
        screen.blit(line1, (30, 20))

        if st.get("kind") in ("cellar", "depths"):
            qs = font_small.render(st["quest"], True, (244, 234, 216))
            qp = pygame.Surface((qs.get_width() + 28, 38), pygame.SRCALPHA)
            pygame.draw.rect(qp, (10, 10, 12, 140), qp.get_rect(), border_radius=9)
            screen.blit(qp, (14, 66))
            screen.blit(qs, (28, 72))

        if SHOW_FPS:
            _fps_txt = "FPS %d" % int(clock.get_fps())
            _fps_s = font_small.render(_fps_txt, True, (255, 240, 200))
            screen.blit(_fps_s, (SCREEN_WIDTH - _fps_s.get_width() - 12, 10))

        draw_touch_ui()

        if st.get("kind") == "depths":
            draw_boss_hud(st)
        _lift = 96 if (st.get("boss") and st["boss"]["phase"] in ("fight", "good")) else 0
        _dlg_lift_local(_lift)
        draw_dialogue(elapsed)

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(main())

"""
FILMN9 전체 아키텍처 - Excalidraw JSON 생성기
출력: outputs/FILMN9_excalidraw.json  (excalidraw.com 에서 Import 가능)
"""
import json
import random
import string
from pathlib import Path

random.seed(42)

# ── 캔버스 레이아웃 상수 ────────────────────────────────────────────
LAYER_X   = 50
LAYER_W   = 2100
LAYER_H   = 210
LAYER_GAP = 35
START_Y   = 80

LAYER_COLORS = [
    ("#c0392b", "#fdf2f0"),  # L0 External APIs  - 빨강
    ("#2980b9", "#eaf4fc"),  # L1 .py 파일        - 파랑
    ("#8e44ad", "#f5eef8"),  # L2 Git             - 보라
    ("#27ae60", "#eafaf1"),  # L3 AWS Storage     - 초록
    ("#16a085", "#e8f8f5"),  # L4 EC2 Backend     - 청록
    ("#2471a3", "#eaf2f8"),  # L5 Frontend        - 남색
    ("#6c3483", "#f4ecf7"),  # L6 User Screens    - 자주
]
LAYER_LABELS = [
    "Layer 1: External APIs  (외부 데이터 소스)",
    "Layer 2: .py 파일  (팀별 수집·처리 코드)",
    "Layer 3: Git  (버전 관리 & CI/CD)",
    "Layer 4: AWS Storage  (데이터 저장)",
    "Layer 5: EC2 Backend  (API 서버)",
    "Layer 6: Frontend  (S3 + CloudFront)",
    "Layer 7: User Screens  (최종 화면)",
]

# ── Arrow 색상 ──────────────────────────────────────────────────────
C_DATA   = "#e67e22"  # orange  데이터 흐름
C_CODE   = "#3498db"  # blue    코드 Push
C_DEPLOY = "#27ae60"  # green   CI/CD 배포
C_API    = "#8e44ad"  # purple  API 호출
C_UI     = "#16a085"  # teal    화면 렌더

els: list[dict] = []


# ── 기본 요소 생성 헬퍼 ─────────────────────────────────────────────
def _rid() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _base(eid: str, etype: str) -> dict:
    return {
        "id": eid, "type": etype, "angle": 0, "groupIds": [], "frameId": None,
        "seed": random.randint(1, 999999), "version": 1,
        "versionNonce": random.randint(1, 999999),
        "isDeleted": False, "updated": 1, "link": None, "locked": False,
        "strokeStyle": "solid", "fillStyle": "solid", "roughness": 0, "opacity": 100,
    }


def add_rect(x, y, w, h, stroke, bg, opacity=100, rounded=True):
    eid = _rid()
    e = {
        **_base(eid, "rectangle"),
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": stroke, "backgroundColor": bg,
        "strokeWidth": 2, "opacity": opacity,
        "roundness": {"type": 3} if rounded else None,
        "boundElements": [],
    }
    els.append(e)
    return eid


def add_text(x, y, w, h, text, font_size, color, align="center", family=2):
    eid = _rid()
    e = {
        **_base(eid, "text"),
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": color, "backgroundColor": "transparent", "strokeWidth": 1,
        "text": text, "originalText": text,
        "fontSize": font_size, "fontFamily": family,
        "textAlign": align, "verticalAlign": "middle",
        "containerId": None, "lineHeight": 1.25,
        "roundness": None, "boundElements": None,
    }
    els.append(e)
    return eid


def add_arrow(x1, y1, x2, y2, color="#666666", sw=2):
    eid = _rid()
    dx, dy = x2 - x1, y2 - y1
    e = {
        **_base(eid, "arrow"),
        "x": x1, "y": y1, "width": abs(dx), "height": abs(dy),
        "points": [[0, 0], [dx, dy]],
        "strokeColor": color, "backgroundColor": "transparent",
        "strokeWidth": sw,
        "startBinding": None, "endBinding": None,
        "lastCommittedPoint": None,
        "startArrowhead": None, "endArrowhead": "arrow",
        "roundness": {"type": 2}, "boundElements": [], "elbowed": False,
    }
    els.append(e)


# ── 레이어 배경 + 레이블 ───────────────────────────────────────────
def add_layer_bg(li: int):
    sc, bg = LAYER_COLORS[li]
    y = START_Y + li * (LAYER_H + LAYER_GAP)
    add_rect(LAYER_X, y, LAYER_W, LAYER_H, sc, bg, opacity=28)
    add_text(LAYER_X + 14, y + 7, 800, 22, LAYER_LABELS[li], 13, sc, align="left")


# ── 컴포넌트 박스 ─────────────────────────────────────────────────
def add_box(li: int, col: int, total: int, label: str,
            sub: str = "", bw: int = 185, bh: int = 90) -> tuple[float, float]:
    """레이어 li, col번째 위치에 박스를 추가. 중심점 (cx, cy) 반환."""
    sc, bg = LAYER_COLORS[li]
    layer_y = START_Y + li * (LAYER_H + LAYER_GAP)
    usable = LAYER_W - 80
    cw = usable / total
    x = LAYER_X + 40 + col * cw + (cw - bw) / 2
    y = layer_y + (LAYER_H - bh) / 2

    add_rect(x, y, bw, bh, sc, bg)
    full = label + ("\n" + sub if sub else "")
    fs = 12 if len(label) <= 14 else 11
    th = 40 if sub else 22
    add_text(x + 5, y + (bh - th) / 2, bw - 10, th, full, fs, "#1a1a1a")
    return x + bw / 2, y + bh / 2


# ─────────────────────────────────────────────────────────────────
# 레이어별 박스 생성
# ─────────────────────────────────────────────────────────────────

# Layer 0: External APIs
add_layer_bg(0)
l0 = [add_box(0, i, 5, lbl, sub) for i, (lbl, sub) in enumerate([
    ("DART API",      "공시·기업정보"),
    ("yfinance",      "주가·PER·PBR"),
    ("Naver Finance", "외국인보유율"),
    ("OpenAI API",    "텍스트 임베딩"),
    ("KRX",           "시장 데이터"),
])]

# Layer 1: .py 파일 (팀별)
add_layer_bg(1)
l1 = [add_box(1, i, 8, lbl, sub, bw=160) for i, (lbl, sub) in enumerate([
    ("수집.py",       "팀원1·DART"),
    ("처리.py",       "팀원1·파서"),
    ("주가수집.py",   "팀원2"),
    ("재무집계.py",   "팀원2"),
    ("임베딩.py",     "팀원3"),
    ("RAG검색.py",    "팀원3"),
    ("html_builder",  "팀원4"),
    ("batch_save.py", "팀원4"),
])]

# Layer 2: Git
add_layer_bg(2)
l2 = [add_box(2, i, 3, lbl, sub, bw=220) for i, (lbl, sub) in enumerate([
    ("GitHub Repo",    "소스코드 저장"),
    ("GitHub Actions", "CI/CD 자동화"),
    ("Git LFS",        "대용량 파일"),
])]

# Layer 3: AWS Storage
add_layer_bg(3)
l3 = [add_box(3, i, 4, lbl, sub, bw=220) for i, (lbl, sub) in enumerate([
    ("S3 (JSONL)", "공시 청크 저장"),
    ("S3 (벡터)",  "임베딩 벡터"),
    ("MongoDB",    "기업 메타데이터"),
    ("Redis",      "캐시·세션"),
])]

# Layer 4: EC2 Backend
add_layer_bg(4)
l4 = [add_box(4, i, 5, lbl, sub, bw=190) for i, (lbl, sub) in enumerate([
    ("Nginx",         "리버스 프록시"),
    ("FastAPI",       "백엔드 서버"),
    ("/api/company",  "기업정보 EP"),
    ("/api/stock",    "주가 EP"),
    ("/api/search",   "RAG 검색 EP"),
])]

# Layer 5: Frontend
add_layer_bg(5)
l5 = [add_box(5, i, 4, lbl, sub, bw=220) for i, (lbl, sub) in enumerate([
    ("CloudFront",    "CDN 배포"),
    ("S3 (정적)",     "React 빌드"),
    ("React/Next.js", "프론트엔드"),
    ("v0.dev",        "UI 컴포넌트 생성"),
])]

# Layer 6: User Screens
add_layer_bg(6)
l6 = [add_box(6, i, 3, lbl, sub, bw=240) for i, (lbl, sub) in enumerate([
    ("기업개요 탭",   "재무·주가 정보"),
    ("밸류에이션 탭", "DCF·배수 분석"),
    ("RAG 검색 탭",   "AI 질의응답"),
])]


# ─────────────────────────────────────────────────────────────────
# 화살표
# ─────────────────────────────────────────────────────────────────
VPAD = 46  # 박스 상하 여백 (중심 → 엣지)

# L0 -> L1 (데이터 흐름)
add_arrow(l0[0][0], l0[0][1]+VPAD, l1[0][0], l1[0][1]-VPAD, C_DATA)   # DART -> 수집.py
add_arrow(l0[1][0], l0[1][1]+VPAD, l1[2][0], l1[2][1]-VPAD, C_DATA)   # yfinance -> 주가수집.py
add_arrow(l0[2][0], l0[2][1]+VPAD, l1[2][0], l1[2][1]-VPAD, C_DATA)   # Naver -> 주가수집.py
add_arrow(l0[3][0], l0[3][1]+VPAD, l1[4][0], l1[4][1]-VPAD, C_DATA)   # OpenAI -> 임베딩.py
add_arrow(l0[4][0], l0[4][1]+VPAD, l1[2][0], l1[2][1]-VPAD, C_DATA)   # KRX -> 주가수집.py

# L1 -> L2 (코드 Push)
add_arrow(l1[0][0], l1[0][1]+VPAD, l2[0][0], l2[0][1]-VPAD, C_CODE)
add_arrow(l1[4][0], l1[4][1]+VPAD, l2[0][0], l2[0][1]-VPAD, C_CODE)
add_arrow(l1[6][0], l1[6][1]+VPAD, l2[0][0], l2[0][1]-VPAD, C_CODE)

# L1 -> L3 (데이터 저장)
add_arrow(l1[0][0], l1[0][1]+VPAD, l3[0][0], l3[0][1]-VPAD, C_DATA)   # 수집.py -> S3 JSONL
add_arrow(l1[4][0], l1[4][1]+VPAD, l3[1][0], l3[1][1]-VPAD, C_DATA)   # 임베딩.py -> S3 벡터
add_arrow(l1[2][0], l1[2][1]+VPAD, l3[2][0], l3[2][1]-VPAD, C_DATA)   # 주가수집.py -> MongoDB

# L2 -> L3, L4 (CI/CD 배포)
add_arrow(l2[1][0], l2[1][1]+VPAD, l3[0][0], l3[0][1]-VPAD, C_DEPLOY)
add_arrow(l2[1][0], l2[1][1]+VPAD, l4[1][0], l4[1][1]-VPAD, C_DEPLOY)

# L3 -> L4 (스토리지 -> 백엔드)
add_arrow(l3[0][0], l3[0][1]+VPAD, l4[1][0], l4[1][1]-VPAD, C_DATA)
add_arrow(l3[2][0], l3[2][1]+VPAD, l4[1][0], l4[1][1]-VPAD, C_DATA)
add_arrow(l3[3][0], l3[3][1]+VPAD, l4[1][0], l4[1][1]-VPAD, C_DATA)

# L4 내부: Nginx -> FastAPI -> 엔드포인트
add_arrow(l4[0][0]+96, l4[0][1], l4[1][0]-96, l4[1][1], "#555555")
add_arrow(l4[1][0]+96, l4[1][1], l4[2][0]-96, l4[2][1], "#555555")

# L4 -> L5 (API -> 프론트)
add_arrow(l4[1][0], l4[1][1]+VPAD, l5[2][0], l5[2][1]-VPAD, C_API)

# L5 내부: v0.dev -> React
add_arrow(l5[3][0]-110, l5[3][1], l5[2][0]+110, l5[2][1], "#8e44ad")

# L5 -> L6 (렌더 -> 화면)
add_arrow(l5[0][0], l5[0][1]+VPAD, l6[0][0], l6[0][1]-VPAD, C_UI)
add_arrow(l5[2][0], l5[2][1]+VPAD, l6[1][0], l6[1][1]-VPAD, C_UI)
add_arrow(l5[2][0], l5[2][1]+VPAD, l6[2][0], l6[2][1]-VPAD, C_UI)


# ─────────────────────────────────────────────────────────────────
# 범례 (Legend)
# ─────────────────────────────────────────────────────────────────
lx = LAYER_X + LAYER_W + 40
ly = START_Y
add_rect(lx, ly, 230, 200, "#333333", "#f5f5f5", rounded=True)
add_text(lx + 10, ly + 8, 210, 22, "범례 (Legend)", 14, "#333333", align="left")
for fi, (color, label) in enumerate([
    (C_DATA,   "데이터 흐름"),
    (C_CODE,   "코드 Push"),
    (C_DEPLOY, "CI/CD 배포"),
    (C_API,    "API 호출"),
    (C_UI,     "화면 렌더"),
]):
    fy = ly + 38 + fi * 30
    add_rect(lx + 14, fy + 4, 34, 14, color, color, rounded=True)
    add_text(lx + 56, fy, 165, 22, label, 12, "#333333", align="left")


# ─────────────────────────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────────────────────────
out = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": els,
    "appState": {
        "gridSize": None,
        "viewBackgroundColor": "#f8f9fa",
    },
    "files": {},
}

out_path = Path(__file__).parent / "outputs" / "FILMN9_excalidraw.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"[OK] Saved: {out_path}")
print(f"Total elements: {len(els)}")

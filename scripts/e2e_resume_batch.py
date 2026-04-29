"""
End-to-end автотест IBA Content Editor: загружает 8 файлов, шлёт WS chat,
собирает ответы по батчам, проверяет качество.

Запуск:
  python/venv/bin/python scripts/e2e_resume_batch.py

Бэкенд должен слушать на 127.0.0.1:8765.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx
import websockets

API = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765/ws"
AGENT_ID = "5fb49e3f-a38c-4b55-b452-725ea5add0a6"

FILES = [
    "Kazyna Zeilbek резюме.pdf",
    "Middle Frontend Developer.pdf",
    "PAVEL_TYO_CV.pdf",
    "PAVEL_TYO_CV.html",
    "PAVEL_TYO_CV_EN.pdf",
    "CV_Vyacheslav ZUYENOK _20.03.2026_RUS.docx",
    "Kairat Aidarbekov_CV.pdf",
    "Резюме тренера_Есимсейтова.pdf",
]

# What we expect to see / NOT see for each file
EXPECTATIONS = {
    "Kazyna Zeilbek резюме.pdf": {
        "must_contain": ["Казына", "Зеилбек"],
        "must_not_contain": ["**", "##", "KAZYNA", "ZEILBEK"],
    },
    "Middle Frontend Developer.pdf": {
        "must_contain": ["вакансия"],
        "must_not_contain": ["Имя", "Опыт работы:"],
    },
    "PAVEL_TYO_CV.pdf": {
        "must_contain": ["Тё"],
        "must_not_contain": ["**", "##", "Тио", "Алматинский Университет Энергетики"],
    },
    "PAVEL_TYO_CV.html": {
        "must_contain": ["Тё"],
        "must_not_contain": ["**", "##", "<", "Тио", "вакансия"],
    },
    "PAVEL_TYO_CV_EN.pdf": {
        "must_contain": ["Тё"],
        "must_not_contain": ["**", "##", "Тио", "WORK EXPERIENCE", "EDUCATION"],
    },
    "CV_Vyacheslav ZUYENOK _20.03.2026_RUS.docx": {
        "must_contain": ["Зу"],
        "must_not_contain": ["**", "##", "ДатаКор", "Toptal", "Netcracker", "Softline"],
    },
    "Kairat Aidarbekov_CV.pdf": {
        "must_contain": ["Айдарбеков", "Опыт работы"],
        "must_not_contain": ["**", "##"],
    },
    "Резюме тренера_Есимсейтова.pdf": {
        "must_contain": ["Есимсейтова"],
        "must_not_contain": ["**", "##"],
    },
}


async def upload_file(client: httpx.AsyncClient, path: Path) -> str:
    with open(path, "rb") as f:
        r = await client.post(
            f"{API}/upload",
            files={"file": (path.name, f, "application/octet-stream")},
            timeout=60,
        )
    r.raise_for_status()
    return r.json()["path"]


async def run_chat(file_paths: list[str]) -> list[str]:
    """Send a chat msg with all files, collect assistant message bubbles
    (one per batch). Returns list of bubble strings."""
    content = "\n".join(f"@file:{p}" for p in file_paths)
    async with websockets.connect(WS, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "chat",
            "content": content,
            "agent_id": AGENT_ID,
        }))
        bubbles: list[str] = []
        current = []
        in_msg = False
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=600)
            except asyncio.TimeoutError:
                print("[timeout — stream stuck >10min]")
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            role = msg.get("role")
            if t == "done":
                if in_msg:
                    bubbles.append("".join(current))
                break
            if t == "message" and role == "assistant":
                if msg.get("start"):
                    if in_msg and current:
                        bubbles.append("".join(current))
                    current = []
                    in_msg = True
                elif msg.get("end"):
                    bubbles.append("".join(current))
                    current = []
                    in_msg = False
                elif msg.get("content"):
                    current.append(msg["content"])
            elif t == "error":
                print(f"[backend error: {msg.get('content')}]")
                break
        return bubbles


def check_bubble(filename: str, bubble: str) -> tuple[bool, list[str]]:
    exp = EXPECTATIONS.get(filename)
    if not exp:
        return True, []
    issues = []
    for needle in exp.get("must_contain", []):
        if needle.lower() not in bubble.lower():
            issues.append(f"missing '{needle}'")
    for needle in exp.get("must_not_contain", []):
        if needle.lower() in bubble.lower():
            issues.append(f"contains forbidden '{needle}'")
    return (len(issues) == 0), issues


async def main():
    # Source canonical CV files from the Telegram folder (the originals
    # Dias actually shared). /tmp/dialekt_files is the upload sink and
    # accumulates timestamp-prefixed copies that drift apart from the
    # source over multiple test runs.
    src_dir = Path("/home/dias/Загрузки/Telegram Desktop")
    file_paths: list[str] = []
    for fname in FILES:
        candidate = src_dir / fname
        if not candidate.exists():
            print(f"[skip] not found: {candidate}")
            continue
        async with httpx.AsyncClient() as client:
            uploaded = await upload_file(client, candidate)
            file_paths.append(uploaded)
            print(f"  uploaded: {Path(uploaded).name}")

    print(f"\nSending chat with {len(file_paths)} files to agent {AGENT_ID[:8]}...\n")
    bubbles = await run_chat(file_paths)

    print(f"\n=== Got {len(bubbles)} response bubbles ===\n")
    out_dir = Path("/tmp/dialekt-dev/e2e_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    pass_count = 0
    for i, fname in enumerate(FILES):
        bubble = bubbles[i] if i < len(bubbles) else ""
        out_dir.joinpath(f"{i+1:02d}_{fname.replace('/','_')}.txt").write_text(bubble)
        ok, issues = check_bubble(fname, bubble)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {i+1}. {fname[:50]}")
        if not ok:
            for issue in issues:
                print(f"        - {issue}")
            print(f"        first 200: {bubble[:200].strip()!r}")
        else:
            pass_count += 1

    print(f"\n=== {pass_count}/{len(FILES)} passed ===")
    print(f"Full bubble text saved to {out_dir}/")


if __name__ == "__main__":
    asyncio.run(main())

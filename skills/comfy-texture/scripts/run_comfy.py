#!/usr/bin/env python3
"""ComfyUI の API 形式ワークフローを実行し、出力画像をフォルダに保存する。

標準ライブラリだけで動く（追加インストール不要）。

使い方の例:
  # ワークフローの中身（ノードID・タイトル・変更できる値）を一覧表示
  python run_comfy.py workflows/tileable_pbr_api.json --list

  # プロンプトとseedを変えて実行し、結果を textures/oak_planks に保存
  python run_comfy.py workflows/tileable_pbr_api.json \
      --prompt "weathered oak wooden planks, top-down, flat even lighting, seamless texture" \
      --seed random --out textures/oak_planks --prefix oak_planks

  # 任意のノードの値を直接変える（ノードID.入力名=値）
  python run_comfy.py workflow_api.json --set 13.width=2048 --set 13.height=2048

  # ワークフローを組むための情報を取る（ワークフロー不要）
  python run_comfy.py --node-info SeamlessTile MakeCircularVAE OffsetImage
  python run_comfy.py --models checkpoints
"""

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_PORTS = (8188, 8000)  # インストール方法によってどちらかで待ち受けている
SEED_KEYS = ("seed", "noise_seed")
# ローカルの ComfyUI に直接つなぐため、Windows のプロキシ設定を経由しない
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _setup_utf8_output():
    # Windows で出力をパイプしたときの文字化け・エンコードエラーを防ぐ
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def fail(message, code=1):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    sys.exit(code)


def http_json(url, payload=None, timeout=15):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_bytes(url, timeout=60):
    with _OPENER.open(url, timeout=timeout) as resp:
        return resp.read()


def find_server(explicit):
    candidates = [explicit] if explicit else [f"127.0.0.1:{p}" for p in DEFAULT_PORTS]
    for cand in candidates:
        try:
            http_json(f"http://{cand}/system_stats", timeout=3)
            return cand
        except (urllib.error.URLError, OSError, ValueError):
            continue
    fail(
        "ComfyUI に接続できません。ComfyUI を起動してから再実行してください。"
        f" 試した接続先: {', '.join(candidates)}（--server host:port で指定可）"
    )


def load_workflow(path):
    p = Path(path)
    if not p.exists():
        fail(f"ワークフローが見つかりません: {p}")
    wf = json.loads(p.read_text(encoding="utf-8"))
    # UI 形式（Ctrl+S で保存したもの）は "nodes" 配列を持つ。API 形式はノードIDがキー。
    if isinstance(wf, dict) and "nodes" in wf and isinstance(wf["nodes"], list):
        fail(
            "これは UI 形式のワークフローです。ComfyUI の「ファイル → Export Workflow (API)」"
            "で書き出した API 形式の JSON を使ってください。"
        )
    if not isinstance(wf, dict) or not all(isinstance(v, dict) and "class_type" in v for v in wf.values()):
        fail("API 形式のワークフローとして読み込めませんでした。")
    return wf


def title_of(node):
    return node.get("_meta", {}).get("title") or node.get("class_type", "node")


def list_workflow(wf):
    rows = []
    for nid, node in sorted(wf.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]):
        editable = {
            k: v for k, v in node.get("inputs", {}).items()
            if not (isinstance(v, list) and len(v) == 2 and isinstance(v[1], int))  # リンク（他ノードとの接続）は除外
        }
        rows.append({"id": nid, "class_type": node["class_type"], "title": title_of(node), "values": editable})
    print(json.dumps({"ok": True, "nodes": rows}, ensure_ascii=False, indent=2))


def parse_value(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def apply_set(wf, spec):
    key, sep, raw = spec.partition("=")
    node_id, dot, input_name = key.partition(".")
    if not sep or not dot or node_id not in wf or not input_name:
        fail(f"--set の指定が不正です: {spec}（形式: ノードID.入力名=値）")
    wf[node_id].setdefault("inputs", {})[input_name] = parse_value(raw)


def set_text_by_title(wf, title, text, label):
    targets = [nid for nid, n in wf.items() if title_of(n) == title and "text" in n.get("inputs", {})]
    if not targets:
        candidates = [
            f"{nid}: {title_of(n)}" for nid, n in wf.items() if "text" in n.get("inputs", {})
        ]
        fail(
            f"{label} を入れるノード（タイトル「{title}」）が見つかりません。"
            f" text を持つノード: {candidates}。--prompt-title / --negative-title か --set で指定してください。"
        )
    for nid in targets:
        wf[nid]["inputs"]["text"] = text
    return targets


def set_seeds(wf, seed_arg):
    seed = random.randint(0, 2**32 - 1) if seed_arg == "random" else int(seed_arg)
    changed = []
    for nid, node in wf.items():
        for key in SEED_KEYS:
            if isinstance(node.get("inputs", {}).get(key), int):
                node["inputs"][key] = seed
                changed.append(f"{nid}.{key}")
    return seed, changed


def submit(server, wf, client_id):
    try:
        resp = http_json(f"http://{server}/prompt", {"prompt": wf, "client_id": client_id}, timeout=30)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = body
        fail(f"ワークフローの送信でエラー（HTTP {e.code}）: {json.dumps(detail, ensure_ascii=False)}")
    if resp.get("node_errors"):
        fail(f"ノードの設定エラー: {json.dumps(resp['node_errors'], ensure_ascii=False)}")
    return resp["prompt_id"]


def wait_for(server, prompt_id, timeout):
    start = time.time()
    while time.time() - start < timeout:
        try:
            hist = http_json(f"http://{server}/history/{prompt_id}", timeout=15)
        except (urllib.error.URLError, OSError):
            hist = {}
        entry = hist.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                fail(f"実行中にエラー: {json.dumps(status.get('messages', []), ensure_ascii=False)[:2000]}")
            if status.get("completed", True):
                return entry
        time.sleep(1.5)
    fail(f"{timeout} 秒待っても終わりませんでした（--timeout で延長できます）。prompt_id={prompt_id}")


def safe_name(text):
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_") or "image"


def download_outputs(server, wf, entry, out_dir, prefix):
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for nid, output in entry.get("outputs", {}).items():
        images = output.get("images", [])
        node_title = title_of(wf.get(nid, {"class_type": f"node{nid}"}))
        for i, img in enumerate(images):
            params = urllib.parse.urlencode({
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            })
            data = http_bytes(f"http://{server}/view?{params}")
            ext = Path(img["filename"]).suffix or ".png"
            suffix = f"_{i + 1}" if len(images) > 1 else ""
            name = f"{safe_name(prefix)}_{safe_name(node_title)}{suffix}{ext}" if prefix else f"{safe_name(node_title)}{suffix}{ext}"
            path = out_dir / name
            path.write_bytes(data)
            saved.append({
                "node_id": nid,
                "title": node_title,
                "kind": "preview" if img.get("type") == "temp" else "saved",
                "path": str(path.resolve()),
            })
    return saved


def main():
    _setup_utf8_output()
    ap = argparse.ArgumentParser(description="ComfyUI の API 形式ワークフローを実行して出力画像を保存する")
    ap.add_argument("workflow", nargs="?", help="API 形式のワークフロー JSON（Export Workflow (API) で書き出したもの）")
    ap.add_argument("--list", action="store_true", help="ノード一覧と変更できる値を表示して終了")
    ap.add_argument("--node-info", nargs="+", metavar="CLASS", help="ノードの仕様（入力名・型・選択肢・出力）を ComfyUI から取得して表示（ワークフロー不要）")
    ap.add_argument("--models", metavar="FOLDER", help="ComfyUI に入っているモデル一覧を表示（例: checkpoints）。ワークフロー不要")
    ap.add_argument("--prompt", help="ポジティブプロンプト（タイトルが --prompt-title のノードに入れる）")
    ap.add_argument("--prompt-title", default="Positive Prompt")
    ap.add_argument("--negative", help="ネガティブプロンプト（タイトルが --negative-title のノードに入れる）")
    ap.add_argument("--negative-title", default="Negative Prompt")
    ap.add_argument("--seed", help="seed の値。random でランダム")
    ap.add_argument("--set", action="append", default=[], metavar="ID.INPUT=VALUE", help="任意の値を上書き（複数可）")
    ap.add_argument("--out", default="comfy_outputs", help="保存先フォルダ")
    ap.add_argument("--prefix", default="", help="保存ファイル名の先頭につける名前（素材名など）")
    ap.add_argument("--server", help="host:port（省略時は 127.0.0.1 の 8188 → 8000 を自動で探す）")
    ap.add_argument("--timeout", type=int, default=900, help="完了を待つ最大秒数")
    args = ap.parse_args()

    if args.node_info or args.models:
        server = find_server(args.server)
        result = {"ok": True, "server": server}
        if args.node_info:
            info = {}
            for name in args.node_info:
                try:
                    data = http_json(f"http://{server}/object_info/{urllib.parse.quote(name)}", timeout=30)
                except urllib.error.HTTPError as e:
                    data = {}
                info[name] = data.get(name, "見つかりません（カスタムノード未インストール、または名前違い）")
            result["node_info"] = info
        if args.models:
            try:
                result["models"] = {args.models: http_json(f"http://{server}/models/{urllib.parse.quote(args.models)}", timeout=30)}
            except urllib.error.HTTPError as e:
                fail(f"モデル一覧を取得できませんでした（HTTP {e.code}）。フォルダ名を確認してください。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not args.workflow:
        ap.error("ワークフローの JSON を指定してください")
    wf = load_workflow(args.workflow)
    if args.list:
        list_workflow(wf)
        return

    changes = {}
    if args.prompt is not None:
        changes["prompt_nodes"] = set_text_by_title(wf, args.prompt_title, args.prompt, "プロンプト")
    if args.negative is not None:
        changes["negative_nodes"] = set_text_by_title(wf, args.negative_title, args.negative, "ネガティブプロンプト")
    if args.seed is not None:
        changes["seed"], changes["seed_inputs"] = set_seeds(wf, args.seed)
    for spec in args.set:
        apply_set(wf, spec)

    server = find_server(args.server)
    started = time.time()
    prompt_id = submit(server, wf, str(uuid.uuid4()))
    entry = wait_for(server, prompt_id, args.timeout)
    saved = download_outputs(server, wf, entry, Path(args.out), args.prefix)
    if not saved:
        fail("実行は終わりましたが、画像の出力が見つかりませんでした（Save Image / Preview Image ノードがあるか確認）。")

    print(json.dumps({
        "ok": True,
        "server": server,
        "prompt_id": prompt_id,
        "seconds": round(time.time() - started, 1),
        "changes": changes,
        "files": saved,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

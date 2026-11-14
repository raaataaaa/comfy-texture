---
name: comfy-texture
description: ローカルのComfyUIでシームレスなテクスチャとPBRマップ（basecolor/normal/roughness/metalness/height）を生成し、必要ならBlenderのマテリアルに設定する。「〜のテクスチャを作って」「素材を作って貼って」「PBRマテリアルを生成して」「tileable texture」などの依頼で使う。
---

# ComfyUI テクスチャ生成

ローカルで動いている ComfyUI に、完成済みのワークフロー（API 形式）を「プロンプトと seed だけ変えて」流し、
できた画像をプロジェクトのフォルダに保存する。ワークフローは毎回組み立てず、必ずこのフォルダのものを使う。

以下、このスキルのフォルダを `SKILL_DIR` と書く（SKILL.md があるフォルダ）。

## 前提チェック（最初に1回）

1. `SKILL_DIR/workflows/tileable_pbr_api.json` があるか確認する。無ければ、下の
   「ワークフローを作る」の手順で自分で作る。
2. ワークフローの中身を確認する:
   ```
   python "SKILL_DIR/scripts/run_comfy.py" "SKILL_DIR/workflows/tileable_pbr_api.json" --list
   ```
   - タイトルが `Positive Prompt` / `Negative Prompt` のノードがあるか
   - 出力ノード（Save Image）のタイトル（basecolor, normal など）を覚えておく
   - ComfyUI に接続できないエラーが出たら、ComfyUI を起動してもらうよう伝えて待つ

## 生成の手順

1. **素材ごとにプロンプトを作る**（英語。1回の実行で1素材だけ）
   - 型: `<素材の具体的な説明>, top-down orthographic view, flat even diffuse lighting, no shadows, seamless tileable texture, highly detailed surface`
   - 例: `weathered dark oak wooden planks with nail holes and grain, top-down orthographic view, flat even diffuse lighting, no shadows, seamless tileable texture, highly detailed surface`
   - ネガティブ: `perspective, vanishing point, cast shadow, specular highlight, objects, border, frame, text, watermark, vignette, blurry`
   - 写真っぽい素材は「どんな状態か」（古さ・汚れ・湿り気・色味）を具体的に書く

2. **実行する**（保存先はユーザーのプロジェクト内の `textures/<素材名>`）
   ```
   python "SKILL_DIR/scripts/run_comfy.py" "SKILL_DIR/workflows/tileable_pbr_api.json" --prompt "<プロンプト>" --negative "<ネガティブ>" --seed random --out "<プロジェクト>/textures/<素材名>" --prefix <素材名>
   ```
   - 結果は JSON で出る。`ok: false` ならエラー内容を読んで対処する（下の「困ったとき」）
   - 解像度などを変えたいときは `--list` でノードIDを調べて `--set ID.入力名=値`
   - 1回あたり数十秒〜数分かかる。長い場合は `--timeout 1800`

3. **自分の目で確認する**（必ずやる）
   - 出力された画像を Read で開いて見る
   - 継ぎ目チェック用の画像（タイトルに seam や offset を含む preview）で、中央に十字の境目が見えたら失敗
   - 失敗、または依頼のイメージと違う場合: seed を変えて再実行（同じ素材で最大3回まで）。
     3回ダメならプロンプトを直す。それでもダメならユーザーに状況を報告して相談する

4. **Blender に設定する**（ユーザーが求めた場合、かつ Blender MCP が使える場合）
   - API は Blender のバージョンで変わるので、書く前に `bpy.app.version` を確認し、
     Blender MCP の `search_api_docs` でノード名・プロパティ名を確かめてから実行する
   - マテリアルの組み方:
     - basecolor → Principled BSDF の Base Color（色空間 sRGB）
     - roughness / metalness → Roughness / Metallic（色空間 Non-Color）
     - normal → Normal Map ノード経由で Normal（色空間 Non-Color）。**CHORD の normal は DirectX 形式**なので、
       Normal Map ノードの `convention` を `'DIRECTX'` にする（Blender 5.3 で確認。この設定が無い古い版では G チャンネルを反転する）
     - height → Cycles なら Displacement ノード、軽く済ませるなら Bump（Non-Color）
     - Texture Coordinate + Mapping でスケールを実寸に合わせる（例: 板材1枚の幅が約20cmになるように）
   - 設定したら Blender のスクリーンショットかプレビューレンダーで見た目を確認する

5. **報告する**: 保存したファイルの場所、使ったプロンプトと seed、確認結果を短く伝える。
   気に入った結果の seed は控えておけば同じものを作り直せる。

## ワークフローを作る（tileable_pbr_api.json が無いとき・作り直しを頼まれたとき）

完成形（API 形式。各ノードに `_meta.title` を付ける）:

- SDXL 側: Load Checkpoint（`sd_xl_base_1.0.safetensors`）
  - MODEL → **SeamlessTile**（tiling=enable、copy_model=`Modify in place`）→ KSampler の model
  - VAE → **MakeCircularVAE**（tiling=enable。モデル側と必ず同じ。copy_vae=`Modify in place`）→ VAE Decode の vae
  - 「Make a copy」は使わない（ComfyUI 0.45 で、モデルの複製はエラーになり、VAE の複製の後にサーバーがヒープ破損で異常終了した）
  - CLIP → CLIPTextEncode ×2（タイトル `Positive Prompt` / `Negative Prompt`）→ KSampler
  - Empty Latent 1024×1024 → KSampler → VAE Decode → Save Image（タイトル `texture`）
  - VAE Decode → **OffsetImage** → Preview Image（タイトル `seam_check`）
- CHORD 側: `texture` の画像 → CHORD のモデル読み込み（`chord_v1.safetensors`）と材質推定ノード
  → Save Image ×5（タイトル `basecolor` / `normal` / `roughness` / `metalness` / `height`）

手順:

1. **必要なノードがあるか確認**:
   `python "SKILL_DIR/scripts/run_comfy.py" --node-info SeamlessTile MakeCircularVAE OffsetImage`
   CHORD のノード名は、インストール済みの `ComfyUI/custom_nodes/ComfyUI-Chord` の中身
   （特に `example_workflows/chord_sdxl_t2i_image_to_material.json`）を読んで調べ、同じく `--node-info` で入出力を確認する。
   comfyui-mcp があれば `create_workflow` の `node_info` でもよい。
2. **足りないカスタムノードを入れる**: ComfyUI-seamless-tiling（作者 spinagon）、ComfyUI-Chord（ubisoft）。
   comfyui-mcp の `/comfy:install` か `list_packs` の `install_deps` を使う。
   入れた後は ComfyUI の再起動が必要。Windows ではツールから起動し直せないので、
   **ユーザーに ComfyUI の再起動を頼んで待つ**。
3. **モデルを確認**: `python "SKILL_DIR/scripts/run_comfy.py" --models checkpoints`
   - `sd_xl_base_1.0.safetensors` が無ければ comfyui-mcp の `download_model` で入れる（stabilityai/stable-diffusion-xl-base-1.0）
   - `chord_v1.safetensors` が無ければ、Hugging Face でライセンス同意が必要なモデルなので、
     **ユーザーに Ubisoft/ubisoft-laforge-chord のページで同意してダウンロードし、models/checkpoints に置くよう頼む**
4. **API 形式の JSON を組む**: 入力名・選択肢は必ず `--node-info` の結果に合わせる（推測で書かない）。
   CHORD 部分は example_workflows のつなぎ方をそのまま参考にする。
   comfyui-mcp があれば `create_workflow`（`create` → `modify` → `validate`）で組んでから API 形式で書き出してもよい。
5. **テスト実行**: 上の「生成の手順」で `weathered oak wooden planks` などを1回生成し、
   全部の出力画像を Read で見て確認する。エラーや見た目の問題があれば直して再実行する。
6. **保存**: うまくいった JSON を `SKILL_DIR/workflows/tileable_pbr_api.json` に保存する。
   comfyui-mcp があれば、ユーザーが画面で開いて見られるよう `save_workflow` でも保存しておく。

## 注意

- 画像生成と Blender のレンダリングを同時に動かさない（VRAM 12GB を取り合って遅くなる・落ちる）
- CHORD（PBRマップ推定）のモデルは研究用途限定ライセンス。作品を公開・販売するときはユーザーに確認する
- ワークフローの JSON は書き換えて保存しない（毎回コマンドの引数で上書きする）
- テクスチャ生成の後に通常の SDXL ワークフロー（`workflows/sdxl_t2i_api.json`）を使うときは、先に
  `POST http://127.0.0.1:8188/free` に `{"unload_models": true, "free_memory": true}` を送る。
  SeamlessTile が読み込み済みの SDXL を書き換えたままキャッシュに残り、出力がタイル化されるため。
  この両方を指定した /free か、ComfyUI の再起動で元に戻ることを確認済み
- `workflows/` には通常の画像生成用の `zimage_t2i_api.json` / `klein_t2i_api.json` / `sdxl_t2i_api.json` もある。
  Z-Image と klein のワークフローにはネガティブのノードが無いので、`--negative` は使えない

## 困ったとき

- **接続できない**: ComfyUI が起動しているか確認。ポートが 8188/8000 以外なら `--server 127.0.0.1:ポート`
- **node_errors / ノードの設定エラー**: エラーに出たノードIDを `--list` で確認。モデルファイル名の違いが多い
  （`--list` の ckpt_name などと、ComfyUI に入っているファイル名を比べる）
- **実行中のエラー（out of memory など）**: 解像度を下げる（`--set` で width/height）か、ComfyUI を再起動
- **UI 形式と言われる**: ワークフローを「Export Workflow (API)」で書き出し直してもらう
- comfyui-mcp が入っていれば、`get_history` の diagnose で失敗の原因を調べてもよい

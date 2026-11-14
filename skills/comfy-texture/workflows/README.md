# workflows

ComfyUI の API 形式のワークフローです（「Export Workflow (API)」で書き出す形）。`scripts/run_comfy.py` で実行します。

| ファイル | 中身 |
|---|---|
| `tileable_pbr_api.json` | 継ぎ目のないテクスチャ（SDXL＋SeamlessTile／MakeCircularVAE）→ CHORD で PBR マップ5枚 |
| `zimage_t2i_api.json` | Z-Image Turbo（NVFP4）の普通の画像生成 |
| `klein_t2i_api.json` | FLUX.2 [klein] 4B（FP8）の普通の画像生成 |
| `sdxl_t2i_api.json` | SDXL base の普通の画像生成 |

## ノードのタイトル

run_comfy.py は、ノードのタイトルでプロンプトの入れ先と、保存するファイルの名前を決めます。

- プロンプト：`Positive Prompt`、ネガティブ：`Negative Prompt`
- 保存：`texture` / `basecolor` / `normal` / `roughness` / `metalness` / `height`
- 継ぎ目チェック用の Preview Image：`seam_check`

## 自分で作り直す場合

1. ComfyUI で「シームレスなテクスチャ生成 → CHORD で PBR マップ化」まで動くワークフローを作り、1回実行して確かめる
2. 上のとおりにノードのタイトルを付ける（ノードの上部をダブルクリックで変えられる）
3. 「ファイル → Export Workflow (API)」（日本語表示なら「エクスポート (API)」）で書き出し、`tileable_pbr_api.json` としてこのフォルダに置く。Ctrl+S で保存した普通のファイルは使えない

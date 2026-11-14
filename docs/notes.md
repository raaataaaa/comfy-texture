# 作業の記録（2026-11-14）

手順書とルールを用意して Claude Code に渡し、環境づくりからテストまでを任せたときの記録です。

## 進め方

手順書は7つの段階に分け、段階ごとに「やったこと・結果・問題」を3行ほどで報告してもらいました。

1. 環境の確認（ComfyUI の場所、Python と PyTorch の版、空き容量）
2. スキルを置く
3. モデルをそろえる（公式の Hugging Face のリポジトリからだけ）
4. カスタムノードを入れる
5. モデルごとに試しに生成し、ワークフローを保存する
6. テクスチャのワークフローを作り、「weathered oak wooden planks」で試す
7. Blender の新しいファイルでマテリアルにして確かめる

### 渡したルール

- 推測で書かない。ノードの入力名と選択肢は ComfyUI の `/object_info`（`run_comfy.py --node-info`）で、Blender の API は Blender MCP の `search_api_docs` で確かめる
- 今あるモデル、カスタムノード、ワークフロー、.blend ファイルは消さない・上書きしない。同じ名前があれば飛ばして報告する
- 作業中の .blend は開かない。Blender のテストは新しいファイルでする
- モデルは公式のリポジトリからだけ入れる。401/403 が出たら止まって聞く
- ダウンロードの前に空き容量を確かめる
- カスタムノードを入れるたびに、ComfyUI の Python で PyTorch の版を確かめる。cu130 でなくなっていたら止まる。xformers は入れない
- 止まってよいのは、ComfyUI の再起動、Hugging Face のログインやライセンスへの同意、ComfyUI のフォルダが見つからないときだけ

### 分担

- 自分：手順書とルールを渡した。CHORD のライセンスに同意して、モデルをダウンロードした
- Claude Code：上の段階の作業と、報告書

## 確かめたこと

- モデル：CHORD 以外の6つは最初から入っていたので、Hugging Face の公式とサイズと SHA256 が一致することだけ確かめた（上書きはしていない）
- カスタムノード：comfyui-seamless-tiling（v1.0.0）は入っていた。ComfyUI-Chord（v1.1.1）は `git clone` で入れた
- ComfyUI-Chord の依存として入ったもの：diffusers 0.43.0、ImageIO 2.38.1、omegaconf 2.4.0、importlib_metadata 10.2.0、lazy-importer 0.1.0、zipp 4.1.2。先に `pip install --dry-run` で、torch などが変わらないことを確かめた
- PyTorch は最初から最後まで 2.12.1+cu130 のままだった。ComfyUI の再起動後のログに `IMPORT FAILED` はなかった
- CHORD の部分のつなぎ方は、ComfyUI-Chord の `example_workflows` を参考にした

## テストの結果

### 生成時間（1024×1024、1枚）

ComfyUI の履歴の execution_start から execution_success までの時間です。初回はモデルを解放した直後、2回目は seed を変えてもう一度実行したときです。

| ワークフロー | 初回 | 2回目 |
|---|---|---|
| Z-Image Turbo（NVFP4） | 8.8秒 | 3.9秒 |
| FLUX.2 [klein] 4B（FP8） | 5.1秒 | 2.1秒 |
| SDXL base 1.0 | 11.3秒 | 8.1秒 |
| テクスチャ＋PBR（tileable_pbr） | 49.3秒（CHORD の初回の読み込みを含む） | 14.2秒 |

NVFP4 は、RTX 5070（Blackwell、sm_120）と cu130 の組み合わせで、遅くなることもエラーもなく動いた。

### テクスチャ（weathered oak wooden planks、seed 618261254）

- 7つの出力（texture、seam_check、basecolor、normal、roughness、metalness、height）がそろった
- 継ぎ目チェックの画像（半分ずらしたもの）の中央に、十字の境目はなかった
- 数値でも確かめた。「端どうしの差 ÷ 内側の隣り合う画素の差」は、texture が 0.99 / 1.74、normal が 1.07 / 1.01 だった。1 に近いほど継ぎ目がない。普通の写真は 43.7 / 22.3
- metalness は全面 0（木材なので正しい）。roughness は 0.54〜0.86

### Blender（5.3、新しいファイル）

- 2.6m の平面に、テクスチャを 2×2 で繰り返した（1枚≒1.3m、板の幅が約20cm）
- マテリアルの組み方
  - basecolor（sRGB）→ Principled BSDF の Base Color
  - roughness / metalness（Non-Color）→ Roughness / Metallic
  - normal（Non-Color）→ Normal Map（Tangent、convention = DirectX）→ Bump の Normal
  - height（Non-Color）→ Bump（Distance 5mm）→ Principled BSDF の Normal
  - UV → Mapping（Scale 2）→ 各画像
- 画像は .blend からの相対パスで読み込んだ

## 起きた問題と対処

1. **ComfyUI が異常終了した**
   - SeamlessTile / MakeCircularVAE の「Make a copy」を試したところ、モデル側の複製はエラー（`'NoneType' object is not callable`）になり、VAE 側の複製のあとに普通の SDXL を流したところで落ちた。Windows のイベントログでは、python.exe が例外コード 0xc0000374（ヒープ破損）で終了していた
   - 原因はこの複製の処理である可能性が高い（推定で、確定ではない）
   - 両方を「Modify in place」にしてからは、4回の連続生成と、続けて流した PBR 生成2回で落ちなかった
2. **「Modify in place」の副作用**
   - テクスチャのあとに同じ ComfyUI で `sdxl_t2i_api.json` を流すと、意図せずタイル状の画像になる。読み込み済みの SDXL が書き換わったまま、キャッシュに残るため
   - `POST /free` に `{"unload_models": true, "free_memory": true}` を送ると、基準とまったく同じ画像に戻った。ComfyUI を再起動しても戻る
   - `unload_models` だけを送る方法は確かめていない
3. **CHORD の normal は DirectX 形式**
   - 根拠は2つ。CHORD の `normal_to_height.py` が DirectX を前提にした式になっていること。元のテクスチャの明るさと法線の G の相関が、2つのテクスチャで +0.55 と +0.41 だったこと
   - Blender は OpenGL 形式なので、Normal Map ノードの convention を DirectX にした（Blender 5.3 にある設定）。ほかのツールで使うときは G を反転する
4. **claude.ai の「ComfyUI」コネクタは Comfy Cloud 用だった**
   - 手元のモデルやカスタムノードは見えず、使うとクラウドのクレジットを使う。そのため使わず、手元の HTTP API と run_comfy.py で作業した
5. **Z-Image と klein のワークフローには Negative Prompt のノードがない**
   - 公式テンプレートと同じく ConditioningZeroOut を使っているので、`--negative` を付けるとエラーになる
6. **ComfyUI が実行中に落ちると、run_comfy.py は `--timeout`（既定 900秒）まで待ち続ける**
   - おかしいと思ったら、ComfyUI が動いているかを確かめる

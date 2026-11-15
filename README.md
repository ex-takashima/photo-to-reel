# photo-to-reel（写真からリール）

Meta の AI エージェント **Muse** 用のスキルです。写真や画像を1枚渡すと、番号で選べる質問をしながら、写真の中の主役が動く縦長のリール動画を作ります。個人の SNS 投稿（ペット・家族・家庭菜園・自作のキャラなど）向けです。

- 長さは「10秒・曲つき」か「15〜20秒・3カット」
- 写真のまま／イラスト調／手描きアニメ映画風／3Dアニメ映画風から選べる
- 仕上げ（つなぎ・拡大・音量）まで行い、キャプションとカバー画像を付けて渡す
- 投稿は、ユーザーが「投稿して」と言ったときだけ

## 入れ方

Muse に次のように頼んでください。

```
https://github.com/ex-takashima/photo-to-reel/releases/latest/download/photo-to-reel.zip
このURLのスキルを、あなたが使えるスキルとして登録してください。
```

登録できたら、写真を1枚渡して「この写真をリールにして」と頼みます。

## 中身

- `photo-to-reel/SKILL.md` … スキルの手順
- `photo-to-reel/scripts/reel_tools.py` … 仕上げの道具（Python 3.9 以上と ffmpeg）
- `photo-to-reel/skill.yaml` … Muse のスキル登録用

## ライセンス

MIT License © 2026 digicats

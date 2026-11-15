#!/usr/bin/env python3
"""photo-to-reel の仕上げ道具（ffmpeg のラッパー）。

Python 3.9 以上と ffmpeg / ffprobe だけで動く。追加ライブラリは不要。

使い方（どれも結果を1行の JSON で標準出力に返す）:
  info      VIDEO|IMAGE                   大きさ・縦横比・向き（動画なら長さ・fps・ラウドネスも）
  frame     VIDEO OUT.png [--at SEC]      コマを1枚切り出す（既定は最後のコマ）
  crop      IMAGE OUT.png --ratio 9:16 [--x 0.5 --y 0.5]
                                          画像を指定の比率に切り抜く（x,y は切り抜く中心 0〜1）
  concat    OUT.mp4 CUT1 CUT2 ... [--trims 4,6.5,5] [--ratio 9:16] [--mute]
                                          カットをつなぎ、拡大する（--trims は各カットの頭から何秒使うか。
                                          0 か省略はそのカットを全部使う。--trim1 SEC はカット1だけの旧書式）
  intro     IN.mp4 PHOTO OUT.mp4 [--sec 0.8 --xfade 0.3]
                                          頭に元の写真を --sec 秒見せてから動画へ溶かす（写真が動き出す見せ方）
  loopfade  IN.mp4 OUT.mp4 [--fade 0.5]   最後の --fade 秒で最初のコマへ溶かす（10秒版の繰り返し対策）
  bgm       IN.mp4 BGM OUT.mp4 [--below 9] 環境音を -20 LUFS に上げ、BGM をその --below dB 下で混ぜる
  bgmonly   IN.mp4 BGM OUT.mp4            環境音を使わず BGM だけにする（環境音に変な音があるとき）
  loudness  IN.mp4 OUT.mp4 [--target -14] 全体の音量を揃える
  sheet     VIDEO OUT.jpg [--cols 10]     1秒ごとのコマを並べた検品用の画像
  ssim      A.png B.png                   2枚の似ている度合い（1.0 で完全一致）

MIT License (c) 2026 digicats
"""
import argparse
import json
import math
import re
import subprocess
import sys


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-3000:])
        raise SystemExit(f"ffmpeg が失敗しました: {' '.join(cmd[:6])} ...")
    return p


def ff(*args):
    return run(["ffmpeg", "-hide_banner", "-y", *args])


def probe(path):
    p = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration",
             "-of", "json", path])
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    dur = d.get("format", {}).get("duration")
    info = {"duration": round(float(dur), 3) if dur not in (None, "N/A") else None, "has_audio": a is not None}
    if v:
        num, den = v["r_frame_rate"].split("/")
        info.update(width=v["width"], height=v["height"],
                    fps=round(int(num) / int(den), 3) if int(den) else None,
                    frames=int(v["nb_frames"]) if v.get("nb_frames", "N/A") != "N/A" else None)
        g = math.gcd(v["width"], v["height"])
        info["ratio"] = f"{v['width'] // g}:{v['height'] // g}"
        r = v["width"] / v["height"]
        near = min(("9:16", "3:4", "4:5", "1:1", "4:3", "16:9", "2:3", "3:2"),
                   key=lambda s: abs(math.log(r / (int(s.split(":")[0]) / int(s.split(":")[1])))))
        info["near_ratio"] = near
        info["orientation"] = "縦長" if v["height"] > v["width"] else ("横長" if v["width"] > v["height"] else "正方形")
    return info


def lufs(path):
    """統合ラウドネス（LUFS）と真のピーク（dBTP）を測る。音が無ければ None。"""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    if not m:
        return None
    j = json.loads(m.group(0))
    return {"lufs": float(j["input_i"]), "true_peak": float(j["input_tp"])}


def ratio_size(ratio):
    """比率から仕上げの大きさを決める。長い辺を 1920 にし、偶数にそろえる。"""
    w, h = (float(x) for x in ratio.split(":"))
    if h >= w:
        H = 1920
        W = int(round(1920 * w / h / 2) * 2)
    else:
        W = 1920
        H = int(round(1920 * h / w / 2) * 2)
    return W, H


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def cmd_info(a):
    i = probe(a.video)
    if i["duration"] is None or (not i["has_audio"] and (i["duration"] or 0) <= 0.1):  # 静止画（JPEG は 0.04 秒の動画に見えるため長さでも判定）
        for k in ("fps", "frames", "duration", "has_audio"):
            i.pop(k, None)
    elif i["has_audio"]:
        i.update(lufs(a.video) or {})
    out(i)


def cmd_frame(a):
    i = probe(a.video)
    if a.at is None:
        n = (i["frames"] or int(round(i["duration"] * i["fps"]))) - 1
        ff("-i", a.video, "-vf", f"select='eq(n\\,{n})'", "-frames:v", "1", a.out)
        out({"out": a.out, "frame": n})
    else:
        ff("-ss", str(a.at), "-i", a.video, "-frames:v", "1", a.out)
        out({"out": a.out, "at": a.at})


def cmd_crop(a):
    p = run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", a.image])
    W, H = (int(x) for x in p.stdout.strip().split(",")[:2])
    rw, rh = (float(x) for x in a.ratio.split(":"))
    if W / H > rw / rh:
        h = H
        w = int(H * rw / rh) // 2 * 2
    else:
        w = W
        h = int(W * rh / rw) // 2 * 2
    x = min(max(int(a.x * W - w / 2), 0), W - w)
    y = min(max(int(a.y * H - h / 2), 0), H - h)
    ff("-i", a.image, "-vf", f"crop={w}:{h}:{x}:{y}", a.out)
    out({"out": a.out, "from": [W, H], "size": [w, h], "offset": [x, y]})


def cmd_concat(a):
    W, H = ratio_size(a.ratio)
    infos = [probe(c) for c in a.cuts]
    fps = infos[0]["fps"]
    inputs, parts = [], []
    use_audio = (not a.mute) and all(i["has_audio"] for i in infos)
    trims = [float(x) if x.strip() else 0.0 for x in a.trims.split(",")] if a.trims else []
    if a.trim1 and not trims:
        trims = [a.trim1]
    if len(trims) > len(a.cuts):
        sys.exit(json.dumps({"error": "--trims の数がカットの数より多い"}, ensure_ascii=False))
    trims += [0.0] * (len(a.cuts) - len(trims))
    last = len(a.cuts) - 1
    for k, c in enumerate(a.cuts):
        inputs += ["-i", c]
        sec = trims[k]
        t = f"trim=0:{sec}," if sec > 0 else ""
        at = f"atrim=0:{sec}," if sec > 0 else ""
        if k == last and sec > 0:  # 最後のカットを途中で切ったら、音だけ0.3秒で小さくして終える
            at += f"afade=t=out:st={max(sec - 0.3, 0)}:d=0.3,"
        parts.append(f"[{k}:v]{t}setpts=PTS-STARTPTS,scale={W}:{H}:flags=lanczos,setsar=1,fps={fps}[v{k}]")
        if use_audio:
            parts.append(f"[{k}:a]{at}asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{k}]")
    n = len(a.cuts)
    if use_audio:
        parts.append("".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    else:
        parts.append("".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]"]
    ff(*inputs, "-filter_complex", ";".join(parts), *maps,
       "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", a.out)
    out({"out": a.out, "size": [W, H], "trims": trims, **{k: v for k, v in probe(a.out).items() if k in ("duration", "has_audio")}})


def cmd_intro(a):
    i = probe(a.inp)
    W, H, fps, d = i["width"], i["height"], i["fps"], i["duration"]
    hold = a.sec + a.xfade  # 写真の長さ（溶かす部分を含む）
    fc = (f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
          f"loop=loop=-1:size=1,trim=0:{hold},setpts=N/{fps}/TB,fps={fps},format=yuv420p[p];"
          f"[0:v]setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS[m];"
          f"[p][m]xfade=transition=fade:duration={a.xfade}:offset={a.sec}[v]")
    args = ["-i", a.inp, "-i", a.photo, "-filter_complex", fc, "-map", "[v]"]
    if i["has_audio"]:
        ms = int(a.sec * 1000)
        args += ["-af", f"adelay={ms}|{ms},afade=t=in:st={a.sec}:d=0.05", "-map", "0:a",
                 "-c:a", "aac", "-b:a", "192k"]
    ff(*args, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", a.out)
    out({"out": a.out, "photo_sec": a.sec, "xfade": a.xfade, "duration": probe(a.out)["duration"]})


def cmd_loopfade(a):
    i = probe(a.inp)
    d = i["duration"]
    fps = i["fps"]
    st = max(d - a.fade, 0)
    vf = (f"[0:v]split[m][f];[f]select='eq(n\\,0)',loop=loop=-1:size=1,trim=0:{d},"
          f"setpts=N/{fps}/TB,format=yuva420p,fade=t=in:st={st}:d={a.fade}:alpha=1[o];"
          f"[m][o]overlay=shortest=1,format=yuv420p[v]")
    args = ["-i", a.inp, "-filter_complex", vf, "-map", "[v]"]
    if i["has_audio"]:
        args += ["-af", f"atrim=0:{d},afade=t=in:d=0.05,afade=t=out:st={max(d - 0.3, 0)}:d=0.3",
                 "-map", "0:a", "-c:a", "aac", "-b:a", "192k"]
    ff(*args, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", a.out)
    out({"out": a.out, "fade": a.fade})


def _bgm_chain(d):
    return (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{d},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={max(d - 1, 0)}:d=1")


def cmd_bgm(a):
    i = probe(a.inp)
    if not i["has_audio"]:
        raise SystemExit("動画に音がありません。bgmonly を使ってください")
    d = i["duration"]
    env, bg = -20, -20 - a.below
    fc = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I={env}:TP=-3[env];"
          f"{_bgm_chain(d)},loudnorm=I={bg}:TP=-3[bgm];"
          f"[env][bgm]amix=inputs=2:duration=first:normalize=0[a]")
    ff("-i", a.inp, "-i", a.bgm, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "pcm_s16le", "-f", "matroska", a.out + ".tmp.mkv")
    _finish_loudness(a.out + ".tmp.mkv", a.out, -14)
    out({"out": a.out, "env_lufs": env, "bgm_lufs": bg, **(lufs(a.out) or {})})


def cmd_bgmonly(a):
    d = probe(a.inp)["duration"]
    fc = f"{_bgm_chain(d)}[a]"
    ff("-i", a.inp, "-i", a.bgm, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "pcm_s16le", "-f", "matroska", a.out + ".tmp.mkv")
    _finish_loudness(a.out + ".tmp.mkv", a.out, -14)
    out({"out": a.out, **(lufs(a.out) or {})})


def _finish_loudness(src, dst, target):
    """ゲインで目標に寄せ、リミッターで音割れを防ぐ。2回まで測り直す。"""
    import os
    cur = src
    gain_total = 0.0
    for step in range(2):
        m = lufs(cur)
        if m is None:
            raise SystemExit("音が測れませんでした")
        g = target - m["lufs"]
        if abs(g) < 0.3 and step > 0:
            break
        gain_total += g
        nxt = dst + f".step{step}.mkv"
        ff("-i", src, "-map", "0:v", "-map", "0:a", "-c:v", "copy",
           "-af", f"volume={gain_total:.2f}dB,alimiter=limit=0.89:level=disabled",
           "-c:a", "pcm_s16le", "-f", "matroska", nxt)
        if cur not in (src,):
            os.remove(cur)
        cur = nxt
    ff("-i", cur, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
       "-movflags", "+faststart", dst)
    for f in (cur, src):
        if f.endswith(".mkv") and os.path.exists(f):
            os.remove(f)


def cmd_loudness(a):
    if not probe(a.inp)["has_audio"]:
        raise SystemExit("音がありません")
    import shutil
    tmp = a.out + ".src.mkv"
    ff("-i", a.inp, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "pcm_s16le",
       "-f", "matroska", tmp)
    _finish_loudness(tmp, a.out, a.target)
    out({"out": a.out, "target": a.target, **(lufs(a.out) or {})})


def cmd_sheet(a):
    d = probe(a.video)["duration"]
    n = max(1, int(math.floor(d)))
    rows = math.ceil(n / a.cols)
    ff("-i", a.video, "-vf", f"fps=1,scale=-1:300,tile={a.cols}x{rows}", "-frames:v", "1", a.out)
    out({"out": a.out, "tiles": n, "grid": [a.cols, rows]})


def cmd_ssim(a):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", a.a, "-i", a.b, "-lavfi",
                        "[1:v][0:v]scale2ref=flags=bicubic[b][a];[a][b]ssim", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"All:([0-9.]+)", p.stderr)
    if not m:
        sys.stderr.write(p.stderr[-2000:])
        raise SystemExit("SSIM を測れませんでした")
    out({"ssim": round(float(m.group(1)), 3)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("info"); p.add_argument("video"); p.set_defaults(f=cmd_info)
    p = sp.add_parser("frame"); p.add_argument("video"); p.add_argument("out"); p.add_argument("--at", type=float); p.set_defaults(f=cmd_frame)
    p = sp.add_parser("crop"); p.add_argument("image"); p.add_argument("out"); p.add_argument("--ratio", default="9:16")
    p.add_argument("--x", type=float, default=0.5); p.add_argument("--y", type=float, default=0.5); p.set_defaults(f=cmd_crop)
    p = sp.add_parser("concat"); p.add_argument("out"); p.add_argument("cuts", nargs="+"); p.add_argument("--trim1", type=float)
    p.add_argument("--trims"); p.add_argument("--ratio", default="9:16"); p.add_argument("--mute", action="store_true"); p.set_defaults(f=cmd_concat)
    p = sp.add_parser("intro"); p.add_argument("inp"); p.add_argument("photo"); p.add_argument("out")
    p.add_argument("--sec", type=float, default=0.8); p.add_argument("--xfade", type=float, default=0.3); p.set_defaults(f=cmd_intro)
    p = sp.add_parser("loopfade"); p.add_argument("inp"); p.add_argument("out"); p.add_argument("--fade", type=float, default=0.5); p.set_defaults(f=cmd_loopfade)
    p = sp.add_parser("bgm"); p.add_argument("inp"); p.add_argument("bgm"); p.add_argument("out"); p.add_argument("--below", type=float, default=9); p.set_defaults(f=cmd_bgm)
    p = sp.add_parser("bgmonly"); p.add_argument("inp"); p.add_argument("bgm"); p.add_argument("out"); p.set_defaults(f=cmd_bgmonly)
    p = sp.add_parser("loudness"); p.add_argument("inp"); p.add_argument("out"); p.add_argument("--target", type=float, default=-14); p.set_defaults(f=cmd_loudness)
    p = sp.add_parser("sheet"); p.add_argument("video"); p.add_argument("out"); p.add_argument("--cols", type=int, default=10); p.set_defaults(f=cmd_sheet)
    p = sp.add_parser("ssim"); p.add_argument("a"); p.add_argument("b"); p.set_defaults(f=cmd_ssim)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()

# L-Connect 3 `.template` format (Universal Screen 8.8")

Findings from L-Connect 3 v2.1.29. Unofficial – reverse-engineered, may change between versions.

## Where things live

| Path (under `C:\ProgramData\Lian-Li\L-Connect 3\`) | Contents |
|---|---|
| `universal-screen-8.8-inch\template\*.template` | templates (built-in ones are downloaded as `universal-screen-8.8-inch.zip`) |
| `universal-screen-8.8-inch\video\*.h264` / `*.mp4` | background videos referenced by templates |
| `universal-screen-8.8-inch\preview\template_<id>.png` | thumbnails shown in the template list |
| `universal-screen-8.8-inch\theme\`, `modulars\` | Theme Info and Modular building blocks |
| `profile\<hash>` (gzip JSON) | per-device settings, e.g. `SelectedTemplateId` |

Copying files into `template\` is **not** enough – the list is not rebuilt from that folder.
Use the **"+" tile** (import), which accepts a ZIP.

## Import ZIP

```
My_Template.zip
├── My_Template.template
└── My_Template.h264      # name must match videoName inside the template
```

The video is a raw H.264 elementary stream. L-Connect itself converts uploads with:

```
ffmpeg -i in.mp4 -an -f h264 -pix_fmt yuv420p -c:v libx264 -x264opts bframes=0 -preset ultrafast -r 24 out.h264
```

## The `.template` file

A .NET `BinaryFormatter` (MS-NRBF) stream of `lcd207.Theme` (assembly `lcd207`), followed by zero padding.
`tools/nrbf.py` is a minimal reader that keeps byte offsets so values can be patched without re-serialising.

Important fields of `lcd207.Theme`:

| Field | Meaning |
|---|---|
| `name` | template id / display name |
| `width`, `height` | 480 × 1920 for portrait |
| `themePic` | `System.Drawing.Bitmap` (PNG bytes) – preview incl. sample values |
| `videoPath`, `o_videoPath`, `videoName` | background video reference |
| `GraphList` | `ObservableCollection<lcd207.GraphItem>` – the layers, drawn in order |

Layer types seen in the samurai template:

| Class | Use |
|---|---|
| `lcd207.GraphAnimation` | background video; `bitmap`/`O_bitmap`/`S_bitmap` are first-frame stills, `FilePath` the video |
| `lcd207.GraphImage` | full-screen transparent PNG overlay (pills and lines) |
| `lcd207.GraphItem`, `TypeName = "Data"` | live value; `m_data.DataName` = source (`CPULOAD`, `GPUTEMP`, `RAM_GB`, `TIME`, …) |
| `lcd207.GraphItem`, `TypeName = "Text"` | static text; text in `m_data._Value` |
| `lcd207.GraphStatuBar` | progress bar (`FrontColor`, `width`, `height`, `radius`) |

Positions are `posX`/`posY` in screen pixels. Alignment index: 0 = left, 1 = centre, 2 = right.
Colours are `System.Drawing.Color` (`value` = ARGB as Int64, `knownColor`, `state`; state 2 = use `value`, state 1 = named colour, e.g. knownColor 164 = White).

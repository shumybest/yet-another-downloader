# 多格式媒体捕获与下载设计

## 目标

在保留 HLS 稳定下载链路的基础上，增加浏览器对 MPEG-DASH 和常见直链视频资源的识别，并由本地引擎按资源类型选择下载方式，最终通过 ffprobe 和 ffmpeg 解码检查确保输出可播放。

## 资源分类

浏览器扩展使用响应 URL、`Content-Type` 和路径后缀判定：

- `hls`: `.m3u8`、`application/vnd.apple.mpegurl`、`application/x-mpegurl`
- `dash`: `.mpd`、`application/dash+xml`
- `direct`: `video/mp4`、`video/webm`、`video/quicktime`、`video/x-flv`、`video/mpeg`、`video/ogg`、`video/3gpp` 以及 mp4/webm/mov/m4v/flv/mpeg/mpg/ogv/3gp 等后缀

`.ts`、`.m4s`、`.cmfv`、`.cmfa`、`.aac`、`.vtt`、`.key` 等常见分片和辅助资源不作为独立捕获，除非后续明确需要单片下载。

## 数据流

1. MV3 `webRequest` 记录请求头，并在响应开始时对媒体响应分类、去重、保存页面信息和必要鉴权头。
2. Popup 展示统一的媒体捕获列表，提交完整 `Capture` 给本地引擎。
3. HLS 继续使用本地网关重写播放列表和资源 URL；DASH、直链视频通过 yt-dlp 访问原始 URL，并传递代理、UA、Referer、Origin、Cookie 等请求信息。
4. yt-dlp 产出后，若不是适合的 MP4，则由 ffmpeg 转码或重封装为 H.264/AAC MP4；ffprobe 检查视频流、时长，ffmpeg 做短时解码检查。
5. 任务完成后只公开输出路径和状态，捕获凭据仍只存在进程内存。

## 非目标

- 不复制 Cat-Catch 源码或引入浏览器扩展 GPL 代码。
- 不承诺破解 DRM、绕过登录、绕过永久封禁或恢复失效签名 URL。
- 不把任意网页 HTML 自动识别为视频；本次范围是浏览器网络层实际返回的媒体资源。

## 可验证结果

- 类型识别测试覆盖 HLS、DASH、MP4、WebM、FLV、分片过滤和未知资源。
- Python 任务创建测试覆盖不同媒体类型的下载分流参数。
- 现有 HLS 网关、前端测试和 Tauri debug/release 构建保持通过。

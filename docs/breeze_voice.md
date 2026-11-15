# Breeze 本机语音与声音设置

心迹可通过 Breeze-TTS-2.cpp 的本机 HTTP 服务合成中文语音。角色使用已保存的 `voice_id` 固定音色，每句将支持策略中的 `style`、`speed`、`energy` 转成合成指令。模板保留原有 TTS 选择，使用 Breeze 时需要自行启动服务并注册音色。

## 服务与音色准备

模型来自 [BreezeBlue/Breeze-TTS-2](https://huggingface.co/BreezeBlue/Breeze-TTS-2)，GGUF 服务实现参考 [Breeze-TTS-2.cpp](https://huggingface.co/HoppouAI/Breeze-TTS-2.cpp)。模型权重采用 [BreezeBlue Research and Non-Commercial License](https://huggingface.co/BreezeBlue/Breeze-TTS-2/blob/main/LICENSE)。本项目中的使用范围为研究与比赛演示；其他用途需按该许可核实授权。模型权重、个人参考音频和生成的 `.breeze` 文件不随源码发布。

在 Breeze 可执行程序所在目录启动服务，例如：

```powershell
.\breeze-server.exe ..\breeze-tts-2-q8_0.gguf --host 127.0.0.1 --port 8080 --webui
```

先通过服务的 Web 界面设计并保存音色，记录其 ID。也可在仓库根目录使用项目 Python 环境生成两个合成参考预设：

```powershell
.\.venv\Scripts\python.exe scripts/breeze_smoke.py --create-presets
```

脚本保存 `xinji_gentle`、`xinji_bright`，已有同名预设时拒绝覆盖。此方式生成的声音与比赛演示机的参考音色不保证相同。后续对已保存音色测试时省略 `--create-presets`：

```powershell
.\.venv\Scripts\python.exe scripts/breeze_smoke.py --voice-id xinji_bright --output work/breeze-smoke
```

## 心迹配置

在自己的 `conf.yaml` 中选择引擎；以下字段位于 `character_config.tts_config`：

```yaml
tts_model: breeze_tts
breeze_tts:
  base_url: http://127.0.0.1:8080
  voice_id: xinji_bright
  base_instruction: 自然清晰、轻松亲切的中文陪伴者，保持参考音色
  cfg_scale: 1.0
  seed: 42
  timeout: 60
  max_concurrency: 1
  voices_dir: null
  presets:
    bright:
      label: 元气
      voice_id: xinji_bright
      description: 清亮自然、轻快亲切的陪伴声音
```

`voice_id` 必须已经在服务中注册，预设仅引用本机音色。合成并发需与 Breeze 服务匹配，默认单并发；引擎共享限流槽，遇到 409 按指数退避重试。服务不可用或合成失败时，现有对话链路保留字幕并静音降级。

`voices_dir` 是部署者指定的 Breeze 保存音色目录。需要支持档案自定义音色的永久删除时，将其设置为本机服务实际使用的目录。仅调用上游 DELETE 会卸载内存中的音色，不代表磁盘文件已删除；未配置目录或原服务不可用时，档案删除返回可重试错误。

## 用户声音设置

首次进入声音设置时可以跳过并保存默认选择，也可试听预设或用不超过 200 字的描述生成声音。描述模式每 30 分钟最多尝试 5 次；保存选择后重置计数。确认自定义声音时，后端注册当前描述和种子匹配的同一份试听音频，避免确认后重新生成不同音色。

“我的心迹”底部提供后续修改入口，保存后从下一句开始生效。偏好、生成次数和音色归属绑定服务端档案；完整数据导出包含当前声音偏好。删除档案时只清理其拥有的 `user_*` 音色，聊天历史仍由独立的历史入口管理。

界面和接口拦截明确的真人模仿请求，仅接受音色、音高和语气特征描述。当前规则不等于完整人名识别能力。体验模式下的试听和保存遵守原有同意控制。

## 策略与验证

支持的语气为 `calm`、`warm`、`steady`。强烈难过的回复使用 `warm / 0.9 / 0.8`，危机支持使用 `steady / 0.85 / 0.75`，顺序为语气、语速、能量。危机资源通知继续先于 TTS 下发，语音失败不阻止资源卡片显示。

`scripts/breeze_smoke.py` 记录首个 PCM、整句合成用时、音频时长和实时率。首个 PCM 到达不等于网页首次出声，当前网页播放器仍等待整句文件；本次接入未实现 WebSocket 流式音频播放。

自动化回归覆盖 PCM/WAV 转换、语气指令、并发与退避、失败降级、配置校验、试听确认复用、档案隔离及删除、下一句偏好更新，以及难过和危机语气。

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

前端检查在 `frontend-src` 目录运行：

```powershell
node --test tests/*.test.cjs
npm run typecheck
npm run build:web
```

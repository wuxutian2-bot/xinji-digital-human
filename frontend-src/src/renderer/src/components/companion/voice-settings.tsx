import { useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/context/websocket-context";
import { useCompanion } from "./companion-context";

export function VoiceSettings() {
  const c = useCompanion();
  const { baseUrl } = useWebSocket();
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const [mode, setMode] = useState<"preset" | "custom" | null>(null);
  const [description, setDescription] = useState("");
  const [seed, setSeed] = useState(42);
  const [preview, setPreview] = useState<{
    url: string;
    description?: string;
    seed?: number;
    preset_id?: string;
  } | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const available = !!c.voice?.available;
  const imitation =
    /模仿|克隆|复刻|仿照|真人|明星|名人|声优|[像用].{1,16}(本人|的声音|的嗓音|的声线)|\b(imitate|impersonate|clone|celebrity|sound like|voice of)\b/i.test(
      description,
    );
  useEffect(() => {
    if (c.voiceOpen) {
      setMode(null);
      setError("");
      setAttempts(c.voice?.preview_attempts ?? 0);
      setDescription(c.voice?.preference?.description ?? "");
      setSeed(c.voice?.preference?.seed ?? 42);
      if (!dialog.current?.open) dialog.current?.showModal();
    } else {
      request.current?.abort();
      dialog.current?.close();
      setPreview(null);
    }
  }, [c.voiceOpen]);
  useEffect(
    () => () => {
      request.current?.abort();
    },
    [],
  );
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview.url);
    },
    [preview],
  );

  const generate = async (preset_id?: string) => {
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setBusy(true);
    setError("");
    setPreview(null);
    const nextSeed = preset_id ? seed : seed + 1;
    setSeed(nextSeed);
    if (!preset_id) setAttempts((n) => n + 1);
    try {
      const response = await fetch(`${baseUrl}/api/companion/voice/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        signal: controller.signal,
        body: JSON.stringify(
          preset_id
            ? { preset_id }
            : { description: description.trim(), seed: nextSeed },
        ),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : "试听未完成，请稍后重试。",
        );
      }
      const wav = await response.blob();
      if (!controller.signal.aborted)
        setPreview({
          url: URL.createObjectURL(wav),
          preset_id,
          description: preset_id ? undefined : description.trim(),
          seed: nextSeed,
        });
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "试听未完成");
    } finally {
      if (request.current === controller) setBusy(false);
    }
  };
  const save = async (choice: unknown) => {
    setError("");
    if (await c.mutate("/voice", "PUT", choice)) c.closeVoice();
  };
  const skip = () => {
    if (busy || c.busy) return;
    if (c.voice?.preference) c.closeVoice();
    else void save({ mode: "default" });
  };
  const validPreview =
    preview &&
    (mode === "preset"
      ? !!preview.preset_id
      : preview.description === description.trim());
  return (
    <dialog
      ref={dialog}
      className="xj xj-voice-dialog"
      aria-labelledby="xj-voice-title"
      onCancel={(e) => {
        e.preventDefault();
        skip();
      }}
    >
      <header className="xj-voice-heading">
        <span className="xj-eyebrow">陪伴，也可以有熟悉的声音</span>
        <button disabled={busy || c.busy} onClick={skip}>
          {c.voice?.preference ? "关闭" : "跳过"}
        </button>
      </header>
      <h2 id="xj-voice-title">想自定义陪伴者的声音吗？</h2>
      <p className="xj-muted">
        也可以直接开始。声音设置随时能改，从下一句生效。
      </p>
      {c.voice?.preference && (
        <p className="xj-muted" role="status">
          当前声音：
          {c.voice.preference.mode === "custom"
            ? "自定义声音"
            : c.voice.preference.mode === "preset"
              ? (c.voice.presets.find(
                  (p) => p.id === c.voice?.preference?.preset_id,
                )?.label ?? "预设声音")
              : "默认声音"}
        </p>
      )}
      {!available && (
        <p role="status">声音服务暂时不可用，可以先使用默认声音继续聊天。</p>
      )}
      <div className="xj-voice-options">
        <button
          className="xj-primary"
          disabled={busy || c.busy}
          onClick={() => void save({ mode: "default" })}
        >
          使用默认声音
        </button>
        <button
          disabled={!available || busy || c.busy}
          aria-pressed={mode === "preset"}
          onClick={() => {
            setMode("preset");
            setPreview(null);
          }}
        >
          从预设里选
        </button>
        <button
          disabled={!available || busy || c.busy}
          aria-pressed={mode === "custom"}
          onClick={() => {
            setMode("custom");
            setPreview(null);
          }}
        >
          用一句话描述想要的声音
        </button>
      </div>
      {mode === "preset" && (
        <section className="xj-voice-presets" aria-label="预设音色">
          {c.voice?.presets.map((p) => (
            <article key={p.id}>
              <div>
                <h3>{p.label}</h3>
                <p className="xj-muted">{p.description}</p>
              </div>
              <button
                disabled={busy || c.busy}
                onClick={() => void generate(p.id)}
              >
                试听{p.label}
              </button>
            </article>
          ))}
          {!c.voice?.presets.length && (
            <p>当前角色还没有配置预设，可以使用默认声音。</p>
          )}
        </section>
      )}
      {mode === "custom" && (
        <section className="xj-voice-custom">
          <label htmlFor="xj-voice-description">描述音色、音高和语气</label>
          <textarea
            id="xj-voice-description"
            maxLength={200}
            value={description}
            disabled={busy || c.busy}
            placeholder="例如：温柔自然、声音稍低，像一位耐心的朋友。"
            onChange={(e) => {
              setDescription(e.target.value);
              setPreview(null);
            }}
          />
          <p className="xj-muted">
            {description.length}/200 · 不支持模仿具体真人，请只描述声音特征。
          </p>
          {imitation && (
            <p role="alert">不支持模仿具体真人，请改为描述音色、音高和语气。</p>
          )}
          <button
            disabled={
              busy ||
              c.busy ||
              !description.trim() ||
              imitation ||
              attempts >= 5
            }
            onClick={() => void generate()}
          >
            {preview ? "换一个" : "生成试听"}（{attempts}/5）
          </button>
          {attempts >= 5 && (
            <p className="xj-muted">
              本次试听次数已用完。可以确认当前声音，或先使用默认声音。
            </p>
          )}
        </section>
      )}
      {(busy || c.busy) && (
        <p role="status">{busy ? "正在准备试听，请稍等…" : "正在保存声音…"}</p>
      )}
      {(error || c.error) && <p role="alert">{error || c.error}</p>}
      {validPreview && (
        <section className="xj-voice-preview" aria-label="声音试听">
          <audio
            key={preview.url}
            controls
            src={preview.url}
            aria-label="试听生成的陪伴声音"
          />
          <button
            className="xj-primary"
            disabled={busy || c.busy}
            onClick={() =>
              void save(
                mode === "preset"
                  ? { mode: "preset", preset_id: preview.preset_id }
                  : {
                      mode: "custom",
                      description: preview.description,
                      seed: preview.seed,
                    },
              )
            }
          >
            就用这个
          </button>
        </section>
      )}
    </dialog>
  );
}

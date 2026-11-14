import { useState } from "react";
import { useCompanion } from "./companion-context";

export function DataExport() {
  const { profile, busy, exportData } = useCompanion();
  const [notice, setNotice] = useState("");
  return (
    <section>
      <h3>保存一份自己的记录</h3>
      <p className="xj-muted">
        导出当前档案的全部感受记录、回应执行记录和保存的小步骤，下载为 JSON
        文件。
        {profile?.synthetic_demo && "当前是示例档案，导出内容为虚构记录。"}
      </p>
      <button
        className="xj-primary xj-export-button"
        disabled={busy || !profile}
        onClick={async () => {
          setNotice("");
          if (await exportData()) setNotice("已发起下载，请在下载列表中查看。");
        }}
      >
        {busy ? "正在准备…" : "导出我的数据"}
      </button>
      <p className="xj-muted" role="status">
        {notice}
      </p>
    </section>
  );
}

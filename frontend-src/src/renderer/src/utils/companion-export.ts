/** Download the current server-bound profile, including records beyond UI limits. */
export async function downloadCompanionExport(baseUrl: string): Promise<void> {
  const response = await fetch(`${baseUrl}/api/companion/export`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      typeof detail?.detail === "string"
        ? detail.detail
        : "导出未完成，请检查服务连接后重试。",
    );
  }
  if (
    !response.headers
      .get("Content-Type")
      ?.toLowerCase()
      .startsWith("application/json")
  ) {
    throw new Error("导出未完成，服务返回的格式不正确。");
  }
  const blob = await response.blob();
  if (!blob.size) throw new Error("导出未完成，下载内容为空。");
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename =
    disposition.match(/filename="(xinji-data-\d{8}T\d{6}Z\.json)"/)?.[1] ||
    "xinji-data.json";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  try {
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    // Let the browser acquire the Blob before releasing the temporary URL.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

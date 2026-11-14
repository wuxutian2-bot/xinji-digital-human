# 任务七：档案查询优化与数据导出

2026-11-15。任务六与人工回收已推送至远端main（f25685f、83339ea）。任务七完成Agent档案实例复用、播放回执批量读取和当前用户JSON导出。

## 实现与使用

`companion_for()`优先读取Agent上的CompanionStore，只有memory实例或服务端user_id变化时才重建；退出SQLite模式时清除缓存。API统一使用该解析器。已有MentalHealthAgent初始化逻辑继续持有同一实例，连续请求不会重复执行建表。

`turns()`先读取本批回应，再用精确片段ID一次查询全部播放回执。使用SQLite的`json_each`传递一个JSON数组参数，避免将大量片段展开成绑定变量。本机SQLite 3.40.1已验证JSON1可用。1200个音频片段的测试中共执行2次SELECT；缺回执、失败、中断和静默片段的播放状态保持既有规则。

在“我的心迹”的“数据与隐私”中点击“导出我的数据”，即可下载当前档案的全部感受记录、回应执行记录和保存的小步骤。示例档案会明确说明导出虚构记录。页面内仅显示最近部分数据时，导出仍直接读取服务端完整记录。

接口为`GET /api/companion/export`，返回以下结构：

```json
{
  "schema_version": 1,
  "exported_at": "UTC时间",
  "user_id": "当前服务端档案ID",
  "states": [],
  "turns": [],
  "actions": [],
  "synthetic_demo": false
}
```

状态记录保留编号、历史作用域和已保存的结构化状态；回应保留原记录并组装播放回执状态；小步骤保留已保存内容。导出读取同一SQLite读事务的快照，不使用列表分页上限。导出范围不含原始聊天历史、配置密钥、独立事件表和其他用户记录。读取不要求再次同意体验，也不创建导出事件。

响应设置`Content-Disposition: attachment`、固定格式文件名、`Cache-Control: no-store`和`X-Content-Type-Options: nosniff`。用户身份取自服务端绑定，传入其他user_id查询参数不会切换导出对象。现有本机来源中间件继续限制Host、Origin和跨站请求。适用范围为当前回环单档案部署，本机进程访问权限仍由操作系统负责。

前端对HTTP失败、非JSON响应和空文件显示错误，失败响应不会作为数据下载。成功提示为“已发起下载”，不把浏览器开始下载当作用户已完成保存。临时Blob URL在下载触发后释放；导出按钮悬停时保持深色背景和可读文字。

## 自动化验证

新增8项后端测试：

- 连续API请求复用Agent实例，CompanionStore只初始化一次。
- 切换数据库、服务端用户或退出SQLite模式时更新缓存。
- 1200个片段保持2次SELECT，回执按当前用户隔离。
- 播放完成、失败、中断、静默与缺回执语义保持。
- 10005条状态、1005条回应、1005个小步骤全部导出，另一个用户的同编号记录不会混入；显式零和null按已保存内容保留。
- 已有缓存下切换档案，导出立即采用新的服务端绑定。
- 空档案返回空数组；外部Origin、Host和跨站请求被拒绝。
- 并发写入发生在两次读取之间时，导出仍保留同一读快照。

新增4项前端测试覆盖完整导出地址、下载文件名、对象URL释放、HTTP/格式/空文件失败、点击异常清理，以及按钮的示例范围、成功提示和禁用状态。

实际命令结果：

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests` | 242项通过 |
| `ruff check src/open_llm_vtuber tests scripts` | All checks passed |
| `ruff format --check src/open_llm_vtuber/mental_health tests` | 57 files already formatted |
| 前端`node --test tests/*.test.cjs` | 29项通过 |
| `npm run typecheck` | Node、SDK、Web通过，0错误 |
| `npm run build:web` | 成功，最终构建5.64秒 |
| `git diff --check` | 通过 |

## 实际浏览器验证

使用独立合成数据库，未读取真实心理档案。浏览器点击导出后下载JSON，逐项核对与当前档案数据库一致：10条状态、1条回应、1个小步骤。同库另一个合成用户含同编号回应和小步骤，导出中没有对方的标记或内容。

桌面1440×1080与手机390×844均可操作；手机文档宽度390像素，没有横向溢出。证据为[桌面界面](evidence/task7-export-desktop.png)、[手机界面](evidence/task7-export-mobile.png)与[下载核对摘要](evidence/task7-export-check.json)。临时服务和浏览器已关闭，原始合成下载保存在本地work目录。

构建仍有既有大体积chunk提示，重载页面仍出现此前记录的Live2D初始化控制台异常。该异常随后恢复显示，本次导出成功，SDK生命周期问题仍待单独处理。完整导出目前在内存中组装JSON，尚未做大规模数据的流式导出与并发压力验收。

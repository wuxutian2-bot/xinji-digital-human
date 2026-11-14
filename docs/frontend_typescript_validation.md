# 前端 TypeScript 检查修复

2026-11-15：网页类型检查由585项错误变为0项，完整 `npm run typecheck` 通过。

## 原因与调整

原检查将整个 Live2D SDK 的实现纳入业务代码的严格编译配置。585项诊断中，582项位于 WebSDK，主要涉及其原生配置未开启的严格空值检查、属性初始化和未使用声明检查；另3项是业务代码的未使用声明。

新增 `frontend-src/tsconfig.sdk.json`，继承仓库内 SDK Framework 原生配置，对 Framework、适配器、Core 声明及适配器所引用的独立 `DecisionBehavior` 工具建立独立工程。SDK 继续接受类型检查，开启 `noEmitOnError`，仅将生成的声明与构建缓存写入已忽略的 `frontend-src/node_modules/.tmp/`。SDK 原生配置的 `noImplicitAny` 和 `useUnknownInCatchVariables` 保留。

网页工程通过 TypeScript project reference 使用这些声明，业务配置的 `strict`、`noUnusedLocals`、`noUnusedParameters`、`noFallthroughCasesInSwitch` 保持开启。没有新增 `@ts-ignore`、`@ts-nocheck` 或万能模块声明。Vite 的运行时源码解析配置保持原样。

独立 SDK 检查额外发现3项 JSON 数组参数类型错误：JSON 转换接口将标准解析对象误标为 Cubism 的 `Value` 实例。已改为递归 `JsonValue` / `JsonObject` 类型，并更新解析回调签名；数组按数值索引访问，删除数值转换后不可能执行的分支。新增2项测试覆盖嵌套模型配置、混合数组、零值、false、空字符串、null及空对象和空数组的区别。

业务代码移除了聊天面板未使用的 React 导入、Live2D 配置上下文未使用的 `confUid` 获取和音频钩子未使用的 `Live2DModel` 类型别名。

## 复现与验证

在 `frontend-src` 目录运行：

```powershell
npm run typecheck
node --test tests/*.test.cjs
npm run build:web
```

- 清理 SDK 声明输出后重新运行完整类型检查，Node、SDK、Web 均通过，0项错误。
- 前端测试25项通过，0项失败；网页生产构建成功。
- 使用编译器的虚拟文件覆盖分别注入业务代码的 `number = null` 和 SDK 的 `number = string`，两者均被检出为 TS2322。没有改写磁盘源码。
- `--listFilesOnly` 确认网页检查读取生成的 SDK 声明，直接纳入网页检查的 WebSDK 实现文件为0。
- `git diff --check` 通过。

`typecheck:web` 会先执行 `typecheck:sdk`，首次运行会生成声明。重新安装依赖或删除缓存后，运行一次 `npm run typecheck` 可恢复编辑器所需的声明。`typecheck:sdk` 成功后只输出类型文件，不输出运行时 JavaScript。

本次0错误代表按各工程编译契约检查通过。SDK 实现仍遵循原生的非严格空值契约，未来升级到严格空值检查需要单独处理其生命周期与释放接口。此前记录的 Live2D 初始化运行时异常仍需单独验证。网页构建仍有既有的大体积 chunk 提示。

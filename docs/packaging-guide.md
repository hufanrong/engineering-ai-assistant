# 繁工AI 打包交付说明（v3.3）

> 本仓库已内置 **PWA 可安装能力**，并已把手机端壳（`packaging/fangong-android`）与电脑端壳（`packaging/fangong-desktop`）纳入仓库。
> **自动化构建已配置**：`.github/workflows/build.yml` —— push 到 `main` 或手动触发，即可自动产出 **Android APK** 与 **Windows 安装版（Setup exe）**。

---

## 一、PWA 在线版（已落地，无需任何操作）

- **手机（Android / iOS）**：用浏览器打开应用线上地址 → 菜单 →「添加到主屏幕 / 安装应用」，桌面即出现繁工AI图标，独立窗口运行。
- **电脑（Chrome / Edge）**：打开应用地址，点击地址栏右侧安装图标（⊕）→ 安装。
- 安装后图标、启动画面、主题色均为品牌元素（工程蓝 `#1E5AA8`、安全橙 `#FF7A00`）。
- **应用线上地址**：在妙搭平台点击「预览/发布」后获得的 URL（形如 `https://xxx.feishu.cn/app/<appId>/`），或飞书工作台打开应用后复制地址。

---

## 二、手机端 Android APK

### 方式 A：GitHub Actions 自动构建（推荐）
1. push 代码到 `main`，或到仓库 **Actions** 页手动触发 `Build APK & Windows Installer`。
2. 构建完成后在运行页的 **Artifacts** 中下载 `fangong-ai-apk`，得到 `app-debug.apk`。
3. 传到 Android 手机安装（需允许「安装未知来源应用」）。

### 方式 B：本地构建
前置：Node.js ≥ 18、**JDK 21**、Android SDK（配置 `ANDROID_HOME`）。

```bash
cd packaging/fangong-android
npm ci
npx cap copy android
cd android
./gradlew assembleDebug
# 产物：android/app/build/outputs/apk/debug/app-debug.apk
```

### 说明
- 壳项目位于 `packaging/fangong-android/`，WebView 加载地址配置在 `capacitor.config.json` 的 `server.url`（改地址只需改这一处）。
- 当前为 **debug 签名包**，可正常安装使用；正式上架需生成 release 签名 keystore。

---

## 三、电脑端 Windows 安装版（Setup exe）

### 方式 A：GitHub Actions 自动构建（推荐）
与 APK 同一工作流：push 到 `main` 或手动触发，在 **Artifacts** 下载 `fangong-ai-windows-setup`，得到 `繁工AI Setup <版本>.exe`（NSIS 安装向导版，可选择安装路径）。

### 方式 B：本地构建（Windows 电脑上执行）
前置：Node.js ≥ 18。

```bash
cd packaging/fangong-desktop
npm ci
npx electron-builder --win nsis
# 产物：dist/繁工AI Setup <版本>.exe
```

> 注意：`electron-builder --win nsis` 需在 **Windows 环境**（或配置好 Wine 的环境）构建；Linux 直接构建 NSIS 会因缺少 Wine 失败。GitHub Actions 已用 `windows-latest` runner，无需担心。
> 若只需免安装绿色版，用 `npx electron-builder --win zip`，产物为 `dist/繁工AI-<版本>-win.zip`，解压即用。

### 说明
- 壳项目位于 `packaging/fangong-desktop/`（Electron 在线壳，加载应用线上地址）。
- `main.js`：窗口标题「繁工AI」、关闭最小化到托盘、托盘「退出」正常结束进程。
- 应用图标：`icon-512.png`。

---

## 四、发布安装包到 GitHub Release（分发给他人下载）

在 Actions 页手动运行 `Build APK & Windows Installer`，填写版本标签（如 `3.3.0`），构建成功后自动创建一个 **GitHub Release**，附带 APK 与 Windows 安装包，直接分享 Release 链接即可。

---

## 五、代码上传 GitHub（首次 / 手动）

```bash
cd 项目根目录
git init
git add .
git commit -m "繁工AI v3.3：品牌统一 + PWA 可安装 + 双端打包 CI"
gh repo create engineering-ai-assistant --public --source=. --push
```

无 GitHub Token 时：把项目目录压缩为 zip（排除 `node_modules/`、`dist/`、`build/`），到 GitHub 网页新建仓库 `engineering-ai-assistant` → 「uploading an existing file」→ 拖入解压后的源码 → Commit。

---

## 六、品牌资源与打包结构

| 资源 | 路径 |
|---|---|
| PWA 图标 192/512 | `client/public/icons/icon-192.png` / `icon-512.png` |
| PWA 清单 | `client/public/manifest.webmanifest` |
| 品牌色 | 工程蓝 `#1E5AA8`（主色）、安全橙 `#FF7A00`（点缀） |
| 页内 Logo | `client/src/components/BrandLogo.tsx`（齿轮 + 图纸折线 + 智能节点） |
| 启动动画 | `client/src/components/BrandSplash.tsx` |
| 手机端壳 | `packaging/fangong-android/` |
| 电脑端壳 | `packaging/fangong-desktop/` |
| CI 自动构建 | `.github/workflows/build.yml` |

# 繁工AI 打包交付指南（v3.3）

> 本应用已内置 **PWA 可安装能力**（`client/public/manifest.webmanifest` + 品牌图标），可直接在手机/电脑浏览器安装为独立 App。
> 如需产出原生 **APK** 或 **Windows 安装包（.exe）**，按本指南在你自己的电脑上执行（当前开发环境无法产出原生安装包）。

---

## 一、PWA 安装（已落地，无需任何操作）

- **手机（Android / iOS）**：用浏览器打开应用线上地址 → 菜单 →「添加到主屏幕 / 安装应用」，桌面即出现繁工AI图标，独立窗口运行。
- **电脑（Chrome / Edge）**：打开应用地址，点击地址栏右侧的安装图标（⊕）→ 安装，开始菜单/桌面出现「繁工AI」。
- 安装后图标、启动画面、主题色均为品牌元素（工程蓝 `#1E5AA8`、安全橙 `#FF7A00`）。
- 应用线上地址：在妙搭平台点击「预览/发布」后获得的 URL（形如 `https://xxx.feishu.cn/app/<appId>/`），也可在飞书工作台打开应用后复制地址。

## 二、手机端打包 Android APK（Capacitor）

**前置**：Node.js ≥ 18、JDK 17、Android Studio（含 SDK，配置 `ANDROID_HOME`）。

1. 新建空目录并初始化 Capacitor：

```bash
mkdir fangong-android && cd fangong-android
npm init -y
npm install @capacitor/core @capacitor/cli @capacitor/android
npx cap init "繁工AI" com.fangong.ai --web-dir=dist
```

2. 编辑 `capacitor.config.json`，WebView 直接加载线上地址（把 `https://你的应用线上地址/` 换成实际 URL）：

```json
{
  "appId": "com.fangong.ai",
  "appName": "繁工AI",
  "webDir": "dist",
  "server": {
    "url": "https://你的应用线上地址/",
    "cleartext": false
  }
}
```

3. 生成品牌图标与启动页（把 `client/public/icons/icon-512.png` 复制为 `assets/icon.png`，2732×2732 的 `assets/splash.png` 可由它放大或另行导出）：

```bash
mkdir -p assets
# 复制图标后执行：
npx @capacitor/assets generate --android
```

4. 添加 Android 平台并构建 APK：

```bash
npx cap add android
cd android
./gradlew assembleDebug        # 产物：app/build/outputs/apk/debug/app-debug.apk
# 正式包（需签名）：
./gradlew assembleRelease
```

5. 真机安装 `app-debug.apk`，验证：安装、加载、拍照/语音/文字上传、类型识别、完整性补充。

**GitHub Actions 云端构建（可选，免本地 Android Studio）**：在仓库新建 `.github/workflows/android.yml`：

```yaml
name: Android APK
on: [workflow_dispatch]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: '17' }
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: npm install
      - run: npx cap add android || true
      - run: cd android && ./gradlew assembleDebug
      - uses: actions/upload-artifact@v4
        with:
          name: fangong-ai-debug-apk
          path: android/app/build/outputs/apk/debug/app-debug.apk
```

运行后在 Actions 页面的 Artifacts 里下载 APK。

## 三、电脑端打包 Windows 安装包（Electron）

> 说明：本应用后端（NestJS + 数据库）由妙搭平台托管，桌面端打包为「在线壳」形态——安装包内含前端壳，启动后加载应用线上地址。原方案中 FastAPI/SQLite 本地部署不适用于当前架构，无需 PyInstaller。

1. 初始化 Electron 项目：

```bash
mkdir fangong-desktop && cd fangong-desktop
npm init -y
npm install electron electron-builder --save-dev
```

2. 新建 `main.js`：

```js
const { app, BrowserWindow, Tray, Menu } = require('electron');
const path = require('path');

let win = null;
let tray = null;

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    title: '繁工AI',
    icon: path.join(__dirname, 'icon-512.png'), // 用 client/public/icons/icon-512.png
  });
  win.loadURL('https://你的应用线上地址/'); // 换成实际 URL
  win.on('close', (e) => { e.preventDefault(); win.hide(); }); // 关闭即最小化到托盘
}

app.whenReady().then(() => {
  createWindow();
  tray = new Tray(path.join(__dirname, 'icon-512.png'));
  tray.setToolTip('繁工AI');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => win.show() },
    { label: '退出', click: () => { win.destroy(); app.quit(); } },
  ]));
});
```

3. `package.json` 增加构建配置：

```json
{
  "name": "fangong-ai",
  "version": "3.3.0",
  "main": "main.js",
  "build": {
    "appId": "com.fangong.ai",
    "productName": "繁工AI",
    "win": { "target": "nsis", "icon": "icon-512.png" },
    "nsis": { "oneClick": false, "allowToChangeInstallationDirectory": true }
  },
  "scripts": { "dist": "electron-builder --win" }
}
```

4. 构建带安装向导的 exe：

```bash
npm run dist
# 产物在 dist/ 目录：繁工AI Setup 3.3.0.exe
```

5. 安装自测：安装 → 启动出现繁工AI窗口 → 项目创建 / 文件上传 / 检索 → 关闭窗口最小化到托盘 → 托盘「退出」正常结束进程。

## 四、代码上传 GitHub

**有权限时（优先）**：

```bash
cd 项目根目录
git init
git add .
git commit -m "繁工AI v3.3：品牌统一 + PWA 可安装"
gh repo create engineering-ai-assistant --public --source=. --push
# 或手动：git remote add origin https://github.com/<你的用户名>/engineering-ai-assistant.git
#          git branch -M main && git push -u origin main
```

**无 GitHub Token 时**：在妙搭工作台把本应用源码导出/下载为 zip（或直接压缩项目目录，排除 `node_modules/`、`dist/`、`build/`），在 GitHub 网页新建仓库 `engineering-ai-assistant` → 「uploading an existing file」→ 拖入解压后的源码 → Commit。

## 五、品牌资源位置

| 资源 | 路径 |
|---|---|
| PWA 图标 192/512 | `client/public/icons/icon-192.png` / `icon-512.png` |
| 浏览器图标 | `client/public/icons/icon-192.png`（index.html 引用） |
| PWA 清单 | `client/public/manifest.webmanifest` |
| 品牌色 | 工程蓝 `#1E5AA8`（主色）、安全橙 `#FF7A00`（点缀） |
| 页内 Logo | `client/src/components/BrandLogo.tsx`（齿轮 + 图纸折线 + 智能节点） |
| 启动动画 | `client/src/components/BrandSplash.tsx` |

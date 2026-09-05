# UI 设计指南

> **设计类型**: App 设计（应用架构设计）
> **确认检查**: 本指南适用于可交互的应用/网站/工具。

> ℹ️ Section 1 为设计意图与决策上下文。Code agent 实现时以 Section 2 及之后的具体参数为准。

> **品牌（v3.3）**: 繁工AI（FanGong AI）· 副标语「复杂工程，AI 化简」· 工程蓝主色 `#1E5AA8` + 安全橙点缀 `#FF7A00`；应用为 PWA 可安装（manifest + 品牌图标），启动动画/关于页/侧边栏品牌区已落地，打包交付指南见 `docs/packaging-guide.md`。

## 1. Design Archetype (设计原型)

### 1.1 内容理解

-   **目标用户**: 工程现场管理人员、技术员与外部 AI Agent；场景为高噪音工地与办公室混合，心理预期为高效处理数据而非浏览内容
-   **核心目的**: 建立信任 / 引导行动（通过清晰的待办与状态反馈驱动资料补全与实体归并）
-   **情绪基调**: 掌控感、严谨有序 / 避免焦虑、信息过载

### 1.2 设计方向

-   **Design Style**: Grid 网格风格 — 工程管理需高精度与秩序感，网格线辅助对齐密集数据，强化"结构化"心智模型
-   **Application Type**: Admin/SaaS (Data-Heavy) — 决定采用高视口利用率的多区布局
-   **Aesthetic Direction**: 工业蓝图数字化，用冷静的深蓝灰基底承载高频的状态色块跳动

## 2. Color System (色彩系统)

**色彩关系**: 深靛蓝主色 + 极浅蓝灰底 + 琥珀橙强警示 + 等宽数字强调
**配色设计理由**: 工程行业偏好蓝色系表达专业与稳重；橙色在深蓝背景下对比度极高，精准锚定"待确认/待补充"核心任务
**主色推导**: Primary 取自繁工AI品牌工程蓝 #1E5AA8，用于确立权威感与选中态；Accent 取同色系极低饱和度，仅作 Hover 容器底色不抢夺注意力
**使用比例**: 60% 背景白/浅灰 / 30% 卡片与边框 / 10% Primary+Semantic Orange（仅限 CTA 与待办徽章）

### 2.1 主题颜色

| Token                | HSL 值                 | 说明                                           |
| -------------------- | ---------------------- | ---------------------------------------------- |
| `background`         | hsl(220 20% 97%)       | 页面底色，微冷调减少长时间注视疲劳               |
| `card`               | hsl(0 0% 100%)         | 纯白容器，与背景形成层级                         |
| `foreground`         | hsl(222 47% 11%)       | 主文字，近黑但带蓝相                             |
| `muted-foreground`   | hsl(220 9% 46%)        | 次要说明、禁用态                                 |
| `primary`            | hsl(214 70% 39%)       | 品牌工程蓝 #1E5AA8，主按钮、激活态、关键链接        |
| `primary-foreground` | hsl(0 0% 100%)         | 主色上的反白                                     |
| `accent`             | hsl(220 20% 95%)       | 列表项 Hover、Dropdown Focus，低存在感反馈       |
| `accent-foreground`  | hsl(222 47% 11%)       | Accent 上的文字                                  |
| `border`             | hsl(220 13% 91%)       | 分割线与边框                                     |
| `warning`            | hsl(31 100% 45%)       | 品牌安全橙 #FF7A00，待确认/待补充专用，高可见性   |
| `success`            | hsl(142 76% 36%)       | 完整/成功状态绿                                  |
| `destructive`        | hsl(0 84% 60%)         | 失败/冲突/删除红                                 |

### 2.2 导航区配色

-   **基调关系**: 侧边栏复用 `background` 色或加深至 hsl(222 47% 15%) 形成沉浸感；推荐深色模式以区分内容区
-   **关键状态**: 激活项使用 `primary` 填充或左侧 4px 色条标识；Hover 使用 `accent`
-   **边界与背景**: 右侧 1px `border` 分隔或阴影区分；非透明背景确保可读性

### 2.3 语义颜色

-   **待确认/待补充**: 使用 `warning` 色系，徽章背景 hsl(38 92% 95%) + 文字 hsl(38 92% 40%)
-   **完整/已归并**: 使用 `success` 色系，徽章背景 hsl(142 76% 94%) + 文字 hsl(142 76% 30%)
-   **解析失败/冲突**: 使用 `destructive` 色系，徽章背景 hsl(0 84% 96%) + 文字 hsl(0 84% 50%)

## 3. Typography (字体排版)

-   **Heading**: Inter, "PingFang SC", sans-serif
-   **Body**: Inter, "PingFang SC", sans-serif
-   **Mono/Data**: JetBrains Mono, monospace — 专用于编号、API Key、统计数字、版本号
-   **字体策略**: 正文无衬线保证屏幕阅读效率；所有工程编号、ID、代码片段强制 Mono 字体确保字符对齐与辨识

## 4. Layout Strategy (布局策略)

-   **导航意图**: 必须持久型全局侧边导航（模块多、层级深）；至多一套；移动端折叠为底部 Tab 或汉堡菜单
-   **页面架构**: 左侧固定 Sidebar + 右侧流式内容区；最大宽度 `max-w-[1600px]` 适应数据表格
-   **响应式**: 桌面端双栏/三栏布局充分利用宽屏；移动端采集页全屏沉浸式，管理页简化为卡片流

## 5. Visual Language (视觉语言)

-   **形态参数**: 圆角 `rounded-md (0.375rem)` · 阴影 `shadow-xs` (仅卡片悬浮) · 间距基调 `compact` (表格 p-3, 卡片 p-4)
-   **识别签名**: 统计数字使用 Mono 字体 + tabular-nums；状态徽章统一胶囊形 + 浅色背景深色文字；表格行高紧凑 40px
-   **装饰策略**: 仅在知识图谱页使用深色背景画布；其余页面零装饰，靠网格线与留白建立秩序
-   **动效原则**: 即时反馈 150ms ease-out；进度条线性过渡；列表刷新淡入淡出
-   **可及性**: 橙色文字在白底上使用 hsl(38 92% 35%) 确保 ≥4.5:1；复杂背景加遮罩；焦点环 2px primary offset-2

## 6. Component Principles (组件原则)

-   **状态完整性**: Button/Input/Badge/TableRow 覆盖 Default/Hover/Focus/Active/Disabled/Error；Focus 环清晰可见
-   **层级清晰**: Primary 按钮实心填充；Secondary/Ghost 按钮描边或透明；统计卡片数字字号 ≥ text-3xl font-bold mono
-   **一致性**: 所有表格统一列宽策略与操作列位置；所有弹窗统一尺寸与关闭逻辑；复制按钮统一图标+Toast 反馈

## 7. Image Direction (图片与视觉资产，按需)

-   **Image Role**: 无强制图片需求，优先通过排版、色彩和局部图形建立视觉记忆点
-   **Image Art Direction**: 知识图谱画布若需背景纹理，可使用极细网格线或点阵图案，颜色 hsl(222 47% 20%) opacity 0.3
-   **Image Prompt Keywords**: engineering blueprint grid, dark technical background, subtle dot matrix, minimal data visualization texture
-   **Image Avoidance**: 避免具象建筑工地照片、3D 渲染设备图、通用科技感光效、任何可能干扰节点连线辨识度的元素

## 8. 应避免 (Anti-patterns)

-   ❌ 在数据表格中使用大圆角卡片包裹每一行（破坏扫描节奏，Grid 风格要求锐利边界）
-   ❌ 将"待确认"橙色用于非告警场景（如普通标签），导致语义稀释失去紧迫感
-   ❌ 移动端采集页堆砌小按钮与密集文字（违背"零学习成本快速采集"的核心使命）
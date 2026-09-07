"""
v0.1.89：矿山设备资料完整性检查（按工艺流程检查各系统资料）

按矿山工艺流程（破碎/磨矿/选别/脱水/火法/湿法/公用辅助）检查各系统
应有的工程资料完整性，标记缺失资料，生成待补充清单。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 各工艺流程应有的资料清单
# ============================================================

PROCESS_REQUIRED_DOCS = {
    "1. 破碎系统": {
        "system_docs": [
            # 系统级必备资料
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "施工方案", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "地脚螺栓紧固记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            # 系统级可选资料
            {"doc_type": "大件吊装方案", "required": False, "stage": "安装"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            # 破碎机专用资料
            "颚式破碎机": [
                {"doc_type": "动颚间隙调整记录", "required": True, "stage": "安装"},
                {"doc_type": "排矿口调整记录", "required": True, "stage": "安装"},
                {"doc_type": "破碎机试运转振动测试记录", "required": False, "stage": "试运转"},
            ],
            "圆锥破碎机": [
                {"doc_type": "动锥间隙调整记录", "required": True, "stage": "安装"},
                {"doc_type": "排矿口调整记录", "required": True, "stage": "安装"},
                {"doc_type": "液压系统调试记录", "required": True, "stage": "安装"},
            ],
            "反击式破碎机": [
                {"doc_type": "板锤间隙调整记录", "required": True, "stage": "安装"},
                {"doc_type": "反击板间隙调整记录", "required": True, "stage": "安装"},
            ],
            "锤式破碎机": [
                {"doc_type": "锤头间隙调整记录", "required": True, "stage": "安装"},
                {"doc_type": "篦条间隙调整记录", "required": True, "stage": "安装"},
            ],
            "振动筛": [
                {"doc_type": "筛面倾角调整记录", "required": True, "stage": "安装"},
                {"doc_type": "振动参数测试记录", "required": False, "stage": "试运转"},
                {"doc_type": "筛网更换记录", "required": False, "stage": "安装"},
            ],
            "给料机": [
                {"doc_type": "给料量调整记录", "required": True, "stage": "安装"},
            ],
        },
    },
    "2. 磨矿系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "球磨机/半自磨机专项吊装方案", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "地脚螺栓紧固记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "球磨机": [
                {"doc_type": "主轴承轴瓦刮研记录", "required": True, "stage": "安装"},
                {"doc_type": "筒体吊装记录", "required": True, "stage": "安装"},
                {"doc_type": "大齿圈端面跳动检测记录", "required": True, "stage": "安装"},
                {"doc_type": "大齿圈径向跳动检测记录", "required": True, "stage": "安装"},
                {"doc_type": "齿轮啮合间隙检测记录", "required": True, "stage": "安装"},
                {"doc_type": "齿轮啮合接触率检测记录", "required": True, "stage": "安装"},
                {"doc_type": "衬板安装记录", "required": True, "stage": "安装"},
                {"doc_type": "衬板螺栓紧固记录", "required": True, "stage": "安装"},
                {"doc_type": "高低压润滑系统调试记录", "required": True, "stage": "安装"},
                {"doc_type": "球磨机试运转轴承温升记录", "required": False, "stage": "试运转"},
                {"doc_type": "球磨机试运转振动测试记录", "required": False, "stage": "试运转"},
            ],
            "半自磨机": [
                {"doc_type": "主轴承轴瓦刮研记录", "required": True, "stage": "安装"},
                {"doc_type": "筒体吊装记录（超大型）", "required": True, "stage": "安装"},
                {"doc_type": "筒体翻身记录", "required": True, "stage": "安装"},
                {"doc_type": "大齿圈/环形电机安装检测记录", "required": True, "stage": "安装"},
                {"doc_type": "环形电机气隙检测记录", "required": True, "stage": "安装"},
                {"doc_type": "衬板安装记录", "required": True, "stage": "安装"},
                {"doc_type": "高低压润滑系统调试记录", "required": True, "stage": "安装"},
            ],
            "棒磨机": [
                {"doc_type": "主轴承轴瓦刮研记录", "required": True, "stage": "安装"},
                {"doc_type": "筒体吊装记录", "required": True, "stage": "安装"},
                {"doc_type": "钢棒装填记录", "required": True, "stage": "安装"},
                {"doc_type": "衬板安装记录", "required": True, "stage": "安装"},
            ],
            "螺旋分级机": [
                {"doc_type": "分级机安装倾角调整记录", "required": True, "stage": "安装"},
                {"doc_type": "螺旋叶片间隙检测记录", "required": True, "stage": "安装"},
            ],
            "水力旋流器": [
                {"doc_type": "旋流器安装记录", "required": True, "stage": "安装"},
                {"doc_type": "旋流器给矿压力测试记录", "required": False, "stage": "试运转"},
            ],
        },
    },
    "3. 选别系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "浮选机": [
                {"doc_type": "搅拌轴垂直度检测记录", "required": True, "stage": "安装"},
                {"doc_type": "叶轮与槽底间隙检测记录", "required": True, "stage": "安装"},
                {"doc_type": "三角带张紧力调整记录", "required": True, "stage": "安装"},
                {"doc_type": "充气系统调试记录", "required": True, "stage": "安装"},
                {"doc_type": "液位调节机构调试记录", "required": True, "stage": "安装"},
                {"doc_type": "浮选机带水试运转记录", "required": False, "stage": "试运转"},
            ],
            "磁选机": [
                {"doc_type": "磁滚筒安装记录", "required": True, "stage": "安装"},
                {"doc_type": "磁系间隙调整记录", "required": True, "stage": "安装"},
                {"doc_type": "磁选机磁场强度测试记录", "required": False, "stage": "试运转"},
            ],
            "跳汰机": [
                {"doc_type": "跳汰机安装记录", "required": True, "stage": "安装"},
                {"doc_type": "跳汰周期调整记录", "required": True, "stage": "安装"},
            ],
            "摇床": [
                {"doc_type": "摇床安装记录", "required": True, "stage": "安装"},
                {"doc_type": "床面倾角调整记录", "required": True, "stage": "安装"},
                {"doc_type": "冲程冲次调整记录", "required": True, "stage": "安装"},
            ],
            "加药机": [
                {"doc_type": "加药机安装记录", "required": True, "stage": "安装"},
                {"doc_type": "加药量校准记录", "required": True, "stage": "安装"},
            ],
        },
    },
    "4. 脱水系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "浓缩机": [
                {"doc_type": "浓缩机桥架安装记录", "required": True, "stage": "安装"},
                {"doc_type": "中心传动机构安装记录", "required": True, "stage": "安装"},
                {"doc_type": "耙架安装记录", "required": True, "stage": "安装"},
                {"doc_type": "浓缩机试运转记录", "required": False, "stage": "试运转"},
            ],
            "压滤机": [
                {"doc_type": "压滤机机架安装记录", "required": True, "stage": "安装"},
                {"doc_type": "滤板安装记录", "required": True, "stage": "安装"},
                {"doc_type": "液压系统调试记录", "required": True, "stage": "安装"},
                {"doc_type": "压滤机试压记录", "required": True, "stage": "试运转"},
            ],
            "陶瓷过滤机": [
                {"doc_type": "陶瓷过滤机安装记录", "required": True, "stage": "安装"},
                {"doc_type": "陶瓷滤板安装记录", "required": True, "stage": "安装"},
                {"doc_type": "真空系统调试记录", "required": True, "stage": "安装"},
            ],
            "回转干燥机": [
                {"doc_type": "干燥机筒体安装记录", "required": True, "stage": "安装"},
                {"doc_type": "托轮安装调整记录", "required": True, "stage": "安装"},
                {"doc_type": "挡轮安装记录", "required": True, "stage": "安装"},
                {"doc_type": "大齿圈安装检测记录", "required": True, "stage": "安装"},
                {"doc_type": "干燥机试运转记录", "required": False, "stage": "试运转"},
            ],
        },
    },
    "5. 火法冶炼系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "炉窑砌筑专项方案", "required": True, "stage": "施工准备"},
            {"doc_type": "烘炉方案", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "炉壳安装记录", "required": True, "stage": "安装"},
            {"doc_type": "冷却壁/水套安装记录", "required": True, "stage": "安装"},
            {"doc_type": "冷却壁水压试验记录", "required": True, "stage": "安装"},
            {"doc_type": "耐火材料砌筑记录", "required": True, "stage": "安装"},
            {"doc_type": "耐火砖缝检查记录", "required": True, "stage": "安装"},
            {"doc_type": "膨胀缝检查记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "烘炉记录", "required": True, "stage": "试运转"},
            {"doc_type": "烘炉曲线记录", "required": True, "stage": "试运转"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
            {"doc_type": "耐火材料质量证明文件", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "闪速炉": [
                {"doc_type": "反应塔安装记录", "required": True, "stage": "安装"},
                {"doc_type": "反应塔垂直度检测记录", "required": True, "stage": "安装"},
                {"doc_type": "铜水套水压试验记录", "required": True, "stage": "安装"},
                {"doc_type": "沉淀池安装记录", "required": True, "stage": "安装"},
                {"doc_type": "上升烟道安装记录", "required": True, "stage": "安装"},
                {"doc_type": "燃烧器/喷枪安装记录", "required": True, "stage": "安装"},
                {"doc_type": "炉壳焊接无损检测记录", "required": True, "stage": "安装"},
            ],
            "转炉": [
                {"doc_type": "托圈安装记录", "required": True, "stage": "安装"},
                {"doc_type": "耳轴轴承安装记录", "required": True, "stage": "安装"},
                {"doc_type": "耳轴轴承间隙检测记录", "required": True, "stage": "安装"},
                {"doc_type": "倾动机构安装记录", "required": True, "stage": "安装"},
                {"doc_type": "倾动机构制动器调试记录", "required": True, "stage": "安装"},
                {"doc_type": "倾动试验记录（0°/90°/180°）", "required": True, "stage": "试运转"},
                {"doc_type": "氧枪升降机构安装记录", "required": True, "stage": "安装"},
                {"doc_type": "氧枪定位精度检测记录", "required": True, "stage": "安装"},
            ],
            "阳极炉": [
                {"doc_type": "阳极炉安装记录", "required": True, "stage": "安装"},
                {"doc_type": "滚圈/齿圈安装检测记录", "required": True, "stage": "安装"},
                {"doc_type": "倾动机构安装记录", "required": True, "stage": "安装"},
                {"doc_type": "燃烧系统安装记录", "required": True, "stage": "安装"},
            ],
            "余热锅炉": [
                {"doc_type": "汽包吊装记录", "required": True, "stage": "安装"},
                {"doc_type": "受热面管排通球试验记录", "required": True, "stage": "安装"},
                {"doc_type": "受热面焊口无损检测记录", "required": True, "stage": "安装"},
                {"doc_type": "锅炉水压试验记录", "required": True, "stage": "试运转"},
                {"doc_type": "煮炉记录", "required": True, "stage": "试运转"},
                {"doc_type": "蒸汽严密性试验记录", "required": True, "stage": "试运转"},
                {"doc_type": "安全阀校验记录", "required": True, "stage": "试运转"},
            ],
        },
    },
    "6. 湿法冶炼系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "压力容器安装专项方案", "required": True, "stage": "施工准备"},
            {"doc_type": "耐压试验方案", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "压力容器质量证明书", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "管道吹扫记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "耐压试验记录", "required": True, "stage": "试运转"},
            {"doc_type": "气密性试验记录", "required": True, "stage": "试运转"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "高压釜": [
                {"doc_type": "高压釜吊装记录", "required": True, "stage": "安装"},
                {"doc_type": "支座安装记录（固定端/滑动端）", "required": True, "stage": "安装"},
                {"doc_type": "内件安装记录", "required": True, "stage": "安装"},
                {"doc_type": "搅拌装置安装记录", "required": True, "stage": "安装"},
                {"doc_type": "机械密封静压试验记录", "required": True, "stage": "安装"},
                {"doc_type": "钛衬里电火花检测记录", "required": True, "stage": "安装"},
                {"doc_type": "耐酸砖衬里检查记录", "required": False, "stage": "安装"},
                {"doc_type": "安全阀校验记录", "required": True, "stage": "试运转"},
                {"doc_type": "压力表检定记录", "required": True, "stage": "试运转"},
            ],
            "萃取箱": [
                {"doc_type": "萃取箱安装记录", "required": True, "stage": "安装"},
                {"doc_type": "箱体盛水渗漏试验记录（24h）", "required": True, "stage": "安装"},
                {"doc_type": "搅拌轴垂直度检测记录", "required": True, "stage": "安装"},
                {"doc_type": "相界面调节机构调试记录", "required": True, "stage": "安装"},
                {"doc_type": "耐腐衬里检查记录", "required": True, "stage": "安装"},
            ],
            "电积槽": [
                {"doc_type": "电积槽安装记录", "required": True, "stage": "安装"},
                {"doc_type": "耐酸衬里检查记录", "required": True, "stage": "安装"},
                {"doc_type": "导电排安装记录", "required": True, "stage": "安装"},
                {"doc_type": "导电排接触电阻测试记录", "required": False, "stage": "安装"},
                {"doc_type": "电积槽渗漏试验记录", "required": True, "stage": "安装"},
            ],
            "蒸发器": [
                {"doc_type": "蒸发器安装记录", "required": True, "stage": "安装"},
                {"doc_type": "加热室安装记录", "required": True, "stage": "安装"},
                {"doc_type": "分离室安装记录", "required": True, "stage": "安装"},
                {"doc_type": "蒸发器水压试验记录", "required": True, "stage": "试运转"},
            ],
        },
    },
    "7. 公用辅助系统": {
        "system_docs": [
            {"doc_type": "施工组织设计", "required": True, "stage": "施工准备"},
            {"doc_type": "技术交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "安全交底记录", "required": True, "stage": "施工准备"},
            {"doc_type": "基础验收记录", "required": True, "stage": "基础"},
            {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "基础"},
            {"doc_type": "二次灌浆记录", "required": True, "stage": "基础"},
            {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
            {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
            {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
            {"doc_type": "管道安装记录", "required": True, "stage": "配管"},
            {"doc_type": "管道压力试验记录", "required": True, "stage": "配管"},
            {"doc_type": "电气安装记录", "required": True, "stage": "电气"},
            {"doc_type": "接地电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "绝缘电阻测试记录", "required": True, "stage": "电气"},
            {"doc_type": "DCS/PLC调试记录", "required": True, "stage": "电气"},
            {"doc_type": "联锁试验记录", "required": True, "stage": "试运转"},
            {"doc_type": "单机试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "联动试运转记录", "required": True, "stage": "试运转"},
            {"doc_type": "施工日志", "required": True, "stage": "全过程"},
            {"doc_type": "竣工报告", "required": True, "stage": "资料"},
            {"doc_type": "竣工验收证书", "required": True, "stage": "资料"},
            {"doc_type": "设备质量证明文件", "required": False, "stage": "开箱"},
            {"doc_type": "设备说明书", "required": False, "stage": "开箱"},
        ],
        "equipment_docs": {
            "空压机": [
                {"doc_type": "空压机安装记录", "required": True, "stage": "安装"},
                {"doc_type": "空压机试运转记录", "required": True, "stage": "试运转"},
                {"doc_type": "储气罐水压试验记录", "required": False, "stage": "试运转"},
            ],
            "通风机": [
                {"doc_type": "通风机安装记录", "required": True, "stage": "安装"},
                {"doc_type": "通风机试运转记录", "required": True, "stage": "试运转"},
                {"doc_type": "通风机振动测试记录", "required": False, "stage": "试运转"},
            ],
            "冷却塔": [
                {"doc_type": "冷却塔安装记录", "required": True, "stage": "安装"},
                {"doc_type": "冷却塔填料安装记录", "required": True, "stage": "安装"},
                {"doc_type": "冷却塔试运转记录", "required": False, "stage": "试运转"},
            ],
        },
    },
}


def check_process_completeness(
    devices: list = None,
    existing_docs: list = None,
) -> dict:
    """
    按工艺流程检查资料完整性。
    
    Args:
        devices: 设备列表，用于确定需要检查哪些工艺流程和设备专用资料
        existing_docs: 已有资料列表（资料名称列表）
    
    Returns:
        资料完整性检查结果
    """
    if existing_docs is None:
        existing_docs = []
    
    # 确定需要检查的工艺流程
    if devices:
        processes_needed = set()
        device_types_by_process = {}
        for dev in devices:
            dev_type = dev.get("type", "")
            process = _get_process_for_equipment(dev_type)
            processes_needed.add(process)
            if process not in device_types_by_process:
                device_types_by_process[process] = set()
            device_types_by_process[process].add(dev_type)
    else:
        processes_needed = set(PROCESS_REQUIRED_DOCS.keys())
        device_types_by_process = {}
    
    results = {}
    total_required = 0
    total_existing = 0
    total_missing_required = 0
    total_missing_optional = 0
    all_issues = []
    
    for process in sorted(processes_needed, key=lambda p: list(PROCESS_REQUIRED_DOCS.keys()).index(p) if p in PROCESS_REQUIRED_DOCS else 99):
        process_info = PROCESS_REQUIRED_DOCS.get(process, {})
        system_docs = process_info.get("system_docs", [])
        equipment_docs = process_info.get("equipment_docs", {})
        
        process_required = 0
        process_existing = 0
        process_missing_required = []
        process_missing_optional = []
        process_existing_docs = []
        
        # 检查系统级资料
        for doc in system_docs:
            doc_type = doc["doc_type"]
            required = doc["required"]
            process_required += 1
            
            if _doc_exists(doc_type, existing_docs):
                process_existing += 1
                process_existing_docs.append(doc_type)
            else:
                if required:
                    process_missing_required.append(doc)
                else:
                    process_missing_optional.append(doc)
        
        # 检查设备专用资料
        dev_types = device_types_by_process.get(process, set())
        for dev_type in dev_types:
            dev_docs = equipment_docs.get(dev_type, [])
            for doc in dev_docs:
                doc_type = doc["doc_type"]
                required = doc["required"]
                process_required += 1
                
                if _doc_exists(doc_type, existing_docs):
                    process_existing += 1
                    process_existing_docs.append(doc_type)
                else:
                    if required:
                        process_missing_required.append({**doc, "equipment_type": dev_type})
                    else:
                        process_missing_optional.append({**doc, "equipment_type": dev_type})
        
        completion_rate = round(process_existing / max(process_required, 1) * 100, 1)
        
        results[process] = {
            "process": process,
            "required_docs": process_required,
            "existing_docs": process_existing,
            "missing_required": len(process_missing_required),
            "missing_optional": len(process_missing_optional),
            "completion_rate": completion_rate,
            "missing_required_list": process_missing_required,
            "missing_optional_list": process_missing_optional,
            "existing_docs_list": process_existing_docs,
        }
        
        total_required += process_required
        total_existing += process_existing
        total_missing_required += len(process_missing_required)
        total_missing_optional += len(process_missing_optional)
        
        # 生成问题列表
        for doc in process_missing_required:
            all_issues.append({
                "severity": "high",
                "type": "missing_required_doc",
                "process": process,
                "doc_type": doc["doc_type"],
                "stage": doc.get("stage", ""),
                "equipment_type": doc.get("equipment_type", ""),
                "message": f"[{process}] 缺失必备资料: {doc['doc_type']}" + (f"（{doc['equipment_type']}）" if doc.get("equipment_type") else ""),
            })
    
    # 按严重程度排序
    all_issues.sort(key=lambda x: 0 if x["severity"] == "high" else 1)
    
    overall_completion_rate = round(total_existing / max(total_required, 1) * 100, 1)
    
    result = {
        "ok": True,
        "total_processes": len(results),
        "total_required_docs": total_required,
        "total_existing_docs": total_existing,
        "total_missing_required": total_missing_required,
        "total_missing_optional": total_missing_optional,
        "overall_completion_rate": overall_completion_rate,
        "processes": list(results.values()),
        "issues": all_issues[:100],  # 最多显示100个
        "todo_list": _generate_todo_list(results),
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return result


def _get_process_for_equipment(dev_type: str) -> str:
    """获取设备所属工艺流程。"""
    try:
        from . import mining_schedule as _ms
        return _ms.EQUIPMENT_PROCESS_MAP.get(dev_type, "7. 公用辅助系统")
    except Exception:
        return "7. 公用辅助系统"


def _doc_exists(doc_type: str, existing_docs: list) -> bool:
    """检查资料是否已存在（模糊匹配）。"""
    doc_type_lower = doc_type.lower()
    for existing in existing_docs:
        existing_lower = existing.lower()
        # 精确匹配
        if doc_type_lower == existing_lower:
            return True
        # 包含匹配（资料名称包含关键词）
        if doc_type_lower in existing_lower or existing_lower in doc_type_lower:
            return True
        # 关键词匹配（去掉"记录"、"报告"等后缀后匹配）
        doc_keywords = doc_type_lower.replace("记录", "").replace("报告", "").replace("证书", "").strip()
        existing_keywords = existing_lower.replace("记录", "").replace("报告", "").replace("证书", "").strip()
        if doc_keywords and existing_keywords and (doc_keywords in existing_keywords or existing_keywords in doc_keywords):
            return True
    return False


def _generate_todo_list(results: dict) -> list:
    """生成待补充资料清单（按优先级排序）。"""
    todo = []
    for process, info in results.items():
        for doc in info.get("missing_required_list", []):
            todo.append({
                "priority": "high",
                "process": process,
                "doc_type": doc["doc_type"],
                "stage": doc.get("stage", ""),
                "equipment_type": doc.get("equipment_type", ""),
                "action": f"补充{doc['doc_type']}",
            })
        for doc in info.get("missing_optional_list", []):
            todo.append({
                "priority": "medium",
                "process": process,
                "doc_type": doc["doc_type"],
                "stage": doc.get("stage", ""),
                "equipment_type": doc.get("equipment_type", ""),
                "action": f"补充{doc['doc_type']}（可选）",
            })
    # 按优先级排序
    todo.sort(key=lambda x: 0 if x["priority"] == "high" else 1)
    return todo


def get_process_doc_requirements(process: str) -> dict:
    """获取指定工艺流程的资料要求清单。"""
    if process not in PROCESS_REQUIRED_DOCS:
        return {"ok": False, "error": f"未找到工艺流程: {process}"}
    
    info = PROCESS_REQUIRED_DOCS[process]
    return {
        "ok": True,
        "process": process,
        "system_docs": info.get("system_docs", []),
        "equipment_docs": info.get("equipment_docs", {}),
        "total_system_docs": len(info.get("system_docs", [])),
        "total_equipment_types": len(info.get("equipment_docs", {})),
    }


def get_all_processes() -> dict:
    """获取所有工艺流程列表。"""
    return {
        "ok": True,
        "processes": list(PROCESS_REQUIRED_DOCS.keys()),
        "total": len(PROCESS_REQUIRED_DOCS),
    }

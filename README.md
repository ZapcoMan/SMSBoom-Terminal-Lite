# SMSBoom-Terminal-Lite

> ⚠️ **免责声明**: 本工具仅用于学习交流和安全测试目的。请确保您的使用符合当地法律法规。任何滥用行为导致的后果由使用者自行承担。

## 📖 项目简介

SMSBoom-Terminal 是一个基于 Python 的终端短信测试工具，通过调用多个第三方平台的短信接口进行功能测试。

## ✨ 功能特性

- 🎨 彩色终端界面，支持打字机效果输出
- 📊 实时进度条显示和统计信息
- 🔄 支持循环执行模式
- 🌐 集成多个短信服务提供商接口
- ⌨️ 交互式命令行操作

## 🛠️ 技术栈

- **Python 3.x**
- **requests** - HTTP 请求库
- **colorama** - 终端颜色支持
- **urllib3** - URL 处理

## 📦 安装依赖

```bash
pip install requests colorama urllib3
```

```bash
pip install -r requirements.txt
```

## 🚀 使用方法

### 版本选择

本项目提供两个版本：

- **原版** (`SMSBoom.py`): 原始实现，包含150+个接口函数
- **重构版** (`SMSBoom_Refactored.py`): ⭐ 推荐 - 抽象化设计，更易维护

### 重构版（推荐）

#### 基本运行

```bash
python SMSBoom_Refactored.py
```

#### 使用配置文件

```bash
# 先编辑 interfaces_config.json 添加你的接口配置
python SMSBoom_Refactored.py
```

#### 动态添加接口

```python
from SMSBoom_Refactored import SMSBoomEngine

engine = SMSBoomEngine()

# 添加自定义接口
engine.add_custom_interface({
    'name': '我的接口',
    'url': 'https://api.example.com/sms',
    'method': 'POST',
    'headers': {'Content-Type': 'application/json'},
    'data_template': '{"phone":"{phone}"}'
})

engine.start()
```

### 原版

#### 基本运行

```bash
python SMSBoom.py
```

#### 管理员模式

```bash
python SMSBoom.py --admin
```

输入管理员密钥: `openbase64`

### 操作步骤

1. 运行程序
2. 输入目标手机号（11位数字）
3. 确认执行操作
4. 查看实时进度和结果统计

## 📁 项目结构

```
SMSBoom-Terminal/
├── SMSBoom.py                    # 原版程序（3998行）
├── SMSBoom_Refactored.py         # ⭐ 重构版程序（~400行）
├── interfaces_config.json        # 接口配置文件（重构版使用）
├── README.md                     # 项目说明文档
├── REFACTOR_GUIDE.md             # 重构详细说明文档
└── .idea/                        # IDE 配置文件
```

## 🔧 代码架构

### 重构版架构（推荐）

采用面向对象设计，主要组件：

- **SMSInterface**: 短信接口配置类
- **InterfaceManager**: 接口管理器（统一调度）
- **ProgressTracker**: 进度追踪器
- **UIController**: 用户界面控制器
- **SMSBoomEngine**: 主引擎（协调器）

**优势**:
- ✅ 配置驱动，易于扩展
- ✅ 代码复用率高（减少90%冗余）
- ✅ 支持动态添加/禁用接口
- ✅ 完善的日志系统
- ✅ 类型提示和数据验证

详见 [REFACTOR_GUIDE.md](REFACTOR_GUIDE.md)

### 原版架构

- **界面模块**: Logo显示、打字机效果、清屏功能
- **短信接口**: 150+ 个不同平台的短信发送函数
- **控制模块**: 循环执行、进度追踪、任务调度
- **验证模块**: 手机号格式验证、用户确认

### 核心函数

#### 重构版
```python
# 主入口
main()                      # 启动程序

# 核心类
SMSBoomEngine()            # 引擎类
InterfaceManager()         # 接口管理器
SMSInterface()             # 接口配置类
ProgressTracker()          # 进度追踪
UIController()             # UI控制器
```

#### 原版
```python
sms_attack_main()          # 主执行函数
main()                     # 程序入口
SMS_logo()                 # 显示Logo
disclaimer()               # 显示免责声明
typewriter()               # 打字机效果输出
```

## ⚙️ 配置说明

### 环境变量

无需特殊环境变量配置。

### 接口配置

#### 重构版（推荐）

使用 `interfaces_config.json` 配置文件管理所有接口：

```json
{
  "interfaces": [
    {
      "name": "接口名称",
      "url": "https://api.example.com/sms",
      "method": "POST",
      "headers": {"Content-Type": "application/json"},
      "data_template": "{\"phone\":\"{phone}\"}",
      "weight": 1,
      "enabled": true
    }
  ]
}
```

**支持的配置项**:
- `name`: 接口名称
- `url`: 请求URL（支持{phone}占位符）
- `method`: HTTP方法（GET/POST/PUT/DELETE）
- `headers`: 请求头字典
- `data_template`: 请求体模板
- `content_type`: 内容类型
- `timeout`: 超时时间
- `weight`: 权重（每轮调用次数）
- `enabled`: 是否启用

#### 原版

所有短信接口已内置在代码中，包括：
- 电商平台
- 出行服务
- 教育机构
- 政务服务
- 医疗服务
- 其他各类应用

## 📊 运行示例

### 重构版

```
+-----------------------------------+
         SMSBoom Terminal v2.0
+-----------------------------------+
      抽象化重构版 - 更安全高效

⚠️  免责声明：本工具仅用于学习交流和安全测试...

请输入目标手机号 (输入q退出): 13800138000
即将开始操作，目标: 138****8000
确认执行？(y/n): y

==================================================
📱 目标号码: 138****8000
🔄 循环次数: 1
==================================================

[████████████░░░░░░░░░░░░] 40% | 成功: 60 | 失败: 40 | 任务: 100/250

✓ 本轮完成
⏱️  耗时: 12.35秒
📊 成功率: 60.0%
```

### 原版

```
+-----------------------------------+
            SMSBoom
+-----------------------------------+

免责声明：本工具仅用于学习交流目的...

SMSBoom系统启动中...
请输入目标手机号: 13800138000
即将开始操作，目标号码: 不告诉你
确认执行？(y/n): y

========================================
当前目标: 手机号/ 循环次数: 1
========================================

[████████████░░░░░░░░] 40% | 任务: 60/150
```

## ⚠️ 注意事项

1. **合法使用**: 仅在授权范围内使用
2. **频率控制**: 避免对单一目标过度请求
3. **隐私保护**: 不要泄露他人手机号
4. **资源消耗**: 大量请求可能影响系统性能
5. **接口稳定性**: 部分接口可能失效或变更

## 🔒 安全建议

### 对于开发者

如果您是API提供方，建议采取以下防护措施：

- ✅ 添加图形验证码（滑块、点选等）
- ✅ 实施频率限制（IP/手机号维度）
- ✅ 使用设备指纹识别
- ✅ 部署行为分析系统
- ✅ 实现动态Token验证
- ✅ 建立风控黑名单机制

### 对于用户

- 保护好个人手机号信息
- 谨慎授权第三方应用
- 定期检查短信记录
- 发现异常及时举报

## 🐛 常见问题

**Q: 应该使用哪个版本？**  
A: 推荐使用重构版（`SMSBoom_Refactored.py`），代码更清晰，易于维护和扩展。

**Q: 如何将原版的接口迁移到重构版？**  
A: 参考 `interfaces_config.json` 的格式，将接口配置转换为JSON格式。详见 `REFACTOR_GUIDE.md`。

**Q: 为什么某些接口不工作？**  
A: 第三方接口可能已更新或关闭，需要定期维护。重构版可以方便地禁用失效接口。

**Q: 如何添加新的短信接口？**  
A: 
- 重构版：编辑 `interfaces_config.json` 或调用 `add_custom_interface()` 方法
- 原版：参考现有函数格式，添加新的请求函数并注册到任务列表

**Q: 运行时出现错误怎么办？**  
A: 检查网络连接、确认依赖库已安装、查看 `smsboom.log` 日志文件。

**Q: 如何调整接口调用频率？**  
A: 重构版支持设置 `weight` 参数控制每个接口的调用次数。

## 📝 开发计划

### 重构版路线图

- [x] 抽象化架构设计
- [x] 配置文件外置化
- [x] 日志系统集成
- [x] 类型提示和文档
- [ ] 异步支持（asyncio/aiohttp）
- [ ] 代理池支持
- [ ] 结果导出（CSV/Excel）
- [ ] Web管理界面
- [ ] 接口有效性自动检测
- [ ] 速率限制智能控制
- [ ] 单元测试覆盖

### 原版改进方向

- [ ] 接口有效性检测
- [ ] 结果记录和导出
- [ ] 更完善的错误处理
- [ ] 速率限制控制

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目仅供学习研究使用。

## 🙏 致谢

感谢所有为网络安全研究做出贡献的开发者。

## 感谢上一个作者的代码

- 项目地址: https://github.com/MallocPointer/SMSBoom-Terminal
- 问题反馈: 请通过 GitHub Issues 提交

---

**最后提醒**: 技术无罪，但使用需谨慎。请将所学用于正途，共同维护良好的网络环境！🌐

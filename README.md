# 体适能跑步管理工具

基于 Python 的命令行管理工具，提供学校信息同步、账号授权、跑步任务、历史路径采集、人脸图片更新和跑步统计查询等功能。

## 使用须知

- 本项目仅供合法的学习、研究和接口兼容性测试使用。
- 使用前请确认行为符合所在学校、平台及当地法律法规的要求。
- 同一账号运行本程序时，请退出手机端账号并避免同时登录，以免认证状态相互覆盖。
- 程序会连接第三方服务并提交账号、设备、运动和人脸相关数据，请在充分了解风险后使用。

## 主要功能

1. 更新学校列表
2. 授权账号
3. 执行晨跑、阳光跑或自由跑任务
4. 从历史运动记录采集可复用路径
5. 下载并更新人脸图片
6. 查询跑步有效次数和累计里程

跑步模块包含轨迹清洗、距离预算重采样、速度与步幅计算、60 秒步数分桶、中途人脸验证点排程和提交前数据校验。

## 环境要求

- Python 3.11 或更高版本
- Windows、macOS 或 Linux
- 可访问相关服务的网络环境

默认使用当前目录下的 SQLite 数据库 `tsn_data.db`。如需使用其他数据库，可通过 `DATABASE_URL` 环境变量覆盖连接地址，并自行安装对应的异步数据库驱动。

## 安装

建议使用独立的虚拟环境：

```bash
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS 或 Linux：

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 启动

在项目根目录执行：

```bash
python main.py
```

程序首次启动时会自动创建数据库表。

## 推荐使用顺序

1. 选择“更新学校列表”，同步可用学校。
2. 选择“授权账号”，选择学校并输入登录凭据。
3. 选择“爬取路径数据”，准备可复用的历史路线。
4. 按账号要求更新人脸图片。
5. 选择跑步类型和距离，确认后执行任务。
6. 使用统计查询查看有效次数和累计里程。

## 主菜单

```text
============================================================
  TiShiNeng 管理系统
============================================================
1. 更新学校列表
2. 授权账号
3. 开始跑步
4. 爬取路径数据
5. 更新人脸图片
6. 查询跑步有效次数和里程
0. 退出系统
============================================================
```

## 项目结构

```text
.
├── main.py
├── tsnRunServer.py
├── tsnClient.py
├── TiShiNengSdkBase.py
├── TiShiNengSdkPrivate.py
├── TiShiNengSdkPublic.py
├── TiShiNengRunPathManage.py
├── tsn_environment.py
├── tsn_face_schedule.py
├── tsn_payload.py
├── tsn_routes.py
├── spiderServer.py
├── validCountServer.py
├── track_clean.py
├── track_geo.py
├── track_log.py
├── track_metrics.py
├── track_resample.py
├── track_validate.py
├── step_buckets.py
├── database.py
├── models.py
├── services/
│   ├── tsnAccount/
│   └── tsnSchool/
├── requirements.txt
└── LICENSE
```

## 模块说明

| 模块 | 作用 |
| --- | --- |
| `main.py` | 命令行入口和交互流程 |
| `tsnRunServer.py` | 跑步任务初始化、人脸处理、轨迹生成和数据提交 |
| `tsnClient.py` | 账号认证、客户端创建和 Token 更新 |
| `TiShiNengSdkPrivate.py` | 私版服务接口 |
| `TiShiNengSdkPublic.py` | 公版服务接口 |
| `TiShiNengRunPathManage.py` | 跑步路径生成入口 |
| `track_*.py` | 轨迹清洗、度量、重采样和校验 |
| `spiderServer.py` | 历史运动路径采集 |
| `validCountServer.py` | 有效次数和里程统计 |
| `database.py`、`models.py` | 异步数据库连接和数据模型 |

## 本地数据与隐私

程序运行后可能在本地生成：

- `tsn_data.db`：学校、账号、认证信息和路径数据
- `face_images/`：从服务端获取的人脸图片
- 终端或日志输出：部分请求状态、接口响应或异常信息

数据库模型包含用户名、密码、Token 和设备标识等敏感字段。当前实现不提供字段级加密，请不要共享运行后生成的数据库、人脸目录或日志。公开发布前应再次检查并排除以下内容：

```text
tsn_data.db
face_images/
*.log
.env
__pycache__/
```

代码中包含应用接口所需的应用标识、签名、公钥和兼容性参数。这些内容不是个人账号凭据，但仍应按照项目的安全策略评估是否适合公开。

## 常见问题

### 无法授权账号

先确认学校列表已更新、学校类型选择正确、账号未在其他设备同时登录，并检查网络连接和登录信息。

### 没有可用路径

先运行“爬取路径数据”。如果账号没有历史运动记录，则无法生成可复用路径。

### 人脸图片获取失败

确认账号已经在官方客户端上传人脸图片，并检查网络、认证状态和 `face_images/` 目录的写入权限。

### Token 失效

程序会尝试刷新认证状态。若刷新失败，请退出后重新授权账号。

### 数据库连接失败

默认配置无需额外设置。使用自定义 `DATABASE_URL` 时，请确认连接地址、数据库服务和异步驱动均可用。

## 许可证

本项目采用 GNU General Public License v3.0，完整条款见 `LICENSE`。

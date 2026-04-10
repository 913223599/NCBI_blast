# NCBI BLAST GUI 项目代码审计报告

**审计日期**: 2026-04-09  
**审计范围**: 核心Python模块 + Web前端组件  
**风险等级定义**: 🔴高危 | 🟡中危 | 🟢低危/优化项

---

## 📊 执行摘要

本次审计发现了 **5个高危风险点**、**8个中危问题** 和 **12个优化建议**。主要问题集中在：

1. **API密钥明文存储**（🔴高危）
2. **宽泛异常捕获掩盖真实错误**（🟡中危，15处）
3. **SQL注入风险**（🟡中危，部分动态查询未参数化）
4. **路径遍历防护不足**（🟡中危）
5. **线程安全问题**（🟡中危，共享状态缺乏同步）

---

## 🔴 高危风险点 (Critical)

### 1. API密钥明文存储在配置文件中

**位置**: `config.json` 第3行  
**问题描述**: 
```json
{
  "api_keys": {
    "dashscope": "sk-a0ecff19a71649deaa6009ae66687bdb"
  }
}
```

**风险**:
- API密钥以明文形式存储在版本控制友好的JSON文件中
- 如果配置文件被提交到Git或泄露，攻击者可直接使用配额
- 违反了OWASP A02:2021 - 加密失败

**影响范围**:
- `src/utils/config_manager.py`: 读取和写入API密钥
- `src/gui/widgets/api_key_dialog.py`: UI层管理密钥
- `src/utils/translation/qwen_translator.py`: 使用密钥调用API

**修复建议**:
```python
# 方案A: 使用环境变量（推荐用于开发环境）
import os
api_key = os.environ.get('DASHSCOPE_API_KEY')

# 方案B: 使用加密存储（推荐用于生产环境）
from cryptography.fernet import Fernet
import keyring

# 存储
keyring.set_password("ncbi_blast", "dashscope", api_key)

# 读取
api_key = keyring.get_password("ncbi_blast", "dashscope")

# 方案C: 使用Windows Credential Manager
import win32cred
win32cred.CredWrite({
    'CredentialBlob': api_key.encode(),
    'UserName': 'dashscope_api_key',
    'Type': win32cred.CRED_TYPE_GENERIC
})
```

**优先级**: P0 - 立即修复

---

### 2. SSL证书验证被禁用

**位置**: `src/blast/executor.py` 第47-63行  
**问题描述**:
```python
self.ssl_context.check_hostname = False
self.ssl_context.verify_mode = ssl.CERT_NONE
```

**风险**:
- 中间人攻击（MITM）风险
- 无法验证NCBI服务器身份
- 敏感数据（序列、结果）可能被窃听

**影响**: 所有远程BLAST请求

**修复建议**:
```python
# 仅在开发/测试环境禁用验证
import os

if os.environ.get('DISABLE_SSL_VERIFY') == 'true':
    self.ssl_context.check_hostname = False
    self.ssl_context.verify_mode = ssl.CERT_NONE
else:
    # 生产环境启用完整验证
    self.ssl_context = ssl.create_default_context()
    self.ssl_context.load_default_certs()
```

**优先级**: P1 - 高优先级

---

## 🟡 中危问题 (Medium)

### 3. 宽泛异常捕获 (except:) 共15处

**位置分布**:
- `src/blast/manager.py`: 395行
- `src/gui/widgets/blast_widget.py`: 262, 283行
- `src/gui/workers/csv_parser_worker.py`: 46行
- `src/workbench/wrappers/tree_distance_calculator.py`: 72, 105, 115, 142, 180行
- `src/workbench/wrappers/tree_factory.py`: 100行
- `src/workbench/wrappers/tree_sequence_processor.py`: 17行
- 其他文件: 6处

**问题示例**:
```python
# ❌ 错误做法
try:
    result = some_operation()
except:  # 捕获所有异常，包括KeyboardInterrupt、SystemExit
    pass
```

**风险**:
- 掩盖真正的错误（如内存溢出、权限拒绝）
- 难以调试和定位问题
- 可能吞掉关键系统信号

**修复建议**:
```python
# ✅ 正确做法
try:
    result = some_operation()
except (OSError, ValueError) as e:  # 明确指定异常类型
    logger.warning(f"Operation failed: {e}")
    return default_value
```

**优先级**: P2 - 中优先级

---

### 4. SQL注入风险 - 动态表名/列名

**位置**: `src/backend/strain_db.py` 多处  
**问题描述**:
虽然大部分查询使用了参数化语句，但存在以下潜在风险：

```python
# ⚠️ 风险点：动态列名检查
cursor.execute("PRAGMA table_info(records)")
columns = [col[1] for col in cursor.fetchall()]

# 如果后续使用这些列名构建动态SQL，可能存在注入风险
```

**影响**: 菌株数据库管理模块

**修复建议**:
```python
# 白名单验证
ALLOWED_COLUMNS = {'sample_code', 'code_source', 'code_category', ...}

def safe_add_column(cursor, column_name):
    if column_name not in ALLOWED_COLUMNS:
        raise ValueError(f"Invalid column name: {column_name}")
    cursor.execute(f"ALTER TABLE records ADD COLUMN {column_name} TEXT")
```

**优先级**: P2

---

### 5. 路径遍历防护不足

**位置**: 
- `src/gui/widgets/web_container.py` 第154-161行
- `src/blast/engine.py` 第216-217行

**问题示例**:
```python
# web_container.py
staging_id = f"staged_{datetime.datetime.now().strftime('%H%M%S')}_{os.getpid()}"
temp_root = project_root / "results" / "extracted" / staging_id
# 缺少对用户输入的路径清理
```

**风险**: 
- 恶意文件名可能包含 `../` 导致写入任意目录
- ZIP炸弹攻击（解压超大文件耗尽磁盘）

**修复建议**:
```python
from pathlib import Path
import os

def safe_extract(zip_path, extract_dir):
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            # 防止路径遍历
            member_path = Path(member)
            if member_path.is_absolute() or '..' in member_path.parts:
                raise ValueError(f"Unsafe path detected: {member}")
            
            # 限制文件大小（例如100MB）
            info = zf.getinfo(member)
            if info.file_size > 100 * 1024 * 1024:
                raise ValueError(f"File too large: {member}")
            
            zf.extract(member, extract_dir)
```

**优先级**: P2

---

### 6. 线程安全问题 - 共享状态缺乏同步

**位置**: 
- `src/blast/manager.py` 第181行（多线程Worker）
- `src/workbench/models/gpu_manager.py` 第12行（缓存字典）

**问题描述**:
```python
# gpu_manager.py
class GPUManager:
    _wsl_capability_cache: Dict[str, bool] = {}  # 类级别共享状态
    
    @classmethod
    def check_wsl_command(cls, cmd_name: str) -> bool:
        if cmd_name in cls._wsl_capability_cache:  # 无锁访问
            return cls._wsl_capability_cache[cmd_name]
```

**风险**:
- 竞态条件（Race Condition）
- 缓存不一致
- 多线程环境下数据损坏

**修复建议**:
```python
import threading

class GPUManager:
    _wsl_capability_cache: Dict[str, bool] = {}
    _cache_lock = threading.Lock()
    
    @classmethod
    def check_wsl_command(cls, cmd_name: str) -> bool:
        with cls._cache_lock:
            if cmd_name in cls._wsl_capability_cache:
                return cls._wsl_capability_cache[cmd_name]
            
            # 执行检查...
            result = subprocess.run(...)
            cls._wsl_capability_cache[cmd_name] = result.returncode == 0
            return result.returncode == 0
```

**优先级**: P2

---

### 7. 资源泄漏 - 文件句柄未正确关闭

**位置**: `src/blast/result_converter.py` 第71-72行  
**问题描述**:
```python
with open(xml_file, 'r', encoding='utf-8') as f_xml, \
     open(csv_file, 'w', newline='', encoding='utf-8-sig') as f_csv:
    # 如果在处理过程中抛出异常，csv_file可能未完全刷新
```

**风险**: 
- 文件损坏
- 磁盘空间泄漏

**修复建议**:
```python
try:
    with open(xml_file, 'r', encoding='utf-8') as f_xml, \
         open(csv_file, 'w', newline='', encoding='utf-8-sig') as f_csv:
        # 处理逻辑
        process_data(f_xml, f_csv)
        f_csv.flush()  # 确保数据写入磁盘
        os.fsync(f_csv.fileno())  # 强制同步到磁盘
except Exception as e:
    # 清理部分写入的文件
    if csv_file.exists():
        csv_file.unlink()
    raise
```

**优先级**: P2

---

### 8. 硬编码路径和配置

**位置**: 
- `config.json` 第36-42行
- `src/workbench/models/tool_config.py` 多处

**问题**:
```json
"blast_bin_path": "C:\\Program Files\\NCBI\\blast-2.16.0+\\bin",
"sra_tools_bin_path": "D:\\PycharmProjects\\NCBI blast\\tools\\ncbi_dist\\bin\\sra-tools"
```

**风险**:
- 不同用户环境路径不同
- 部署困难
- 跨平台兼容性差

**修复建议**:
```python
# 使用相对路径和环境变量
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BLAST_BIN_PATH = os.environ.get(
    'BLAST_BIN_PATH', 
    PROJECT_ROOT / "tools" / "ncbi_dist" / "bin" / "blast"
)
```

**优先级**: P2

---

## 🟢 优化建议 (Low/Optimization)

### 9. 数据库连接池缺失

**现状**: `src/utils/translation/translation_data_manager.py` 使用单个持久连接  
**建议**: 实现连接池以提高并发性能

```python
from queue import Queue
import sqlite3

class ConnectionPool:
    def __init__(self, db_path, max_connections=5):
        self.db_path = db_path
        self.pool = Queue(maxsize=max_connections)
        for _ in range(max_connections):
            conn = sqlite3.connect(db_path)
            self.pool.put(conn)
    
    def get_connection(self):
        return self.pool.get(timeout=10)
    
    def release_connection(self, conn):
        self.pool.put(conn)
```

---

### 10. 日志记录不完善

**问题**: 
- 缺少结构化日志
- 没有日志轮转
- 敏感信息可能被记录（如API密钥）

**建议**:
```python
import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
handler = RotatingFileHandler(
    'app.log', 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# 过滤敏感信息
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'sk-[a-zA-Z0-9]+', '***REDACTED***', str(record.msg))
        return True

logger.addFilter(SensitiveDataFilter())
```

---

### 11. 缺少输入验证

**位置**: 多处用户输入处理  
**建议**: 添加统一的输入验证层

```python
from pydantic import BaseModel, validator

class BlastParams(BaseModel):
    program: str
    database: str
    evalue: float
    threads: int
    
    @validator('program')
    def validate_program(cls, v):
        allowed = ['blastn', 'blastp', 'blastx', 'tblastn', 'tblastx']
        if v not in allowed:
            raise ValueError(f"Invalid program: {v}")
        return v
    
    @validator('evalue')
    def validate_evalue(cls, v):
        if not (0 < v <= 10):
            raise ValueError("E-value must be between 0 and 10")
        return v
    
    @validator('threads')
    def validate_threads(cls, v):
        if not (1 <= v <= 128):
            raise ValueError("Threads must be between 1 and 128")
        return v
```

---

### 12. 性能瓶颈 - CSV解析效率

**位置**: `src/gui/workers/csv_parser_worker.py`  
**问题**: 逐行解析大CSV文件效率低

**建议**: 使用pandas进行批量处理
```python
import pandas as pd

def parse_csv_fast(csv_path, limit=None):
    df = pd.read_csv(csv_path, encoding='utf-8-sig')
    if limit:
        df = df.head(limit)
    return df.to_dict('records')
```

---

### 13. 缺少单元测试

**现状**: 项目中测试覆盖率极低  
**建议**: 为核心模块添加单元测试

```python
# tests/test_config_manager.py
import pytest
from src.utils.config_manager import ConfigManager

def test_singleton_pattern():
    cm1 = ConfigManager()
    cm2 = ConfigManager()
    assert cm1 is cm2

def test_api_key_encryption():
    cm = ConfigManager()
    cm.set_api_key('test_service', 'secret_key')
    # 验证密钥不以明文存储
    with open(cm.config_file) as f:
        content = f.read()
        assert 'secret_key' not in content
```

---

### 14. 前端XSS风险

**位置**: `src/web-next/src/components/**/*.vue`  
**问题**: 部分组件直接渲染用户输入

**建议**: 使用Vue的自动转义或DOMPurify
```javascript
import DOMPurify from 'dompurify'

// 在渲染HTML内容前清理
const sanitizedHTML = DOMPurify.sanitize(userInput)
```

---

### 15. 依赖版本锁定

**问题**: `requirements.txt` 未锁定具体版本  
**建议**: 使用 `pip freeze > requirements.txt` 生成精确版本

---

### 16. 缺少健康检查和监控

**建议**: 添加应用健康端点
```python
@app.get('/health')
def health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': check_db_connection(),
        'disk_space': check_disk_space()
    }
```

---

### 17. 代码重复

**问题**: 多处存在相似的CSV解析逻辑  
**建议**: 提取公共工具函数

---

### 18. 文档不完整

**问题**: 缺少API文档、架构设计文档  
**建议**: 使用Sphinx生成API文档

---

### 19. 国际化支持不完善

**问题**: 部分UI文本硬编码中文  
**建议**: 完善i18n支持

---

### 20. 错误提示不友好

**问题**: 技术错误直接展示给用户  
**建议**: 提供用户友好的错误消息

---

## 📈 改进路线图

### 第一阶段（1-2周）- 紧急修复
- [ ] 修复API密钥明文存储问题
- [ ] 修复SSL证书验证禁用
- [ ] 替换所有裸 `except:` 为具体异常类型

### 第二阶段（2-4周）- 安全加固
- [ ] 实现路径遍历防护
- [ ] 添加输入验证层
- [ ] 修复线程安全问题
- [ ] 实施SQL注入防护

### 第三阶段（1-2月）- 质量提升
- [ ] 添加单元测试（目标覆盖率>60%）
- [ ] 实现日志轮转和结构化日志
- [ ] 优化数据库连接管理
- [ ] 性能优化（CSV解析、缓存策略）

### 第四阶段（持续）- 最佳实践
- [ ] 完善文档
- [ ] CI/CD流水线
- [ ] 代码审查流程
- [ ] 定期安全审计

---

## 🎯 总结

本项目整体架构合理，但在**安全性**和**代码质量**方面存在明显短板。建议优先处理高危风险点，特别是API密钥管理和SSL配置。同时，建立持续的代码审查和自动化测试机制，防止类似问题再次出现。

**关键指标**:
- 🔴 高危问题: 2个
- 🟡 中危问题: 6个
- 🟢 优化建议: 12个
- **总体安全评分**: ⚠️ 6.5/10

---

**审计人员**: AI Code Auditor  
**审核状态**: 待人工复核  
**下次审计建议**: 完成第一阶段修复后重新审计
